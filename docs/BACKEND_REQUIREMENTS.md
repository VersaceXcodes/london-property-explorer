# Backend Requirements — London Property Explorer API

Functional and non-functional requirements for the FastAPI service in `/api`. Contract: `openapi.yaml` (authoritative). SQL: `DATABASE_REQUIREMENTS.md` §5. AI design: `AGENTIC_AI.md`. Requirements are numbered `B-#` for traceability; each must be verifiably true before its milestone closes.

---

## 1. Runtime & deployment

- **B-1** Python 3.12, FastAPI, uvicorn (`uvicorn main:app --host 0.0.0.0 --port $PORT`), single worker. The deployment is a constrained free instance; benchmark its current limits instead of encoding provider CPU/RAM marketing values into implementation logic.
- **B-2** Deployed as a Render **Web Service** defined in `/render.yaml`; health check path `/api/health`.
- **B-3** Runtime dependencies are pinned by compatible ranges in `pyproject.toml`: FastAPI/uvicorn, asyncpg, Pydantic settings, LangGraph/LangChain, Anthropic direct, OpenRouter through the OpenAI-compatible LangChain adapter, Pinecone, LangSmith, SSE, HTTP/YAML/HTML ingestion support. Test and static-analysis dependencies are isolated in the `dev` extra.
- **B-4** App structure under `/api/app`: `api/routes` (HTTP contracts), `core` (configuration/errors/middleware), `db` (pool/queries/repository), `services` (domain behavior/binary encoding), and `ai` (typed graph, tools, retrieval, prompts, tracing, evaluation). Routes do not contain SQL or provider-specific orchestration.

### Environment variables (documented in `/.env.example`)

| Var | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes in production | Supabase direct connection string or session-pooler string; the API disables asyncpg statement caching for pooler safety. When unset locally, the API may use `LOCAL_SQLITE_PATH` |
| `LOCAL_SQLITE_PATH` | no | Local-only read model built from the real downloaded CSVs by `scripts/build_local_sqlite.py`; not a production substitute for PostGIS |
| `FRONTEND_ORIGIN` | yes (prod) | CORS allow-origin, e.g. `https://lpe.onrender.com` |
| `AI_PROVIDER` | no | `anthropic` or `openrouter`; default `anthropic` |
| `ANTHROPIC_API_KEY` | no | Enables chat when `AI_PROVIDER=anthropic`; absent → `/api/capabilities.chat=false` and chat returns 503 |
| `ANTHROPIC_MODEL` | no | Default `claude-haiku-4-5` |
| `OPENROUTER_API_KEY` | no | Enables chat when `AI_PROVIDER=openrouter`; server-side only |
| `OPENROUTER_MODEL` | no | Default `anthropic/claude-sonnet-4.5` |
| `OPENROUTER_BASE_URL` | no | Default `https://openrouter.ai/api/v1` |
| `OPENROUTER_APP_URL` / `OPENROUTER_APP_TITLE` | no | Optional OpenRouter attribution headers |
| `PINECONE_API_KEY` | no | Enables curated RAG; absent → SQL routes continue and RAG reports source retrieval unavailable |
| `PINECONE_INDEX` | no | Default `lpe-knowledge-v1` |
| `PINECONE_NAMESPACE` | no | Active, versioned corpus namespace |
| `PINECONE_EMBED_MODEL` | no | Default `llama-text-embed-v2` for ingestion/index creation |
| `PINECONE_RERANK_MODEL` | no | Default `bge-reranker-v2-m3` |
| `LANGSMITH_API_KEY` | no | Enables remote traces and feedback attachment |
| `LANGSMITH_PROJECT` | no | Trace project, default `london-property-explorer` |
| `LANGSMITH_TRACING` | no | Explicit remote-tracing switch, default `false` |
| `AGENT_HARD_COST_LIMIT_USD` | no | Per-turn hard cap, default `0.08` |
| `AGENT_TIMEOUT_SECONDS` | no | Whole-graph timeout, default `25` |
| `MAX_POINTS` | no | Default 25000 |
| `CELL_PX` | no | Grid cell pixel size, default 32 |

---

## 2. Cross-cutting requirements

