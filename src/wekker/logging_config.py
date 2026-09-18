"""Logging met redactie van geheimen (tokens/wachtwoorden) uit logregels."""

from __future__ import annotations

import logging
import re
from logging.config import dictConfig

_PATTERNS = [
    re.compile(r"(?i)(password\s*[:=]\s*)(['\"]?)([^\s'\",}]+)(\2)"),
    re.compile(r"(?i)(token\s*[:=]\s*)(['\"]?)([^\s'\",}]+)(\2)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/=]+)"),
]


def redact(text: str) -> str:
    """Vervang waarschijnlijke geheimen door ***."""
    out = text
    for pat in _PATTERNS:
        out = pat.sub(lambda m: m.group(1) + "***", out)
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(str(record.getMessage()))
            record.args = ()
        except Exception:  # logging mag nooit crashen
            pass
        return True


def setup_logging(level: str = "INFO") -> None:
    dictConfig(
        {
            "version": 1,
            "filters": {"redact": {"()": RedactingFilter}},
            "formatters": {
                "std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "std",
                    "filters": ["redact"],
                }
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )
