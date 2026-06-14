# Functional Requirements Document — London Property Explorer

System-level functional requirements, numbered for traceability. Priorities follow the PRD's MoSCoW scope. Each requirement is testable; acceptance criteria (AC) state how. Traces point to the implementing docs: `openapi.yaml` (endpoints), `BACKEND_REQUIREMENTS.md` (B-#), `FRONTEND_VIEWS.md` (views V#/layers L#), `DATABASE_REQUIREMENTS.md` (queries Q#).

Conventions: "the system" = frontend + API + DB acting together. **Must/Should/Could** per PRD §5.

---

## FR-100 Map & navigation

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-101 | Must | The app shall present an interactive labelled OpenFreeMap map of Greater London (pan, zoom, pinch, double-tap), opening centred on central London. | Map interactive < 2 s broadband; touch gestures work on a phone. | V1; UI/UX §4 |
| FR-102 | Must | Map navigation shall remain responsive while data layers are loading; data fetches shall never block input. | Pan during an in-flight fetch is smooth; no input freezes in a 30 s interaction trace. | V1; FRONTEND_VIEWS §4 |
| FR-103 | Must | The map shall constrain panning to a loose Greater-London bounding region. | Panning to Scotland is not possible. | V1 |

## FR-200 Transactions layer

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-201 | Must | At zoom < 12 the system shall display server-aggregated clusters: position, size ∝ member count, colour by median price, count labels on larger cells. | Full-London view renders 200–800 cells; labels legible; no individual points visible. | L1; B-21; Q1 |
| FR-202 | Must | At zoom ≥ 12 the system shall display individual sale points coloured by price, capped at 25,000 per viewport. | Zoom-13 dense view shows discrete points; payload row count ≤ 25,000. | L2; B-21; Q2 |
| FR-203 | Must | Crossing zoom 12 shall switch modes; changing integer zoom below 12 shall refresh the zoom-sized cluster grid. | Zooming 10→11 changes aggregation scale; 11→12→11 swaps cluster/point rendering without stale mixed states. | FRONTEND_VIEWS §3,4 |
| FR-204 | Must | The system shall fetch only viewport-bounded data, debounced ≥ 250 ms after camera rest, cancelling superseded requests, with a +20 % bbox margin and a zoom/truncation-correct cache. | Contained untruncated data reuses cache; cluster zoom changes miss; truncated point entries never satisfy a different contained viewport. | FRONTEND_VIEWS §4; B-21 |
| FR-205 | Must | When the point cap is hit, the UI shall state it explicitly without calling the inflated request count an exact visible count. | Dense viewport shows "25,000+ loaded — zoom in". | FR-601; V3 |
| FR-206 | Should | Points-mode data shall be transferable as packed binary, decoded off the main thread, and rendered from binary attributes. | `format=bin` round-trip renders identically to JSON; decode runs in a worker (verified in profiler); README table populated per SPEC §8. | B-30; `schema.js`; FRONTEND_VIEWS §4 |
| FR-207 | Must | Hovering a point or cluster (pointer devices) shall show a tooltip within one frame: price/type/date for points; count + median for clusters. | Tooltip follows cursor at 60 fps in a trace. | V1; UI/UX §6 |
| FR-208 | Should | Clicking a cluster shall zoom toward it (drill-down). | Click on cell flies to +2 zoom centred on the cell. | L1 |

## FR-300 Choropleth

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-301 | Must | The system shall offer a toggleable district-level choropleth of **median sale price** by postcode district, off by default and loaded on first use. | Toggle renders the complete district set with blue intensity by median and a distinct highlighted district. | L3; B-22/23; Q4 |
| FR-302 | Must | Choropleth data (geometry + stats) shall load lazily on first toggle and be cached for the session. | No `/api/districts` request before first toggle; second toggle is instant (no network). | FRONTEND_VIEWS §6.2 |
| FR-303 | Must | A legend shall always explain the active colour scale with £-formatted bin edges. | Legend visible whenever a data layer is; bins match rendered colours. | V5; UI/UX §5 |
| FR-304 | Must | Districts lacking stats or geometry shall render neutral / be omitted without error, and the choropleth shall be labelled as unfiltered all-data medians. | No console errors with partial coverage; caption "District medians · all sales" visible. | FRONTEND_VIEWS §5,6.3 |
| FR-305 | Must | Hovering a district shall show its code, median price, and sales count. | "SW11 — median £740k, 4,102 sales". | L3 |

## FR-400 Filters

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-401 | Must | Users shall be able to filter transactions by property type (D/S/T/F/O, multi-select), tenure (F/L), and price range (min/max). | Selecting "Flats" + "Leasehold" + max £500k updates clusters *and* points to matching subset (server-filtered). | V2; B-21 |
| FR-402 | Must | Filters shall apply to both transaction modes and persist across zoom/pan until changed. | Filter set at zoom 10 still applied after zooming to 14 and panning. | FRONTEND_VIEWS §6.3 |
| FR-403 | Must | An active-filter state shall be visible and clearable in one action. | Chips show selected state; "Clear" resets to all data. | V2; UI/UX §5 |
| FR-404 | Should | Date-range filtering shall be supported by the API (`from`/`to`) and exposed in the UI. | Date menu and filter-panel date inputs update the server query params and map results. | B-21; V2 |

