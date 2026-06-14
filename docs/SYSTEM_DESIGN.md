# System Design — London Property Explorer

**Companion documents:** `../SPEC.md` (build plan & milestones) · `openapi.yaml` (API contract) · `DATA_MODEL.md` · `DATABASE_REQUIREMENTS.md` · `BACKEND_REQUIREMENTS.md` · `FRONTEND_VIEWS.md` · `../schema.js` (frontend contract mirror).

---

## 1. Purpose

A public, free-tier-hosted single-page map application that renders a reproducible snapshot of ~466k standard Category A London price-paid transactions (HM Land Registry, from 2021-01-01 through the source maximum date) as interactive layers. The system demonstrates viewport-bounded querying, zoom-dependent server-side aggregation, lazy layer loading, and measured binary transport.

### Goals
- Smooth (~60 fps) pan/zoom over hundreds of thousands of points on mid-range hardware and phones.
- Never ship more than a bounded, capped slice of data to the browser.
- One measured, documented performance optimisation (JSON → binary transport).
- Zero recurring cost; survives weeks of inactivity (reviewer-proof).

### Non-goals
- No auth, no user accounts, no writes from the client — the dataset is read-only and public.
- No real-time data; the dataset is a static snapshot, reloaded only by re-running the pipeline.
- No multi-region/HA concerns; a single free instance of each component.

---

## 2. Architecture

```
                      ┌────────────────────────────────────────────┐
                      │ Render Static Site (CDN)                   │
   Browser ◀──────────│  /frontend build: React + MapLibre + deck  │
      │               └────────────────────────────────────────────┘
      │  fetch JSON / ArrayBuffer  (CORS: FRONTEND_ORIGIN)
      ▼
┌──────────────────────────────┐         ┌────────────────────────────┐
│ Render Web Service           │  asyncpg│ Supabase Postgres 15+      │
│  FastAPI + uvicorn           │────────▶│  PostGIS                   │
│  /api/transactions (json|bin)│ pool ≤5 │  transactions (~466k rows) │
│  /api/districts, /district-  │         │  districts (~280 polys)    │
│  stats, /postcode/{pc}/      │         │  district_stats (matview)  │
│  history, /meta, /health     │         └────────────────────────────┘
│  /api/chat + SSE             ├──▶ Claude via Anthropic or OpenRouter
│  typed LangGraph             ├──▶ Pinecone curated evidence
│  traces/evals/feedback       ├──▶ LangSmith
└──────────────────────────────┘
      ▲
      │ GET /api/health every 10 min
┌─────┴────────────┐                     ┌────────────────────────────┐
│ Uptime pinger    │                     │ Offline pipeline (local)   │
│ (UptimeRobot)    │                     │  Python: download → filter │
└──────────────────┘                     │  → geocode → \copy load    │
                                         └────────────────────────────┘
```

| Component | Responsibility | Explicitly NOT responsible for |
|---|---|---|
| Frontend (Render Static Site) | Map rendering, layer management, viewport-driven fetching, client cache, interactions, binary decode (web worker) | Filtering the full dataset; any computation over > 25k rows |
| API (Render Web Service) | Validating requests, zoom-dependent SQL, response shaping (JSON/binary), caching headers, CORS, AI rate limiting, typed LangGraph orchestration, trace-safe metrics | Holding the dataset in memory; clustering in Python in production (PostGIS does it); exposing provider credentials |
| Database (Supabase) | Storage, spatial index lookups, grid aggregation, medians | Serving traffic directly to the browser (PostgREST/Supabase client SDK is **not** used) |
| Pinecone | Versioned curated methodology/provenance corpus and integrated retrieval/reranking | Storing or answering from transaction rows |
| LangSmith | Redacted traces, feedback, eval datasets, and regression comparisons | Becoming a runtime dependency for SQL/map availability |
| Pipeline / local builder | Acquiring, cleaning, geocoding, simplifying, loading production PostGIS artifacts; building a local SQLite read model for real-data UI/API testing | Anything at production request time |
| Uptime pinger | Keeping Render warm and Supabase unpaused | Monitoring beyond up/down |

