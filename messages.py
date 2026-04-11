from datetime import datetime
from typing import Dict, Iterable, Optional

from checkers.base import BalanceResult, HealthResult


def current_date_ru() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def _format_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def format_balance_value(result: BalanceResult) -> str:
    if not result.ok:
        return "не удалось получить"
    if result.value is None:
        return "нет данных"

    if result.unit == "usd":
        return f"${result.value:.2f}"
    if result.unit == "api_key_ok":
        return "ключ API работает (сумму в $ по API не отдали)"
    if result.unit == "tokens":
        return f"{_format_number(result.value)} токенов"
    if result.unit == "credits":
        return f"{_format_number(result.value)} кредитов"
    if result.unit == "chars":
        return f"{_format_number(result.value)} символов"
    return _format_number(result.value)


def _topup_suffix(service_key: str, last_topup: Dict[str, Optional[str]]) -> str:
    date_value = last_topup.get(service_key)
    if not date_value:
        return ""
    return f" | пополнение: {date_value}"


def format_balance_report(
    results: Dict[str, BalanceResult], last_topup: Dict[str, Optional[str]]
) -> str:
    today = current_date_ru()
    lines = [f"🔋 Баланс нейросетей ({today})", ""]
    for service_key, result in results.items():
        lines.append(
            f"{result.service} - {format_balance_value(result)} ({today})"
            f"{_topup_suffix(service_key, last_topup)}"
        )
    return "\n".join(lines)


def format_daily_report(
    balances: Dict[str, BalanceResult],
    health_results: Iterable[HealthResult],
    last_topup: Dict[str, Optional[str]],
) -> str:
    today = current_date_ru()
    lines = [f"📊 Статус нейросетей ({today})", "", "💰 Балансы:"]
    for service_key, result in balances.items():
        lines.append(
            f"{result.service} - {format_balance_value(result)} ({today})"
            f"{_topup_suffix(service_key, last_topup)}"
        )

    lines.append("")
    lines.append("✅ Работоспособность:")
    for result in health_results:
        if result.ok:
            lines.append(f"{result.service} - работает ✅ ({today})")
        else:
            lines.append(f'{result.service} - не работает 🔴 ({today})')
    return "\n".join(lines)


def build_alerts(
    balances: Dict[str, BalanceResult], alert_usd: float, alert_tokens: int
) -> list[str]:
    alerts: list[str] = []
    for result in balances.values():
        if not result.ok or result.value is None:
            continue

        if result.unit == "usd" and result.value < alert_usd:
            alerts.append(
                f"{result.service} - ${result.value:.2f} (ниже порога ${alert_usd:.2f})"
            )
        elif result.unit == "tokens" and result.value < alert_tokens:
            alerts.append(
                f"{result.service} - {int(result.value)} токенов (ниже порога {alert_tokens})"
            )
        elif result.unit == "credits":
            # Runway credits: 1 кредит = $0.01.
            credits_threshold = alert_usd / 0.01
            if result.value < credits_threshold:
                alerts.append(
                    f"{result.service} - {int(result.value)} кредитов "
                    f"(ниже эквивалента ${alert_usd:.2f})"
                )
    return alerts


def format_alert_message(alert_lines: list[str]) -> Optional[str]:
    if not alert_lines:
        return None
    return "⚠️ ВНИМАНИЕ!\n" + "\n".join(alert_lines)

