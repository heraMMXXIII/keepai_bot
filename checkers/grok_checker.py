import httpx

from .base import HealthResult


async def check_grok_health(api_key: str) -> HealthResult:
    if not api_key:
        return HealthResult(service="Grok", ok=False, error="API key is missing")

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://api.x.ai/v1/models", headers=headers)
        response.raise_for_status()
        return HealthResult(service="Grok", ok=True)
    except Exception as error:
        return HealthResult(service="Grok", ok=False, error=str(error))

