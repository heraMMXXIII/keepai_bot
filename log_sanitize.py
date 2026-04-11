"""Маскировка секретов в логах httpx (?key=…, Bearer, URL Telegram Bot API)."""
from __future__ import annotations

import logging
import re


class RedactUrlSecretsFilter(logging.Filter):
    """Маскирует секреты в строках логов HTTP-клиентов (?key=…, Bearer, токен Telegram в пути)."""

    _key_qs = re.compile(r"([?&]key=)[^&\s]+")
    _bearer = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-.]+", re.I)
    # https://api.telegram.org/bot<token>/getUpdates — токен между /bot и следующим /
    _telegram_bot_path = re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        new = self._key_qs.sub(r"\1***", msg)
        new = self._bearer.sub(r"\1***", new)
        new = self._telegram_bot_path.sub(r"\1***", new)
        if new != msg:
            record.msg = new
            record.args = ()
        return True


class SuppressHttpxHostsFilter(logging.Filter):
    """Не логировать строки запросов к указанным хостам (меньше шума в консоли)."""

    _hosts = (
        "generativelanguage.googleapis.com",  # Gemini / Google AI
        "api.dev.runwayml.com",
        "api.openai.com",  # ChatGPT / OpenAI
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not any(h in msg for h in self._hosts)


def attach_http_log_redaction() -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).addFilter(RedactUrlSecretsFilter())


def attach_http_host_suppression() -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).addFilter(SuppressHttpxHostsFilter())
