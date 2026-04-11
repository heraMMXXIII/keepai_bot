import httpx

from .base import HealthResult


async def check_claude_health(api_key: str) -> HealthResult:
    if not api_key:
        return HealthResult(service="Claude", ok=False, error="API key is missing")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://api.anthropic.com/v1/models", headers=headers)
        response.raise_for_status()
        return HealthResult(service="Claude", ok=True)
    except Exception as error:
        return HealthResult(service="Claude", ok=False, error=str(error))

