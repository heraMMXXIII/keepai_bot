import logging
import os
import warnings
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands, Update
from telegram.request import HTTPXRequest
from telegram.warnings import PTBUserWarning
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from config import Settings, load_settings
from log_sanitize import attach_http_host_suppression, attach_http_log_redaction
from scheduler import send_daily_snapshot, start_scheduler
from storage import BALANCE_SERVICES, TopupStorage

# Чтобы LOG_HTTP_* из keepai_bot/.env применялся до настройки httpx
load_dotenv(Path(__file__).resolve().parent / ".env")


def _configure_http_client_logging() -> None:
    """Логи httpx: по умолчанию видны запросы к API; key/Bearer маскируются; Gemini/Runway не логируем."""
    raw = os.getenv("LOG_HTTP_REQUESTS", "true").strip().lower()
    verbose = raw in ("1", "true", "yes", "on")
    level = logging.INFO if verbose else logging.WARNING
    logging.getLogger("httpx").setLevel(level)
    logging.getLogger("httpcore").setLevel(level)
    attach_http_host_suppression()
    if os.getenv("LOG_HTTP_REDACT_SECRETS", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
        "",
    ):
        attach_http_log_redaction()


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# Тише только Telegram и планировщик; httpx/httpcore оставляем — видно запросы к API нейросетей.
for noisy in (
    "telegram",
    "telegram.ext",
    "telegram.ext._application",
    "apscheduler",
    "apscheduler.executors",
    "apscheduler.scheduler",
):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

_configure_http_client_logging()

# Смешанные CallbackQuery + MessageHandler в ConversationHandler — PTB шумит про per_*; это ожидаемо.
warnings.filterwarnings("ignore", category=PTBUserWarning)

# По умолчанию PTB даёт connect=5s — при прокси/медленном канале часто ConnectTimeout.
_TELEGRAM_HTTP = HTTPXRequest(
    connect_timeout=25.0,
    read_timeout=30.0,
    write_timeout=30.0,
    pool_timeout=10.0,
)


async def _global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        logger.warning("Telegram API: сеть/таймаут (%s). Повторите действие.", err)
        return
    logger.error(
        "Необработанная ошибка при обработке update",
        exc_info=(type(err), err, err.__traceback__),
    )


async def gatekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Только пользователи из TELEGRAM_ALLOWED_USER_IDS (или TELEGRAM_CHAT_ID)."""
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    if user is None:
        raise ApplicationHandlerStop
    if user.id in settings.telegram_allowed_user_ids:
        return
    if update.message:
        await update.message.reply_text(
            "Доступ запрещён. Ваш Telegram user id не в списке разрешённых."
        )
    elif update.callback_query:
        await update.callback_query.answer("Нет доступа.", show_alert=True)
    raise ApplicationHandlerStop


STATE_WAITING_DATE = 1
CB_CHECK_NOW = "check_now"
CB_DATES = "dates_menu"
CB_MAIN_MENU = "main_menu"
CB_CANCEL = "cancel_set_date"
CB_SET_DATE_PREFIX = "set_date:"


def _service_label(service: str) -> str:
    names = {
        "elevenlabs": "ElevenLabs",
        "suno": "Suno",
        "runway": "Runway",
    }
    return names[service]


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Проверить сейчас", callback_data=CB_CHECK_NOW)],
            [InlineKeyboardButton("📅 Даты пополнения", callback_data=CB_DATES)],
        ]
    )


def _dates_menu(storage: TopupStorage) -> InlineKeyboardMarkup:
    dates = storage.get_all_dates()
    buttons = []
    for service in BALANCE_SERVICES:
        value = dates.get(service) or "не задана"
        title = f"{_service_label(service)}: {value}"
        buttons.append(
            [InlineKeyboardButton(title, callback_data=f"{CB_SET_DATE_PREFIX}{service}")]
        )
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_MAIN_MENU)])
    return InlineKeyboardMarkup(buttons)


def _parse_date(raw_value: str) -> str:
    parsed = datetime.strptime(raw_value.strip(), "%d.%m.%Y")
    return parsed.strftime("%d.%m.%Y")


async def start_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Бот мониторинга KeepAI готов к работе.", reply_markup=_main_menu()
    )


async def show_main_menu(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Главное меню бота мониторинга KeepAI.", reply_markup=_main_menu()
    )


async def show_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    storage: TopupStorage = context.application.bot_data["storage"]
    await query.edit_message_text(
        "Выбери нейронку для изменения даты последнего пополнения.",
        reply_markup=_dates_menu(storage),
    )


async def ask_new_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    service = data.replace(CB_SET_DATE_PREFIX, "", 1)
    context.user_data["editing_service"] = service
    await query.edit_message_text(
        f"Введи дату последнего пополнения для {_service_label(service)} "
        "в формате ДД.ММ.ГГГГ.\n\nДля отмены нажми /cancel"
    )
    return STATE_WAITING_DATE


async def save_new_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    service = context.user_data.get("editing_service")
    if not service:
        await update.message.reply_text("Сервис не выбран. Нажми /start.")
        return ConversationHandler.END

    raw_date = update.effective_message.text
    try:
        normalized_date = _parse_date(raw_date)
    except ValueError:
        await update.effective_message.reply_text(
            "Неверный формат. Используй ДД.ММ.ГГГГ, например 10.04.2026."
        )
        return STATE_WAITING_DATE

    storage: TopupStorage = context.application.bot_data["storage"]
    storage.set_date(service, normalized_date)
    context.user_data.pop("editing_service", None)

    await update.effective_message.reply_text(
        f"Дата для {_service_label(service)} сохранена: {normalized_date}",
        reply_markup=_main_menu(),
    )
    return ConversationHandler.END


async def cancel_set_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("editing_service", None)
    await update.effective_message.reply_text(
        "Изменение даты отменено.", reply_markup=_main_menu()
    )
    return ConversationHandler.END


async def popolnenie_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Меню выбора нейронки для даты пополнения (то же, что «Даты пополнения»)."""
    context.user_data.pop("editing_service", None)
    storage: TopupStorage = context.application.bot_data["storage"]
    await update.effective_message.reply_text(
        "Выбери нейронку для изменения даты последнего пополнения.",
        reply_markup=_dates_menu(storage),
    )


