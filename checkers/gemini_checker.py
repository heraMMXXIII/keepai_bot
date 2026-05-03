import json

import httpx

from .base import HealthResult

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _gemini_error_snippet(text: str, limit: int = 400) -> str:
    if not text:
        return ""
    try:
        data = json.loads(text)
        err = data.get("error") or {}
        msg = err.get("message") or text
        return (msg[:limit] + "…") if len(msg) > limit else msg
    except json.JSONDecodeError:
        return text[:limit]


def _normalize_gemini_model_id(model: str) -> str:
    m = (model or "gemini-2.5-flash-lite").strip()
    if m.startswith("models/"):
        m = m[len("models/") :]
    return m


async def check_gemini_health(
    api_key: str,
    model: str = "gemini-2.5-flash-lite",
) -> HealthResult:
    """Только generateContent: список моделей не отражает квоту на генерацию (как у старого OpenAI)."""
    if not api_key:
        return HealthResult(service="Gemini", ok=False, error="API key is missing")

    key = api_key.strip()
    key_param = {"key": key}
    primary = _normalize_gemini_model_id(model)
    fallbacks = ("gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-1.5-flash")
    models_to_try = []
    for m in (primary,) + fallbacks:
        if m and m not in models_to_try:
            models_to_try.append(m)

    minimal_body = {
        "contents": [{"parts": [{"text": "."}]}],
        "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
    }
    headers_json = {"Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            for i, m in enumerate(models_to_try):
                gen_url = f"{API_BASE}/models/{m}:generateContent"
                gen_resp = await client.post(
                    gen_url,
                    params=key_param,
                    headers=headers_json,
                    json=minimal_body,
                )
                if gen_resp.status_code == 200:
                    return HealthResult(
                        service="Gemini", ok=True, model_used=m
                    )
                body = gen_resp.text or ""
                if gen_resp.status_code in (400, 404) and i < len(models_to_try) - 1:
                    low = body.lower()
                    if "model" in low or "not found" in low or "not_found" in low:
                        continue
                detail = _gemini_error_snippet(body[:2000])
                return HealthResult(
                    service="Gemini",
                    ok=False,
                    error=f"HTTP {gen_resp.status_code}: {detail}",
                    model_used=m,
                )
    except Exception as error:
        return HealthResult(
            service="Gemini",
            ok=False,
            error=str(error),
            model_used=models_to_try[0] if models_to_try else None,
        )
