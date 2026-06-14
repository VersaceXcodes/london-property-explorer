from __future__ import annotations

CLUSTERS = """
SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(center_x, center_y), 3857), 4326)) AS lng,
       ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(center_x, center_y), 3857), 4326)) AS lat,
       cnt AS count,
       median_price
FROM (
  SELECT avg(ST_X(geom_3857)) AS center_x,
         avg(ST_Y(geom_3857)) AS center_y,
         count(*) AS cnt,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::integer AS median_price
  FROM (
    SELECT geom_3857, price, ST_SnapToGrid(geom_3857, $5, $5) AS cell
    FROM transactions
    WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
      AND ($6::integer IS NULL OR price >= $6)
      AND ($7::integer IS NULL OR price <= $7)
      AND ($8::text[] IS NULL OR property_type = ANY($8))
      AND ($9::text[] IS NULL OR tenure = ANY($9))
      AND ($10::date IS NULL OR date >= $10)
      AND ($11::date IS NULL OR date <= $11)
  ) points
  GROUP BY cell
) cells
ORDER BY count DESC, lng, lat
"""

PRECOMPUTED_CLUSTERS = """
SELECT lng, lat, sale_count AS count, median_price
FROM cluster_cells
WHERE zoom = $1
  AND cell_px = $2
  AND bbox && ST_MakeEnvelope($3, $4, $5, $6, 4326)
ORDER BY count DESC, lng, lat
"""

POINTS = """
SELECT id, ST_X(geom) AS lng, ST_Y(geom) AS lat,
       price, property_type AS type, date, postcode
FROM transactions
WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
  AND ($5::integer IS NULL OR price >= $5)
  AND ($6::integer IS NULL OR price <= $6)
  AND ($7::text[] IS NULL OR property_type = ANY($7))
  AND ($8::text[] IS NULL OR tenure = ANY($8))
  AND ($9::date IS NULL OR date >= $9)
  AND ($10::date IS NULL OR date <= $10)
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(($1 + $3) / 2.0, ($2 + $4) / 2.0), 4326), id
LIMIT $11
"""

POSTCODE_HISTORY = """
SELECT id, price, date, property_type AS type, tenure, is_new,
       paon, saon, street, town
FROM transactions
WHERE postcode = $1
ORDER BY date DESC, id DESC
LIMIT 201
"""

DISTRICT_STATS = "SELECT district, sales, median_price FROM district_stats ORDER BY district"

DISTRICTS = """
SELECT json_build_object(
  'type', 'FeatureCollection',
  'features', coalesce(
    json_agg(
      json_build_object(
        'type', 'Feature',
        'properties', json_build_object('code', code),
        'geometry', ST_AsGeoJSON(geom, 5)::json
      ) ORDER BY code
    ),
    '[]'::json
  )
) AS feature_collection
FROM districts
"""

META = 'SELECT total, from_date AS "from", to_date AS "to" FROM dataset_meta WHERE id'

TOP_DISTRICTS = """
SELECT district, sales, median_price
FROM district_stats
ORDER BY
  CASE WHEN $1 = 'sales' AND $2 = 'asc' THEN sales END ASC,
  CASE WHEN $1 = 'sales' AND $2 = 'desc' THEN sales END DESC,
  CASE WHEN $1 = 'median_price' AND $2 = 'asc' THEN median_price END ASC,
  CASE WHEN $1 = 'median_price' AND $2 = 'desc' THEN median_price END DESC,
  district ASC
LIMIT $3
"""
