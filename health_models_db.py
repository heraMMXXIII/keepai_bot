"""
Модели для health-check такие же, как на сайте: из таблицы Django core_aimodelcost.

Порядок ключей совпадает с MODEL_COST_KEYS в keepai_backend/core/views/stars.py;
нормализация имён — с тем же смыслом, что AIModelCost._get_record_for_model.
"""

from __future__ import annotations

import logging
from dataclasses import replace
import asyncpg

from config import Settings

log = logging.getLogger("keepai_bot")

TABLE = "core_aimodelcost"

# Как на фронте (stars.MODEL_COST_KEYS): первая доступная активная запись в этом порядке.
MODEL_COST_KEYS: dict[str, tuple[str, ...]] = {
    "claude": ("haiku", "sonnet", "opus"),
    "gemini": ("flash", "pro", "flash-exp"),
    "gpt": ("gpt-5.2", "gpt-5-mini", "gpt-5-nano"),
    "perplexity": ("sonar", "sonar-pro"),
    "grok": ("grok-4-1-fast-reasoning", "grok-3"),
}

TEXT_HEALTH_EXCLUDED = frozenset(
    {
        "gpt-image-reference",
        "grok-image-reference",
        "gpt-text-image-reference",
        "claude-text-image-reference",
        "gemini-text-image-reference",
        "grok-text-image-reference",
    }
)


def _normalize_for_db(ai_model: str, key: str) -> str | None:
    """Возвращает model_name для поиска в БД (как нормализация во views/models)."""
    claude_mapping = {
        "claude-haiku-4-5-20251001": "claude-haiku-4-5",
        "claude-sonnet-4-5-20250929": "claude-sonnet-4-5",
        "claude-opus-4-1-20250805": "claude-opus-4-1",
        "claude-opus-4-5-20251101": "claude-opus-4-1",
        "haiku": "claude-haiku-4-5",
        "sonnet": "claude-sonnet-4-5",
        "opus": "claude-opus-4-6",
    }
    gemini_mapping = {
        "gemini-2.0-flash-exp": "gemini-2.0-flash-exp",
        "flash-exp": "gemini-2.0-flash-exp",
        "flash": "gemini-1.5-flash",
        "pro": "gemini-1.5-pro",
    }
    perplexity_mapping = {
        "sonar": "sonar",
        "sonar-pro": "sonar-pro",
    }
    grok_mapping = {
        "grok-4-1-fast-reasoning": "grok-4-1-fast-reasoning",
        "grok-3": "grok-3",
        "grok-imagine-image": "grok-imagine-image",
    }
    gpt_mapping = {
        "gpt-5.2": "gpt-5.2",
        "gpt-5-mini": "gpt-5-mini",
        "gpt-5-nano": "gpt-5-nano",
    }
    if ai_model == "claude":
        return claude_mapping.get(key, key)
    if ai_model == "gemini":
        return gemini_mapping.get(key, key)
    if ai_model == "perplexity":
        return perplexity_mapping.get(key, key)
    if ai_model == "grok":
        return grok_mapping.get(key, key)
    if ai_model == "gpt":
        return gpt_mapping.get(key, key)
    return None


def _text_model_ok(ai_model: str, model_name: str) -> bool:
    mn = (model_name or "").strip()
    if not mn:
        return False
    if mn in TEXT_HEALTH_EXCLUDED:
        return False
    if mn.endswith("-reference"):
        return False
    if ai_model == "grok" and mn in ("grok-imagine-image", "grok-2-image-1212"):
        return False
    if ai_model == "gpt" and (mn.startswith("dall-e") or "gpt-image" in mn):
        return False
    if ai_model == "gemini" and mn.startswith("nano-banana"):
        return False
    return True


async def _fetch_one_active(
    conn: asyncpg.Connection, ai_model: str, normalized: str
) -> str | None:
    row = await conn.fetchrow(
        f"""
        SELECT model_name FROM {TABLE}
        WHERE ai_model = $1 AND model_name = $2 AND is_active = true
        LIMIT 1
        """,
        ai_model,
        normalized,
    )
    if row and row["model_name"]:
        return str(row["model_name"]).strip()
    return None


async def _resolve_opus(conn: asyncpg.Connection) -> str | None:
    for name in ("claude-opus-4-6", "claude-opus-4-1"):
        found = await _fetch_one_active(conn, "claude", name)
        if found:
            return found
    return None


async def _fallback_any_text(conn: asyncpg.Connection, ai_model: str) -> str | None:
    rows = await conn.fetch(
        f"""
        SELECT model_name, cost FROM {TABLE}
        WHERE ai_model = $1
          AND is_active = true
          AND model_name IS NOT NULL
          AND btrim(model_name) <> ''
        ORDER BY cost ASC NULLS LAST, model_name ASC
        """,
        ai_model,
    )
    for row in rows:
        mn = str(row["model_name"] or "").strip()
        if _text_model_ok(ai_model, mn):
            return mn
    return None


async def _resolve_provider(conn: asyncpg.Connection, ai_model: str) -> str | None:
    keys = MODEL_COST_KEYS.get(ai_model, ())
    for key in keys:
        normalized = _normalize_for_db(ai_model, key)
        if not normalized:
            continue
        if ai_model == "claude" and key == "opus":
            found = await _resolve_opus(conn)
            if found:
                return found
            continue
        found = await _fetch_one_active(conn, ai_model, normalized)
        if found and _text_model_ok(ai_model, found):
            return found
    return await _fallback_any_text(conn, ai_model)


_FIELD_BY_AI: tuple[tuple[str, str], ...] = (
    ("gpt", "gpt_model"),
    ("claude", "claude_model"),
    ("gemini", "gemini_model"),
    ("perplexity", "perplexity_model"),
    ("grok", "grok_model"),
)


async def fetch_text_health_models_from_db(dsn: str) -> dict[str, str] | None:
    """Вернуть поля Settings (gpt_model, …) или None при ошибке подключения / пустой БД."""
    try:
        conn = await asyncpg.connect(dsn, timeout=15)
    except Exception as e:
        log.warning("БД health-моделей: не удалось подключиться: %s", e)
        return None
    try:
        updates: dict[str, str] = {}
        for ai_model, field in _FIELD_BY_AI:
            mid = await _resolve_provider(conn, ai_model)
            if mid:
                updates[field] = mid
        return updates or None
    finally:
        await conn.close()


async def resolve_health_models(settings: Settings) -> Settings:
    """Подставить модели из БД бэкенда; при сбое оставить значения из .env."""
    if not settings.health_models_from_db:
        return settings
    if not settings.db_dsn:
        return settings
    updates = await fetch_text_health_models_from_db(settings.db_dsn)
    if not updates:
        return settings
    log.info(
        "Health-check: модели из БД — %s",
        ", ".join(f"{k}={v}" for k, v in sorted(updates.items())),
    )
    return replace(settings, **updates)
