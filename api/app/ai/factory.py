from __future__ import annotations

from api.app.ai.cost import CostRates
from api.app.ai.graph import AgentRuntime
from api.app.ai.model import ClaudeGateway, ModelGateway, OpenRouterGateway
from api.app.ai.retrieval.base import KnowledgeRetriever, UnavailableRetriever
from api.app.ai.retrieval.pinecone import PineconeKnowledgeRetriever
from api.app.ai.tracing import TraceManager
from api.app.core.config import Settings
from api.app.db.repository import Repository


def create_trace_manager(settings: Settings) -> TraceManager:
    return TraceManager(
        api_key=settings.langsmith_api_key,
        project=settings.langsmith_project,
        enabled=settings.tracing_enabled,
    )


def create_agent_runtime(
    settings: Settings,
    repository: Repository,
    trace_manager: TraceManager,
) -> AgentRuntime | None:
    model = create_model_gateway(settings)
    if model is None:
        return None
    retriever: KnowledgeRetriever = UnavailableRetriever()
    if settings.pinecone_api_key:
        retriever = PineconeKnowledgeRetriever(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index,
            namespace=settings.pinecone_namespace,
            rerank_model=settings.pinecone_rerank_model,
        )
    return AgentRuntime(
        repository=repository,
        model=model,
        retriever=retriever,
        trace_manager=trace_manager,
        corpus_version=settings.pinecone_namespace if settings.pinecone_api_key else None,
        timeout_seconds=settings.agent_timeout_seconds,
        hard_cost_limit_usd=settings.agent_hard_cost_limit_usd,
        cost_rates=CostRates(
            input_per_million=settings.anthropic_input_cost_per_million,
            output_per_million=settings.anthropic_output_cost_per_million,
        ),
    )


def create_model_gateway(settings: Settings) -> ModelGateway | None:
    if settings.ai_provider == "openrouter":
        if not settings.openrouter_api_key:
            return None
        return OpenRouterGateway(
            api_key=settings.openrouter_api_key,
            model_name=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            app_url=settings.openrouter_app_url,
            app_title=settings.openrouter_app_title,
        )
    if not settings.anthropic_api_key:
        return None
    return ClaudeGateway(settings.anthropic_api_key, settings.anthropic_model)
