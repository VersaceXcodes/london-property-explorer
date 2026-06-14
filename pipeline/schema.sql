CREATE EXTENSION IF NOT EXISTS postgis;

DROP MATERIALIZED VIEW IF EXISTS district_stats;
DROP TABLE IF EXISTS cluster_cells;
DROP TABLE IF EXISTS districts;
DROP TABLE IF EXISTS dataset_meta;
DROP TABLE IF EXISTS transactions;

CREATE TABLE transactions (
  id            uuid PRIMARY KEY,
  price         integer NOT NULL CHECK (price BETWEEN 10000 AND 50000000),
  date          date NOT NULL CHECK (date >= DATE '2021-01-01'),
  postcode      text NOT NULL CHECK (postcode ~ '^[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}$'),
  district      text NOT NULL CHECK (district ~ '^[A-Z]{1,2}[0-9][0-9A-Z]?$'),
  property_type char(1) NOT NULL CHECK (property_type IN ('D','S','T','F','O')),
  is_new        boolean NOT NULL,
  tenure        char(1) NOT NULL CHECK (tenure IN ('F','L')),
  paon          text,
  saon          text,
  street        text,
  town          text,
  geom          geometry(Point, 4326) NOT NULL,
  geom_3857     geometry(Point, 3857)
                GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED
);

CREATE INDEX transactions_geom_idx ON transactions USING gist (geom);
CREATE INDEX transactions_district_idx ON transactions (district);
CREATE INDEX transactions_date_idx ON transactions (date);
CREATE INDEX transactions_postcode_idx ON transactions (postcode);

CREATE TABLE districts (
  code text PRIMARY KEY CHECK (code ~ '^[A-Z]{1,2}[0-9][0-9A-Z]?$'),
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
       count(*) AS sales,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::integer AS median_price
FROM transactions
GROUP BY district;

CREATE UNIQUE INDEX district_stats_pk ON district_stats (district);

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_reader') THEN
    CREATE ROLE app_reader LOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_reader;
GRANT SELECT ON transactions, districts, dataset_meta, cluster_cells, district_stats TO app_reader;
ALTER ROLE app_reader SET statement_timeout = '5s';
