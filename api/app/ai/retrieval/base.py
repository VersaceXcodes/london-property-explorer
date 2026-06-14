from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from api.app.ai.state import Evidence


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence: list[Evidence]
    degraded: bool = False


class KnowledgeRetriever(Protocol):
    async def retrieve(self, query: str) -> RetrievalResult: ...


class UnavailableRetriever:
    async def retrieve(self, query: str) -> RetrievalResult:
        del query
        return RetrievalResult(evidence=[], degraded=True)
