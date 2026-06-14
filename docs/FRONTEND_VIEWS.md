# Frontend Data-Map: Views ↔ Backend Contract

How every frontend view/component maps onto backend endpoints: what triggers each call, what state it feeds, how payload fields become visual channels, and the loading/error behaviour. Wire shapes: `openapi.yaml` / `/schema.js` (imported as `@schema`). Backend behaviour: `BACKEND_REQUIREMENTS.md`.

All requests go to `import.meta.env.VITE_API_BASE_URL` (Render web service origin; `http://localhost:8000` in dev) — the frontend is a separate origin (Render Static Site), so every fetch is CORS.

---

## 1. Component tree & view inventory

```
<App>
 ├── V1 MapCanvas ──────────── MapLibre map + deck.gl MapboxOverlay
 │     ├── L1 ClusterLayer        ScatterplotLayer + TextLayer   (zoom < 12)
 │     ├── L2 PointsLayer         ScatterplotLayer               (zoom ≥ 12)
 │     └── L3 ChoroplethLayer     GeoJsonLayer                   (toggle, lazy)
 ├── V2 ControlPanel ───────── layer toggles, type/tenure chips, price min/max, dates
 ├── V3 StatusPill ─────────── loading / count / truncation
 ├── V4 PropertyCard ───────── postcode history + SVG sparkline (click)
 ├── V5 Legend ─────────────── colour-ramp for the active layer
 ├── V6 ChatPanel ──────────── grounded conversational data agent
 └── V7 Footer ─────────────── attribution + dataset totals
```

## 2. View ↔ endpoint matrix

| View / layer | Endpoint | Trigger | Feeds state | Client cache |
|---|---|---|---|---|
| L1 + L2 | `GET /api/transactions` | map `moveend` (debounced 250 ms); filter change; integer cluster-zoom change; mode crossing | `data.transactions` | LRU 20; entries store bbox + filters + mode/cluster zoom + truncation |
| L3 + V5 | `GET /api/districts` + `GET /api/district-stats` | first choropleth toggle ON | `districts.{geojson,stats}` | session-permanent |
| V4 | `GET /api/postcode/{pc}/history` | point click; postcode comes from JSON or binary row | `selection` | per-postcode Map, max 50 |
| V3 | — (derived) | — | reads `data.*` | — |
| V6 | `GET /api/capabilities`; `POST /api/chat/stream`; `POST /api/chat/{run_id}/feedback` | app/chat mount; send; review | transcript, citations, execution steps, feedback, proposed `map_action` | transcript in memory only (`no-store`) |
| V7 | `GET /api/meta` | app mount | `meta` | once per session |

`/api/health` is never called by the frontend (pinger-only).

## 3. App state model

Single source of truth at `<App>` (React state + context; no state library):

```ts
interface AppState {
  viewport: { longitude: number; latitude: number; zoom: number };  // controlled by map
  filters: Filters;                       // @schema Filters; EMPTY_FILTERS initially
  layers: { transactions: boolean; choropleth: boolean };           // true / false initially
  data: {
    transactions: TransactionsResponse | DecodedBinaryPoints | null;
    loading: boolean;
    truncated: boolean;
    error: string | null;
  };
  districts: { geojson: DistrictFeatureCollection | null;
               stats: Map<string, DistrictStats> | null;            // keyed by code
               loading: boolean };
  selection: { postcode: string; history: PostcodeHistory | null; loading: boolean } | null;
  meta: Meta | null;
  chat: {
    open: boolean;
    capabilities: Capabilities | null;
    transcript: ChatMessage[];             // session-only; sent each turn
    pending: { status: string } | null;     // updated from SSE execution events
    proposedAction: MapAction | null;
  };
}
```

Derived (never stored): `mode = viewport.zoom >= CLUSTER_ZOOM_THRESHOLD ? 'points' : 'clusters'`; `queryZoom = floor(viewport.zoom)`; cluster cache scope includes `queryZoom`, points scope does not; quantile colour breaks (§7); status-pill text.

---

## 4. The transactions fetch loop (L1/L2 ↔ `GET /api/transactions`)

```
moveend / filter change
  └▶ visibleBbox = current viewport; filters + mode/clusterZoom = lookup scope
      ├─ exact request-key hit (including truncated responses)
      │    └▶ setState(data) — no network
      ├─ newest compatible fetchedBbox fully contains visibleBbox
      │    and response is clusters or untruncated points
      │    └▶ setState(data) — no network
      └─ no containing entry
           └▶ requestBbox = visibleBbox inflated by BBOX_INFLATE_RATIO (+20%)
              └▶ key = quantisedBbox(requestBbox) + mode + clusterZoom-if-any + JSON(filters)
                 └▶ abort in-flight controller; fetch
                   mode clusters ──▶ JSON → ClustersResponse.safeParse (dev) → state
                   mode points   ──▶ format=bin → ArrayBuffer → worker →
                                     decodePointsBinary + interleavePositions →
                                     transferables back → state
                                     (truncated ← X-Truncated header)
```

- Points mode uses `format=bin` by default; JSON remains the documented fallback contract for API debugging and binary equivalence tests.
- Each cache entry records the exact fetched bbox. Containment comparison uses unrounded numbers; quantisation is only for exact-key storage. Never containment-reuse truncated points. A response landing for a stale key is dropped.
- Error → keep last good data on the map, set `data.error`, show retry toast (§9).

### Worker contract (`/frontend/src/workers/points.worker.ts`)

```
postMessage(in):  { buffer: ArrayBuffer }                    [transfer: buffer]
postMessage(out): { positions: Float32Array,                 [transfer: input buffer + positions.buffer]
                    price: Uint32Array, dateDays: Uint16Array,
                    typeCode: Uint8Array, postcodeBytes: Uint8Array,
                    length: number }
```

The decoded scalar columns share the original input `ArrayBuffer`; `positions` owns one new buffer. Post the result with transfer list `[buffer, positions.buffer]` exactly once each — never repeat the shared buffer for every view. The worker imports `decodePointsBinary` / `interleavePositions` from `@schema`, the only frontend module that touches the layout.

---

## 5. Layer specs — payload field → visual channel

### L1 ClusterLayer (`mode === 'clusters'`)

| Visual channel | Source field | Mapping |
|---|---|---|
| position | `cell.lng/lat` | as-is |
| radius (px) | `cell.count` | `8 + 4·sqrt(count/10)`, clamp [8, 40] |
| fill colour | `cell.median_price` | stable green/blue/red price band (§7) |
| label (TextLayer) | `cell.count` | abbreviated ("1.8k"); only cells with radius ≥ 14 px |
| opacity | — | 0.85 |

Click on a cell → `flyTo(cell, zoom: min(zoom+2, 13))` — drill-down, no API call.

### L2 PointsLayer (`mode === 'points'`)

| Visual channel | Source field | Mapping |
|---|---|---|
| position | binary `positions` (or JSON lng/lat) | deck binary attributes: `{length, attributes: {getPosition: {value: positions, size: 2}}}` |
| fill colour | `price` | same quantile ramp, breaks from currently loaded prices (§7) |
| radius (px) | zoom | `interpolate(zoom, [12, 16], [2, 6])`, units `'pixels'` |
| picking | index → `typeCode`, `price`, `dateDays`, fixed-width postcode (or equivalent JSON fields) | `pickable: true`, `autoHighlight`; decode only the selected/hovered row's postcode/date |

### L3 ChoroplethLayer (toggle)

| Visual channel | Source field | Mapping |
|---|---|---|
| geometry | district feature | as-is |
| fill colour | `stats.get(code).median_price` | blue intensity relative to the loaded maximum, alpha 0.6; highlighted district uses amber |
| stroke | — | 0.5 px, white @ 20% |
| hover | `code` + stats | tooltip: "SW11 — median £740k, 4,102 sales" |

Render order: choropleth under points/clusters. All three layer instances memoised; recreated only on data / filter / toggle change — never per camera frame or hover.

---

## 6. Interaction flows

### 6.1 Click → V4 PropertyCard

```
deck onClick(L2 point, index i)
  ├─ JSON mode:   pc/date = points[i].postcode/date
  └─ binary mode: pc = postcodeAt(decoded,i); date = isoDateFromEpochDay(dateDays[i])
        └▶ card opens immediately (skeleton + locally-known price/type/date)
           GET /api/postcode/{encodeURIComponent(pc)}/history
           response → address header (saon paon street, town, postcode),
           entries list (date, price, type label, tenure, new-build badge),
           sparkline: inline SVG polyline of (date → price), returned entries,
                      dots on entries; no chart library
           truncated=true → show "Showing latest 200 sales" notice
```
404 for an unknown postcode is an integrity error: keep the local point summary visible, show a compact "History unavailable" state, and log the postcode in development. Card layout: right-side panel ≥ 768 px, bottom sheet below. Dismiss: ✕, Esc, or map click.

### 6.2 Choropleth toggle (lazy-load story)

```
toggle ON (first time) ─▶ V2 shows mini-spinner
  ├▶ GET /api/districts        (≈ ≤500 KB GeoJSON)
  └▶ GET /api/district-stats   (parallel)
      └▶ stats → Map<code, …>; compute district breaks; render L3 + V5 ramp
later toggles ─▶ instant (session cache)        either request fails ─▶ toggle
                                                 reverts OFF + toast
```

### 6.3 Filter change (V2 → L1/L2)

Chips (D/S/T/F/O), tenure chips (F/L), validated whole-pound price min/max (0–50,000,000; min ≤ max; commit on blur/Enter), and date range values update `filters` → same loop as §4. Choropleth is **not** filtered (district medians are all-data by design — note in UI copy: "District medians · all sales").

### 6.4 Conversational data agent (V6, required M5 — design: `AGENTIC_AI.md`)

```
open/mount ─▶ GET /api/capabilities
send ─▶ append user msg to chat.transcript
     ─▶ POST /api/chat/stream { messages: bounded alternating transcript }
        run_started / step_started / step_completed update the pending status
        citation events may be rendered incrementally
  final ─▶ ChatResponseSchema.safeParse
        reply + citations → assistant message
        steps → expandable execution facts with durations
        metrics → route and latency display; never hidden chain-of-thought
        map_action non-null ─▶ MapActionSchema.safeParse ─▶ show Apply
             Apply ─▶ capture current filters/highlight as undoState
                   ─▶ apply validated proposal through normal map state
             Undo  ─▶ restore captured state and clear undoState
        thumbs up/down ─▶ POST /api/chat/{run_id}/feedback when capability enabled
  429 ─▶ system bubble: "Hold on — too many questions, try again in a minute."
  error event / non-2xx ─▶ system bubble: "I couldn't answer that — try e.g.
             'median price in SW11?'"  (user msg stays; can resend)
  chat=false ─▶ panel remains inspectable but input is disabled with an unavailable message
```

Transcript and Undo state are in memory only. Provider credentials, SQL plans, raw retrieved chunks, and trace payloads never reach the browser. All API payloads are runtime-validated through `schema.js` before use.

---

## 7. Shared colour scale (L1, L2, L3, V5)

The transaction layers use three stable, labelled price bands: under £400k (green), £400k–£800k (blue), and over £800k (red). Stable thresholds keep the same colour meaning while users pan between viewports. The district layer uses a restrained blue intensity scale with a distinct highlighted-district colour.

| Consumer | Break input | Recomputed when |
|---|---|---|
| L2 points | each point's price | decoded in the worker |
| L1 clusters | each cell's `median_price` | each transactions response |
| L3 choropleth | district median relative to the loaded maximum | once at first lazy stats load |

V5 Legend renders the stable transaction price bands. District hover supplies the exact median and sales count for the choropleth.

## 8. V3 StatusPill states

| Condition | Text |
|---|---|
| `data.loading` | spinner + "Loading…" |
| clusters mode | "{Σ cells.count·formatted} sales loaded" |
| points, `!truncated` | "{points.length} sales loaded" |
| points, `truncated` | "25,000+ loaded — zoom in" |
| `data.error` | "Connection lost — retrying" |

## 9. Loading & error policy (all views)

- **Never blank the map:** fetch failures keep the last rendered layer; errors surface in V3 + a toast with a Retry action (re-runs the last key).
- First-load failure (API cold-start worst case): basemap renders regardless; V3 shows "Waking the server…" if the first `/api/meta` takes > 3 s, then auto-retries (2 attempts, 5 s apart) — this is the Render free-tier cold-start path made honest.
- A `safeParse` failure is treated as a failed response: log details in development, retain the last good layer, and show the normal retry error. Never pass contract-invalid raw data into rendering code.

## 10. Performance obligations on the frontend (from SPEC §6)

| Rule | Where enforced |
|---|---|
| No fetch storms | single debounced effect on `moveend` (§4); never fetch in render |
| No main-thread megabyte parses | binary path decodes in worker; JSON clusters payloads are small (≤ ~50 KB) |
| 60 fps hover | tooltip div updated via ref from `onHover`; zero React state per frame |
| No layer churn | memoised layer instances; accessors defined at module scope |
| Bundle < 1 MB gz | maplibre + deck are the budget; no chart/CSS/state libraries (sparkline is hand-rolled SVG) |
| moveend→render < 600 ms p50 | `performance.mark/measure` around §4 loop — same instrumentation feeds the README §8 table |
