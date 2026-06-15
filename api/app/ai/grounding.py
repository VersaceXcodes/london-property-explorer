from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

NUMBER = re.compile(r"(?<![A-Za-z])(?:£|\$)?-?\d[\d,]*(?:\.\d+)?\s*[kKmM]?%?")


@dataclass(frozen=True, slots=True)
class GroundingResult:
    valid: bool
    reason: str


def _normalise_number(value: str) -> Decimal | None:
    cleaned = value.replace(",", "").replace("£", "").replace("$", "").replace(" ", "")
    cleaned = cleaned.removesuffix("%")
    multiplier = Decimal(1)
    if cleaned[-1:].lower() == "k":
        multiplier = Decimal(1_000)
        cleaned = cleaned[:-1]
    elif cleaned[-1:].lower() == "m":
        multiplier = Decimal(1_000_000)
        cleaned = cleaned[:-1]
    try:
        return Decimal(cleaned) * multiplier
    except InvalidOperation:
        return None


def verify_grounding(
    *,
    reply: str,
    cited_ids: list[str],
    evidence_ids: set[str],
    evidence_texts: list[str],
    sql_facts: list[dict[str, Any]],
    sql_plan: dict[str, Any] | None,
    require_citation: bool,
) -> GroundingResult:
    invalid_citations = set(cited_ids) - evidence_ids
    if invalid_citations:
        return GroundingResult(False, "response cited evidence that was not retrieved")
    if require_citation and not cited_ids:
        return GroundingResult(False, "evidence-backed response omitted a citation")

    allowed_text = " ".join(
        [
            json.dumps(sql_plan or {}, default=str, sort_keys=True),
            json.dumps(sql_facts, default=str, sort_keys=True),
            *evidence_texts,
        ]
    )
    allowed = {
        value
        for token in NUMBER.findall(allowed_text)
        if (value := _normalise_number(token)) is not None
    }
    claimed = {
        value for token in NUMBER.findall(reply) if (value := _normalise_number(token)) is not None
    }
    ungrounded = claimed - allowed
    if ungrounded:
        raw_ungrounded = sorted(
            {
                token.strip()
                for token in NUMBER.findall(reply)
                if ((value := _normalise_number(token)) is not None and value in ungrounded)
            }
        )
        claims = ", ".join(raw_ungrounded)
        return GroundingResult(
            False,
            f"response introduced numeric claims absent from SQL facts: {claims}",
        )
    return GroundingResult(True, "numeric claims and citations are grounded")
