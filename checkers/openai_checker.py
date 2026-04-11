import json
import re

import httpx

from .base import HealthResult

MODELS_URL = "https://api.openai.com/v1/models"

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
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        if err.get("code") == "invalid_api_key":
            return (
                "Неверный или отозванный API ключ (ответ OpenAI). "
                "Обновите GPT_API_KEY в .env: https://platform.openai.com/account/api-keys"
            )
        msg = (err.get("message") or "").strip()
        if msg:
            inner = msg.lower()
            if "incorrect api key" in inner:
                return (
                    "Неверный или отозванный API ключ (ответ OpenAI). "
                    "Обновите GPT_API_KEY в .env: https://platform.openai.com/account/api-keys"
                )
            return _redact_sk_in_text(msg)[:400]
    except json.JSONDecodeError:
        pass
    return _redact_sk_in_text(body[:400])


async def check_openai_health(api_key: str) -> HealthResult:
    """Проверка ключа: GET /v1/models (как в проде). Баланс $ по API не запрашиваем."""
    if not api_key:
        return HealthResult(service="ChatGPT", ok=False, error="API key is missing")

    headers = {"Authorization": f"Bearer {api_key.strip()}"}

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(MODELS_URL, headers=headers, params={"limit": 1})
        response.raise_for_status()
        return HealthResult(service="ChatGPT", ok=True)
    except httpx.HTTPStatusError as error:
        body = ""
        try:
            body = error.response.text or ""
        except Exception:
            pass
        detail = _error_for_telegram(body[:2000])
        msg = f"HTTP {error.response.status_code}: {detail}"
        return HealthResult(service="ChatGPT", ok=False, error=msg)
    except Exception as error:
        return HealthResult(
            service="ChatGPT", ok=False, error=_redact_sk_in_text(str(error))
        )