- **B-10 CORS:** `CORSMiddleware` allowing the configured `FRONTEND_ORIGIN` plus `http://localhost:5174`, methods `GET, POST, OPTIONS`, no credentials, and exposing `X-Truncated` and `X-Request-ID`.
- **B-11 Compression:** `GZipMiddleware` (minimum_size=1024, compresslevel=5). Applies to JSON; the binary payload is served as-is because the measured optimisation prioritises low serialization/CPU overhead. Never set `Content-Encoding` unless bytes were actually encoded.
- **B-12 Caching headers:** all `GET` data endpoints → `Cache-Control: public, max-age=3600`; health, capabilities, chat, stream, and feedback responses → `no-store`.
- **B-13 Error envelope:** every non-2xx body is `{"error": {"code": <enum per openapi.yaml>, "message": <human string>}}`. FastAPI validation errors are mapped to `BAD_REQUEST` (not the default 422 shape) via an exception handler, so the frontend sees one error shape everywhere.
- **B-14 DB access:** production uses one module-level asyncpg pool (`min_size=1, max_size=5`, `statement_cache_size=0`), created on startup, closed on shutdown. All production SQL is parameterized; `statement_timeout` 5 s (role-level per `DATABASE_REQUIREMENTS.md` §2). Pool exhaustion / timeout → `503 DB_TIMEOUT`. Local development may use the read-only SQLite repository generated from the same source snapshot; it must preserve the public API contract but does not replace PostGIS release/performance evidence.
- **B-15 Logging:** one structured line per request: method, route template (not raw postcode path/query string), status, duration ms, response bytes, and for `/api/transactions` the mode + row/cell count. No request bodies or full postcodes in logs.
- **B-16 In-process caches:** districts GeoJSON (Q4) and `/api/meta` result cached at first use for process lifetime (dataset is static). No other caching layer.

---

## 3. Per-endpoint requirements

### B-20 `GET /api/health`
`SELECT 1` against the pool. 200 `{"status":"ok"}` / 503 envelope. This is the uptime-pinger target — it must touch the DB (keeps Supabase unpaused), and must not be cached.

### B-21 `GET /api/transactions`
1. Validate per `openapi.yaml`: bbox parses to 4 finite floats, legal lng/lat ranges, min<max; zoom 0–22; real ISO calendar dates; prices are integers in 0–50,000,000 with `min_price ≤ max_price`; `from ≤ to`; types are unique and ⊆ {D,S,T,F,O}. Violations → 400 `BAD_REQUEST` (malformed bbox → `BAD_BBOX`).
2. **Points-mode guard:** if `zoom ≥ 12` and bbox spans > 2.0° on either side → 400 `BAD_BBOX` (prevents "whole world at zoom 12" abuse).
3. `zoom < CLUSTER_ZOOM_THRESHOLD` → Q1 with `cell = 40075016.686 / 2^zoom / 256 * CELL_PX`; unfiltered zooms 6–11 use precomputed `cluster_cells`, while filtered requests use the exact dynamic aggregation over `transactions`. Respond `{mode:"clusters", cells:[…]}`. `format=bin` is ignored in clusters mode.
4. `zoom ≥ threshold` → Q2 (`LIMIT MAX_POINTS+1`); pop the sentinel row → `truncated`.
   - `format=json` (default): `{mode:"points", truncated, points:[…]}`.
   - `format=bin`: encode per **B-30**; `Content-Type: application/octet-stream`, header `X-Truncated: true|false`.

### B-22 `GET /api/districts`
Q4 GeoJSON, in-process cache (B-16), `Content-Type: application/geo+json`. Total payload must be < 500 KB — assert at startup-time first build and log a warning if exceeded (the fix is pipeline-side simplification, not API-side).

### B-23 `GET /api/district-stats`
Q4 stats projection, JSON array.

### B-24 `GET /api/postcode/{postcode}/history`
Normalise input (upper-case, strip, remove internal whitespace; validate the no-space form against `^[A-Z]{1,2}[0-9][0-9A-Z]?[0-9][A-Z]{2}$`; insert one space before the final 3 chars). Invalid shape → 400. Run Q3 with `LIMIT 201`; empty → 404. Pop the sentinel if present and return `count=len(entries)`, `truncated=true`; otherwise false. Response per `PostcodeHistory`.

### B-26 `GET /api/meta`
Q4 meta from `dataset_meta`, cached (B-16).

