import json

import httpx

from .base import HealthResult

CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"


def _grok_error_snippet(body: str, limit: int = 400) -> str:
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


async def check_grok_health(api_key: str, model: str = "grok-2-latest") -> HealthResult:
    """Мини-запрос к chat/completions (как OpenAI), не GET /v1/models."""
    if not api_key:
        return HealthResult(service="Grok", ok=False, error="API key is missing")

    primary = (model or "grok-2-latest").strip()
    fallbacks = ("grok-2-latest", "grok-2-1212", "grok-beta")
    models_to_try = []
    for m in (primary,) + fallbacks:
        if m and m not in models_to_try:
            models_to_try.append(m)

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            for i, m in enumerate(models_to_try):
                payload = {
                    "model": m,
                    "messages": [{"role": "user", "content": "."}],
                    "max_tokens": 1,
                }
                response = await client.post(
                    CHAT_COMPLETIONS_URL, headers=headers, json=payload
                )
                if response.status_code == 200:
                    return HealthResult(service="Grok", ok=True)
                body = response.text or ""
                if response.status_code == 404 and i < len(models_to_try) - 1:
                    try:
                        data = response.json()
                        err_msg = (data.get("error") or {}).get("message") or ""
                        if "model" in err_msg.lower():
                            continue
                    except Exception:
                        continue
                detail = _grok_error_snippet(body[:2000])
                return HealthResult(
                    service="Grok",
                    ok=False,
                    error=f"HTTP {response.status_code}: {detail}",
                )
    except Exception as error:
        return HealthResult(service="Grok", ok=False, error=str(error))