---

## 3. Key design decisions

| # | Decision | Alternative rejected | Rationale |
|---|---|---|---|
| D1 | Server-side grid aggregation below zoom 12, raw capped points above | Client-side supercluster over all points | Can't ship 466k points to cluster client-side without violating the payload thesis; PostGIS `ST_SnapToGrid` + spatial filtering does it in one query. Above zoom 12 the viewport bounds the row count naturally — this *is* the clustering trade-off story. |
| D2 | Plain bbox query API, not tile API, for the core build | MVT/PMTiles from day one | Bbox + debounce is simpler to build and to explain; vector tiles are the documented stretch (11.1) and the comparison itself is a deliverable. |
| D3 | Versioned binary column transport as the measured optimisation | Web-worker JSON parse, memoised styles only | `LPE1` columns feed deck.gl attributes without per-point objects while retaining date + postcode for exact hover/click behavior. Magic/version validation prevents silent decoder drift. |
| D4 | PostGIS on Supabase, queried via plain Postgres protocol (asyncpg) | DuckDB in the API process; Supabase PostgREST/JS client | Spatial index + `percentile_cont` + `ST_SnapToGrid` in one engine; the interview talking point is PostGIS. PostgREST adds a hop and can't express the grid aggregation cleanly. |
| D5 | FastAPI on a persistent Render web service | Serverless functions | Persistent process → ordinary connection pool, in-process caching of the districts GeoJSON, no per-invocation cold start (only idle spin-down, mitigated by pinger). |
| D6 | Supabase direct connection when reachable, otherwise session pooler with asyncpg statement caching disabled | Supavisor transaction-mode pooler with prepared statements enabled | One persistent service needs few connections, but local/direct IPv6 can be unavailable. `statement_cache_size=0` keeps asyncpg compatible with the session-pooler path used for validation. |
| D7 | MapLibre + OpenFreeMap Liberty basemap | Mapbox GL + credentialed styles | Free, no browser token, global coverage, and standard OpenMapTiles/OSM attribution. |
| D8 | Choropleth metric = median price by district | £/m² | PPD has no floor area (see `DATA_MODEL.md` §7); £/m² needs an EPC join — stretch only. |
| D9 | `schema.js` (Zod) as the frontend's contract mirror; Pydantic on the server; `openapi.yaml` authoritative | Codegen from OpenAPI | Hand-kept mirror is tiny (≈10 schemas) and keeps the frontend dependency-light; both sides cite `openapi.yaml` as the source of truth. |

---

## 4. Request lifecycles

### 4.1 Initial load
```
Browser → Static Site: HTML/JS/CSS (CDN, cached)
Browser → OpenFreeMap: basemap style + tiles            [budget: visible < 2 s]
Browser → API: GET /api/meta                            (footer stats)
Browser → API: GET /api/transactions?bbox=…&zoom=11     → clusters mode
deck.gl renders cluster layer                           [budget: < 3.5 s]
```

### 4.2 Pan / zoom (the core loop)
```
map moveend ──▶ debounce 250 ms ──▶ derive mode + integer query zoom
   ──▶ compatible exact/containing cache entry? ──yes──▶ render from cache
        (same cluster zoom; truncated points exact-key only)
        │ no
   ──▶ inflate visible bbox +20% to form request bbox
   ──▶ AbortController.abort() any in-flight request
   ──▶ GET /api/transactions?bbox&zoom[&filters][&format=bin]
        zoom < 12 → SQL grid aggregation → cells JSON
        zoom ≥ 12 → SQL bbox query LIMIT 25001 → points JSON or binary
   ──▶ (binary) worker: validate `LPE1`, decode typed columns + postcode/date
   ──▶ deck.gl layer update                              [budget: < 600 ms p50 warm]
```

### 4.3 Choropleth toggle (lazy loading story)
```
first toggle ON ──▶ parallel: GET /api/districts (GeoJSON ≤ 500 KB, API serves
                    from in-process cache after first DB read)
                    + GET /api/district-stats
             ──▶ client joins stats→features by district code, computes quantile
                 breaks, renders GeoJsonLayer; both cached for the session
later toggles ──▶ instant, no network
```

