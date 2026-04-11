from typing import Any

import httpx

from .base import BalanceResult


def _find_credit_value(node: Any) -> float:
    if isinstance(node, dict):
        for key, value in node.items():
            key_lower = key.lower()
            if "credit" in key_lower and isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, (dict, list)):
                found = _find_credit_value(value)
                if found >= 0:
                    return found
    elif isinstance(node, list):
        for item in node:
            found = _find_credit_value(item)
            if found >= 0:
                return found
    return -1.0


async def get_runway_balance(api_key: str) -> BalanceResult:
    if not api_key:
        return BalanceResult(service="Runway", ok=False, error="API key is missing")

    url = "https://api.dev.runwayml.com/v1/organization"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": "2024-11-06",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        credits = _find_credit_value(payload)
        if credits < 0:
            return BalanceResult(
                service="Runway",
                ok=False,
                error="Unable to parse credits from response",
            )
        return BalanceResult(service="Runway", ok=True, value=credits, unit="credits")
    except Exception as error:
        return BalanceResult(service="Runway", ok=False, error=str(error))

