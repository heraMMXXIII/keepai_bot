import json

import httpx

from .base import HealthResult

CHAT_COMPLETIONS_URL = "https://api.perplexity.ai/chat/completions"
# Sonar требует min 16 (иначе HTTP 400).
PERPLEXITY_HEALTH_MAX_TOKENS = 16

_DEPRECATED_MODELS = frozenset(
    {
        "llama-3.1-sonar-small-128k-online",
        "llama-3.1-sonar-large-128k-online",
        "llama-3.1-sonar-huge-128k-online",
    }
)


def _normalize_perplexity_model(model: str | None) -> str:
    m = (model or "sonar").strip()
    if not m or m in _DEPRECATED_MODELS or m.startswith("llama-"):
        return "sonar"
    return m


def _perplexity_error_snippet(body: str, limit: int = 400) -> str:
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


async def check_perplexity_health(api_key: str, model: str = "sonar") -> HealthResult:
    """POST chat/completions — одна модель из настроек, без fallback."""
    if not api_key:
        return HealthResult(service="Perplexity", ok=False, error="API key is missing")

    m = _normalize_perplexity_model(model)
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": m,
        "messages": [{"role": "user", "content": "."}],
        "max_tokens": PERPLEXITY_HEALTH_MAX_TOKENS,
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                CHAT_COMPLETIONS_URL, headers=headers, json=payload
            )
        if response.status_code == 200:
            return HealthResult(service="Perplexity", ok=True, model_used=m)

        body = response.text or ""
        if response.status_code in (401, 403):
            return HealthResult(
                service="Perplexity",
                ok=False,
                error=f"Unauthorized ({response.status_code})",
                model_used=m,
            )
        if response.status_code >= 500:
            return HealthResult(
                service="Perplexity",
                ok=False,
                error=f"HTTP {response.status_code}",
                model_used=m,
            )
        detail = _perplexity_error_snippet(body[:2000])
        return HealthResult(
            service="Perplexity",
            ok=False,
            error=f"HTTP {response.status_code}: {detail}",
            model_used=m,
        )
    except Exception as error:
        return HealthResult(
            service="Perplexity",
            ok=False,
            error=str(error),
            model_used=m,
        )