### 4.4 Point click
```
click point ──▶ card opens with locally-known fields (price/type/date)
            ──▶ postcode comes from the selected JSON/binary row
            ──▶ GET /api/postcode/{pc}/history → address + transaction list
            ──▶ sparkline (inline SVG) of prices over time
```

### 4.5 Conversational data agent (required M5 — full design: `AGENTIC_AI.md`)
```
send message ──▶ POST /api/chat/stream {messages: client-held transcript}
   API: validate + rate limit (10 requests/minute; ≤12 messages / ≤6k chars)
   API: typed LangGraph
        validate → classify → retrieve → SQL tools → map proposal
        → generate → verify grounding (one retry) → finalize
   SQL route ──▶ fixed parameterized PostGIS repository tools
   RAG route ──▶ Pinecone top-20 integrated search → reranked top five
   all nodes ──▶ redacted LangSmith child spans + local metrics fallback
   SSE ──▶ run_started / step_started / step_completed / citation / final / error
client: validates final ChatResponse, renders citations and execution facts,
        and offers Apply for map proposals. Apply preserves an Undo snapshot.
```

---

## 5. Zoom-mode state machine

```
            zoom crosses 12 upward
 ┌──────────┐ ───────────────────────▶ ┌────────┐
 │ clusters │                          │ points │   points mode additionally:
 │ (z < 12) │ ◀─────────────────────── │ (z≥12) │   truncated flag when 25k cap hit
 └──────────┘   zoom crosses 12 down   └────────┘
```
Mode is derived state (`zoom >= CLUSTER_ZOOM_THRESHOLD`), never stored independently. Crossing the threshold always invalidates the current dataset and triggers a fetch (cache keys include the mode).

---

## 6. Performance design — where each budget is enforced

| Budget (from SPEC §6) | Enforced by |
|---|---|
| Payload ≤ 25k points | SQL `LIMIT 25001` + `truncated` flag (API) |
| No megabyte JSON parse on main thread | binary mode decoded in web worker (frontend) |
| No redundant fetches | 250 ms debounce, +20% bbox inflation, zoom/truncation-correct containment LRU, AbortController (frontend) |
| 60 fps interaction | memoised deck layers, binary attributes, ref-based tooltip — no React state per frame (frontend) |
| < 600 ms moveend→render p50 | indexed SQL (GIST) + gzip + small payloads (DB/API) measured via `performance.measure` |
| Choropleth costs nothing until used | lazy load on first toggle (frontend) + in-process GeoJSON cache (API) |

---

## 7. Security

- **No app-owned user database or auth.** The government dataset is public. Chat text is processed transiently; when LangSmith tracing is explicitly enabled, redacted inputs/outputs and execution metadata are sent to that configured observability service.
- **CORS** restricted to `FRONTEND_ORIGIN` + localhost. Not a security boundary (data is public) but keeps the API from becoming someone else's free backend.
- **SQL injection:** all queries parameterized via asyncpg; the only string interpolation permitted is for validated, whitelisted values (none currently needed).
- **Conversational agent:** analytics are selected through validated structured plans and execute fixed read-only repository queries; no model-authored SQL is accepted. RAG can access only versioned curated sources. Map output is a schema-constrained proposal and cannot mutate the browser until Apply. Input/output grounding is checked before finalization.
- **Trace privacy:** emails, phone numbers, UUID-like values, and arbitrary marked sensitive text are anonymized before remote tracing. IP addresses, request bodies, and raw application logs are never attached. Feedback requires a live trace and human review before eval promotion.
- **Secrets:** `DATABASE_URL`, `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`, `PINECONE_API_KEY`, and `LANGSMITH_API_KEY` are Render environment variables only. The browser receives capability booleans, never provider credentials. The Supabase service-role key is never used.
- **DB role:** API connects as a SELECT-only role (`DATABASE_REQUIREMENTS.md` §5).

---

## 8. Failure modes & degradation

