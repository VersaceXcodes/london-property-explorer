from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from api.app.ai.contracts import AnswerDraft, ModelResult, ModelUsage, SQLPlan
from api.app.ai.prompts import ANSWER_PROMPT, SQL_PLAN_PROMPT
from api.app.ai.state import Evidence

T = TypeVar("T", bound=BaseModel)


class ModelGateway(Protocol):
    model_name: str

    async def plan_sql(self, question: str) -> ModelResult[SQLPlan]: ...

    async def generate_answer(
        self,
        *,
        question: str,
        route: str,
        sql_facts: list[dict[str, Any]],
        evidence: list[Evidence],
        correction: str | None = None,
    ) -> ModelResult[AnswerDraft]: ...


def _usage(raw: Any) -> ModelUsage:
    metadata = getattr(raw, "usage_metadata", None) or {}
    return ModelUsage(
        input_tokens=int(metadata.get("input_tokens", 0)),
        output_tokens=int(metadata.get("output_tokens", 0)),
    )


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return str(content)


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("structured output must be a JSON object")
    return parsed


def _json_instruction(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"), default=str)
    return (
        "Return only one valid JSON object. Do not use markdown fences or explanatory text. "
        "The object must validate against this Pydantic JSON schema:\n"
        f"{schema_json}"
    )


class ClaudeGateway:
    def __init__(self, api_key: str, model_name: str) -> None:
        self.model_name = model_name
        self._model = ChatAnthropic(
            api_key=api_key,
            model=model_name,
            temperature=0,
            max_tokens=1_200,
        )

    async def _structured(
        self,
        schema: type[T],
        system: str,
        human: str,
    ) -> ModelResult[T]:
        structured = self._model.with_structured_output(schema, include_raw=True)
        result = await structured.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        if not isinstance(result, dict):
            raise RuntimeError("Claude structured output did not return a result mapping")
        parsed = result.get("parsed")
        if parsed is None:
            error = result.get("parsing_error")
            raise RuntimeError(f"Claude returned invalid structured output: {error}")
        return ModelResult(value=parsed, usage=_usage(result.get("raw")))

    async def plan_sql(self, question: str) -> ModelResult[SQLPlan]:
        return await self._structured(SQLPlan, SQL_PLAN_PROMPT, question)

    async def generate_answer(
        self,
        *,
        question: str,
        route: str,
        sql_facts: list[dict[str, Any]],
        evidence: list[Evidence],
        correction: str | None = None,
    ) -> ModelResult[AnswerDraft]:
        payload = {
            "question": question,
            "route": route,
            "sql_facts": sql_facts,
            "evidence": evidence,
            "correction": correction,
        }
        return await self._structured(AnswerDraft, ANSWER_PROMPT, str(payload))


class OpenRouterGateway:
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str,
        app_url: str | None = None,
        app_title: str = "London Property Explorer",
    ) -> None:
        self.model_name = model_name
        headers = {"X-Title": app_title}
        if app_url:
            headers["HTTP-Referer"] = app_url
        self._model = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=0,
            max_completion_tokens=1_200,
            default_headers=headers,
        )

    async def _structured(
        self,
        schema: type[T],
        system: str,
        human: str,
    ) -> ModelResult[T]:
        raw = await self._model.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=f"{human}\n\n{_json_instruction(schema)}"),
            ]
        )
        text = _content_text(getattr(raw, "content", ""))
        try:
            parsed = schema.model_validate(_json_object(text))
        except Exception as error:
            raise RuntimeError(f"OpenRouter returned invalid structured JSON: {error}") from error
        return ModelResult(value=parsed, usage=_usage(raw))

    async def plan_sql(self, question: str) -> ModelResult[SQLPlan]:
        return await self._structured(SQLPlan, SQL_PLAN_PROMPT, question)

    async def generate_answer(
        self,
        *,
        question: str,
        route: str,
        sql_facts: list[dict[str, Any]],
        evidence: list[Evidence],
        correction: str | None = None,
    ) -> ModelResult[AnswerDraft]:
        payload = {
            "question": question,
            "route": route,
            "sql_facts": sql_facts,
            "evidence": evidence,
            "correction": correction,
        }
        return await self._structured(AnswerDraft, ANSWER_PROMPT, str(payload))
