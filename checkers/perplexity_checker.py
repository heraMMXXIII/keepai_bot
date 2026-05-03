import json

import httpx

from .base import HealthResult

# Как в keepai_backend/config/settings.py — PERPLEXITY_API_URL
CHAT_COMPLETIONS_URL = "https://api.perplexity.ai/chat/completions"


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
    """
    POST chat/completions, max_tokens=1 — как OpenAI. Запасные модели при 404/неверном имени.
    """
    if not api_key:
        return HealthResult(service="Perplexity", ok=False, error="API key is missing")

    primary = (model or "sonar").strip()
    fallbacks = ("sonar", "sonar-pro", "llama-3.1-sonar-small-128k-online")
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
                    return HealthResult(
                        service="Perplexity", ok=True, model_used=m
                    )
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
                if response.status_code in (400, 404) and i < len(models_to_try) - 1:
                    low = body.lower()
                    if "model" in low or "invalid" in low:
                        continue
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
            model_used=models_to_try[0] if models_to_try else None,
        )
