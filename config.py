import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    """Кому разрешено пользоваться ботом и кому слать отчёты (личные user id)."""
    telegram_allowed_user_ids: tuple[int, ...]
    timezone: str
    report_hour: int
    balance_alert_usd: float
    balance_alert_tokens: int
    gpt_api_key: str
    eleven_labs_api_key: str
    suno_api_key: str
    claude_api_key: str
    gemini_api_key: str
    perplexity_api_key: str
    grok_api_key: str
    runway_api_key: str
    ideogram_api_key: str
    claude_model: str
    gemini_model: str
    perplexity_model: str
    grok_model: str


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Environment variable '{name}' is required.")
    return value


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _parse_user_ids(raw: str) -> tuple[int, ...]:
    """Список через запятую: 123456789,987654321"""
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return tuple(int(p) for p in parts)


def load_settings() -> Settings:
    bot_dir = Path(__file__).resolve().parent
    bot_env_path = bot_dir / ".env"
    backend_default_env_path = bot_dir.parent / "keepai_backend" / ".env"

    bot_env = dotenv_values(bot_env_path)
    backend_env_path_raw = _first_non_empty(
        bot_env.get("BACKEND_ENV_FILE"),
        os.getenv("BACKEND_ENV_FILE"),
    )
    backend_env_path = (
        Path(backend_env_path_raw).expanduser()
        if backend_env_path_raw
        else backend_default_env_path
    )
    backend_env = dotenv_values(backend_env_path) if backend_env_path.exists() else {}

    def pick(
        name: str,
        *aliases: str,
        required: bool = False,
        default: str = "",
        prefer_backend: bool = True,
    ) -> str:
        """
        prefer_backend=True: OS → backend .env → keepai_bot/.env (ключи/модели как на сайте).
        prefer_backend=False: OS → bot .env → backend (токен бота, TELEGRAM_* и т.д.).
        """
        keys = (name,) + aliases

        def layer_values(getter) -> list[str | None]:
            return [getter(k) for k in keys]

        if prefer_backend:
            parts = (
                layer_values(os.getenv)
                + layer_values(lambda k: backend_env.get(k))
                + layer_values(lambda k: bot_env.get(k))
            )
        else:
            parts = (
                layer_values(os.getenv)
                + layer_values(lambda k: bot_env.get(k))
                + layer_values(lambda k: backend_env.get(k))
            )

        value = _first_non_empty(*parts, default)
        if required and not value:
            raise ValueError(
                f"Environment variable '{name}' is required "
                f"(checked bot .env, backend .env and OS env)."
            )
        return value

    allowed_raw = pick("TELEGRAM_ALLOWED_USER_IDS", default="", prefer_backend=False)
    legacy_chat = pick("TELEGRAM_CHAT_ID", default="", prefer_backend=False)

    if allowed_raw.strip():
        telegram_allowed_user_ids = _parse_user_ids(allowed_raw)
    elif legacy_chat.strip():
        telegram_allowed_user_ids = (int(legacy_chat.strip()),)
    else:
        raise ValueError(
            "Укажите TELEGRAM_ALLOWED_USER_IDS (через запятую) "
            "или для одного человека TELEGRAM_CHAT_ID (это тот же user id в личке)."
        )

    return Settings(
        telegram_bot_token=pick("TELEGRAM_BOT_TOKEN", required=True, prefer_backend=False),
        telegram_allowed_user_ids=telegram_allowed_user_ids,
        timezone=pick("TIMEZONE", default="Europe/Moscow", prefer_backend=False),
        report_hour=int(pick("REPORT_HOUR", default="8", prefer_backend=False)),
        balance_alert_usd=float(pick("BALANCE_ALERT_USD", default="5.0", prefer_backend=False)),
        balance_alert_tokens=int(pick("BALANCE_ALERT_TOKENS", default="1000", prefer_backend=False)),
        gpt_api_key=pick("GPT_API_KEY", "ChatGPT_API_KEY"),
        eleven_labs_api_key=pick("ELEVEN_LABS_API_KEY"),
        suno_api_key=pick("SUNO_API_KEY"),
        claude_api_key=pick("CLAUDE_API_KEY"),
        gemini_api_key=pick("GEMINI_API_KEY"),
        perplexity_api_key=pick("PERPLEXITY_API_KEY"),
        grok_api_key=pick("GROK_API_KEY"),
        runway_api_key=pick("RUNWAYML_API_SECRET", "RUNWAY_API_KEY"),
        ideogram_api_key=pick("IDEOGRAM_API_KEY"),
        claude_model=pick("CLAUDE_MODEL", default="claude-3-5-haiku-latest"),
        gemini_model=pick(
            "GEMINI_MODEL",
            default="gemini-2.5-flash-lite",
        ),
        perplexity_model=pick("PERPLEXITY_MODEL", default="sonar"),
        grok_model=pick("GROK_MODEL", default="grok-2-latest"),
    )

