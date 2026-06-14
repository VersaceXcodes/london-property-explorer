# Database Requirements — London Property Explorer

Platform, schema, canonical queries, and operational requirements for the PostGIS database. Logical model and field provenance: `DATA_MODEL.md`.

---

## 1. Platform

| Requirement | Value |
|---|---|
| Engine | PostgreSQL 15+ (Supabase free tier) |
| Extension | PostGIS (enable: `CREATE EXTENSION IF NOT EXISTS postgis;` or Supabase dashboard → Database → Extensions) |
| Storage budget | deployment gate < 450 MB total (current free quota 500 MB; preserve headroom for Postgres overhead) |
| Region | Pick the Supabase region closest to Render's region (use the same provider region pair, e.g. both in Frankfurt or both in Oregon) — this latency is inside the 600 ms moveend→render budget |

### Free-tier constraints that shape the design

| Constraint | Consequence |
|---|---|
| Project may pause after sustained low activity | `/api/health` runs `SELECT 1` and is pinged every 10 min externally (SPEC §7 step 5) — this is a deployment requirement, not optional |
| Shared CPU | Selective viewport queries must use the spatial index. A full-London aggregate may legitimately use a sequential scan if PostgreSQL estimates it cheaper; judge it by measured buffers/latency, not plan-node ideology. |
| Connection limits | API uses a pool of **max 5**. Prefer the direct connection string (port 5432). If the environment cannot reach Supabase's direct IPv6 host, use the session pooler with `statement_cache_size=0`; never use Supavisor transaction mode with asyncpg prepared statements enabled. |

### Connection strings (env `DATABASE_URL`)

| Consumer | String | Why |
|---|---|---|
| FastAPI (Render) | Direct `postgresql://…@db.<ref>.supabase.co:5432/postgres`, or session pooler if direct IPv6 is unavailable | Persistent process, small pool; code disables asyncpg statement caching so the pooler path is safe |
| Pipeline (local) | Direct preferred; session pooler accepted for this Python loader | Bulk load runs through asyncpg `copy_records_to_table` in one session and uses `statement_cache_size=0` |

---

## 2. Roles & access

- **Application role:** `app_reader` — `LOGIN`, `SELECT` on `transactions`, `districts`, `dataset_meta`, `cluster_cells`, and `district_stats` only. No DDL, no writes. `ALTER ROLE app_reader SET statement_timeout = '5s';`. The loader sets its password from `APP_READER_PASSWORD` using server-side SQL literal escaping; it is never written to a generated artifact. After changing the role password, the Supabase pooler can take a short time to accept fresh `app_reader` logins.
- **Pipeline/admin:** the default `postgres` role, used only from the local machine. Schema replacement, bulk copy, materialized-view refresh, row-count assertion, analyze, and the 450 MB check occur in one transaction so any failed gate restores the prior database state.
- **Row Level Security:** not used — the dataset is public, read-only, and the API connects over the Postgres protocol (not Supabase's PostgREST). Tables stay in a dedicated schema or `public` with RLS disabled; the Supabase **service-role key and anon key are never used** by this system.

---

## 3. Sizing estimate

| Object | Estimate |
|---|---|
| `transactions` heap (~466k rows, including generated 3857 geometry) | ~90–140 MB |
| GIST(geom) + 3 btrees + PK | ~90–140 MB |
| `districts` (simplified) | < 5 MB |
| `cluster_cells` + `dataset_meta` | < 1 MB |
| `district_stats` | < 1 MB |
| **Total estimate** | **~180–300 MB**; verify after load with `pg_total_relation_size`, do not trust the estimate |

---

## 4. Canonical DDL

(Also at `/pipeline/schema.sql` — keep identical.)

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

CREATE TABLE dataset_meta (
  id              boolean PRIMARY KEY DEFAULT true CHECK (id),
  total           integer NOT NULL CHECK (total > 0),
  from_date       date NOT NULL,
  to_date         date NOT NULL CHECK (to_date >= from_date),
  source_manifest jsonb NOT NULL,
  loaded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cluster_cells (
  zoom         integer NOT NULL CHECK (zoom BETWEEN 6 AND 11),
  cell_px      integer NOT NULL CHECK (cell_px BETWEEN 24 AND 64),
  cell_x       integer NOT NULL,
  cell_y       integer NOT NULL,
  lng          double precision NOT NULL CHECK (lng BETWEEN -180 AND 180),
  lat          double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  sale_count   integer NOT NULL CHECK (sale_count > 0),
  median_price integer NOT NULL CHECK (median_price BETWEEN 10000 AND 50000000),
  geom         geometry(Point, 4326) NOT NULL,
  bbox         geometry(Polygon, 4326) NOT NULL,
  PRIMARY KEY (zoom, cell_px, cell_x, cell_y)
);

CREATE INDEX cluster_cells_lookup_idx ON cluster_cells (zoom, cell_px);
CREATE INDEX cluster_cells_bbox_idx ON cluster_cells USING gist (bbox);

CREATE MATERIALIZED VIEW district_stats AS
SELECT district,
       count(*)                                                AS sales,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::int AS median_price
FROM transactions
GROUP BY district;

CREATE UNIQUE INDEX district_stats_pk ON district_stats (district);
```

Index rationale: `gist(geom)` serves viewport point and filtered cluster queries (`&&` bbox); `district` serves the matview build; `date` serves date-range filters; `postcode` serves the history/card lookups. `cluster_cells` is the measured free-tier escalation for unfiltered low-zoom map loads; its bbox GIST index avoids scanning `transactions` for the first map view.

---

## 5. Canonical queries

These are the queries the backend must run (parameter style: asyncpg `$n`). They are the contract between `BACKEND_REQUIREMENTS.md` and this document — performance targets in §6 apply to exactly these shapes.

### Q1 — Grid aggregation (clusters mode, zoom < 12)

Unfiltered zooms 6–11 use the precomputed table generated during load:

```sql
SELECT lng, lat, sale_count AS count, median_price
FROM cluster_cells
WHERE zoom = $1
  AND cell_px = $2
  AND bbox && ST_MakeEnvelope($3, $4, $5, $6, 4326)
ORDER BY count DESC, lng, lat;
```

Filtered requests and zooms outside the precomputed range use the exact dynamic query.

Cell size in metres: `cell = 40075016.686 / 2^zoom / 256 * CELL_PX`, with `CELL_PX = 32` (tunable 24–64 to land 200–800 cells on a full-London view).

```sql
SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(center_x, center_y), 3857), 4326)) AS lng,
       ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(center_x, center_y), 3857), 4326)) AS lat,
       cnt                                    AS count,
       median_price
