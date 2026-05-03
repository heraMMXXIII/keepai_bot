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


def _grok_should_try_next_model(status_code: int, body: str) -> bool:
    if status_code == 404:
        low = (body or "").lower()
        return "model" in low or "not_found" in low
    if status_code == 400:
        try:
            data = json.loads(body)
            err = data.get("error")
            if isinstance(err, dict):
                err_msg = (err.get("message") or "").strip()
            else:
                err_msg = str(err) if err else ""
        except json.JSONDecodeError:
            err_msg = body or ""
        em = err_msg.lower()
        if "model not found" in em:
            return True
        return "model" in em and ("not found" in em or "invalid" in em)
    return False


async def check_grok_health(api_key: str, model: str = "grok-beta") -> HealthResult:
    """Мини-запрос к chat/completions (как OpenAI), не GET /v1/models."""
    if not api_key:
        return HealthResult(service="Grok", ok=False, error="API key is missing")

    primary = (model or "grok-beta").strip()
    fallbacks = (
        "grok-4-1-fast-reasoning",
        "grok-3",
        "grok-beta",
        "grok-2-1212",
    )
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
                    return HealthResult(service="Grok", ok=True, model_used=m)
                body = response.text or ""
                if i < len(models_to_try) - 1 and _grok_should_try_next_model(
                    response.status_code, body
                ):
                    continue
                detail = _grok_error_snippet(body[:2000])
                return HealthResult(
                    service="Grok",
                    ok=False,
                    error=f"HTTP {response.status_code}: {detail}",
                    model_used=m,
                )
    except Exception as error:
        return HealthResult(
            service="Grok",
            ok=False,
            error=str(error),
            model_used=models_to_try[0] if models_to_try else None,
        )
