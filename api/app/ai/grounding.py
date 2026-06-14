from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

NUMBER = re.compile(r"(?<![A-Za-z])(?:£|\$)?-?\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True, slots=True)
class GroundingResult:
    valid: bool
    reason: str


def _normalise_number(value: str) -> Decimal | None:
    cleaned = value.replace(",", "").replace("£", "").replace("$", "").removesuffix("%")
    try:
        return Decimal(cleaned)
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
        return GroundingResult(False, "response introduced a numeric claim absent from SQL facts")
    return GroundingResult(True, "numeric claims and citations are grounded")
