from typing import Any

import httpx

from .base import BalanceResult


def _is_credit_limit_key(key: str) -> bool:
    """Поля вроде maxMonthlyCreditSpend — лимит тарифа, не остаток кредитов."""
    kl = key.lower().replace("_", "")
    if "max" in kl and "credit" in kl:
        return True
    if "max" in kl and "spend" in kl:
        return True
    if "creditlimit" in kl:
        return True
    return False


def _balance_key_score(key: str) -> int:
    """Выше — надёжнее как «остаток / баланс», ниже — запасной вариант."""
    if _is_credit_limit_key(key):
        return 0
    kl = key.lower()
    if "remaining" in kl and "credit" in kl:
        return 100
    if "available" in kl and "credit" in kl:
        return 95
    if kl in ("creditbalance", "creditsbalance", "credit_balance"):
        return 92
    if "balance" in kl and "credit" in kl:
        return 90
    if "remaining" in kl:
        return 85
    if kl in ("credits", "credit"):
        return 75
    if "credit" in kl:
        return 40
    return 0


def _collect_numeric_leaves(
    node: Any, prefix: str = ""
) -> list[tuple[str, str, float]]:
    """Список (последний ключ JSON, полный путь, значение) для числовых листьев."""
    out: list[tuple[str, str, float]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                out.append((key, path, float(value)))
            elif isinstance(value, (dict, list)):
                out.extend(_collect_numeric_leaves(value, path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            out.extend(_collect_numeric_leaves(item, f"{prefix}[{i}]"))
    return out


def _find_credit_balance(payload: Any) -> tuple[float, str]:
    """
    Остаток кредитов, а не лимиты (maxMonthlyCreditSpend и т.п.).
    Возвращает (значение, имя поля) или (-1, "").
    """
    if not isinstance(payload, dict):
        return (-1.0, "")

    leaves = _collect_numeric_leaves(payload)
    scored: list[tuple[int, str, float]] = []
    for last_key, _path, val in leaves:
        kl = last_key.lower()
        # Расход за период — не остаток (если только это и есть в ответе — покажем ошибку).
        if any(x in kl for x in ("used", "spent", "consumed")) and "remain" not in kl:
            continue
        score = _balance_key_score(last_key)
        if score > 0:
            scored.append((score, last_key, val))

    if not scored:
        return (-1.0, "")

    scored.sort(key=lambda x: (-x[0], x[1]))
    _best_score, best_key, best_val = scored[0]
    return (best_val, best_key)


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
        credits, _field = _find_credit_balance(payload)
        if credits < 0:
            return BalanceResult(
                service="Runway",
                ok=False,
                error=(
                    "В JSON нет поля остатка кредитов (часто API отдаёт только лимиты tier). "
                    "Сверяйтесь с dev.runwayml.com."
                ),
            )
        return BalanceResult(
            service="Runway",
            ok=True,
            value=credits,
            unit="credits",
        )
    except httpx.HTTPStatusError as error:
        reason = getattr(error.response, "reason_phrase", "") or ""
        msg = f"HTTP {error.response.status_code}" + (f" {reason}" if reason else "")
        return BalanceResult(service="Runway", ok=False, error=msg.strip())
    except Exception as error:
        return BalanceResult(service="Runway", ok=False, error=str(error))

