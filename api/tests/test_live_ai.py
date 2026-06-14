from __future__ import annotations

import os

import pytest

from api.app.ai.cost import CostRates
from api.app.ai.factory import create_model_gateway
from api.app.ai.graph import AgentRuntime
from api.app.ai.retrieval.pinecone import PineconeKnowledgeRetriever
from api.app.ai.tracing import TraceManager
from api.app.core.config import Settings
from api.app.db.pool import create_pool
from api.app.db.repository import PostgresRepository
from api.app.models import ChatMessage, ChatRequest

pytestmark = [
    pytest.mark.live_ai,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_AI") != "1", reason="protected live suite"),
]


@pytest.mark.asyncio
async def test_live_sql_and_rag_routes() -> None:
    settings = Settings()
    assert settings.database_url
    assert settings.ai_enabled
    assert settings.pinecone_api_key
    assert settings.langsmith_api_key
    model = create_model_gateway(settings)
    assert model is not None
    pool = await create_pool(settings.database_url)
    try:
        repository = PostgresRepository(pool)
        await repository.health()
        trace = TraceManager(
            api_key=settings.langsmith_api_key,
            project=settings.langsmith_project,
            enabled=True,
        )
        runtime = AgentRuntime(
            repository=repository,
            model=model,
            retriever=PineconeKnowledgeRetriever(
                api_key=settings.pinecone_api_key,
                index_name=settings.pinecone_index,
                namespace=settings.pinecone_namespace,
                rerank_model=settings.pinecone_rerank_model,
            ),
            trace_manager=trace,
            corpus_version=settings.pinecone_namespace,
            timeout_seconds=settings.agent_timeout_seconds,
            hard_cost_limit_usd=settings.agent_hard_cost_limit_usd,
            cost_rates=CostRates(
                input_per_million=settings.anthropic_input_cost_per_million,
                output_per_million=settings.anthropic_output_cost_per_million,
            ),
        )
        sql = await runtime.run(
            ChatRequest(messages=[ChatMessage(role="user", content="How many sales are recorded?")])
        )
        rag = await runtime.run(
            ChatRequest(
                messages=[ChatMessage(role="user", content="What is the source methodology?")]
            )
        )
        assert sql.metrics.route == "sql"
        assert rag.metrics.route == "rag"
        assert rag.citations
        assert trace.enabled
    finally:
        await pool.close()
