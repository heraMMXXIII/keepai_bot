import logging
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
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
from scheduler import send_daily_snapshot, start_scheduler
from storage import BALANCE_SERVICES, TopupStorage


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
        "openai": "OpenAI",
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


async def run_check_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Формирую отчёт...")

    settings: Settings = context.application.bot_data["settings"]
    storage: TopupStorage = context.application.bot_data["storage"]
    uid = query.from_user.id if query.from_user else None
    await send_daily_snapshot(
        context.application.bot,
        settings,
        storage,
        recipient_user_ids=(uid,) if uid is not None else None,
    )
    try:
        await query.edit_message_text(
            "Отчёт отправлен. Можешь запустить снова или изменить даты пополнения.",
            reply_markup=_main_menu(),
        )
    except BadRequest as error:
        # Telegram: тот же текст и клавиатура — «Message is not modified»
        if "not modified" in (getattr(error, "message", "") or str(error)).lower():
            await query.answer("Отчёт отправлен.")
        else:
            raise


async def post_init(application: Application) -> None:
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
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.bot_data["settings"] = settings
    app.bot_data["storage"] = storage

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
        fallbacks=[CommandHandler("cancel", cancel_set_date)],
        allow_reentry=True,
    )
    app.add_handler(conversation)

    return app


def main() -> None:
    app = build_application()
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()

