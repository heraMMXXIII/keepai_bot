from datetime import datetime
from typing import Dict, Iterable, Optional

from checkers.base import BalanceResult, HealthResult
from storage import HEALTH_TOPUP_KEYS


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


def _balance_date_in_parens(
    service_key: str, last_topup: Dict[str, Optional[str]], today: str
) -> str:
    """Дата в скобках у строки баланса: последнее пополнение или сегодня."""
    raw = last_topup.get(service_key)
    if raw and str(raw).strip():
        return str(raw).strip()
    return today


def _balance_detail_block(result: BalanceResult) -> str:
    if not result.detail:
        return ""
    lines = result.detail.split("\n")
    indented = "\n".join(f"   {line}" for line in lines)
    return f"\n   ответ API:\n{indented}"


def _balance_needs_alert(
    result: BalanceResult,
    alert_usd: float,
    alert_tokens: int,
    alert_chars: int,
) -> bool:
    if not result.ok or result.value is None:
        return False
    if result.unit == "usd" and result.value < alert_usd:
        return True
    if result.unit == "tokens" and result.value < alert_tokens:
        return True
    if result.unit == "chars" and result.value < alert_chars:
        return True
    if result.unit == "credits":
        credits_threshold = alert_usd / 0.01
        if result.value < credits_threshold:
            return True
    return False


def _balance_line(
    result: BalanceResult,
    service_key: str,
    last_topup: Dict[str, Optional[str]],
    today: str,
    alert_usd: float,
    alert_tokens: int,
    alert_chars: int,
) -> str:
    line_date = _balance_date_in_parens(service_key, last_topup, today)
    core = (
        f"{result.service} - {format_balance_value(result)} ({line_date})"
        f"{_balance_detail_block(result)}"
    )
    if _balance_needs_alert(result, alert_usd, alert_tokens, alert_chars):
        return f"⚠️ ВНИМАНИЕ {core}"
    return core


def format_balance_report(
    results: Dict[str, BalanceResult],
    last_topup: Dict[str, Optional[str]],
    alert_usd: float,
    alert_tokens: int,
    alert_chars: int,
) -> str:
    today = current_date_ru()
    lines = [f"🔋 Баланс нейросетей ({today})", ""]
    for service_key, result in results.items():
        lines.append(
            _balance_line(
                result, service_key, last_topup, today, alert_usd, alert_tokens, alert_chars
            )
        )
    return "\n".join(lines)


def _health_model_note(result: HealthResult) -> str:
    if result.model_used:
        return f" · {result.model_used}"
    return ""


def format_daily_report(
    balances: Dict[str, BalanceResult],
    health_results: Iterable[HealthResult],
    last_topup: Dict[str, Optional[str]],
    alert_usd: float,
    alert_tokens: int,
    alert_chars: int,
) -> str:
    today = current_date_ru()
    lines = [f"📊 Статус нейросетей ({today})", "", "💰 Балансы:"]
    for service_key, result in balances.items():
        lines.append(
            _balance_line(
                result, service_key, last_topup, today, alert_usd, alert_tokens, alert_chars
            )
        )

    lines.append("")
    lines.append("✅ Работоспособность:")
    for service_key, result in zip(HEALTH_TOPUP_KEYS, health_results):
        line_date = _balance_date_in_parens(service_key, last_topup, today)
        note = _health_model_note(result)
        if result.ok:
            lines.append(f"{result.service} - работает ✅{note} ({line_date})")
        else:
            detail = ""
            if result.error:
                err = result.error.strip().replace("\n", " ")
                if len(err) > 500:
                    err = err[:497] + "…"
                detail = f"\n   └ {err}"
            lines.append(
                f"{result.service} - не работает 🔴{note} ({line_date}){detail}"
            )
    return "\n".join(lines)


def format_health_alert_report(health_results: Iterable[HealthResult]) -> str | None:
    today = current_date_ru()
    failed = [result for result in health_results if not result.ok]
    if not failed:
        return None

    lines = [f"⚠️ ВНИМАНИЕ: проблемы в health-check ({today})", ""]
    for result in failed:
        detail = ""
        if result.error:
            err = result.error.strip().replace("\n", " ")
            if len(err) > 500:
                err = err[:497] + "…"
            detail = f"\n   └ {err}"
        note = _health_model_note(result)
        lines.append(f"{result.service} - не работает 🔴{note}{detail}")
    return "\n".join(lines)

