import asyncio
import json

import httpx

from .base import HealthResult

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_OVERLOAD_RETRIES = 3
CLAUDE_OVERLOAD_RETRY_DELAYS_SEC = (1.0, 2.0, 4.0)


def _claude_error_snippet(body: str, limit: int = 400) -> str:
    if not body:
        return ""
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        if isinstance(err, dict):
            msg = (err.get("message") or "").strip() or json.dumps(err)[:limit]
        else:
            msg = str(err)
        return (msg[:limit] + "…") if len(msg) > limit else msg
    except json.JSONDecodeError:
        return body[:limit]


def _is_claude_overload(status_code: int, body: str) -> bool:
    if status_code == 529:
        return True
    low = (body or "").lower()
    return status_code in (503, 502, 504) and "overload" in low


async def check_claude_health(
    api_key: str, model: str = "claude-sonnet-4-5"
) -> HealthResult:
    """Мини-запрос к Messages API; retry при 529 Overloaded."""
    if not api_key:
        return HealthResult(service="Claude", ok=False, error="API key is missing")

    key = api_key.strip()
    primary = (model or "claude-sonnet-4-5").strip()
    fallbacks = ("claude-haiku-4-5", "claude-3-5-haiku-latest")
    models_to_try = []
    for m in (primary,) + fallbacks:
        if m and m not in models_to_try:
            models_to_try.append(m)

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            for i, m in enumerate(models_to_try):
                payload = {
                    "model": m,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                }
                last_overload_detail = ""
                for attempt in range(CLAUDE_OVERLOAD_RETRIES + 1):
                    response = await client.post(
                        MESSAGES_URL, headers=headers, json=payload
                    )
                    if response.status_code == 200:
                        return HealthResult(
                            service="Claude", ok=True, model_used=m
                        )

                    body = response.text or ""
                    if _is_claude_overload(response.status_code, body):
                        last_overload_detail = _claude_error_snippet(body[:2000])
                        if attempt < CLAUDE_OVERLOAD_RETRIES:
                            delay = CLAUDE_OVERLOAD_RETRY_DELAYS_SEC[
                                min(
                                    attempt,
                                    len(CLAUDE_OVERLOAD_RETRY_DELAYS_SEC) - 1,
                                )
                            ]
                            await asyncio.sleep(delay)
                            continue
                        break

                    if response.status_code == 404 and i < len(models_to_try) - 1:
                        low = body.lower()
                        if "model" in low or "not_found" in low:
                            break

                    detail = _claude_error_snippet(body[:2000])
                    return HealthResult(
                        service="Claude",
                        ok=False,
                        error=f"HTTP {response.status_code}: {detail}",
                        model_used=m,
                    )

                if last_overload_detail:
                    return HealthResult(
                        service="Claude",
                        ok=False,
                        error=(
                            "HTTP 529: временная перегрузка у провайдера (Overloaded), "
                            f"попробуйте позже. Детали: {last_overload_detail}"
                        ),
                        model_used=m,
                        temporary_issue=True,
                    )

        return HealthResult(
            service="Claude",
            ok=False,
            error="Не удалось проверить Claude (модель не найдена или недоступна)",
            model_used=primary,
        )
    except Exception as error:
        return HealthResult(
            service="Claude",
            ok=False,
            error=str(error),
            model_used=models_to_try[0] if models_to_try else None,
        )
