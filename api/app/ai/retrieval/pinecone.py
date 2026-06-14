from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, PrivateAttr

from api.app.ai.retrieval.base import RetrievalResult
from api.app.ai.state import Evidence


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


class PineconeLangChainRetriever(BaseRetriever):
    """LangChain adapter over Pinecone integrated text search."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    index_name: str
    namespace: str
    rerank_model: str
    api_key: str
    _index: Any = PrivateAttr()
    _last_degraded: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        from pinecone import Pinecone

        self._index = Pinecone(api_key=self.api_key).Index(self.index_name)

    def _search(self, query: str, *, rerank: bool) -> list[Document]:
        options: dict[str, Any] = {
            "namespace": self.namespace,
            "query": {"inputs": {"text": query}, "top_k": 20},
            "fields": [
                "chunk_text",
                "source_url",
                "publisher",
                "title",
                "section",
                "licence",
                "source_hash",
                "corpus_version",
            ],
        }
        if rerank:
            options["rerank"] = {
                "model": self.rerank_model,
                "top_n": 5,
                "rank_fields": ["chunk_text"],
            }
        response = self._index.search(**options)
        result = _value(response, "result", response)
        hits = list(_value(result, "hits", []))[:5]
        documents: list[Document] = []
        for hit in hits:
            fields = _value(hit, "fields", {}) or {}
            metadata = dict(fields)
            metadata["id"] = str(_value(hit, "_id", _value(hit, "id", "")))
            metadata["score"] = _value(hit, "_score", _value(hit, "score"))
            documents.append(
                Document(page_content=str(fields.get("chunk_text", "")), metadata=metadata)
            )
        return documents

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        del run_manager
        try:
            self._last_degraded = False
            return self._search(query, rerank=True)
        except Exception:
            self._last_degraded = True
            return self._search(query, rerank=False)

    async def _aget_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        del run_manager
        return await asyncio.to_thread(self._get_relevant_documents, query, run_manager=None)


class PineconeKnowledgeRetriever:
    def __init__(self, *, api_key: str, index_name: str, namespace: str, rerank_model: str) -> None:
        self._adapter = PineconeLangChainRetriever(
            api_key=api_key,
            index_name=index_name,
            namespace=namespace,
            rerank_model=rerank_model,
        )

    async def retrieve(self, query: str) -> RetrievalResult:
        try:
            documents = await self._adapter.ainvoke(query)
        except Exception:
            return RetrievalResult(evidence=[], degraded=True)
        evidence: list[Evidence] = []
        for document in documents:
            metadata = document.metadata
            evidence.append(
                {
                    "id": str(metadata.get("id", "")),
                    "content": document.page_content,
                    "title": str(metadata.get("title", "Untitled source")),
                    "section": metadata.get("section"),
                    "publisher": str(metadata.get("publisher", "Unknown publisher")),
                    "url": str(metadata.get("source_url", "")),
                    "licence": metadata.get("licence"),
                    "score": metadata.get("score"),
                }
            )
        return RetrievalResult(evidence=evidence, degraded=self._adapter._last_degraded)
