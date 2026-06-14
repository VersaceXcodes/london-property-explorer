from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Literal
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from api.app.ai import GRAPH_VERSION
from api.app.ai.contracts import ModelUsage
from api.app.ai.cost import CostRates, estimate_cost
from api.app.ai.grounding import verify_grounding
from api.app.ai.model import ModelGateway
from api.app.ai.prompts import prompt_hash
from api.app.ai.retrieval import KnowledgeRetriever
from api.app.ai.state import AgentState, Evidence, StepRecord
from api.app.ai.tools import execute_sales_plan
from api.app.ai.tracing import TraceManager
from api.app.core.errors import AppError
from api.app.db.repository import Repository
from api.app.models import (
    AgentMetrics,
    ChatRequest,
    ChatResponse,
    ChatStep,
    Citation,
    MapAction,
)

SQL_WORDS = {
    "sale",
    "sales",
    "sold",
    "price",
    "prices",
    "median",
    "count",
    "transactions",
    "district",
    "ranking",
    "trend",
    "expensive",
    "cheapest",
}
RAG_WORDS = {
    "methodology",
    "licence",
    "license",
    "provenance",
    "source",
    "limitations",
    "coverage",
    "meaning",
    "definition",
    "ons",
    "hmlr",
}
MAP_WORDS = {"map", "show", "zoom", "focus", "highlight", "display", "filter"}
UNSUPPORTED_PATTERNS = (
    "ignore previous",
    "ignore your instructions",
    "system prompt",
    "developer message",
    "reveal your prompt",
    "medical advice",
    "legal advice",
    "write code",
    "weather",
)
DISTRICT = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b", re.IGNORECASE)
PRICE = re.compile(r"(?:£|gbp\s*)?([0-9][0-9,]*(?:\.\d+)?)\s*([km])?", re.IGNORECASE)


def classify_route(question: str) -> tuple[str, str]:
    lowered = question.lower()
    if any(pattern in lowered for pattern in UNSUPPORTED_PATTERNS):
        return "unsupported", "request is unsafe or outside the property explorer scope"
    words = set(re.findall(r"[a-z]+", lowered))
    has_sql = bool(words & SQL_WORDS)
    has_rag = bool(words & RAG_WORDS)
    has_map = bool(words & MAP_WORDS)
    if has_map and not has_rag:
        return "map_action", "request proposes a map or filter change"
    if has_sql and has_rag:
        return "hybrid", "request needs transaction facts and source documentation"
    if has_sql:
        return "sql", "request needs deterministic transaction analytics"
    if has_rag:
        return "rag", "request needs curated methodology or provenance evidence"
    return "unsupported", "request does not match a supported property-data capability"


