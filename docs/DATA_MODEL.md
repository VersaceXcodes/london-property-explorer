# Data Model — London Property Explorer

Logical and physical data model, field provenance, and the mapping from stored entities to API DTOs. Physical DDL lives in `DATABASE_REQUIREMENTS.md` §4 (canonical) and `/pipeline/schema.sql` (executable).
Measured source evidence and exact snapshot fingerprints live in `SOURCE_DATA_PROFILE.md`.

---

## 1. Source datasets

| Source | What we take | Licence |
|---|---|---|
| HM Land Registry Price Paid Data (PPD), `pp-complete.csv` snapshot | Standard Category A price-paid records from 2021-01-01 onward: price, date, postcode, type, tenure, address fields | OGL v3.0 |
| ONS Postcode Directory (ONSPD), latest edition | `PCDS` → WGS84 centroid (`LAT`/`LONG`) plus `LAD25CD` for authoritative Greater London membership | OGL v3.0 |
| `missinglink/uk-postcode-polygons` (OSM-derived) | Postcode-district (outward code) boundary polygons | ODbL |

PPD is the system of record for transactions; ONSPD and the polygons are reference data joined in at pipeline time. Nothing is fetched from these sources at request time.

---

## 2. Entity overview

```
┌─────────────────────────┐         ┌──────────────────────┐
│ transactions  (~466k)   │  N    1 │ districts  (~280)    │
│ id PK                   │─────────│ code PK  e.g. 'SW11' │
│ price, date, postcode   │district │ geom MultiPolygon    │
│ district  ──────────────┤  =code  └──────────────────────┘
│ property_type, tenure,  │                   ▲
│ is_new, address fields  │                   │ 1:1 by district code
│ geom 4326 + geom_3857   │         ┌─────────┴────────────┐
└─────────────────────────┘         │ district_stats (MV)  │
        (grouped by district) ─────▶│ district PK          │
                                    │ sales, median_price  │
                                    └──────────────────────┘
```

- `transactions.district` → `districts.code` is a *soft* reference (no FK): some outward codes present in transactions may lack a polygon (dropped from the choropleth only; see SYSTEM_DESIGN §10).
- `district_stats` is a **materialized view** derived entirely from `transactions`; refreshed only after a pipeline (re)load.
- `cluster_cells` is a small derived serving table for unfiltered low-zoom map loads; filtered clusters still aggregate from `transactions`.
- `dataset_meta` is a one-row derived serving table for total count, final date range, manifest JSON, and load timestamp.
- There is deliberately no `postcodes` table: postcode centroids are baked into `transactions.geom` at pipeline time; the postcode string is retained for grouping/history lookups.

---

## 3. Field dictionary

### 3.1 `transactions`

| Column | Type | Null | Source / derivation | Notes |
|---|---|---|---|---|
| `id` | `uuid` PK | no | PPD col 1, braces stripped | Land Registry transaction GUID |
| `price` | `integer` | no | PPD col 2 | GBP; pipeline-filtered to £10k–£50M |
| `date` | `date` | no | PPD col 3 (date of transfer) | |
| `postcode` | `text` | no | PPD col 4, canonicalised: uppercase, one space before final 3 characters | Display/history key; the pipeline uses a temporary no-space key for the ONSPD join |
| `district` | `text` | no | Derived: outward code = postcode before the space (e.g. `SW11`) | Choropleth/group key |
| `property_type` | `char(1)` | no | PPD col 5 | Enum: see §5 |
| `is_new` | `boolean` | no | PPD col 6 (`Y`→true) | New build flag |
| `tenure` | `char(1)` | no | PPD col 7 | `F` freehold / `L` leasehold |
| `paon` | `text` | yes | PPD col 8 | Primary addressable object (house number/name) |
| `saon` | `text` | yes | PPD col 9 | Secondary (flat number) |
| `street` | `text` | yes | PPD col 10 | |
| `town` | `text` | yes | PPD col 12 (town/city) | Cols 11/13 (locality, LA district) not stored |
| `geom` | `geometry(Point, 4326)` | no | ONSPD centroid for `postcode` | **Postcode-centroid precision** — all sales in a postcode share one point (see §6) |
| `geom_3857` | `geometry(Point, 3857)` generated | no | Stored transform of `geom` | Avoids per-request `ST_Transform` during grid aggregation |