### B-27 AI interfaces and runtime (required M5; full design: `AGENTIC_AI.md`)
1. `GET /api/capabilities` reports chat, RAG, tracing, streaming, feedback, graph version, and active corpus namespace. Missing credentials for the selected model provider disable chat; missing Pinecone disables only RAG; missing LangSmith disables feedback.
2. `POST /api/chat` and `POST /api/chat/stream` share one `AgentRuntime`. The stream emits `run_started`, `step_started`, `step_completed`, `citation`, `final`, and `error`; `final` is exactly schema-valid `ChatResponse`.
3. Rate limit chat endpoints to 10 requests/minute per process-local client key. Never include that key or an IP address in traces or application logs.
4. Validate transcripts: ≤12 messages, first and last are `user`, roles alternate, each user message ≤500 characters, and total text ≤6,000 characters. Violations use the uniform error envelope.
5. Execute a typed LangGraph with nodes `validate_input`, `classify_route`, `retrieve_evidence`, `execute_sql_tools`, `propose_map_action`, `generate_response`, `verify_grounding`, and `finalize`. Routes are `sql`, `rag`, `hybrid`, `map_action`, and `unsupported`.
6. Numeric analytics use only fixed, parameterized repository operations selected through validated structured output. The model never emits executable SQL. RAG searches only the curated knowledge corpus and never embeds transaction rows.
7. Pinecone retrieval requests 20 candidates and reranks to five with `bge-reranker-v2-m3`; reranking failure falls back to raw search and marks the response degraded. Complete source metadata becomes explicit response citations.
8. `ChatResponse` contains `run_id`, `reply`, `citations`, execution-fact `steps`, optional proposed `map_action`, `degraded`, and metrics for route, latency, tokens, estimated cost, graph/prompt/model/corpus versions. Steps never expose hidden reasoning.
9. Map actions are inert, strictly validated `set_filters` or `highlight_district` proposals. The browser applies them only after user confirmation and retains filters, highlight, and layer mode for Undo.
10. Enforce the configured whole-graph timeout (default 25 seconds) and hard estimated-cost cap (default $0.08). Grounding validation retries generation once and then returns a clean `AI_GROUNDING_FAILED` error.
11. LangSmith receives redacted root runs and child spans for graph nodes, retrieval, model calls, SQL tools, validation, and retries. Traces record versions, route, usage, cost, latency, retrieved IDs, and validation output without raw logs or IP addresses.
12. `POST /api/chat/{run_id}/feedback` accepts thumbs up/down, reason, and optional correction only while LangSmith tracing is healthy. Reviewed negative traces may be exported to eval datasets; feedback is never promoted automatically.

---

## 4. B-30 Binary points encoding (authoritative)

Version `LPE1`, little-endian throughout. For N points from Q2 (after the truncation pop), in Q2's deterministic row order:

| Offset | Type | Content |
|---|---|---|
| 0 | `Uint8 × 4` | ASCII magic/version `LPE1` |
| 4 | `Uint32` | N |
| 8 | `Float32 × N` | longitude |
| 8 + 4N | `Float32 × N` | latitude |
| 8 + 8N | `Uint32 × N` | price (GBP) |
| 8 + 12N | `Uint16 × N` | UTC days since 1970-01-01 |
| 8 + 14N | `Uint8 × N` | typeCode: D=0 S=1 T=2 F=3 O=4 |
| 8 + 15N | `Uint8 × 8N` | canonical postcode, exactly 8 null-padded ASCII bytes per row |

Total `8 + 23N` bytes (~575 KB at the 25k cap). Implementation: preallocate one `bytearray` and fill it with explicit little-endian `struct.pack_into` calls, or byteswap standard-library arrays when the host is not little-endian; `numpy` is not a declared dependency. Reject a postcode that is non-ASCII or longer than 8 bytes instead of truncating it, and reject dates outside the `Uint16` epoch-day range instead of wrapping. The decoder lives in `/schema.js`; layout changes require a new magic/version and matching changes to OpenAPI and tests.

Float32 note: ~0.3 m worst-case error at London latitudes — below the postcode-centroid precision. Date and postcode remain exact, avoiding ambiguous coordinate-to-postcode lookup where multiple postcodes share a centroid.

---

## 5. Performance requirements (measured on Render free tier, warm)

| Endpoint | p50 | p95 |
|---|---|---|
| `/api/transactions` clusters (full-London) | < 400 ms | < 1 s |
| `/api/transactions` points 25k JSON | < 500 ms | < 1.2 s |
| `/api/transactions` points 25k binary | < 300 ms | < 800 ms |
| history / stats / meta | < 100 ms | < 300 ms |

These include DB time (`DATABASE_REQUIREMENTS.md` §6) and serialization. The JSON-vs-binary delta feeds the README performance table (SPEC §8) — record real numbers.

## 6. Testing requirements

- **B-40 Unit:** param validation matrix for B-21 (valid/invalid bbox, zoom edges 11/12, filter combinations); cell-size formula; binary encoder round-trip (encode in Python → decode with a JS test via the layout constants, or a Python re-decoder asserting byte offsets); postcode normalisation cases (`sw114nb`, `SW11 4NB`, ` sw11 4nb `).
- **B-41 Integration:** against a loaded dev database — each endpoint returns schema-valid responses; zoom 11 vs 12 mode switch; deterministic capped selection; truncation flag at a dense bbox; 404 paths; binary postcode/date identity remains exact for two fixture postcodes sharing one centroid.
- **B-42 Smoke (post-deploy):** scripted curl of every endpoint against the live URL asserting status + content-type + non-empty payload; run after each deploy and at the 24 h re-verify (SPEC §7 step 6).

## 7. Non-goals

No auth, no sessions, no writes, no migrations framework (schema = re-load), no Redis/external cache, no Celery/queues, no WebSockets. If a requirement seems to need one of these, the requirement is being misread.