async def popolnenie_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Во время ввода даты /popolnenie сбрасывает шаг и снова показывает выбор нейронки."""
    await popolnenie_command(update, context)
    return ConversationHandler.END


def _is_not_modified_error(err: BadRequest) -> bool:
    msg = (getattr(err, "message", None) or str(err)).lower()
    return "not modified" in msg


async def run_check_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    # Ответ на callback — сразу (до долгих HTTP), иначе истечёт таймаут query.
    await query.answer()

    settings: Settings = context.application.bot_data["settings"]
    storage: TopupStorage = context.application.bot_data["storage"]
    uid = query.from_user.id if query.from_user else None

    try:
        await query.edit_message_text(
            "⏳ Проверяю балансы и доступность API…\n"
            "(запросы идут параллельно, обычно 10–40 с)",
            reply_markup=_main_menu(),
        )
    except BadRequest as err:
        if not _is_not_modified_error(err):
            raise

    await send_daily_snapshot(
        context.application.bot,
        settings,
        storage,
        recipient_user_ids=(uid,) if uid is not None else None,
    )

    done_text = (
        "Отчёт отправлен. Можешь запустить снова или изменить даты пополнения."
    )
    try:
        await query.edit_message_text(done_text, reply_markup=_main_menu())
    except BadRequest as err:
        if _is_not_modified_error(err):
            return
        raise


async def post_init(application: Application) -> None:
    # Кнопка «Menu» слева от поля ввода: список команд бота (Telegram Bot API).
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Главное меню"),
            BotCommand("popolnenie", "Дата пополнения по нейронке"),
        ]
    )
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    settings: Settings = application.bot_data["settings"]
    storage: TopupStorage = application.bot_data["storage"]
    scheduler = start_scheduler(application, settings, storage)
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started.")


async def post_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped.")


def build_application() -> Application:
    settings = load_settings()
    storage = TopupStorage(Path(__file__).with_name("storage.json"))
    storage.get_all_dates()

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .request(_TELEGRAM_HTTP)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.bot_data["settings"] = settings
    app.bot_data["storage"] = storage

    app.add_error_handler(_global_error_handler)
    app.add_handler(TypeHandler(Update, gatekeeper), group=-1)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_set_date))
    app.add_handler(CallbackQueryHandler(run_check_now, pattern=f"^{CB_CHECK_NOW}$"))
    app.add_handler(CallbackQueryHandler(show_dates, pattern=f"^{CB_DATES}$"))
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern=f"^{CB_MAIN_MENU}$"))

    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_new_date, pattern=f"^{CB_SET_DATE_PREFIX}.+")
        ],
        states={
            STATE_WAITING_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_date)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_set_date),
            CommandHandler("popolnenie", popolnenie_fallback),
        ],
        allow_reentry=True,
    )
    app.add_handler(conversation)
    # После ConversationHandler: /popolnenie вне диалога; внутри диалога — fallback выше.
    app.add_handler(CommandHandler("popolnenie", popolnenie_command))

    return app


def main() -> None:
    app = build_application()
    logger.info("Запуск long polling (бот онлайн, Ctrl+C — остановка).")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()

