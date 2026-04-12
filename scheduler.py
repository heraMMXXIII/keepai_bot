import asyncio
import logging
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
    check_openai_health,
    check_perplexity_health,
    get_elevenlabs_balance,
    get_runway_balance,
    get_suno_balance,
)
from checkers.base import BalanceResult, HealthResult
from config import Settings
from messages import format_balance_report, format_daily_report
from storage import TopupStorage

log = logging.getLogger("keepai_bot")


async def collect_balances(settings: Settings) -> OrderedDict[str, BalanceResult]:
    eleven, suno, runway = await asyncio.gather(
        get_elevenlabs_balance(settings.eleven_labs_api_key),
        get_suno_balance(settings.suno_api_key),
        get_runway_balance(settings.runway_api_key),
    )
    return OrderedDict(
        [
            ("elevenlabs", eleven),
            ("suno", suno),
            ("runway", runway),
        ]
    )


async def collect_health(settings: Settings) -> list[HealthResult]:
    chatgpt, claude, gemini, perplexity, grok, ideogram = await asyncio.gather(
        check_openai_health(settings.gpt_api_key),
        check_claude_health(settings.claude_api_key),
        check_gemini_health(settings.gemini_api_key, settings.gemini_model),
        check_perplexity_health(
            settings.perplexity_api_key, settings.perplexity_model
        ),
        check_grok_health(settings.grok_api_key),
        check_ideogram_health(settings.ideogram_api_key),
    )
    return [chatgpt, claude, gemini, perplexity, grok, ideogram]


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
    message = format_balance_report(
        balances,
        last_topup,
        settings.balance_alert_usd,
        settings.balance_alert_tokens,
    )
    targets = _recipients(settings, recipient_user_ids)
    await _broadcast(bot, targets, message)


async def send_daily_snapshot(
    bot: Bot,
    settings: Settings,
    storage: TopupStorage,
    *,
    recipient_user_ids: Sequence[int] | None = None,
) -> None:
    balances, health = await asyncio.gather(
        collect_balances(settings),
        collect_health(settings),
    )
    last_topup = storage.get_all_dates()

    message = format_daily_report(
        balances,
        health,
        last_topup,
        settings.balance_alert_usd,
        settings.balance_alert_tokens,
    )
    targets = _recipients(settings, recipient_user_ids)
    await _broadcast(bot, targets, message)


def start_scheduler(
    application: Application, settings: Settings, storage: TopupStorage
) -> AsyncIOScheduler:
    timezone = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)

    async def interval_job() -> None:
        await send_balance_snapshot(application.bot, settings, storage)
        log.info(
            "Автоотчёт: балансы (интервал %s мин)",
            max(1, settings.balance_interval_minutes),
        )

    async def daily_job() -> None:
        await send_daily_snapshot(application.bot, settings, storage)
        log.info(
            "Автоотчёт: полный отчёт о нейросетях (%02d:%02d)",
            settings.report_hour,
            settings.report_minute,
        )

    interval_min = max(1, settings.balance_interval_minutes)
    scheduler.add_job(
        interval_job,
        "interval",
        minutes=interval_min,
        next_run_time=datetime.now(timezone) + timedelta(minutes=interval_min),
        id="balance_interval_report",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_job,
        "cron",
        hour=settings.report_hour,
        minute=settings.report_minute,
        id="daily_full_report",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler

