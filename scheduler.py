from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.ext import Application

from checkers import (
    check_claude_health,
    check_gemini_health,
    check_grok_health,
    check_ideogram_health,
    check_perplexity_health,
    get_elevenlabs_balance,
    get_openai_balance,
    get_runway_balance,
    get_suno_balance,
)
from checkers.base import BalanceResult, HealthResult
from config import Settings
from messages import (
    build_alerts,
    format_alert_message,
    format_balance_report,
    format_daily_report,
)
from storage import TopupStorage


async def collect_balances(settings: Settings) -> OrderedDict[str, BalanceResult]:
    return OrderedDict(
        [
            ("openai", await get_openai_balance(settings.gpt_api_key)),
            ("elevenlabs", await get_elevenlabs_balance(settings.eleven_labs_api_key)),
            ("suno", await get_suno_balance(settings.suno_api_key)),
            ("runway", await get_runway_balance(settings.runway_api_key)),
        ]
    )


async def collect_health(settings: Settings) -> list[HealthResult]:
    return [
        await check_claude_health(settings.claude_api_key),
        await check_gemini_health(settings.gemini_api_key, settings.gemini_model),
        await check_perplexity_health(
            settings.perplexity_api_key, settings.perplexity_model
        ),
        await check_grok_health(settings.grok_api_key),
        await check_ideogram_health(settings.ideogram_api_key),
    ]


async def _broadcast(bot: Bot, user_ids: Sequence[int], text: str) -> None:
    for chat_id in user_ids:
        await bot.send_message(chat_id=chat_id, text=text)


def _recipients(
    settings: Settings, recipient_user_ids: Sequence[int] | None
) -> tuple[int, ...]:
    if recipient_user_ids is not None:
        return tuple(recipient_user_ids)
    return settings.telegram_allowed_user_ids


async def send_balance_snapshot(
    bot: Bot,
    settings: Settings,
    storage: TopupStorage,
    *,
    recipient_user_ids: Sequence[int] | None = None,
) -> None:
    balances = await collect_balances(settings)
    last_topup = storage.get_all_dates()
    message = format_balance_report(balances, last_topup)
    targets = _recipients(settings, recipient_user_ids)
    await _broadcast(bot, targets, message)

    alert_lines = build_alerts(
        balances, settings.balance_alert_usd, settings.balance_alert_tokens
    )
    alert_message = format_alert_message(alert_lines)
    if alert_message:
        await _broadcast(bot, targets, alert_message)


async def send_daily_snapshot(
    bot: Bot,
    settings: Settings,
    storage: TopupStorage,
    *,
    recipient_user_ids: Sequence[int] | None = None,
) -> None:
    balances = await collect_balances(settings)
    health = await collect_health(settings)
    last_topup = storage.get_all_dates()

    message = format_daily_report(balances, health, last_topup)
    targets = _recipients(settings, recipient_user_ids)
    await _broadcast(bot, targets, message)

    alert_lines = build_alerts(
        balances, settings.balance_alert_usd, settings.balance_alert_tokens
    )
    alert_message = format_alert_message(alert_lines)
    if alert_message:
        await _broadcast(bot, targets, alert_message)


def start_scheduler(
    application: Application, settings: Settings, storage: TopupStorage
) -> AsyncIOScheduler:
    timezone = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)

    async def interval_job() -> None:
        await send_balance_snapshot(application.bot, settings, storage)

    async def daily_job() -> None:
        await send_daily_snapshot(application.bot, settings, storage)

    scheduler.add_job(
        interval_job,
        "interval",
        hours=5,
        next_run_time=datetime.now(timezone) + timedelta(hours=5),
        id="balance_every_5h",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_job,
        "cron",
        hour=settings.report_hour,
        minute=0,
        id="daily_8am_report",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler

