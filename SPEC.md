# London Property Explorer — Implementation Specification

**Audience:** an autonomous coding agent implementing this project end-to-end.
**Goal:** a single-page map application rendering the validated ~466k standard Category A London price-paid snapshot as interactive, performant map layers, with a live URL, public repo, and a README documenting one measured performance optimisation.
**Time budget mindset:** ship in 3–5 working sessions. Shipped and documented beats perfect. Do not gold-plate.

---

## 1. Hard constraints (non-negotiable)

1. **Free tiers only, kept alive.** The reviewer URL must still work three weeks after deployment: no expiring trials and no paid Mapbox tier. MapLibre GL JS (not Mapbox GL) requires no token. Render free web services spin down after 15 minutes without inbound traffic and the workspace receives 750 free instance hours per calendar month; Supabase may pause low-activity free projects. An external pinger hitting `/api/health` (which touches the DB) every 10 minutes is therefore required. Use a Render workspace with no other always-on free web service and monitor monthly usage because the allowance is shared per workspace.
2. **One repo, one live URL.** Monorepo containing pipeline, API, and frontend.
3. **No secrets in the repo.** `.env.example` documents every variable; real values come from platform environment variables. `DATABASE_URL`, `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`, `PINECONE_API_KEY`, and `LANGSMITH_API_KEY` are server-side only and are never shipped to the browser.
4. **Never ship the full dataset to the browser.** All point data is served viewport-bounded and capped. This is the central thesis of the project.
5. **Real data, honest numbers.** Performance numbers in the README must be actually measured, not estimated or invented. If a measurement wasn't taken, don't claim it.
6. **Works on mobile.** Touch pan/zoom, readable UI at 375 px width, tested before calling any milestone done.

---

## 2. Architecture

```
┌─────────────────────────┐      ┌──────────────────────────┐      ┌─────────────────┐
│ Frontend (Vite + React  │HTTPS │ API (FastAPI, Python)    │ SQL  │ PostgreSQL +    │
│ + TS + MapLibre GL JS   │─────▶│ Render Web Service       │─────▶│ PostGIS         │
│ + deck.gl overlay)      │ CORS │ viewport-bounded queries │      │ (Supabase free) │
│ Render Static Site      │      │ zoom-dependent agg       │      └─────────────────┘
└─────────────────────────┘      └──────────────────────────┘              ▲
                                                                           │
                              offline pipeline (Python, run locally) ──────┘
```

- **Frontend:** TypeScript + React + Vite. MapLibre GL JS renders the OpenFreeMap Liberty style (`https://tiles.openfreemap.org/styles/liberty`) and deck.gl (`@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/mapbox` `MapboxOverlay`) renders the data layers. The basemap requires no browser credential and retains OpenMapTiles/OpenStreetMap attribution.
- **Backend:** FastAPI (Python 3.12) + uvicorn, deployed as a Render **Web Service** from `/api`. The frontend lives on a different origin, so the API enables CORS restricted to the frontend's Render URL (`FRONTEND_ORIGIN`) plus localhost and explicitly exposes `X-Truncated`. Production connects to Supabase Postgres with a small asyncpg pool over the direct connection string when reachable, or the session pooler when direct IPv6 is unavailable; asyncpg statement caching is disabled so the pooler path is safe. Local real-data testing can instead use `LOCAL_SQLITE_PATH`, generated from the same source CSVs, while PostGIS remains the release/performance target. Request/response models are Pydantic; `docs/openapi.yaml` is authoritative and `/schema.js` is the frontend's Zod mirror.
- **Database:** Supabase free tier Postgres with the PostGIS extension (enable via `CREATE EXTENSION postgis;` or the dashboard). Expected footprint ≈ 180–300 MB including indexes; deployment is blocked at 450 MB to preserve headroom within the current 500 MB free quota. Supabase free projects may pause after sustained low activity — the keep-alive pinger in §7 prevents this.
- **Pipeline:** Python scripts run locally (not deployed) that download, filter, geocode, and load the data into Supabase over the direct (port 5432) connection.

If Render's free tier cannot meet the measured acceptance criteria, stop and record the failed criterion. There is no pre-approved free fallback: Fly.io's general free allowance is legacy-only for existing organisations, so it does not satisfy this build's free-only constraint for a new account. Any hosting replacement requires an explicit architecture decision and a fresh verification of current pricing, persistence, sleep, and quota rules.

Provider assumptions were last verified on **2026-06-13** against the official [Render free-service documentation](https://render.com/docs/free), [Supabase pricing](https://supabase.com/pricing), and [Supabase local-development requirements](https://supabase.com/docs/guides/local-development). Re-check them at deployment; provider terms are not stable project constants.

### Repository layout

```
/frontend/          Vite app (TypeScript, React) — deployed as a Render Static Site
/api/               FastAPI app — deployed as a Render Web Service
/pipeline/          download / filter / geocode / load scripts (Python) + SQL DDL
/data/              raw + intermediate files (gitignored)
/docs/              design documents: PRD, functional requirements, UI/UX, QA/test spec,
                    system design, openapi.yaml, data model, DB/backend/frontend requirements
schema.js           Zod mirror of the API contract, consumed by the frontend (Vite alias `@schema`)
README.md
SPEC.md             this file
.env.example
render.yaml         Render Blueprint defining both services
```

---

## 3. Data pipeline (run once, locally)

### 3.1 Sources

| Dataset | Source | Licence |
|---|---|---|
| HM Land Registry Price Paid Data (PPD), complete CSV snapshot | gov.uk "Price Paid Data downloads" page; use `pp-complete.csv` so one immutable input drives the build | OGL; attribution required |
| Postcode → lat/lng centroids | ONS Postcode Directory (ONSPD), latest edition, from the ONS Open Geography Portal (`geoportal.statistics.gov.uk`). Acceptable lighter alternative: Open Postcode Geo single-CSV distribution (ONSPD-derived, OGL) | OGL |
| Postcode-district boundary polygons | `https://github.com/missinglink/uk-postcode-polygons` (GeoJSON per postcode area, OSM-derived) | ODbL; attribution required |

If any URL is dead at build time, locate the current official download on the same publisher's site. Do **not** substitute a different dataset.

The validated local inputs are `$HOME/Downloads/pp-complete.csv` and
`$HOME/Downloads/ONSPD_Online_Latest_Centroids_-966716609290186519.csv`.
Paths are CLI arguments, never hard-coded in application code. The pipeline writes
`pipeline/output/source-manifest.json` containing each source's basename, byte size,
SHA-256, processing timestamp, source min/max dates, and all row-count checkpoints.
Commit the small manifest; git-ignore the multi-GB sources and generated clean CSV.
The inspected hashes, value domains, nullability, unique-postcode counts, and geographic
bounds for this snapshot are recorded in `docs/SOURCE_DATA_PROFILE.md`. Exact baseline
counts apply only when those hashes match.

### 3.2 Source formats

PPD has **no header row**. Column order:

```
1 transaction_id (GUID)   2 price (int)        3 date_of_transfer
4 postcode                5 property_type      6 old_new (Y/N)
7 duration (F/L)          8 paon               9 saon
10 street                 11 locality          12 town_city
13 district               14 county            15 ppd_category (A/B)
16 record_status (A/C/D)
```

`property_type`: D=detached, S=semi, T=terraced, F=flat, O=other.

The downloaded ONSPD CSV has a header. Required fields are `PCDS` (display
postcode), `DOTERM` (termination date), `LAD25CD` (local-authority code), `LAT`,
and `LONG`. Terminated postcodes are deliberately retained: historical sales can
legitimately refer to them. For this snapshot, ONSPD contains 2,723,596 data rows
and PPD contains 31,270,275 rows.

### 3.3 Transformations

1. Read both CSVs as streams with a standards-compliant CSV parser (quoted fields, UTF-8/UTF-8-SIG); never split rows manually and never load either multi-GB file fully into memory. Resolve ONSPD fields by header name, not numeric position, because portal exports may append columns.
2. PPD filter: `date_of_transfer >= 2021-01-01`, `county == "GREATER LONDON"`, `ppd_category == "A"` (standard-price-paid records), `record_status == "A"`, non-empty postcode, and price between £10,000 and £50,000,000. Abort if a supposedly consolidated `pp-complete.csv` contains `C`/`D` records; update files require change/delete application and are not accepted as substitutes.
3. Canonicalise each postcode by uppercasing, removing all whitespace, validating against `^[A-Z]{1,2}[0-9][0-9A-Z]?[0-9][A-Z]{2}$`, then inserting one space before the final 3 characters. Keep both canonical display form (`SW11 4NB`) and a no-space join key (`SW114NB`) during processing.
4. Join the PPD key to ONSPD `PCDS` normalised by the same function. Require finite WGS84 coordinates (`LONG` in `[-180,180]`, `LAT` in `[-90,90]`); retain rows regardless of `DOTERM`. Log unmatched rows and codes. Abort on duplicate canonical ONSPD keys rather than choosing an arbitrary row.
5. Enforce actual Greater London membership after the join: require `LAD25CD` in the explicit allowlist `E09000001`–`E09000033`. The PPD county label is only a coarse prefilter and is not authoritative.
6. Derive `district` from the canonical postcode's outward part (everything before the space, e.g. `SW11`).
7. Build the district boundary file: merge the per-area GeoJSONs from uk-postcode-polygons, keep only districts present in the transaction data, validate/fix geometry, and simplify with topology preservation so the final districts payload is **< 500 KB**.
8. Write a load-ready CSV plus the source manifest. Load with `\copy` over the direct (port 5432) connection, never row-by-row inserts; refresh materialized views and run `ANALYZE`.

Validated baseline for the downloaded June 2026 snapshot:

| Checkpoint | Rows |
|---|---:|
| Greater London county label, date from 2021, Category A, valid postcode/price | 466,398 |
| Failed ONSPD coordinate join | 3 |
| Joined postcode resolves outside Greater London LAD allowlist | 27 |
| **Final load** | **466,368** |
| Diagnostic: final rows using a terminated ONSPD postcode | 35 |

The source maximum transfer date is **2026-04-30**. Runtime copy must call this
dataset "since January 2021" or "2021–present snapshot", not a rolling "last five
years" dataset. `/api/meta` remains the source of truth for displayed count and
date range. The selected PPD rows contain only property types D/S/T/F, new-build codes
Y/N, and tenures F/L; `saon` and `street` are nullable. Abort outside 400k–550k rows,
if row-level join coverage drops below 99.9%, if enum domains drift, or if any retained
coordinate falls outside the broad UK sanity box (`LONG [-9,3]`, `LAT [49,61]`). Those
conditions indicate source/schema drift, not normal loss. See the full measured profile
in `docs/SOURCE_DATA_PROFILE.md`.

### 3.4 Schema (DDL lives in `/pipeline/schema.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE transactions (
  id            uuid PRIMARY KEY,
  price         integer NOT NULL CHECK (price BETWEEN 10000 AND 50000000),
  date          date NOT NULL CHECK (date >= DATE '2021-01-01'),
  postcode      text NOT NULL CHECK (postcode ~ '^[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}$'),
  district      text NOT NULL CHECK (district ~ '^[A-Z]{1,2}[0-9][0-9A-Z]?$'),
  property_type char(1) NOT NULL CHECK (property_type IN ('D','S','T','F','O')),
  is_new        boolean NOT NULL,
  tenure        char(1) NOT NULL CHECK (tenure IN ('F','L')),
  paon text, saon text, street text, town text,
  geom          geometry(Point, 4326) NOT NULL,
  geom_3857     geometry(Point, 3857)
                GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED
);
CREATE INDEX transactions_geom_idx     ON transactions USING gist (geom);
CREATE INDEX transactions_district_idx ON transactions (district);
CREATE INDEX transactions_date_idx     ON transactions (date);
CREATE INDEX transactions_postcode_idx ON transactions (postcode);

