# Agentic AI — Implemented M5 Design

The required M5 assistant answers questions about the London Property Explorer, proposes reversible map changes, and explains source methodology. It uses a typed LangGraph workflow, LangChain provider adapters, Claude structured output through Anthropic direct or prompt-only JSON with local Pydantic validation through OpenRouter, Pinecone retrieval, and LangSmith traces/evaluations.

## Grounding Boundary

- Counts, prices, medians, rankings, filters, and trends come only from parameterized PostGIS tools.
- Pinecone is used only for HMLR/ONS methodology, licensing, provenance, limitations, and curated project documentation.
- Transaction rows are never embedded.
- A map action is a proposal. The browser applies it only after the user selects Apply; Undo restores the prior state.
- Steps expose execution facts and timing, never hidden reasoning or chain-of-thought.

## Typed Graph

```text
START
  -> validate_input
  -> classify_route
  -> retrieve_evidence
  -> execute_sql_tools
  -> propose_map_action
  -> generate_response
  -> verify_grounding -- retry once --> generate_response
  -> finalize
  -> END
```

Routes are `sql`, `rag`, `hybrid`, `map_action`, and `unsupported`. Prompt-injection patterns and out-of-scope requests route to a bounded refusal. SQL planning uses Pydantic discriminated unions; repository methods map only to fixed read-only queries.

## Retrieval

- Pinecone index: `lpe-knowledge-v1`.
- Serverless region: AWS `us-east-1`.
- Integrated embedding: `llama-text-embed-v2` over `chunk_text`.
- Query: retrieve 20 candidates and rerank to 5 with `bge-reranker-v2-m3`.
- Reranking failure: repeat integrated search without reranking, return raw top five, and mark the run degraded.
- Chunks are heading-aware, approximately 1,500 characters with 200-character overlap.
- IDs are SHA-256 of source hash, section, and chunk content.
- Metadata includes source URL, publisher, title, section, licence, retrieval date, source hash, and corpus version.

Every rebuild targets a new namespace. `--promote` requires a complete eval report with `release_passed=true` before atomically changing `PINECONE_NAMESPACE` in the selected environment file.

## Public Contract

- `GET /api/capabilities`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/chat/{run_id}/feedback`

The transcript contains at most 12 alternating messages, starts and ends with `user`, limits each user message to 500 characters, and limits total content to 6,000 characters.

```json
{
  "run_id": "uuid",
  "reply": "string",
  "citations": [],
  "steps": [],
  "map_action": null,
  "degraded": false,
  "metrics": {
    "route": "sql",
    "latency_ms": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0,
    "graph_version": "lpe-agent-v1",
    "prompt_hash": "string",
    "model": "string",
    "corpus_version": null
  }
}
```

SSE event order is `run_started`, `step_started`, zero or more `step_completed`, zero or more `citation`, then `final` or `error`. The first two events are emitted before graph execution.

## Verification And Cost

The answer validator checks that cited IDs were retrieved and that numeric claims appear in the user question or SQL facts. A failed check triggers one corrected generation. A second failure returns `AI_GROUNDING_FAILED` without an answer.

The runtime records input/output tokens and estimates cost from configurable model rates. The response is rejected if estimated cost exceeds `$0.08`. The complete request has a 25-second timeout.

## Tracing And Feedback

The root LangSmith trace and child spans record graph version, prompt hash, model, corpus version, route, tokens, estimated cost, latency, SQL plan, retrieved IDs, validation result, degradation, and retry outcome.

Emails, phone numbers, UUIDs, authorization fields, and IP fields are redacted. Raw IP addresses and request bodies are never added to trace metadata or application logs. When LangSmith is unavailable, chat continues with response-local metrics; feedback returns `FEEDBACK_UNAVAILABLE` and M5 cannot pass release.

Thumb feedback, reason, and optional correction attach to the root trace. Negative traces are not promoted automatically. `scripts/promote_eval_case.py` requires a human reviewer identity and appends a versioned eval case.

## Failure Behaviour

| Failure | Behaviour |
|---|---|
| No selected model-provider key | Capabilities report chat disabled; chat endpoints return `AI_UNAVAILABLE` |
| Pinecone unavailable | SQL questions continue; RAG-only questions state source retrieval is unavailable |
| Rerank quota exhausted | Raw top-five retrieval; trace and response marked degraded |
| LangSmith unavailable | Chat continues; feedback disabled; release blocked |
| Model-provider failure | Clean error, no unsupported answer |
| Grounding fails twice | `AI_GROUNDING_FAILED` |
| SQL timeout | Common database error envelope; existing map data remains rendered |
| Hard timeout | `AI_TIMEOUT` |
| Cost cap exceeded | `AI_COST_LIMIT` |

## Release Gates

- Route accuracy at least 95%.
- SQL tool arguments at least 95%.
- Numeric groundedness and citation validity exactly 100%.
- Retrieval recall@5 at least 90%.
- End-to-end task success at least 90%.
- Unsupported refusal exactly 100%; critical injection failures zero.
- First SSE event p95 below 1 second.
- Full response p50 below 6 seconds and p95 below 14 seconds.
- Typical turn at most `$0.02`, p95 at most `$0.05`, hard cap `$0.08`.
- No critical regression and no task-success reduction greater than two percentage points.

PR CI runs deterministic unit, integration-fake, contract, browser, and route replay tests. The protected nightly/manual workflow uses live credentials. Promotion and release remain blocked until the complete live report passes.
