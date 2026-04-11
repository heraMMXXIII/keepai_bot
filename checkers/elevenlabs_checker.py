import httpx

from .base import BalanceResult


async def get_elevenlabs_balance(api_key: str) -> BalanceResult:
    if not api_key:
        return BalanceResult(service="ElevenLabs", ok=False, error="API key is missing")

    url = "https://api.elevenlabs.io/v1/user/subscription"
    headers = {"xi-api-key": api_key}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        chars_used = int(data.get("character_count", 0))
        chars_limit = int(data.get("character_limit", 0))
        chars_left = max(chars_limit - chars_used, 0)
        return BalanceResult(
            service="ElevenLabs",
            ok=True,
            value=float(chars_left),
            unit="chars",
        )
    except Exception as error:
        return BalanceResult(service="ElevenLabs", ok=False, error=str(error))

