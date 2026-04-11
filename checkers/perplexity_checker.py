import httpx

from .base import HealthResult

# Как в keepai_backend/config/settings.py — PERPLEXITY_API_URL
CHAT_COMPLETIONS_URL = "https://api.perplexity.ai/chat/completions"


async def check_perplexity_health(api_key: str, model: str = "sonar") -> HealthResult:
    """
    GET /models у Perplexity нет (404). Проверяем тем же POST, что и сайт: chat/completions.
    Минимальный запрос (max_tokens=1), чтобы не тратить лишнее.
    """
    if not api_key:
        return HealthResult(service="Perplexity", ok=False, error="API key is missing")

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "."}],
        "max_tokens": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                CHAT_COMPLETIONS_URL, headers=headers, json=payload
            )

        if response.status_code in (401, 403):
            return HealthResult(
                service="Perplexity",
                ok=False,
                error=f"Unauthorized ({response.status_code})",
            )
        if response.status_code >= 500:
            return HealthResult(
                service="Perplexity",
                ok=False,
                error=f"HTTP {response.status_code}",
            )
        if response.is_success:
            return HealthResult(service="Perplexity", ok=True)

        detail = response.text[:300] if response.text else ""
        return HealthResult(
            service="Perplexity",
            ok=False,
            error=f"HTTP {response.status_code} {detail}",
        )
    except Exception as error:
        return HealthResult(service="Perplexity", ok=False, error=str(error))