Rows excluded at pipeline time: transfer date before 2021-01-01, `county != 'GREATER LONDON'`, `ppd_category != 'A'`, `record_status != 'A'`, missing/invalid postcode, price outside bounds, failed ONSPD coordinate join, invalid WGS84 coordinate, or ONSPD `LAD25CD` outside the explicit Greater London allowlist `E09000001`–`E09000033`. The county test is only a prefilter; ONSPD LAD membership is authoritative. ONSPD rows with `DOTERM` populated are retained for historical sales.

### 3.2 `districts`

| Column | Type | Null | Source / derivation | Notes |
|---|---|---|---|---|
| `code` | `text` PK | no | Outward code from polygon properties | Only districts present in `transactions` are loaded |
| `geom` | `geometry(MultiPolygon, 4326)` | no | uk-postcode-polygons, simplified at pipeline time | Whole-set GeoJSON budget < 500 KB |

### 3.3 `cluster_cells`

| Column | Type | Derivation |
|---|---|---|
| `zoom`, `cell_px`, `cell_x`, `cell_y` | integer composite PK | Web Mercator grid bucket |
| `lng`, `lat` | double precision | Member centroid transformed back to WGS84 |
| `sale_count` | integer | `count(*)` for the bucket |
| `median_price` | integer | `percentile_cont(0.5) WITHIN GROUP (ORDER BY price)` |
| `geom` | `geometry(Point, 4326)` | Centroid for map display |
| `bbox` | `geometry(Polygon, 4326)` | Cell envelope used for viewport lookup |

Only unfiltered clusters use this table. Filtered clusters still aggregate exact matching transactions at request time.

### 3.4 `dataset_meta`

| Column | Type | Derivation |
|---|---|---|
| `id` | boolean PK | Constant `true`; enforces one metadata row |
| `total` | integer | Final transaction count after row-count assertion |
| `from_date`, `to_date` | date | Final min/max transaction date from the manifest |
| `source_manifest` | jsonb | Full pipeline manifest |
| `loaded_at` | timestamptz | Database load timestamp |

### 3.5 `district_stats` (materialized view)

| Column | Type | Derivation |
|---|---|---|
| `district` | `text` | `GROUP BY transactions.district` |
| `sales` | `bigint` | `count(*)` |
| `median_price` | `integer` | `percentile_cont(0.5) WITHIN GROUP (ORDER BY price)` |

Refresh: `REFRESH MATERIALIZED VIEW district_stats;` after every load. Not refreshed at request time.

---

## 4. API DTOs and their derivation

The wire shapes are defined in `openapi.yaml` (authoritative) and mirrored in `/schema.js`. Mapping back to entities:

