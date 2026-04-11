import httpx

from .base import HealthResult

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def check_gemini_health(
    api_key: str,
    model: str = "gemini-2.5-flash-lite",
) -> HealthResult:
    """
    Дефолтная модель — самая дешёвая стабильная в линейке 2.5 (см. Models | Gemini API).
    Заголовок x-goog-api-key для generateContent; для listModels часто надёжнее ?key=.
    Сначала список моделей; при неудаче — минимальный generateContent.
    """
    if not api_key:
        return HealthResult(service="Gemini", ok=False, error="API key is missing")

    headers = {
        "x-goog-api-key": api_key.strip(),
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            key = api_key.strip()
            list_resp = await client.get(
                f"{API_BASE}/models",
                params={"key": key, "pageSize": 8},
            )
            if list_resp.is_success:
                return HealthResult(service="Gemini", ok=True)

            # Fallback — тот же путь, что GeminiService.send_message
            gen_url = f"{API_BASE}/models/{model}:generateContent"
            body = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": "."}],
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": 1,
                    "temperature": 0,
                },
            }
            gen_resp = await client.post(gen_url, headers=headers, json=body)
            if gen_resp.is_success:
                return HealthResult(service="Gemini", ok=True)

            err = f"list {list_resp.status_code}, generate {gen_resp.status_code}"
            if gen_resp.text:
                err += f": {gen_resp.text[:200]}"
            return HealthResult(service="Gemini", ok=False, error=err)
    except Exception as error:
        return HealthResult(service="Gemini", ok=False, error=str(error))
