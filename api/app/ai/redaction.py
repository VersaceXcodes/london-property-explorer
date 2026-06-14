from __future__ import annotations

import re

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def redact_sensitive_text(value: str) -> str:
    value = EMAIL.sub("[EMAIL]", value)
    value = PHONE.sub("[PHONE]", value)
    return UUID.sub("[UUID]", value)


def redact_payload(value: object) -> object:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key.lower() in {"ip", "ip_address", "authorization"}
            else redact_payload(item)
            for key, item in value.items()
        }
    return value