| DTO | Built from | Transformation |
|---|---|---|
| `ClusterCell` | `cluster_cells` for unfiltered zooms 6–11; otherwise `transactions` | Precomputed low-zoom cells keep the first map view fast on Supabase free tier. Filtered requests use per-request PostGIS grid aggregation over `geom_3857` for exact filter semantics |
| `TransactionPoint` | `transactions` | Deterministic row subset (`id, lng=ST_X, lat=ST_Y, price, type, date, postcode`) within bbox, centre-nearest then UUID, `LIMIT 25001` |
| binary points buffer | `transactions` | Same ordered rows in versioned `LPE1` columns: Float32 lng/lat, Uint32 price, Uint16 epoch-day, Uint8 typeCode, fixed 8-byte postcode. Date/postcode remain available without per-point JS objects |
| `DistrictStats` | `district_stats` | Direct projection |
| `DistrictFeatureCollection` | `districts` | `ST_AsGeoJSON(geom, 5)` (5 decimal places ≈ 1 m), assembled once, cached in-process |
| `HistoryEntry` / `PostcodeHistory` | `transactions` | `WHERE postcode = $1`, ordered by date then UUID descending, `LIMIT 201`; sentinel row becomes `truncated`, at most 200 entries returned |
| `Meta` | `dataset_meta` | Direct projection of final row count and date range; cached in-process |
| `Capabilities` | server settings | Provider-safe booleans for chat, RAG, tracing, streaming, and feedback plus graph/corpus versions; never contains credentials |
| `ChatResponse` | LangGraph final state | Run ID, grounded reply, citations, execution-fact steps, optional map proposal, degraded flag, and versioned cost/latency metadata |
| `MapAction` | LangGraph `propose_map_action` node | Not persisted; inert, strictly validated `set_filters` or `highlight_district` proposal validated again by the client before Apply |

---

## 5. Enumerations

| Enum | Values | Wire form |
|---|---|---|
| Property type | `D` detached · `S` semi-detached · `T` terraced · `F` flat/maisonette · `O` other | `char(1)` in JSON; `Uint8` code in binary: D=0 S=1 T=2 F=3 O=4 (order fixed in `/schema.js` `TYPE_FROM_CODE`) |
| Tenure | `F` freehold · `L` leasehold | `char(1)` |
| Response mode | `clusters` \| `points` | discriminator field `mode` |

---

## 6. Coordinate systems & precision

| Context | CRS / format | Precision implication |
|---|---|---|
| Storage (`geom`) | EPSG:4326 (WGS84), double | Source precision = ONSPD centroid |
| Grid aggregation | EPSG:3857 (Web Mercator) internally, results back to 4326 | Cell size computed in metres |
| JSON wire | decimal degrees, full double | — |
| Binary wire | `LPE1`; **Float32** lng/lat; `Uint16` days since 1970; fixed 8-byte ASCII postcode | Position error is ~0.3 m worst-case at London latitudes; postcode/date preserve exact interaction identity |
| District GeoJSON | 4326, 5 decimal places | ≈ 1 m; fine for a choropleth |

**Honesty requirement carried to the UI:** every point's position is the *postcode centroid*, not the parcel — multiple sales stack on one coordinate, and distinct postcodes can occasionally share the same centroid. The property card therefore uses the postcode carried in the selected point payload; coordinates are never reverse-resolved to identify a postcode.

---

## 7. Known modelling limitation: no floor area

PPD has no floor-area/size field, so **price-per-m² cannot be derived from this model**. The choropleth metric is median sale price by district. A true £/m² requires joining the EPC register (address-matched, lossy) — defined as stretch 11.4 in SPEC.md and deliberately excluded from the core model.

---

## 8. Volume & lifecycle

| Quantity | Expected | Hard bound |
|---|---|---|
| `transactions` rows | 466,368 in the validated June 2026 snapshot | Pipeline aborts outside 400k–550k (SPEC §3.3) |
| Unique loaded postcodes | 105,130 in the validated snapshot | ONSPD canonical keys must be unique |
| `transactions` table + indexes | estimate ~180–300 MB including generated 3857 geometry | Must be measured with `pg_total_relation_size`; deployment gate < 450 MB on a 500 MB database quota |
| `cluster_cells` rows | 992 for the validated snapshot at `CELL_PX=32` | Rebuilt during every PostGIS load |
| `districts` rows | ~280 | — |
| Dataset churn | None at runtime (read-only snapshot) | Refresh = re-run pipeline; matview refresh; `ANALYZE` |

The database is a **disposable, reproducible cache** of the pipeline output: no backups needed beyond pipeline reproducibility; schema changes are re-loads, not migrations.
