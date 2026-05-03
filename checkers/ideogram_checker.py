import httpx

from .base import HealthResult


_IDEO_ENDPOINT_MODEL = "ideogram-v3"


async def check_ideogram_health(api_key: str) -> HealthResult:
    if not api_key:
        return HealthResult(service="Ideogram", ok=False, error="API key is missing")

    headers = {"Api-Key": api_key.strip(), "Content-Type": "application/json"}
    # num_images=0 даёт 400; минимум 1 (запрос лёгкий, без реальной отдачи картинки в отчёт).
    payload = {"prompt": ".", "num_images": 1}
    url = "https://api.ideogram.ai/v1/ideogram-v3/generate"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code in (401, 403):
            return HealthResult(
                service="Ideogram",
                ok=False,
                error="Unauthorized",
                model_used=_IDEO_ENDPOINT_MODEL,
            )
        if response.status_code == 429:
            detail = (response.text or "")[:200]
            return HealthResult(
                service="Ideogram",
                ok=False,
                error=f"HTTP 429 (лимит / rate limit) {detail}",
                model_used=_IDEO_ENDPOINT_MODEL,
            )
        if response.is_success:
            return HealthResult(
                service="Ideogram",
                ok=True,
                model_used=_IDEO_ENDPOINT_MODEL,
            )
        if response.status_code >= 500:
            return HealthResult(
                service="Ideogram",
                ok=False,
                error=f"HTTP {response.status_code}",
                model_used=_IDEO_ENDPOINT_MODEL,
            )
        detail = (response.text or "")[:200]
        return HealthResult(
            service="Ideogram",
            ok=False,
            error=f"HTTP {response.status_code} {detail}",
            model_used=_IDEO_ENDPOINT_MODEL,
        )
    except Exception as error:
        return HealthResult(
            service="Ideogram",
            ok=False,
            error=str(error),
            model_used=_IDEO_ENDPOINT_MODEL,
        )

