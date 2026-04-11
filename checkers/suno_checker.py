import httpx

from .base import BalanceResult

API_BASE = "https://api.sunoapi.org/api/v1"
# Актуальный путь из документации; старый /get-credits даёт 404.
CREDITS_PATH = "/generate/credit"


async def get_suno_balance(api_key: str) -> BalanceResult:
    if not api_key:
        return BalanceResult(service="Suno", ok=False, error="API key is missing")

    url = f"{API_BASE}{CREDITS_PATH}"
    headers = {"Authorization": f"Bearer {api_key.strip()}"}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)

        try:
            payload = response.json()
        except Exception:
            return BalanceResult(
                service="Suno",
                ok=False,
                error=f"HTTP {response.status_code}: не JSON",
            )

        if payload.get("code") != 200:
            return BalanceResult(
                service="Suno",
                ok=False,
                error=payload.get("msg", f"HTTP {response.status_code}"),
            )

        data = payload.get("data")
        if isinstance(data, (int, float)):
            credits = float(data)
        elif isinstance(data, dict):
            credits = float(data.get("credits", 0))
        else:
            return BalanceResult(
                service="Suno",
                ok=False,
                error="Не удалось разобрать поле data в ответе",
            )

        return BalanceResult(service="Suno", ok=True, value=credits, unit="tokens")
    except Exception as error:
        return BalanceResult(service="Suno", ok=False, error=str(error))