| Failure | Detection | Behaviour |
|---|---|---|
| Render cold start (pinger gap) | first request slow | Frontend shows loading state; the OpenFreeMap basemap remains independent, so the page is not blank. Pinger makes this rare. |
| Supabase paused (pinger failed > 7 days) | `/api/health` 5xx | Manual: resume project in Supabase dashboard. Mitigated by pinger; checked at the 24 h re-verify. |
| DB query timeout (> 5 s statement timeout) | asyncpg error | API → `503 {error:{code:"DB_TIMEOUT"}}`; frontend keeps last good layer + shows retry toast. |
| Oversized/invalid bbox or params | API validation | `400 {error:{code:"BAD_REQUEST", message}}`; frontend treats as a bug, logs to console. |
| 25k cap hit | `truncated: true` | Status pill: "25,000+ loaded — zoom in" — degradation is explicit without claiming an exact visible count for the inflated bbox. |
| Pinecone unavailable | retrieval exception or missing capability | SQL questions continue; RAG-only questions state that source retrieval is unavailable. |
| Pinecone reranking quota exhausted | rerank call fails | Retry raw integrated retrieval, keep the top five, and mark the trace/response degraded. |
| LangSmith unavailable | trace operation fails | Chat continues with local structured metrics; feedback is disabled and M5 cannot pass release. |
| Selected Claude provider unavailable or grounding fails twice | provider exception or verifier result | Return a clean AI error without presenting an unsupported answer; the core map is unchanged. |
| Whole-graph timeout or cost cap | 25 s deadline or estimated cost > configured cap | Abort the turn and return the uniform error envelope; the core map is unchanged. |
| OpenFreeMap outage | map error event | Data layers and controls remain mounted; source attribution remains visible. Accepted external risk. |

---

## 9. Operations

- **Environments:** local (preferred quick path: `scripts/build_local_sqlite.py` from the downloaded CSVs, then FastAPI with `LOCAL_SQLITE_PATH`; production-parity path: plain local Postgres+PostGIS, a dev Supabase project, or `supabase start` **with a Docker-compatible container runtime**; frontend `npm run dev`, API `uvicorn --reload`) and production (Render + Supabase). No staging.
- **Deploy:** push to `main` → Render auto-deploys both services per `render.yaml`.
- **Monitoring:** uptime pinger on `/api/health`, structured Render request logs, local AI metrics, and redacted LangSmith traces/evals when enabled. Release checks include immediate, 24-hour, and 7-day smoke evidence.
- **Data refresh:** re-run pipeline locally → `\copy` into fresh tables → `REFRESH MATERIALIZED VIEW district_stats` → `ANALYZE`. Zero-downtime not required.

---

## 10. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Constrained Render free instance too slow gzipping 25k-point JSON | Medium | Binary mode is smaller and cheaper to produce; gzip level 5; measured budgets catch it at M2. If the hard ceiling still fails, stop and make an explicit hosting/architecture decision per SPEC §2; there is no assumed free fallback. |
| Supabase free CPU makes full-London grid aggregation slow | Low–Medium | GIST index + bbox always present; tune cell size; if needed, pre-aggregate low-zoom cells into a table at pipeline time (documented deviation) |
| ONSPD postcode/schema drift | Low | Pipeline logs row-level join coverage and aborts below 99.9%; current measured coverage before LAD validation is 99.99936% |
| ONSPD sentinel/invalid coordinates | Low | Parse finite numbers, validate WGS84 and broad UK bounds, then apply the London LAD allowlist; the current final set has zero invalid coordinates |
| PPD county label includes non-London postcodes | Certain, small | ONSPD `LAD25CD` allowlist is authoritative; current snapshot removes 27 otherwise-valid rows |
| District polygons repo gaps for some outward codes | Low | Districts missing geometry are dropped from the choropleth only; points unaffected; note count in README |
| Free-tier policies change | Low | Everything reproducible from pipeline + `render.yaml`; swapping hosts is config, not code |
| Keep-alive consumes the shared Render free-instance allowance | Medium | Keep exactly one always-on free web service in the workspace, monitor usage, and verify the URL after 24 h; static sites do not need a pinger |
