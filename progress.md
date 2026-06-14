# Project Progress

**Last updated:** 2026-06-14  
**Current phase:** M4 performance/deployment evidence pending  
**Overall status:** Local real-data app is running from Supabase PostGIS and OpenRouter SQL chat is smoke-tested; deployment, Pinecone, LangSmith, and full live-eval release evidence remain pending

## Verified Evidence

- Earlier source inspection established the exact snapshot: 466,398 selected PPD rows, 3 unmatched rows, 27 rows outside the London LAD allowlist, 466,368 final transactions, 105,130 loaded postcodes, and 35 retained rows on terminated postcodes.
- Implemented streaming PPD parsing, selective ONSPD matching, disk-backed global ONSPD duplicate detection, paired-source exact-snapshot gates, source/final date ranges, staged artifact publication, district coverage/size checks, manifests, and validation reports.
- Implemented PostGIS DDL, spatial/generated geometry indexes, dataset metadata, precomputed low-zoom cluster cells, materialized district statistics, read-only grants/password provisioning, client-side bulk loading, manifest row-count checks, and a rollback-safe predicted 450 MB gate in one transaction.
- Implemented FastAPI lifecycle/configuration, repositories, services, uniform errors, cache/CORS/compression/logging middleware, data endpoints, capabilities, chat, SSE, and feedback.
- Implemented and cross-checked the `LPE1` 8+23N binary format in Python and JavaScript.
- Implemented the React first-screen map with MapLibre/OpenFreeMap, deck.gl binary attributes, a web worker, cancellation, debounce, stale-response rejection, bounded cache reuse, labelled clusters, points, lazy choropleth loading, filters, history, errors, mobile layouts, and fully restorative Apply/Undo behavior.
- Implemented a typed LangGraph workflow with SQL/RAG/hybrid/map/unsupported routes, strict SQL/map arguments, Claude structured output, Pinecone retrieval/rerank/outage fallback, mandatory evidence citations, two-pass numeric grounding, hard timeout/cost limits, redacted LangSmith traces, and human-reviewed feedback promotion.
- Added configurable Claude-provider selection: Anthropic direct remains supported, and OpenRouter now works through an OpenAI-compatible LangChain gateway using `AI_PROVIDER=openrouter` plus server-side `OPENROUTER_API_KEY`.
- Hardened the OpenRouter gateway for live Anthropic routing by using prompt-only JSON output plus local Pydantic validation, avoiding provider-side schema features that reject `oneOf`.
- Implemented versioned Pinecone ingestion with deterministic chunk IDs and promotion blocked until a complete eval report passes.
- Added deterministic quality evaluators, baselines, protected live-provider tests, PR CI, nightly/manual live workflow, Render Blueprint, smoke scripts, and measurement scripts.
- Reconciled SPEC, PRD, backend/frontend/system/QA/UI/data-model documents with the implemented required M5 graph, Pinecone/LangSmith behavior, current interfaces, OpenFreeMap attribution, and Apply/Undo semantics.
- Regenerated `docs/openapi.yaml` from FastAPI; all 10 paths are present, including capabilities, chat, SSE, and feedback.
- Added a local SQLite read model for real-data development when `DATABASE_URL` is unset. `scripts/build_local_sqlite.py` streams the downloaded PPD/ONSPD files through the same source validation gates and writes `data/local/lpe-local.sqlite3`.
- Built `data/local/lpe-local.sqlite3` from `/Users/moel/Downloads/pp-complete.csv` and `/Users/moel/Downloads/ONSPD_Online_Latest_Centroids_-966716609290186519.csv`: 466,368 transactions, date range 2021-01-01 to 2026-04-30, 279 postcode districts, file size about 131 MB.
- Restarted the local API on `http://127.0.0.1:8000` with `LOCAL_SQLITE_PATH=data/local/lpe-local.sqlite3`; the existing Vite frontend on `http://127.0.0.1:5174` now renders real local data.
- Verified real local endpoints: `/api/meta`, clusters for a Greater London bbox, binary points (`LPE1`, 25,000 rows, 575,008 bytes, `X-Truncated: true`), and `SW11 4NB` history.
- Tightened implementation/spec alignment: no-store headers on chat/stream/feedback, transaction mode/count request logging, local district payload size warning, London map max bounds, initial zoom 11, point tooltip price/type/date, exact truncation copy, history Esc close, SSE event validation through `schema.js`, and cleaned duplicate `frontend/package.json` engines.
- Reworked the frontend UI/UX to match the supplied PropertyIQ-style references: persistent left navigation, global search/filter toolbar, KPI strip, polished filter card, richer live map overlays/legend/AI callout, integrated AI Copilot panel, and bottom analytics cards while preserving the real-data MapLibre/deck.gl fetch path.
- Fixed shell sizing after the redesign so the app grid is viewport-bound, only dashboard content scrolls, the first screen starts at the top, and the copilot no longer auto-scrolls away from the prompt on empty conversations.
- Refined the map composition so the filter card behaves as a desktop overlay on top of the live map, the map gets a wider central canvas, and the map badges, legend, and AI callout no longer overlap the filter overlay.
- Hardened scheduled map viewport refreshes so intentional aborts during hot reload, navigation, or superseded map requests do not surface as noisy unhandled promise warnings.
- Generated production pipeline artifacts from the validated local sources plus `missinglink/uk-postcode-polygons`: `transactions.csv` 58 MB, `districts.geojson` 329,301 bytes, `validation-report.json` valid, 466,368 final transactions, 279 districts, 105,130 final unique postcodes, 35 terminated-postcode rows retained, and 99.9993568% row-level join coverage.
- Loaded Supabase project `iifcmkixgexxvkxwqnck` through the session pooler with PostGIS schema, `app_reader`, 466,368 transactions, 279 districts, 279 district stats rows, 992 precomputed cluster cells, one dataset metadata row, managed relation size 136,470,528 bytes, and database size 155,913,363 bytes.
- Validated read-only Supabase API behavior through FastAPI TestClient with local SQLite disabled: health 200, meta total 466,368/date range 2021-01-01 to 2026-04-30, full-London zoom-11 clusters 701 cells in about 68 ms, zoom-13 binary points 25,000 rows/575,008 bytes with `X-Truncated: true`, 279 district stats rows, districts GeoJSON 329,301 bytes, and `SW11 4NB` history count 4.
- Configured a local OpenRouter provider key in `.env` without recording the secret. With `LOCAL_SQLITE_PATH=` and Supabase active, `/api/capabilities` reports `chat=true`, `streaming=true`, `rag=false`, `tracing=false`, and `feedback=false`.
- Verified live OpenRouter SQL chat against Supabase: `POST /api/chat` answered the dataset-count question with 466,368 sales, route `sql`, model `anthropic/claude-sonnet-4.5`, grounded validation passed, latency 7,599 ms, input/output tokens 1,090/126, and estimated cost $0.00172.
- Verified `POST /api/chat/stream` emitted `run_started`, `step_started`, completed execution steps, and `final`; the final response again reported 466,368 sales with route `sql`, model `anthropic/claude-sonnet-4.5`, latency 3,822 ms, and estimated cost $0.00172.
- Refreshed the local frontend in the in-app browser after the OpenRouter configuration: the page shows 466,368 loaded sales, the `Ask AI` surface is enabled, no unavailable-state copy is visible, and console error logs are empty.
- Tested the AI agent through the in-app Browser UI: SQL count prompt returned 466,368 sales with visible execution steps and grounded verification; `Highlight SW11 on the map` produced a reversible map action with visible Undo; unsupported weather prompt refused cleanly; browser console errors remained empty.

