# QA / Testing Specification — London Property Explorer

Test strategy, levels, tooling, key test cases, traceability to `FUNCTIONAL_REQUIREMENTS.md` (FR-#) and `BACKEND_REQUIREMENTS.md` (B-#), and the exit gates each SPEC milestone must pass. Philosophy: **risk-based and lightweight** — this is a 3–5 evening build; testing effort concentrates where failure embarrasses (data correctness, the reviewer journey, the live URL staying alive) and stays thin elsewhere.

---

## 1. Strategy

| Risk | Why it matters | Covered by |
|---|---|---|
| Wrong data (bad join, price/coord swap, broken median) | Product is worthless if numbers are wrong | Pipeline assertions + API integration tests |
| Contract drift (API ↔ `schema.js` ↔ binary layout) | Silent frontend breakage | Contract tests + binary round-trip |
| Reviewer journey breaks (P1 persona) | The whole point of the project | E2E journeys + manual device pass |
| Dead URL after idle weeks | Brief's explicit "what not to do" | Post-deploy smoke + 24 h re-verify + pinger check |
| Performance regressions | The README claims numbers | SPEC §8 protocol + budget checks |

Out of scope: load/stress testing beyond stated budgets, security penetration testing, fuzzing, cross-browser beyond evergreen (Chrome, Firefox, Safari last-2), localisation testing.

## 2. Test levels & tooling

| Level | Tooling | Lives in | Runs |
|---|---|---|---|
| Pipeline data checks | plain Python asserts in pipeline scripts | `/pipeline` | every pipeline run (blocking) |
| Backend unit | `pytest` | `/api/tests` | local + pre-deploy |
| Backend integration | `pytest` + `httpx` against a seeded local SQLite/PostGIS DB | `/api/tests` with `integration` marker when external DB is required | local + pre-deploy |
| Contract | response validation: Pydantic models (server side) + `zod` `parse()` against recorded fixtures (client side) | both test trees | with unit suites |
| Frontend unit | `vitest` | `/frontend/src/**/*.test.ts` | local + pre-deploy |
| E2E | Playwright (Chromium; WebKit for the mobile pass), against local full stack | `/frontend/e2e` | before each milestone close |
| Performance | SPEC §8 scripted protocol + Lighthouse (mobile preset) | manual, documented | M2 and M4 |
| Accessibility | Lighthouse a11y + axe DevTools + manual keyboard pass | manual | M3 |
| Post-deploy smoke | bash + `curl` (`scripts/smoke.sh`) | `/scripts` | after every deploy + 24 h re-verify |

Pull-request CI runs deterministic Python, frontend, contract, and replay checks. Protected nightly/manual CI runs live providers. Every suite also remains runnable locally with one command (`pytest`, `npm test`, `npm run e2e`, `./scripts/smoke.sh <url>`).

## 3. Test environments & data

| Env | Stack | Data |
|---|---|---|
| Local | uvicorn + Vite dev + generated SQLite read model, or local/dev Supabase | **Real local dataset**: `scripts/build_local_sqlite.py` builds `data/local/lpe-local.sqlite3` from the downloaded PPD/ONSPD files so the map can be tested without cloud PostGIS. Deterministic unit tests also build a tiny SQLite fixture in temp storage. |
| Local-full | local/dev Supabase or Supabase production project | Full validated 466,368-row snapshot in PostGIS — required for performance protocol and EXPLAIN checks (`DATABASE_REQUIREMENTS.md` §6) |
| Production | Render + Supabase | Full dataset; smoke + Lighthouse only — no test writes exist anywhere (read-only system) |

Fixture invariants (the "golden numbers"): exact row count, exact median for 2 known districts, one postcode with ≥ 5 sales, one postcode with exactly 1 sale, **two distinct postcodes sharing an identical centroid**, and a bbox that yields > cap rows when `MAX_POINTS` is lowered.

## 4. Key test cases

### Pipeline (TC-P)
- **TC-P1** For the hashes in `SOURCE_DATA_PROFILE.md`, checkpoint counts exactly match the manifest: 466,398 pre-join, 3 unmatched, 27 outside London LAD, 466,368 final, including 35 final rows on terminated ONSPD postcodes. For different snapshots, final count must remain 400k–550k or the pipeline aborts.
- **TC-P2** Row-level ONSPD join coverage ≥ 99.9%; every loaded row has numeric coordinates and `LAD25CD` in `E09000001`–`E09000033`. Include a source row whose county says Greater London but LAD is outside London and assert it is rejected.
- **TC-P3** Spot-check 5 known transactions against the source CSV (price, date, postcode survive the pipeline untouched).
- **TC-P4** District GeoJSON total size < 500 KB; every feature has a `code`; codes are unique.
- **TC-P5** `district_stats` median for a hand-computed district matches `percentile_cont` expectation exactly.
- **TC-P6** Postcode canonicalisation handles irregular whitespace, retains terminated ONSPD postcodes, and produces max 8-byte ASCII display values suitable for binary encoding.
- **TC-P7** ONSPD canonical keys are unique; non-finite/out-of-range coordinate fixtures are rejected; final rows are all in the London LAD allowlist and broad UK coordinate sanity box. Enum-domain drift (`property_type`, `old_new`, `duration`) aborts before CSV output.
- **TC-P7** `source-manifest.json` records source sizes/SHA-256, min/max dates, processing time, all exclusion counts, final count, join coverage, and outside-London count.

### Backend unit (TC-B)
- **TC-B1** bbox validation matrix: malformed, inverted, out-of-range, >2°-at-points-zoom → `BAD_BBOX`; valid passes (B-21.1/2).
- **TC-B2** zoom boundary: 11 → clusters branch; 12 → points branch (FR-203 server half).
- **TC-B3** Filter param matrix incl. `min>max` → 400; types whitelist; tenures whitelist/duplicate rejection; date parsing.
- **TC-B4** Cell-size formula: expected metres at zooms 8/10/11 (Q1 constant).
- **TC-B5** Binary encoder: encode fixture rows → assert `LPE1` magic, N, exact `8+23N` length, offsets, little-endian values, epoch dates, type codes, and null-padded postcodes. Bad magic, short/trailing bytes, over-cap N, non-ASCII/overlength postcode all fail closed.
- **TC-B6** Postcode normalisation: `sw114nb`, ` SW11  4NB `, `Sw11 4Nb` → `SW11 4NB`; garbage → 400.
- **TC-B7** Error envelope: every handler path returns `ApiError` shape, including FastAPI validation rewrites (B-13).

### Backend integration (TC-I, seeded fixture DB)
- **TC-I1** Each endpoint returns 200 + schema-valid body (Pydantic round-trip) + correct `Cache-Control` (B-12) and content-type.
- **TC-I2** Clusters: sum of `cells[].count` over a bbox == direct `count(*)` for same bbox/filters (no rows lost/duplicated by gridding).
- **TC-I3** Points: row set for a small bbox matches direct SQL; a capped dense bbox returns centre-nearest then UUID deterministically across repeated calls; `truncated` flips correctly with `MAX_POINTS=10`.
- **TC-I4** Filters actually filter (type F query returns only F) in both modes.
- **TC-I5** History: deterministic date/UUID descending order, ≤ 200 returned, `truncated` flips with a 201-row fixture, all nullable address keys present, and 404 on unknown postcode.
- **TC-I6** JSON vs binary same-bbox equivalence: identical ordered rows by position/price/type/date/postcode (within Float32 tolerance); `X-Truncated` matches JSON `truncated`. The shared-centroid fixture proves each selected postcode opens its own history.
- **TC-I7** CORS: response carries the allow-origin for `FRONTEND_ORIGIN`, not `*`, and exposes `X-Truncated` so browser JavaScript can read it.

### Frontend unit (TC-F)
- **TC-F1** `decodePointsBinary`: backend-written golden buffer decodes every column; `postcodeAt` and `isoDateFromEpochDay` return exact values; invalid magic, wrong length, and over-cap count throw.
- **TC-F2** `interleavePositions` correctness; `transactionsParams` builds exact query strings including type/tenure/date filters, floors fractional map zoom, omits null filters, and rejects invalid bbox/zoom/filter ranges or unknown formats.
- **TC-F3** Quantile `computeBreaks`: known arrays → known breaks; degenerate inputs (all-equal, n<5) don't crash.
- **TC-F4** Fetch-loop logic: debounce and stale-drop; compatible contained cluster/untruncated-point entries hit; cluster integer-zoom changes miss; different filters miss; truncated points hit only on exact key and miss for a different contained viewport; superseded requests abort.
- **TC-F5** `safeParse` guards: a contract-drifted fixture logs and falls through without throwing (FRONTEND_VIEWS §9).

### E2E journeys (TC-E, Playwright)
- **TC-E1 The reviewer journey** (mirrors UI/UX §3): load → clusters visible → zoom to 13 → points visible → click point → card with history + sparkline → toggle choropleth → legend updates. Single test, must always pass — this is the product.
- **TC-E2** Truncation: dense viewport (cap lowered via env) shows the "zoom in for all" pill text (FR-205/601).
- **TC-E3** Filters: select Flats + max price → pill count drops; clear → restores (FR-401–403).
- **TC-E4** Failure honesty: route-abort `/api/transactions` mid-session → map keeps last layer, toast with Retry works (FR-602).
- **TC-E5** Mobile viewport (375×812, WebKit): FAB opens controls, tap point opens bottom sheet, swipe dismisses (FR-804, UI/UX §4).
- **TC-E6** Choropleth laziness: no `/api/districts` request before first toggle; none on second toggle (FR-302) — asserted via Playwright network log.

### Performance (TC-PERF — protocol, not pass/fail automation)
- **TC-PERF1** SPEC §8 protocol: 5-run medians for JSON vs binary (payload, decode, moveend→render) on the fixed script — feeds the README table; numbers must be real.
- **TC-PERF2** Budgets table (SPEC §6) checked on deployed URL: first layer < 3.5 s, bundle < 1 MB gz, pan trace ≥ ~50 fps.
- **TC-PERF3** `EXPLAIN (ANALYZE, BUFFERS)` on Q1/Q2 with full data: index scan present, targets per `DATABASE_REQUIREMENTS.md` §6.
- **TC-PERF4** Lighthouse mobile on deployed URL: Perf ≥ 80, A11y ≥ 95 (UI/UX §11).

### Accessibility (TC-A11Y, manual, at M3)
- **TC-A11Y1** Keyboard-only: full reviewer journey minus map-canvas picking; Esc closes card; visible focus ring throughout (UI/UX §9).
- **TC-A11Y2** axe scan: zero critical violations on default view, card open, choropleth on.
- **TC-A11Y3** Pill `aria-live` announces count/truncation changes (VoiceOver spot-check).
- **TC-A11Y4** `prefers-reduced-motion` disables flyTo animation and transitions.

### Conversational data agent (TC-AI — required M5; details in `AGENTIC_AI.md`)
- **TC-AI1 Deterministic replay:** route accuracy ≥95%, SQL structured arguments ≥95%, unsupported refusal 100%, and zero critical prompt-injection failures. Unit tests cover the classifier, structured plans, cost calculation, redaction, citations, and grounding verifier without provider calls.
- **TC-AI2 Grounding:** fixture-backed SQL answers have numeric groundedness 100%; RAG answers have citation validity 100%; retrieval datasets achieve recall@5 ≥90%. Missing or invented evidence IDs fail the case.
- **TC-AI3 Contracts and limits:** invalid transcript shapes fail uniformly; the 11th request/minute receives 429; timeout, $0.08 cap, provider failure, and a second grounding failure return clean errors. `ChatResponse`, every SSE event, feedback body, Pydantic, OpenAPI, and Zod remain compatible.
- **TC-AI4 Degradation and privacy:** no selected Claude-provider credential disables chat; no Pinecone preserves SQL and declines unsupported RAG; rerank failure returns raw top-five evidence with `degraded=true`; no LangSmith disables feedback. Trace fixtures contain versions/usage/cost/latency/retrieved IDs/validation but no IP, raw request log, email, phone, UUID, or marked sensitive text.
- **TC-AI5 Reviewer journey:** Playwright covers streaming status, citations, expandable execution facts, thumbs feedback, map proposal Apply/Undo, failure UI, and 390 px mobile behavior. The map never changes before Apply.
- **TC-AI6 Live release suite:** protected manual/nightly CI uses a real Claude provider, Pinecone, and LangSmith credentials; compares to the pinned baseline; requires end-to-end success ≥90%, first SSE event p95 <1 s, response p50 <6 s/p95 <14 s, typical cost ≤$0.02/p95 ≤$0.05, and no task-success regression >2 percentage points.

### Post-deploy smoke (`scripts/smoke.sh <base-url>`) (TC-S)
- **TC-S1** Every endpoint: expected status, content-type, non-empty/schema-plausible body; `/api/transactions` both modes; binary bytes 0–3 equal ASCII `LPE1` and bytes 4–7 decode to a count consistent with `Content-Length`.
- **TC-S2** CORS preflight from `FRONTEND_ORIGIN` passes.
- **TC-S3** Frontend URL serves the app shell (200, contains the title string).
- **TC-S4** Re-run the script ≥ 24 h after deploy **and** once ≥ 7 days after (Supabase pause check) — calendar reminders, results noted in the PR/commit.

## 5. Traceability (FR → tests)

| FR group | Covered by |
|---|---|
| FR-1xx map | TC-E1, TC-E5, TC-PERF2 |
| FR-2xx transactions | TC-B1–5, TC-I2–4, TC-I6, TC-F1–4, TC-E1–3, TC-PERF1/3 |
| FR-3xx choropleth | TC-P4/5, TC-I1, TC-E1, TC-E6 |
| FR-4xx filters | TC-B3, TC-I4, TC-E3 |
| FR-5xx card | TC-I5, TC-E1, TC-E5 |
| FR-6xx honesty/status | TC-E2, TC-E4, TC-A11Y3 |
| FR-7xx chat agent | TC-AI1–4 |
| FR-8xx system | TC-S1–4, TC-I7, TC-I1 (cache headers) |

## 6. Milestone exit gates

| Milestone | Must pass before closing |
|---|---|
| M1 | TC-P1–P5; manual: dots visible on local map |
| M2 | TC-B1–4, TC-I1–4; TC-PERF3; manual mode-switch check |
| M3 | TC-E1, TC-E3, TC-E5, TC-E6; TC-A11Y1–4; UI/UX §10 states checklist walked |
| M4 (release) | full suites green; TC-B5, TC-I6, TC-F1; TC-PERF1/2/4; TC-S1–3 on production; TC-E2/E4 |
| Post-release | TC-S4 (24 h and 7-day re-verifies) |
| M5 (if 11.2 ships) | TC-AI1–4 |

## 7. Defect policy

| Sev | Definition | Action |
|---|---|---|
| S1 | Reviewer journey broken, wrong data shown, dead URL | Fix before anything else; blocks release |
| S2 | A Must-FR fails off the golden path; budget miss > 25 % | Fix before milestone close |
| S3 | Should/Could degradation, visual polish, copy | Fix in polish pass or log in README known-issues |

One regression rule: any S1/S2 fix adds a test that would have caught it.
