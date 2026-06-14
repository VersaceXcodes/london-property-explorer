from __future__ import annotations

import re

POSTCODE_KEY_RE = re.compile(r"^[A-Z]{1,2}[0-9][0-9A-Z]?[0-9][A-Z]{2}$")
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}$")
DISTRICT_RE = re.compile(r"^[A-Z]{1,2}[0-9][0-9A-Z]?$")


def postcode_join_key(value: str) -> str:
    """Return the normalized no-space postcode used for source joins."""
    key = "".join(value.upper().split())
    if not POSTCODE_KEY_RE.fullmatch(key):
        raise ValueError(f"invalid UK postcode: {value!r}")
    return key


def canonical_postcode(value: str) -> str:
    """Return an uppercase UK postcode with one space before the inward code."""
    normalized_whitespace = " ".join(value.upper().split())
    if " " in normalized_whitespace and not POSTCODE_RE.fullmatch(normalized_whitespace):
        raise ValueError(f"invalid UK postcode: {value!r}")
    key = postcode_join_key(value)
    return f"{key[:-3]} {key[-3:]}"


def postcode_district(value: str) -> str:
    district = canonical_postcode(value).split(" ", maxsplit=1)[0]
    if not DISTRICT_RE.fullmatch(district):
        raise ValueError(f"invalid postcode district: {district!r}")
    return district