CREATE TABLE districts (
  code text PRIMARY KEY,
  geom geometry(MultiPolygon, 4326) NOT NULL
);

CREATE MATERIALIZED VIEW district_stats AS
SELECT district,
       count(*)                                              AS sales,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::int AS median_price
FROM transactions
GROUP BY district;

CREATE UNIQUE INDEX district_stats_pk ON district_stats (district);
```

> **Important data caveat:** PPD contains **no floor-area field**, so true price-per-m² is not computable from this dataset alone. The required choropleth metric is therefore **median sale price by postcode district**. True £/m² via an EPC-register join is stretch goal 11.4 only. Do not burn core time on it.

---

## 4. API (FastAPI)

The core data/system endpoints are `GET`. M5 adds `GET /api/capabilities`, `POST /api/chat`, `POST /api/chat/stream`, and `POST /api/chat/{run_id}/feedback`. Static data responses set `Cache-Control: public, max-age=3600`; health, capabilities, chat, stream, and feedback are `no-store`. JSON responses are gzip-compressed (`GZipMiddleware`). The authoritative contract is `docs/openapi.yaml`.

### 4.1 `GET /api/transactions`

Query params: `bbox=minLng,minLat,maxLng,maxLat` (required), `zoom` (required, integer), and optional filters `min_price`, `max_price`, `types` (comma-separated D/S/T/F/O), `tenures` (comma-separated F/L), `from`, `to` (ISO dates).

Behaviour is **zoom-dependent** — this is the server-side vs client-side clustering story:

- **`zoom < 12` → aggregated mode.** PostGIS grid aggregation in Web Mercator (`ST_SnapToGrid(geom_3857, cell, cell)`), with `cell = 40075016.686 / 2^zoom / 256 * CELL_PX` and default `CELL_PX=32`; tune within 24–64 so a full-London view returns 200–800 cells. Each cell: member centroid (lng/lat), `count`, `median_price`.

  ```json
  { "mode": "clusters",
    "cells": [ {"lng": -0.12, "lat": 51.5, "count": 1843, "median_price": 612000}, … ] }
  ```

- **`zoom >= 12` → points mode.** Raw rows within the bbox, capped at **25,000** (`LIMIT 25001`, set `"truncated": true` if the extra row came back). Selection is deterministic: order by distance to the requested bbox centre, then transaction UUID. This keeps the most relevant central points when capped and prevents arbitrary subsets/flicker. Fields: `id`, `lng`, `lat`, `price`, `type`, `date`, `postcode`.

  ```json
  { "mode": "points", "truncated": false,
    "points": [ {"id": "…", "lng": -0.168, "lat": 51.46, "price": 850000, "type": "T", "date": "2024-03-15", "postcode": "SW11 4NB"}, … ] }
  ```

- **Binary variant (`&format=bin`, points mode only):** versioned `application/octet-stream` ArrayBuffer. Header = ASCII magic `LPE1` + little-endian `uint32 count`; column blocks then contain `Float32` lng, `Float32` lat, `Uint32` price, `Uint16` days since `1970-01-01`, `Uint8` type code, and fixed-width 8-byte null-padded ASCII canonical postcode. Total = `8 + 23N` bytes. Postcode and date are required so hover and click remain exact even when multiple postcodes share an ONSPD centroid. `X-Truncated` carries the cap flag and must be exposed through CORS. This is the §8 optimisation — build JSON first, add `bin` in M4.

Validate bbox bounds (reject world-spanning boxes > 2° on a side at point zooms with HTTP 400) and clamp all filters server-side.

### 4.2 `GET /api/districts` and `GET /api/district-stats`

- `/api/districts` → the simplified district polygons as a single GeoJSON `FeatureCollection` (each feature: `code`). Served once, lazily, when the user first toggles the choropleth.
- `/api/district-stats` → `[{ "district": "SW11", "sales": 4102, "median_price": 740000 }, …]`. Joined to polygons client-side so the polygon payload stays cacheable and metric changes don't re-ship geometry.

### 4.3 `GET /api/postcode/{postcode}/history`

Transactions for one postcode (the click-card data source): address fields,
price, date, type, tenure, newest first, capped at 200 with an explicit `truncated`
flag when older rows exist. Both JSON and binary point
payloads carry the canonical postcode. There is deliberately no coordinate-to-postcode
endpoint: different postcodes can share an ONSPD centroid, so nearest-point resolution
would be ambiguous.

### 4.4 `GET /api/meta`

`{ "total": 466368, "from": "2021-01-01", "to": "2026-04-30" }` for the validated snapshot; values are always queried from the loaded table and are never hard-coded in the UI.

---

## 5. Frontend

### 5.1 Map and layers

- MapLibre map, OpenFreeMap Liberty style, initial view: central London (`[-0.118, 51.509]`, zoom 11), `maxBounds` loosely around Greater London.
- deck.gl layers via `MapboxOverlay`:
  - **Cluster layer** (zoom < 12): `ScatterplotLayer` of cells — radius scaled by `sqrt(count)`, colour by `median_price` quantile; `TextLayer` with abbreviated counts ("1.8k") on cells above a size threshold.
  - **Points layer** (zoom ≥ 12): `ScatterplotLayer`, radius 2–6 px by zoom, colour = price quantile ramp (compute quantile breaks once from the loaded data, memoised). With binary mode active, feed deck.gl **binary attributes** directly (`data: {length, attributes: {getPosition, …}}`) — no per-point JS objects.
  - **Choropleth layer** (toggleable, off by default): `GeoJsonLayer` of districts, fill colour by `median_price` quantile, 60 % opacity, thin stroke. Geometry + stats are **lazy-loaded on first toggle** and cached for the session.
- Layer instances are memoised (`useMemo`) and recreated only when their data or the filter state changes — never on hover or camera change. Accessor functions defined once, not inline per render.

### 5.2 Data fetching (the viewport story)

- Fetch on `moveend`, **debounced 250 ms**, with an `AbortController` cancelling any in-flight request when a new one starts.
- Request bbox is the viewport **inflated by 20 %** so small pans hit already-loaded data.
- Tiny client cache: max 20 LRU entries storing fetched inflated bbox, mode, cluster integer zoom (clusters only), filters, response, and truncation. Before fetching, reuse the newest compatible entry whose fetched bbox contains the current visible bbox. Compatibility means same filters plus the same cluster integer zoom; points share one mode. A truncated points entry is containment-reusable **only for its exact request key**, never for a different smaller viewport, because its omitted rows are unknown.
- A slim status pill describes the fetched slice honestly, e.g. "12,402 sales loaded" / "25,000+ loaded — zoom in". The request bbox includes a 20% margin, so it must not claim that every counted row is inside the visible viewport.

### 5.3 Interactions

- **Hover** (pointer devices): lightweight tooltip — price, type label, date (points) or count + median (cells/districts). Tooltip is a single absolutely-positioned div updated from deck's `onHover`; no React state churn per frame (use a ref).
- **Click** on a point: slide-in card (right side desktop, bottom sheet mobile) showing the full address, then fetching `/api/postcode/{pc}/history`: list of that postcode's transactions plus a **price-history sparkline** rendered as plain inline SVG (no chart library).
- **Controls** (top-left panel): layer toggles (Transactions / Choropleth), property-type filter chips (D/S/T/F/O), price-range min/max inputs. Filter changes re-fetch and update layers.
- Footer: data attribution (see §10) + total from `/api/meta`.

### 5.4 Visual polish (budget ~30 min, but required)

Use the labelled OpenFreeMap Liberty basemap with restrained white/soft-grey operational surfaces, a high-contrast three-band price legend, a system font stack, and count/date copy derived from `/api/meta` (validated snapshot: "466,368 standard sales · Jan 2021–Apr 2026"). It must look like a focused analysis tool, not a marketing page.

---

## 6. Performance requirements

| Metric | Budget | How measured |
|---|---|---|
| Basemap visible | < 2 s on broadband | Chrome DevTools, cold load |
| First data layer rendered | < 3.5 s | performance.mark from load → first deck render |
| Pan/zoom frame rate with full point load | no sustained drops below ~50 fps | DevTools performance trace while panning at zoom 13 |
| `moveend` → layer updated | < 600 ms p50 (warm API) | in-app instrumentation (§8) |
| JS bundle (gzip, all chunks) | < 1 MB | `vite build` report |
| Points JSON payload, 25k points | recorded, then beaten by binary mode | DevTools network panel |

Main-thread discipline rules: no JSON parsing of megabyte payloads inside React render; binary decode happens in a **web worker**; no per-frame allocations in accessors; debounced camera events only.

---

## 7. Deployment

1. Supabase project created, PostGIS extension enabled; pipeline run from the local machine over the direct or session-pooler connection → tables populated, precomputed cluster cells built, metadata inserted, matview refreshed, `ANALYZE` run.
2. Render **Web Service** for `/api`: `uvicorn main:app --host 0.0.0.0 --port $PORT`, env vars `DATABASE_URL` (Supabase direct connection string) and `FRONTEND_ORIGIN`; health check path `/api/health`.
3. Render **Static Site** for `/frontend`: build `npm run build`, publish `dist/`, env var `VITE_API_BASE_URL` = the web service URL.
4. Both services defined in `render.yaml` (Render Blueprint) so the deploy is reproducible.
5. **Keep-alive:** external uptime pinger (UptimeRobot or cron-job.org) hitting `GET /api/health` every 10 minutes — keeps the Render service warm and generates Supabase traffic to reduce inactivity-pause risk. Alerts and the 24 h / 7 day smoke checks remain required; the pinger is not treated as a platform guarantee.
6. Verify the live URL from a clean browser profile **and** a phone, then re-verify after 24 h (catches cold-start and pause regressions).

---

## 8. The documented performance decision (required deliverable)

The README must document **one** deliberate optimisation with real before/after numbers. The designated optimisation:

**"Switched the points endpoint from per-row JSON objects to versioned binary columns, decoded in a web worker and fed to deck.gl as binary attributes."**

Protocol:

1. Build everything with JSON first (milestones M1–M3).
2. Instrument: payload bytes (network panel), client decode/parse ms, and `moveend → onAfterRender` total, logged via `performance.measure` for a fixed scripted interaction (load app → jump to zoom 13 over Clapham → pan once). Record 5 runs, take medians.
3. Implement `format=bin` + worker decode + binary attributes.
4. Repeat the same scripted measurement. Record the table in the README:

| | payload (gzip) | parse/decode | moveend→render |
|---|---|---|---|
| JSON, 25k pts | _measured_ | _measured_ | _measured_ |
| Binary, 25k pts | _measured_ | _measured_ | _measured_ |

If the numbers don't improve, that's still a valid documented finding — write what was measured and why (e.g. gzip already closed the payload gap), and say what you'd try next. **Do not fabricate an improvement.**

---

## 9. Milestones & acceptance criteria

Work strictly in order; commit (with a sensible message) at each milestone boundary. Each criterion must be verified, not assumed.

**M1 — Data on a map** *(≈ evening 1)*
- [ ] Pipeline scripts download, filter, geocode, and `COPY`-load the data; row count and join-loss % logged.
- [ ] Schema, indexes, matview created in Supabase.
- [ ] Vite app shows the OpenFreeMap basemap with a naive capped sample of points from `/api/transactions` (JSON).
- [ ] Deterministic Python/frontend CI is configured; protected live-provider evals remain separate.

**M2 — Viewport fetching + zoom-dependent aggregation** *(≈ evening 2)*
- [ ] Debounced, abortable, bbox-inflated fetching as in §5.2.
- [ ] Aggregated cells below zoom 12; raw capped points above; visually smooth handoff between modes.
- [ ] Full-London view returns in < 1 s warm; status pill shows counts/truncation.

**M3 — Choropleth + interactions + polish** *(≈ evening 3)*
- [ ] Toggleable, lazy-loaded district choropleth with legend.
- [ ] Hover tooltips and click → property card with price-history sparkline.
- [ ] Filters (type, price) wired through API and UI.
- [ ] Visual polish pass done; mobile layout verified.

**M4 — Performance decision + deploy + README** *(≈ evening 4)*
- [ ] Binary points mode + worker decode + binary deck.gl attributes.
- [ ] Before/after measurements taken per §8 protocol and written into README.
- [ ] Deployed to Render (both services) with the keep-alive pinger configured; live URL verified on desktop + phone; basemap and data load within budgets.
- [ ] README finished per §12.

**M5 — Required AI quality milestone (starts after the core M4 release)**
- [ ] Typed LangGraph routes SQL, RAG, hybrid, map-action, and unsupported requests.
- [ ] Claude generation, through Anthropic direct or OpenRouter, is grounded in parameterized SQL and curated Pinecone evidence.
- [ ] Streaming, citations, reversible map proposals, feedback, traces, and regression evals pass the release gates in §11.2.

---

## 10. Licensing & attribution (must appear in footer + README)

- "Contains HM Land Registry data © Crown copyright and database right 2026. Licensed under the Open Government Licence v3.0."
- ONS postcode data: © Crown copyright, OGL v3.0.
- District boundaries derived from OpenStreetMap via uk-postcode-polygons, © OpenStreetMap contributors, ODbL.
- Basemap: OpenFreeMap/OpenMapTiles data and © OpenStreetMap contributors; the MapLibre attribution control must remain visible.

---

## 11. Post-M4 extensions

### 11.1 Vector tiles (highest value)
Export points to newline-delimited GeoJSON → `tippecanoe -zg --drop-densest-as-needed -o london.pmtiles`; host the `.pmtiles` as a static asset (Vercel static or Cloudflare R2). Frontend: `pmtiles` protocol registered with MapLibre, points rendered from the tile source below zoom 12 (replacing the cluster API path), API retained for filtered/point-detail queries. Add a README paragraph comparing tile payloads vs the API approach with measured numbers.

### 11.2 Required conversational data agent ("Ask the data") — full design: `docs/AGENTIC_AI.md`
- `POST /api/chat` and `POST /api/chat/stream` run the same typed LangGraph state machine: validate input, classify route, retrieve evidence, execute SQL tools, propose a map action, generate, verify grounding, and finalize. Supported routes are `sql`, `rag`, `hybrid`, `map_action`, and `unsupported`.
- Counts, medians, rankings, filters, and trends come only from fixed parameterized SQL tools. RAG is restricted to curated HMLR/ONS methodology, licensing, provenance, limitations, and project documentation. Transaction rows are never embedded.
- Pinecone uses index `lpe-knowledge-v1`, integrated `llama-text-embed-v2`, versioned namespaces, 20 retrieval candidates, and `bge-reranker-v2-m3` top-five reranking. Reranking quota failure falls back to raw top-five results and marks the response degraded.
- Evidence is chunked by heading at approximately 1,500 characters with 200-character overlap. Deterministic chunk IDs and metadata make ingestion reproducible; a new namespace is promoted only after retrieval evals pass.
- `ChatResponse` includes a run ID, reply, explicit citations, execution-fact steps, optional map-action proposal, degraded flag, and cost/latency/model metadata. SSE emits `run_started`, `step_started`, `step_completed`, `citation`, `final`, and `error`.
- Map changes are proposals. The client validates each proposal, exposes **Apply**, preserves the prior view, and exposes **Undo**. The model never directly mutates the map.
- LangSmith traces every graph node, retrieval, model call, SQL tool, validation, and retry. Sensitive text is redacted, IP addresses and raw logs are excluded, and reviewed negative feedback may be promoted into versioned eval cases only by a human.
- Hard runtime boundaries are 25 seconds and $0.08 per turn. A grounding failure is retried once, then fails cleanly. Missing Pinecone degrades RAG while SQL continues; missing LangSmith disables feedback and blocks M5 release; missing credentials for the selected Claude provider disables chat through `/api/capabilities`.
- Release gates: route and SQL-argument accuracy ≥95%; numeric groundedness and citation validity 100%; retrieval recall@5 ≥90%; end-to-end task success ≥90%; unsupported refusal 100%; zero critical prompt-injection failures; first SSE event p95 <1 s; response p50 <6 s and p95 <14 s; typical cost ≤$0.02, p95 ≤$0.05, hard cap ≤$0.08. No release may reduce task success by more than two percentage points or regress a critical metric.
- Unanswerable asks such as bedrooms, true £/m², rentals, or station proximity are declined with the dataset's actual limitation.

### 11.3 H3 hexagon layer
Server: `h3-py` aggregation endpoint (resolution 7–9 chosen from zoom), returning `[{h3, count, median_price}]`. Client: `H3HexagonLayer`. Toggle alongside the choropleth.

### 11.4 True £/m² (only if everything else is done)
Join EPC register data (requires free registration) on address to obtain floor area; recompute district stats as median £/m². Document match-rate honestly.

---

## 12. README specification (keep it short — under ~150 lines)

Order: 1) screenshot or GIF (capture at M4; map, choropleth, and detail panel visible), 2) one-paragraph what-it-is + live URL, 3) dataset description (sources, row count, licences), 4) architecture in ≤ 5 lines, 5) **the performance decision with the §8 numbers table**, 6) key trade-offs in 3–4 bullets (server vs client clustering, JSON vs binary, why PostGIS not in-browser filtering, GeoJSON vs vector tiles), 7) local dev quickstart. No tutorial padding, no 2,000-word essays.

---

## 13. Agent working practices

- Verify each acceptance criterion by actually running the thing (curl the API, load the page) before checking it off.
- When a third-party URL or free-tier capability differs from this spec, fix forward within the same architecture and note the deviation in the README's trade-offs section.
- Keep dependencies minimal: no chart libraries, no CSS frameworks heavier than vanilla CSS/CSS modules, no state-management libraries (React state + context is sufficient).
- Commit per milestone at minimum; messages describe the milestone outcome.
- If the dataset row count, payload sizes, or free-tier limits force a scope change (e.g. point cap lower than 25k), make the smallest change that preserves the demonstrated concepts, and document it.