## FR-500 Property card

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-501 | Must | Clicking a sale point shall open a card with the selected row's postcode address and sale history (latest ≤ 200 entries, newest first): price, date, type, tenure, new-build flag. | JSON and binary clicks use the carried postcode; shared-centroid postcodes resolve separately; histories over 200 show an explicit older-entries notice. | V4; B-24; Q3 |
| FR-502 | Must | The card shall include a price-over-time sparkline of the postcode's sales. | SVG sparkline renders with ≥ 2 entries; degrades to text for 1 entry. | V4; UI/UX §5 |
| FR-503 | Must | The card shall open instantly with locally-known data (skeleton for the rest) and be dismissible via ✕, Esc, or map click. | Card visible within one frame of click; all three dismissals work. | FRONTEND_VIEWS §6.1 |
| FR-504 | Must | The card shall present as a side panel ≥ 768 px width and a bottom sheet below. | Verified at 1280 px and 375 px. | UI/UX §4 |

## FR-600 Status, feedback & honesty

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-601 | Must | A persistent status element shall show loading state and the count loaded for the fetched viewport slice, including the truncation message (FR-205). | All five pill states reachable (FRONTEND_VIEWS §8). | V3 |
| FR-602 | Must | Data-fetch failures shall never blank the map: last good layer persists, an error state with retry appears. | Killing the network mid-session leaves the map rendered + toast with working Retry. | FRONTEND_VIEWS §9 |
| FR-603 | Must | A slow first response (server cold start) shall be explained to the user, with automatic retry. | Throttled first load shows "Waking the server…" after 3 s; recovers unaided. | FRONTEND_VIEWS §9 |
| FR-604 | Must | Source attribution (HM Land Registry OGL, ONS, district-boundary OSM/ODbL, and OpenFreeMap/OpenMapTiles/OSM basemap) and dataset totals/date range shall be permanently visible. | Footer formats live `/api/meta` values and preserves the MapLibre attribution control; no dataset count/date is hard-coded. | V7; B-26; SPEC §10 |

## FR-700 Conversational data agent (required M5; design: `AGENTIC_AI.md`)

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-701 | Must | Users shall be able to ask multi-turn questions about prices, volumes, trends, postcode-district comparisons, methodology, provenance, and limitations. | Route accuracy ≥95%, end-to-end task success ≥90%, and SQL arguments ≥95% on the pinned eval set. | V6; B-27; TC-AI1 |
| FR-702 | Must | Every answer shall expose citations and execution facts without exposing hidden reasoning. | Citation validity and numeric groundedness are 100%; expandable steps name completed/degraded operations and durations. | `ChatResponse`; TC-AI2 |
| FR-703 | Must | The agent shall use a typed, bounded graph with fixed parameterized SQL tools, curated RAG, validated inputs, one grounding retry, a 25-second timeout, and a $0.08 hard cost cap. | Unsupported refusal is 100%, critical injection failures are zero, and over-budget/timeout/grounding failures return clean envelopes without unsupported answers. | B-27; SYSTEM_DESIGN §7 |
| FR-704 | Must | AI availability shall be capability-driven and provider credentials shall never reach the browser. | Missing selected Claude-provider credential → `chat=false`; missing Pinecone → `rag=false` while SQL chat continues; missing LangSmith → `feedback=false`. | `GET /api/capabilities` |
| FR-705 | Must | A generated map change shall be a validated proposal requiring explicit Apply and supporting Undo. | No map state changes on receipt; Apply uses ordinary map/filter state, and Undo restores the prior state. | `MapAction`; FRONTEND_VIEWS §6.4 |
| FR-706 | Must | The agent shall state dataset limits instead of improvising when facts are unavailable. | Questions about bedrooms, true £/m², rentals, or proximity produce a limitation/refusal without fabricated numbers. | AGENTIC_AI; TC-AI2 |
| FR-707 | Must | Traces, feedback, and evals shall form a human-reviewed quality loop. | Every graph operation has redacted trace metadata when enabled; negative feedback attaches to the root trace; promotion to a versioned eval case requires explicit review. | LangSmith; TC-AI4 |
| FR-708 | Must | AI latency and cost shall be measured and release-gated. | First SSE event p95 <1 s; full response p50 <6 s and p95 <14 s; typical turn ≤$0.02 and p95 ≤$0.05; no critical regression or task-success drop >2 points. | Eval baseline; release CI |

## FR-800 System behaviours (cross-cutting functional)

| ID | Pri | Requirement | Acceptance criteria | Trace |
|---|---|---|---|---|
| FR-801 | Must | The deployed system shall remain functional after arbitrary idle periods on free tiers. | Keep-alive pinger configured on `/api/health`; live URL verified after 24 h+ idle. | SPEC §7 step 5; B-20 |
| FR-802 | Must | The full row dataset shall never be transferred to a client; every transaction response is viewport-bounded, with raw points capped and low zooms aggregated. | No response contains > 25k raw rows; full-London low-zoom response contains only the tuned aggregate-cell set. | B-21 |
| FR-803 | Must | All data responses shall be HTTP-cacheable for 1 h (static dataset). | `Cache-Control: public, max-age=3600` on data endpoints. | B-12 |
| FR-804 | Must | The app shall be fully usable on a 375 px-wide touch device. | All Must-requirements above pass on a phone. | UI/UX §7 |
| FR-805 | Must | Errors shall use one machine-readable envelope across all endpoints. | Non-2xx bodies match `ApiError` schema, incl. validation failures. | B-13 |

---

## Out of scope (explicitly not requirements)

Accounts/auth/saved state · writes of any kind from clients · £/m² metrics (no floor-area data — `DATA_MODEL.md` §7) · real-time or scheduled data refresh · coverage beyond Greater London · analytics/tracking · localisation (en-GB only) · IE/legacy browser support (evergreen browsers, last 2 versions).

## Verification summary

Must-requirements gate their milestone per SPEC §9 (M2: FR-2xx; M3: FR-3xx–6xx; M4: FR-206, FR-8xx). Each AC is checked by direct manipulation, the API test suites (B-40/41/42), or the SPEC §8 measurement protocol. The hallway test (PRD §6) covers the integrated journey.