FROM (
  SELECT avg(ST_X(geom_3857))                AS center_x,
         avg(ST_Y(geom_3857))                AS center_y,
         count(*)                            AS cnt,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::int AS median_price
  FROM (
    SELECT geom_3857,
           price,
           ST_SnapToGrid(geom_3857, $5, $5) AS cell
    FROM transactions
    WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
      AND ($6::int    IS NULL OR price >= $6)
      AND ($7::int    IS NULL OR price <= $7)
      AND ($8::text[] IS NULL OR property_type = ANY($8))
      AND ($9::date   IS NULL OR date >= $9)
      AND ($10::date  IS NULL OR date <= $10)
  ) pts
  GROUP BY cell
) cells;
```

For point geometries, mean projected X/Y is the equal-weight member centroid.
It avoids materialising `ST_Collect` geometries for every cell.

### Q2 — Viewport points (points mode, zoom ≥ 12)

```sql
SELECT id, ST_X(geom) AS lng, ST_Y(geom) AS lat,
       price, property_type AS type, date, postcode
FROM transactions
WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
  AND ($5::int    IS NULL OR price >= $5)
  AND ($6::int    IS NULL OR price <= $6)
  AND ($7::text[] IS NULL OR property_type = ANY($7))
  AND ($8::date   IS NULL OR date >= $8)
  AND ($9::date   IS NULL OR date <= $9)
ORDER BY geom <-> ST_SetSRID(
           ST_MakePoint(($1 + $3) / 2.0, ($2 + $4) / 2.0), 4326
         ),
         id
LIMIT 25001;          -- MAX_POINTS + 1; the extra row sets truncated=true
```

The ordering is part of the API contract. When a viewport exceeds the cap it
returns the points nearest the requested bbox centre first, with UUID as a stable
tie-breaker. JSON and binary requests over the same snapshot therefore select the
same rows. Do not remove the ordering as an apparent optimisation without replacing
it with another deterministic selection strategy and updating the tests.

### Q3 — Postcode history (card)

```sql
SELECT id, price, date, property_type AS type, tenure, is_new,
       paon, saon, street, town
