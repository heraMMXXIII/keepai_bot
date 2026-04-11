from typing import Any, Dict

import httpx

from .base import BalanceResult

CREDIT_GRANTS_URL = "https://api.openai.com/dashboard/billing/credit_grants"
MODELS_URL = "https://api.openai.com/v1/models"


def _extract_openai_balance(payload: Dict[str, Any]) -> float:
    if "total_available" in payload and isinstance(
        payload["total_available"], (int, float)
    ):
        return float(payload["total_available"])

    grants = payload.get("grants", {})
    if isinstance(grants, dict):
        total_available = grants.get("total_available")
        if isinstance(total_available, (int, float)):
            return float(total_available)

    raise ValueError("Unable to parse OpenAI balance.")


async def get_openai_balance(api_key: str) -> BalanceResult:
    """
    Сумма с credit_grants доступна не всем ключам (часто 401 при рабочем чате).
    Тогда проверяем ключ так же, как прод: GET /v1/models.
    """
    if not api_key:
        return BalanceResult(service="OpenAI", ok=False, error="API key is missing")

    headers = {"Authorization": f"Bearer {api_key.strip()}"}

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            billing_resp = await client.get(CREDIT_GRANTS_URL, headers=headers)

            if billing_resp.is_success:
                balance_usd = _extract_openai_balance(billing_resp.json())
                return BalanceResult(
                    service="OpenAI", ok=True, value=balance_usd, unit="usd"
                )

            # 401/403 на billing — нормально для многих project keys; смотрим /v1/models
            models_resp = await client.get(
                MODELS_URL, headers=headers, params={"limit": 1}
            )
            if models_resp.is_success:
                return BalanceResult(
                    service="OpenAI",
                    ok=True,
                    value=1.0,
                    unit="api_key_ok",
                )

            err = f"billing {billing_resp.status_code}, models {models_resp.status_code}"
            if models_resp.text:
                err += f": {models_resp.text[:200]}"
            return BalanceResult(service="OpenAI", ok=False, error=err)
    except Exception as error:
        return BalanceResult(service="OpenAI", ok=False, error=str(error))