def _elapsed(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _step(name: str, detail: str, started: float, *, degraded: bool = False) -> StepRecord:
    return {
        "name": name,
        "status": "degraded" if degraded else "completed",
        "detail": detail,
        "duration_ms": _elapsed(started),
    }


def _usage_update(state: AgentState, usage: ModelUsage) -> dict[str, int]:
    return {
        "input_tokens": state.get("input_tokens", 0) + usage.input_tokens,
        "output_tokens": state.get("output_tokens", 0) + usage.output_tokens,
    }


class AgentRuntime:
    def __init__(
        self,
        *,
        repository: Repository,
        model: ModelGateway,
        retriever: KnowledgeRetriever,
        trace_manager: TraceManager,
        corpus_version: str | None,
        timeout_seconds: float,
        hard_cost_limit_usd: float,
        cost_rates: CostRates,
    ) -> None:
        self.repository = repository
        self.model = model
        self.retriever = retriever
        self.trace = trace_manager
        self.corpus_version = corpus_version
        self.timeout_seconds = timeout_seconds
        self.hard_cost_limit_usd = hard_cost_limit_usd
        self.cost_rates = cost_rates
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("validate_input", self._validate_input)
        graph.add_node("classify_route", self._classify_route)
        graph.add_node("retrieve_evidence", self._retrieve_evidence)
        graph.add_node("execute_sql_tools", self._execute_sql_tools)
        graph.add_node("propose_map_action", self._propose_map_action)
        graph.add_node("generate_response", self._generate_response)
        graph.add_node("verify_grounding", self._verify_grounding)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "validate_input")
        graph.add_edge("validate_input", "classify_route")
        graph.add_edge("classify_route", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "execute_sql_tools")
        graph.add_edge("execute_sql_tools", "propose_map_action")
        graph.add_edge("propose_map_action", "generate_response")
        graph.add_edge("generate_response", "verify_grounding")
        graph.add_conditional_edges(
            "verify_grounding",
            self._verification_route,
            {"retry": "generate_response", "done": "finalize"},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    def _run_id(self, state: AgentState) -> UUID:
        return UUID(state["run_id"])

    async def _validate_input(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        async with self.trace.span(self._run_id(state), "validate_input"):
            question = state["messages"][-1]["content"].strip()
            if not question:
                raise AppError(422, "INVALID_CHAT", "The final user message is empty")
        return {
            "question": question,
            "steps": [
                *state.get("steps", []),
                _step("validate_input", "Input contract accepted", started),
            ],
        }

    async def _classify_route(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        async with self.trace.span(self._run_id(state), "classify_route"):
            route, reason = classify_route(state["question"])
        return {
            "route": route,
            "route_reason": reason,
            "steps": [
                *state.get("steps", []),
                _step("classify_route", f"Selected {route} route", started),
            ],
        }

    async def _retrieve_evidence(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        if state["route"] not in {"rag", "hybrid"}:
            async with self.trace.span(self._run_id(state), "retrieve_evidence", {"skipped": True}):
                pass
            return {
                "evidence": [],
                "steps": [
                    *state.get("steps", []),
                    _step("retrieve_evidence", "Not required for this route", started),
                ],
            }
        async with self.trace.span(
            self._run_id(state), "retrieve_evidence", {"route": state["route"]}
        ):
            result = await self.retriever.retrieve(state["question"])
        detail = f"Retrieved {len(result.evidence)} curated evidence chunks"
        if result.degraded:
            detail = "Reranking or source retrieval was unavailable; fallback evidence was used"
        return {
            "evidence": result.evidence,
            "degraded": state.get("degraded", False) or result.degraded,
            "steps": [
                *state.get("steps", []),
                _step("retrieve_evidence", detail, started, degraded=result.degraded),
            ],
        }

    async def _execute_sql_tools(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        async with self.trace.span(
            self._run_id(state), "execute_sql_tools", {"route": state["route"]}
        ):
            pass
        if state["route"] not in {"sql", "hybrid"}:
            return {
                "sql_facts": [],
                "steps": [
                    *state.get("steps", []),
                    _step("execute_sql_tools", "Not required for this route", started),
                ],
            }
        async with self.trace.span(self._run_id(state), "sql_plan_model"):
            planned = await self.model.plan_sql(state["question"])
        if planned.value.plan.kind == "none":
            raise AppError(
                422, "UNSUPPORTED_QUERY", "The request could not be mapped to a safe SQL tool"
            )
        async with self.trace.span(
            self._run_id(state),
            "sql_tool",
            {"plan": planned.value.model_dump(mode="json")},
        ):
            facts = await execute_sales_plan(self.repository, planned.value)
        usage = _usage_update(state, planned.usage)
        return {
            "sql_plan": planned.value,
            "sql_facts": facts,
            **usage,
            "steps": [
                *state.get("steps", []),
                _step("execute_sql_tools", f"Executed {planned.value.plan.kind} tool", started),
            ],
        }

    async def _propose_map_action(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        action: MapAction | None = None
        if state["route"] == "map_action":
            action = self._map_action(state["question"])
        async with self.trace.span(self._run_id(state), "propose_map_action"):
            detail = "Proposed a reversible map action" if action else "No map change proposed"
        return {
            "map_action": action,
            "steps": [*state.get("steps", []), _step("propose_map_action", detail, started)],
        }

    def _map_action(self, question: str) -> MapAction | None:
        district_match = DISTRICT.search(question.upper())
        if district_match:
            district = district_match.group(1).upper()
            return MapAction(
                kind="highlight_district",
                payload={"district": district},
                label=f"Highlight {district}",
            )
        lowered = question.lower()
        property_types = {
            "detached": "D",
            "semi-detached": "S",
            "terraced": "T",
            "flat": "F",
            "other": "O",
        }
        payload: dict[str, object] = {}
        selected = [code for name, code in property_types.items() if name in lowered]
        if selected:
            payload["types"] = selected
        price_match = PRICE.search(lowered)
        if price_match and ("under" in lowered or "below" in lowered):
            amount = float(price_match.group(1).replace(",", ""))
            multiplier = {"k": 1_000, "m": 1_000_000}.get((price_match.group(2) or "").lower(), 1)
            payload["max_price"] = round(amount * multiplier)
        if not payload:
            return None
        return MapAction(kind="set_filters", payload=payload, label="Apply proposed filters")

    async def _generate_response(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        route = state["route"]
        async with self.trace.span(self._run_id(state), "generate_response", {"route": route}):
            pass
        usage = ModelUsage()
        cited_ids: list[str] = []
        if route == "unsupported":
            reply = (
                "I can only help with this explorer's London property transactions, "
                "map controls, data sources, methodology, and limitations."
            )
        elif route == "map_action" and state.get("map_action"):
            reply = (
                "I prepared a map change for you to review. Apply it to update the map, "
                "or leave the current view unchanged."
            )
        elif route == "map_action":
            reply = (
                "I could not derive a safe map change. Specify a postcode district, "
                "property type, or maximum price."
            )
        elif route in {"rag", "hybrid"} and not state.get("evidence"):
            if route == "rag":
                reply = (
                    "Source retrieval is currently unavailable, so I cannot provide a "
                    "grounded methodology or provenance answer."
                )
            else:
                reply = (
                    "The transaction query completed, but source retrieval is unavailable. "
                    "I cannot safely combine the result with methodology claims."
                )
        else:
            correction = (
                state.get("validation_result") if state.get("verification_attempts", 0) else None
            )
            async with self.trace.span(
                self._run_id(state),
                "answer_model" if correction is None else "answer_model_retry",
            ):
                generated = await self.model.generate_answer(
                    question=state["question"],
                    route=route,
                    sql_facts=state.get("sql_facts", []),
                    evidence=state.get("evidence", []),
                    correction=correction,
                )
            reply = generated.value.reply
            cited_ids = generated.value.cited_ids
            usage = generated.usage

        evidence_by_id = {item["id"]: item for item in state.get("evidence", [])}
        citations = [
            self._citation(evidence_by_id[item]) for item in cited_ids if item in evidence_by_id
        ]
        totals = _usage_update(state, usage)
        return {
            "reply": reply,
            "citations": citations,
            "draft_cited_ids": cited_ids,
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "steps": [
                *state.get("steps", []),
                _step("generate_response", "Generated a bounded answer draft", started),
            ],
        }

    def _citation(self, evidence: Evidence) -> Citation:
        return Citation(
            id=evidence["id"],
            title=evidence["title"],
            section=evidence["section"],
            publisher=evidence["publisher"],
            url=evidence["url"],
            licence=evidence["licence"],
        )

    async def _verify_grounding(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        cited_ids = state.get("draft_cited_ids", [])
        sql_plan = state.get("sql_plan")
        async with self.trace.span(self._run_id(state), "verify_grounding"):
            result = verify_grounding(
                reply=state["reply"],
                cited_ids=cited_ids,
                evidence_ids={item["id"] for item in state.get("evidence", [])},
                evidence_texts=[item["content"] for item in state.get("evidence", [])],
                sql_facts=state.get("sql_facts", []),
                sql_plan=sql_plan.model_dump(mode="json") if sql_plan is not None else None,
                require_citation=state["route"] in {"rag", "hybrid"}
                and bool(state.get("evidence")),
            )
            estimated = estimate_cost(
                state.get("input_tokens", 0),
                state.get("output_tokens", 0),
                self.cost_rates,
            )
            if estimated > self.hard_cost_limit_usd:
                raise AppError(
                    503, "AI_COST_LIMIT", "The response exceeded the configured cost limit"
                )
        attempts = state.get("verification_attempts", 0) + 1
        if not result.valid and attempts >= 2:
            raise AppError(503, "AI_GROUNDING_FAILED", "A grounded answer could not be produced")
        return {
            "validation_result": result.reason,
            "verification_attempts": attempts,
            "estimated_cost_usd": estimated,
            "steps": [
                *state.get("steps", []),
                _step("verify_grounding", result.reason, started, degraded=not result.valid),
            ],
        }

    def _verification_route(self, state: AgentState) -> Literal["retry", "done"]:
        return (
            "done" if state.get("validation_result", "").startswith("numeric claims") else "retry"
        )

    async def _finalize(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        async with self.trace.span(self._run_id(state), "finalize"):
            pass
        return {
            "steps": [
                *state.get("steps", []),
                _step("finalize", "Response contract finalized", started),
            ]
        }

    async def run(self, request: ChatRequest, *, run_id: UUID | None = None) -> ChatResponse:
        run_id = run_id or uuid4()
        started = time.perf_counter()
        messages = [message.model_dump() for message in request.messages]
        initial: AgentState = {
            "run_id": str(run_id),
            "messages": messages,
            "steps": [],
            "degraded": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "verification_attempts": 0,
            "prompt_hash": prompt_hash(),
            "started_at": started,
        }
        metadata = {
            "graph_version": GRAPH_VERSION,
            "prompt_hash": prompt_hash(),
            "model": self.model.model_name,
            "corpus_version": self.corpus_version,
        }
        self.trace.start(run_id, {"messages": messages}, metadata)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                state = await self.graph.ainvoke(initial)
            latency_ms = _elapsed(started)
            response = ChatResponse(
                run_id=run_id,
                reply=state["reply"],
                citations=state.get("citations", []),
                steps=[ChatStep.model_validate(step) for step in state.get("steps", [])],
                map_action=state.get("map_action"),
                degraded=state.get("degraded", False),
                metrics=AgentMetrics(
                    route=state["route"],
                    latency_ms=latency_ms,
                    input_tokens=state.get("input_tokens", 0),
                    output_tokens=state.get("output_tokens", 0),
                    estimated_cost_usd=state.get("estimated_cost_usd", 0),
                    graph_version=GRAPH_VERSION,
                    prompt_hash=prompt_hash(),
                    model=self.model.model_name,
                    corpus_version=self.corpus_version,
                ),
            )
        except TimeoutError as exc:
            self.trace.finish(run_id, {}, "timeout")
            raise AppError(
                504, "AI_TIMEOUT", "The assistant exceeded its 25 second deadline"
            ) from exc
        except Exception as exc:
            self.trace.finish(run_id, {}, type(exc).__name__)
            raise
        trace_output = {
            "response": response.model_dump(mode="json"),
            "retrieved_ids": [item["id"] for item in state.get("evidence", [])],
            "validation_result": state.get("validation_result"),
            "sql_plan": state.get("sql_plan").model_dump(mode="json")
            if state.get("sql_plan")
            else None,
        }
        self.trace.finish(run_id, trace_output)
        return response
