import json

import httpx

from .base import HealthResult

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _gemini_error_snippet(text: str, limit: int = 400) -> str:
    if not text:
        return ""
    try:
        data = json.loads(text)
        err = data.get("error") or {}
        msg = err.get("message") or text
        return (msg[:limit] + "…") if len(msg) > limit else msg
    except json.JSONDecodeError:
        return text[:limit]


async def check_gemini_health(
    api_key: str,
    model: str = "gemini-2.5-flash-lite",
) -> HealthResult:
    """
    Проверка ключа Gemini (Google AI / AI Studio).

    Документация модели: https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite

    Ключ передаём в query `?key=` (как в официальных примерах REST) — так надёжнее, чем
    только заголовок в некоторых окружениях. Тело — минимальный generateContent без role
    (как в Quickstart).
    """
    if not api_key:
        return HealthResult(service="Gemini", ok=False, error="API key is missing")

    key = api_key.strip()
    key_param = {"key": key}

    # Минимальное тело по Quickstart (без поля role — часть клиентов так шлёт стабильнее).
    minimal_body = {
        "contents": [{"parts": [{"text": "ok"}]}],
        "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
    }

    headers_json = {"Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1) Список моделей (без pageSize — редко даёт 400 из-за параметров).
            list_resp = await client.get(f"{API_BASE}/models", params=key_param)
            if list_resp.is_success:
                return HealthResult(service="Gemini", ok=True)

            # 2) Прямой generateContent с ключом в URL (рекомендуемый способ в доке).
            gen_url = f"{API_BASE}/models/{model}:generateContent"
            gen_resp = await client.post(
                gen_url,
                params=key_param,
                headers=headers_json,
                json=minimal_body,
            )
            if gen_resp.is_success:
                return HealthResult(service="Gemini", ok=True)

            err_parts = [
                f"listModels HTTP {list_resp.status_code}",
                _gemini_error_snippet(list_resp.text),
                f"generateContent HTTP {gen_resp.status_code}",
                _gemini_error_snippet(gen_resp.text),
            ]
            err = " | ".join(p for p in err_parts if p)
            return HealthResult(service="Gemini", ok=False, error=err)
    except Exception as error:
        return HealthResult(service="Gemini", ok=False, error=str(error))