FROM transactions
WHERE postcode = $1          -- normalised: upper, single space
ORDER BY date DESC, id DESC
LIMIT 201;                    -- 200 returned + one truncation sentinel
```

### Q4 — District stats / districts GeoJSON / meta

```sql
SELECT district, sales, median_price FROM district_stats ORDER BY district;

SELECT json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
         json_build_object('type', 'Feature',
                           'properties', json_build_object('code', code),
                           'geometry',   ST_AsGeoJSON(geom, 5)::json)), '[]'))
FROM districts;              -- cached in-process by the API after first call

SELECT total, from_date AS "from", to_date AS "to" FROM dataset_meta WHERE id;
```

### Q5 — Filtered aggregation (required M5 SQL tool)

Same filter clauses as Q2; `group_by` is a **whitelisted** column expression chosen server-side from `{year: date_trunc('year', date), month: date_trunc('month', date), district, property_type}` — never interpolated from model output. Output capped at 60 rows.

```sql
SELECT <group_expr>                                          AS "group",   -- omitted when no grouping
       count(*)                                              AS sales,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::int AS median_price
FROM transactions
WHERE ($1::text[] IS NULL OR district = ANY($1))
  AND ($2::int    IS NULL OR price >= $2)
  AND ($3::int    IS NULL OR price <= $3)
  AND ($4::text[] IS NULL OR property_type = ANY($4))
  AND ($5::date   IS NULL OR date >= $5)
  AND ($6::date   IS NULL OR date <= $6)
GROUP BY 1            -- only when grouping
ORDER BY 1
LIMIT 60;
```

Uses `transactions_district_idx` / `transactions_date_idx`; district-filtered calls are fast, but an *unfiltered* whole-dataset aggregation is a permitted full scan (~466k rows, infrequent, chat-only) — acceptable within the 5 s statement timeout; verify with `EXPLAIN ANALYZE` at M5.

---

## 6. Performance requirements (warm DB, real dataset)

| Query | Target p50 | Hard ceiling |
|---|---|---|
| Q1 full-London bbox, zoom 10 | < 250 ms | 1 s |
| Q2 zoom-13 bbox (25k cap hit) | < 150 ms | 500 ms |
| Q3 | < 30 ms | 100 ms |
| Q4 (stats/meta) | < 30 ms | 100 ms |

Acceptance: run each with `EXPLAIN (ANALYZE, BUFFERS)` after load + `ANALYZE`. Q2 and filtered Q1 viewports must use `transactions_geom_idx`; unfiltered Q1 zooms 6–11 must use `cluster_cells`. The dynamic Q1 path remains the exact fallback for filters and for any zoom not represented by the precomputed cells.

---

## 7. Load procedure (pipeline → DB)

1. `psql $DATABASE_URL -f pipeline/schema.sql` (idempotent: `DROP ... IF EXISTS` guards or a fresh schema).
2. Bulk load: `\copy` into a staging table with numeric `lng`/`lat`, validate counts and nulls, then `INSERT ... ST_SetSRID(ST_MakePoint(lng, lat), 4326)` into `transactions`. The generated `geom_3857` is populated automatically. Use the **direct** connection and one transaction so a failed load cannot leave partial production data.
3. Load `districts` from the simplified GeoJSON (`ogr2ogr` or a small Python loader).
4. Build `cluster_cells` for unfiltered zooms 6–11 using the configured `CELL_PX`.
5. Insert one `dataset_meta` row with final row count, date range, manifest JSON, and load timestamp.
6. `REFRESH MATERIALIZED VIEW district_stats;`
7. `ANALYZE transactions; ANALYZE districts; ANALYZE dataset_meta; ANALYZE cluster_cells;`
6. Log and persist the source manifest: hashes, source min/max dates, every exclusion count, final row count, unique-postcode counts, ONSPD row-level join coverage, duplicate-key count, outside-London LAD count, terminated-postcode count, final coordinate bounds, and districts without polygons. Abort outside 400k–550k rows, below 99.9% join coverage, on any duplicate canonical ONSPD key, enum-domain drift, or any retained coordinate outside the UK sanity box in `SOURCE_DATA_PROFILE.md`.
8. Record `SELECT pg_size_pretty(pg_database_size(current_database()))` and each relation size. Abort deployment at 450 MB so maintenance/index growth cannot silently exceed the free quota.

## 8. Backup & recovery

None required beyond reproducibility: the database is a disposable cache of pipeline output (`DATA_MODEL.md` §8). Recovery = re-run pipeline (≈ minutes of compute + download time). Do not enable paid backup features.
