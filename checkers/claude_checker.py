import json

import httpx

from .base import HealthResult

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _claude_error_snippet(body: str, limit: int = 400) -> str:
    if not body:
        return ""
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        if isinstance(err, dict):
            msg = (err.get("message") or "").strip() or json.dumps(err)[:limit]
        else:
            msg = str(err)
        return (msg[:limit] + "…") if len(msg) > limit else msg
    except json.JSONDecodeError:
        return body[:limit]


async def check_claude_health(
    api_key: str, model: str = "claude-3-5-haiku-latest"
) -> HealthResult:
    """Мини-запрос к Messages API (как OpenAI: реальный вывод, не только список моделей)."""
    if not api_key:
        return HealthResult(service="Claude", ok=False, error="API key is missing")

    key = api_key.strip()
    primary = (model or "claude-3-5-haiku-latest").strip()
    fallbacks = ("claude-3-5-haiku-20241022", "claude-3-5-haiku-latest")
    models_to_try = []
    for m in (primary,) + fallbacks:
        if m and m not in models_to_try:
            models_to_try.append(m)

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            for i, m in enumerate(models_to_try):
                payload = {
                    "model": m,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                }
                response = await client.post(MESSAGES_URL, headers=headers, json=payload)
                if response.status_code == 200:
                    return HealthResult(service="Claude", ok=True)
                body = response.text or ""
                if response.status_code == 404 and i < len(models_to_try) - 1:
                    low = body.lower()
                    if "model" in low or "not_found" in low:
                        continue
                detail = _claude_error_snippet(body[:2000])
                return HealthResult(
                    service="Claude",
                    ok=False,
                    error=f"HTTP {response.status_code}: {detail}",
                )
    except Exception as error:
        return HealthResult(service="Claude", ok=False, error=str(error))
