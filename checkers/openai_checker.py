import json
import re

import httpx

from .base import HealthResult

CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

# Фрагменты ключа не показываем в Telegram (в теле 401 OpenAI подставляет свой текст).
_SK_TOKEN = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}", re.I)


def _redact_sk_in_text(text: str) -> str:
    return _SK_TOKEN.sub("sk-***", text)


def _error_for_telegram(body: str) -> str:
    low = body.lower()
    if "incorrect api key" in low or "invalid_api_key" in low:
        return (
            "Неверный или отозванный API ключ (ответ OpenAI). "
            "Обновите GPT_API_KEY в .env: https://platform.openai.com/account/api-keys"
        )
    if "insufficient_quota" in low or "exceeded your current quota" in low:
        return (
            "Не хватает квоты или баланса OpenAI. "
            "Пополните биллинг: https://platform.openai.com/account/billing"
        )
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        if err.get("code") == "invalid_api_key":
            return (
                "Неверный или отозванный API ключ (ответ OpenAI). "
                "Обновите GPT_API_KEY в .env: https://platform.openai.com/account/api-keys"
            )
        msg = (err.get("message") or "").strip()
        code = str(err.get("code") or "").lower()
        if code == "insufficient_quota":
            return (
                "Не хватает квоты или баланса OpenAI. "
                "Пополните биллинг: https://platform.openai.com/account/billing"
            )
        if msg:
            inner = msg.lower()
            if "incorrect api key" in inner:
                return (
                    "Неверный или отозванный API ключ (ответ OpenAI). "
                    "Обновите GPT_API_KEY в .env: https://platform.openai.com/account/api-keys"
                )
            if "exceeded your current quota" in inner or "insufficient_quota" in inner:
                return (
                    "Не хватает квоты или баланса OpenAI. "
                    "Пополните биллинг: https://platform.openai.com/account/billing"
                )
            return _redact_sk_in_text(msg)[:400]
    except json.JSONDecodeError:
        pass
    return _redact_sk_in_text(body[:400])


async def check_openai_health(api_key: str) -> HealthResult:
    """Реальный мини-запрос к Chat Completions: ловит исчерпанный баланс/квоту.

    Раньше был только GET /v1/models — при нулевом балансе он часто остаётся 200,
    хотя DALL-E и чат уже не работают; отчёт вводил в заблуждение.
    DALL-E отдельно не дергаем (лишняя стоимость и нет «сухого» эндпоинта).
    """
    if not api_key:
        return HealthResult(service="OpenAI", ok=False, error="API key is missing")

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    models_to_try = ("gpt-4o-mini", "gpt-3.5-turbo")

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            for i, model in enumerate(models_to_try):
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "."}],
                    "max_tokens": 1,
                }
                response = await client.post(
                    CHAT_COMPLETIONS_URL, headers=headers, json=payload
                )
                if response.status_code == 200:
                    return HealthResult(service="OpenAI", ok=True)
                body = ""
                try:
                    body = response.text or ""
                except Exception:
                    pass
                if response.status_code == 404 and i < len(models_to_try) - 1:
                    try:
                        data = response.json()
                        err_msg = (data.get("error") or {}).get("message") or ""
                        if "model" in err_msg.lower():
                            continue
                    except Exception:
                        continue
                detail = _error_for_telegram(body[:2000])
                msg = f"HTTP {response.status_code}: {detail}"
                return HealthResult(service="OpenAI", ok=False, error=msg)
    except Exception as error:
        return HealthResult(
            service="OpenAI", ok=False, error=_redact_sk_in_text(str(error))
        )