## Local Validation

| Check | Result |
|---|---|
| `ruff format --check` and `ruff check` | Pass |
| `mypy api pipeline evals scripts` | Pass, 67 source files |
| `pytest -q` | 39 passed, 1 protected live test skipped |
| `npm audit --audit-level=high` | Pass, 0 vulnerabilities |
| Frontend ESLint | Pass |
| Vitest | 4 tests passed |
| Production frontend build | Pass; 569 KB gzip main bundle warning remains for M4 measurement/code-splitting |
| Playwright | 4 journeys passed across desktop and mobile projects |
| Deterministic route replay | 100% route accuracy, 100% unsupported refusal, 0 critical injection failures; live metrics intentionally incomplete |
| In-app visual review | Redesigned local real-data map confirmed in Browser: KPI card shows 466,368 loaded sales, map badge showed `Clusters · 219,500 sales loaded` for the inspected overlay viewport, topbar/sidebar are pinned, copilot starts at the prompt, no map overlay collisions, and no horizontal overflow |
| Local real-data API | `data/local/lpe-local.sqlite3` serves real clusters, points, history, stats, and metadata without Supabase |
| Supabase PostGIS load | Pass: app_reader reads 466,368 transactions, 279 districts, 279 district stats rows, 992 cluster cells, 1 metadata row; database size 149 MB; managed relation size about 130 MB |
| Production-parity API smoke | Pass against Supabase via FastAPI TestClient: meta, clusters, binary points, district stats, districts GeoJSON, and postcode history all returned real data |
| OpenRouter provider adapter | Pass: full backend ruff/mypy/pytest pass; `api/tests/test_ai.py` has 11 tests including OpenRouter local JSON validation. Live `/api/chat` and `/api/chat/stream` SQL smokes pass through OpenRouter against Supabase. |
| Browser AI capability refresh | Pass: `http://127.0.0.1:5174/` shows 466,368 loaded sales, enabled `Ask AI`, no unavailable copy, and no console errors after reload. |
| Browser AI agent test | Pass: UI submitted SQL, map-action, and unsupported prompts through the Copilot; responses, steps, Apply/Undo behavior, and refusal behavior were visible; console errors were empty. |

## Milestone State

| Milestone | State | Remaining release evidence |
|---|---|---|
| M0 Governance and tooling | Complete | None |
| M1 Pipeline and PostGIS | Complete | None |
| M2 FastAPI | Complete with Supabase smoke | Full deployed smoke still belongs to M4 |
| M3 React map | Complete locally with real data | Record performance measurements against production-parity stack |
| M4 Performance and deployment | Pending | Deploy Render/Supabase, run five-run measurements, smoke, 24-hour, and 7-day checks |
| M5 Agentic AI | Implemented, OpenRouter SQL smoke verified | Build Pinecone namespace, enable LangSmith, run complete live eval suite, and pass every release threshold |
| M6 Release gate | Pending | Requires all external evidence above |

## Active Decisions

- SQL is the only authority for counts, prices, medians, rankings, filters, and trends.
- Pinecone stores explanatory evidence only; transaction rows are never embedded.
- Map actions are proposals and require Apply; Undo restores the prior filters/highlight.
- LangSmith failure does not stop chat, but disables feedback and prevents M5 release.
- No unrun deployment, performance, cost, latency, or durability metric is reported as complete.

## Next Work

1. Deploy the API/frontend with `render.yaml` and run `scripts/smoke.sh` and `scripts/measure.sh` against the live URLs.
2. Capture Render/Supabase five-run performance evidence and decide whether any remaining cold-start or serialization tuning is needed.
3. Build a new Pinecone namespace, enable LangSmith tracing, run complete live evals, and promote only after the report passes.
4. Record 24-hour and 7-day durability checks, then close M6.

## Update Rule

Update this file whenever work is completed, blocked, or materially changed. Planned or credential-dependent work must never be presented as verified evidence.
