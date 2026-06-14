import { GeoJsonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { AlertCircle, Layers3, LoaderCircle, Sparkles } from 'lucide-react';
import maplibregl from 'maplibre-gl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  BBOX_INFLATE_RATIO,
  CLUSTER_ZOOM_THRESHOLD,
  FETCH_DEBOUNCE_MS,
  PROPERTY_TYPE_LABELS,
  TYPE_FROM_CODE,
  isoDateFromEpochDay,
} from '@schema';

import { ViewportCache } from '../api/cache';
import { fetchDistricts, fetchDistrictStats, fetchTransactions } from '../api/client';
import type { BinaryPoints, Filters, TransactionPayload } from '../api/types';

interface MapViewProps {
  filters: Filters;
  choropleth: boolean;
  highlightedDistrict: string | null;
  stationRadiusEnabled: boolean;
  planningEnabled: boolean;
  onPostcodeSelect: (postcode: string) => void;
  onViewMatchingAreas: () => void;
}

interface HoverInfo {
  x: number;
  y: number;
  title: string;
  detail: string;
  tone?: 'low' | 'mid' | 'high' | 'district';
}

type BBox = [number, number, number, number];
type Rgba = [number, number, number, number];
const LONDON_MAX_BOUNDS: [[number, number], [number, number]] = [[-0.72, 51.2], [0.36, 51.75]];
const PRICE_BANDS = {
  low: { label: 'Under £400k', color: [20, 184, 124] as const },
  mid: { label: '£400k-£800k', color: [20, 105, 235] as const },
  high: { label: 'Over £800k', color: [239, 91, 62] as const },
} as const;

function inflate(bbox: BBox): BBox {
  const width = bbox[2] - bbox[0];
  const height = bbox[3] - bbox[1];
  return [
    Math.max(-180, bbox[0] - width * BBOX_INFLATE_RATIO),
    Math.max(-90, bbox[1] - height * BBOX_INFLATE_RATIO),
    Math.min(180, bbox[2] + width * BBOX_INFLATE_RATIO),
    Math.min(90, bbox[3] + height * BBOX_INFLATE_RATIO),
  ];
}

function money(value: number): string {
  return new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency: 'GBP',
    maximumFractionDigits: 0,
  }).format(value);
}

function compactCount(value: number): string {
  return new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function priceBand(value: number): keyof typeof PRICE_BANDS {
  if (value < 400_000) return 'low';
  if (value < 800_000) return 'mid';
  return 'high';
}

function priceColor(value: number, alpha = 220): Rgba {
  const [red, green, blue] = PRICE_BANDS[priceBand(value)].color;
  return [red, green, blue, alpha];
}

function clusterRadius(count: number): number {
  return Math.max(120, Math.sqrt(count) * 30);
}

function clusterLabelSize(count: number): number {
  return Math.max(10, Math.min(13, 9 + Math.sqrt(count) / 14));
}

function pointRadius(price: number): number {
  if (price > 1_000_000) return 34;
  if (price > 650_000) return 30;
  return 26;
}

function payloadStatus(payload: TransactionPayload | null): string {
  if (!payload) return 'Loading…';
  if (payload.mode === 'clusters') {
    const total = payload.cells.reduce((sum, cell) => sum + cell.count, 0);
    return `${total.toLocaleString()} sales loaded`;
  }
  if (payload.truncated) return '25,000+ loaded — zoom in';
  return `${payload.length.toLocaleString()} sales loaded`;
}

function isAbortLike(caught: unknown): boolean {
  return typeof caught === 'object' && caught !== null && 'name' in caught && caught.name === 'AbortError';
}

export function MapView({
  filters,
  choropleth,
  highlightedDistrict,
  stationRadiusEnabled,
  planningEnabled,
  onPostcodeSelect,
  onViewMatchingAreas,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sequenceRef = useRef(0);
  const debounceRef = useRef<number | null>(null);
  const cacheRef = useRef(new ViewportCache());
  const requestViewportRef = useRef<() => Promise<void>>(async () => undefined);
  const [payload, setPayload] = useState<TransactionPayload | null>(null);
  const [districts, setDistricts] = useState<unknown>(null);
  const [stats, setStats] = useState<Map<string, { sales: number; median: number }>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [districtError, setDistrictError] = useState<string | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const filtersKey = useMemo(() => JSON.stringify(filters), [filters]);

  const requestViewport = useCallback(async () => {
    const map = mapRef.current;
    if (!map) return;
    const bounds = map.getBounds();
    const requested: BBox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
    const expanded = inflate(requested);
    const zoom = Math.floor(map.getZoom());
    const exactKey = `${requested.map((value) => value.toFixed(5)).join(',')}:${zoom}:${filtersKey}`;
    const cached = cacheRef.current.get(requested, zoom, filtersKey, exactKey);
    if (cached) {
      setPayload(cached);
      setLoading(false);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const sequence = ++sequenceRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchTransactions(expanded, zoom, filters, controller.signal);
      if (sequence !== sequenceRef.current) return;
      cacheRef.current.set({ bbox: expanded, zoom, filters: filtersKey, payload: next, exactKey });
      setPayload(next);
    } catch (caught) {
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      setError(caught instanceof Error ? caught.message : 'Map data failed to load');
    } finally {
      if (sequence === sequenceRef.current) setLoading(false);
    }
  }, [filters, filtersKey]);

  useEffect(() => {
    requestViewportRef.current = requestViewport;
  }, [requestViewport]);

  useEffect(() => {
    cacheRef.current.clear();
    void requestViewport().catch((caught: unknown) => {
      if (!isAbortLike(caught)) throw caught;
    });
  }, [filtersKey, requestViewport]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: import.meta.env.VITE_MAP_STYLE_URL ?? 'https://tiles.openfreemap.org/styles/liberty',
      center: [-0.118, 51.509],
      zoom: 11,
      minZoom: 8,
      maxZoom: 18,
      maxBounds: LONDON_MAX_BOUNDS,
      attributionControl: { compact: true },
    });
    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    map.addControl(overlay as unknown as maplibregl.IControl);
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    const schedule = () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      debounceRef.current = window.setTimeout(() => {
        void requestViewportRef.current().catch((caught: unknown) => {
          if (!isAbortLike(caught)) throw caught;
        });
      }, FETCH_DEBOUNCE_MS);
    };
    map.on('load', schedule);
    map.on('moveend', schedule);
    mapRef.current = map;
    overlayRef.current = overlay;
    return () => {
      abortRef.current?.abort();
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!choropleth || districts) return;
    const controller = new AbortController();
    Promise.all([fetchDistricts(controller.signal), fetchDistrictStats(controller.signal)])
      .then(([features, rows]) => {
        setDistrictError(null);
        setDistricts(features);
        setStats(new Map((rows as Array<{ district: string; sales: number; median_price: number }>).map(
          (row) => [row.district, { sales: row.sales, median: row.median_price }],
        )));
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setDistrictError(caught instanceof Error ? caught.message : 'District layer unavailable');
        }
      });
    return () => controller.abort();
  }, [choropleth, districts]);

  useEffect(() => {
    const layers = [];
    if (choropleth && districts) {
      const medians = [...stats.values()].map((value) => value.median);
      const maximum = Math.max(...medians, 1);
      layers.push(new GeoJsonLayer({
        id: 'districts',
        data: districts as never,
        filled: true,
        stroked: true,
        lineWidthMinPixels: 1,
        lineWidthMaxPixels: 4,
        getLineWidth: (feature: { properties: { code: string } }) => highlightedDistrict === feature.properties.code ? 3 : 1,
        getLineColor: (feature: { properties: { code: string } }) => highlightedDistrict === feature.properties.code ? [124, 58, 237, 235] : [255, 255, 255, 210],
        getFillColor: (feature: { properties: { code: string } }) => {
          const code = feature.properties.code;
          if (highlightedDistrict === code) return [124, 58, 237, 120];
          const ratio = (stats.get(code)?.median ?? 0) / maximum;
          return [20, 118 + Math.round(76 * ratio), 154 + Math.round(75 * ratio), 118];
        },
        pickable: true,
        onHover: ({ object, x, y }) => {
          if (!object) return setHover(null);
          const code = object.properties.code as string;
          const value = stats.get(code);
          setHover({ x, y, title: code, detail: value ? `${value.sales.toLocaleString()} sales · ${money(value.median)}` : 'No sales', tone: 'district' });
        },
      }));
    }
    if (payload?.mode === 'clusters') {
      layers.push(new ScatterplotLayer({
        id: 'cluster-halos',
        data: payload.cells,
        getPosition: (cell) => [cell.lng, cell.lat],
        getRadius: (cell) => clusterRadius(cell.count) * 1.7,
        radiusUnits: 'meters',
        radiusMinPixels: 7,
        radiusMaxPixels: 26,
        getFillColor: (cell) => priceColor(cell.median_price, 28),
        getLineColor: [255, 255, 255, 0],
        stroked: false,
        pickable: false,
      }));
      layers.push(new ScatterplotLayer({
        id: 'clusters',
        data: payload.cells,
        getPosition: (cell) => [cell.lng, cell.lat],
        getRadius: (cell) => clusterRadius(cell.count),
        radiusUnits: 'meters',
        radiusMinPixels: 4,
        radiusMaxPixels: 18,
        getFillColor: (cell) => priceColor(cell.median_price, 208),
        getLineColor: [255, 255, 255, 245],
        lineWidthMinPixels: 1.25,
        stroked: true,
        pickable: true,
        onHover: ({ object, x, y }) => setHover(object ? { x, y, title: `${object.count.toLocaleString()} sales`, detail: `${PRICE_BANDS[priceBand(object.median_price)].label} · median ${money(object.median_price)}`, tone: priceBand(object.median_price) } : null),
      }));
      layers.push(new TextLayer({
        id: 'cluster-labels',
        data: payload.cells.filter((cell) => cell.count >= 1_000),
        getPosition: (cell) => [cell.lng, cell.lat],
        getText: (cell) => compactCount(cell.count),
        getColor: [255, 255, 255, 245],
        getSize: (cell) => clusterLabelSize(cell.count),
        sizeUnits: 'pixels',
        fontWeight: 800,
        pickable: false,
      }));
    }
    if (payload?.mode === 'points') {
      const points = payload as BinaryPoints;
      const radii = new Float32Array(points.length);
      for (let index = 0; index < points.length; index += 1) radii[index] = pointRadius(points.prices[index]);
      layers.push(new ScatterplotLayer({
        id: 'point-halos',
        data: {
          length: points.length,
          attributes: {
            getPosition: { value: points.positions, size: 2 },
          },
        },
        getRadius: 42,
        radiusUnits: 'meters',
        radiusMinPixels: 7,
        radiusMaxPixels: 14,
        getFillColor: [15, 25, 55, 34],
        stroked: false,
        pickable: false,
      }));
      layers.push(new ScatterplotLayer({
        id: 'points',
        data: {
          length: points.length,
          attributes: {
            getPosition: { value: points.positions, size: 2 },
            getFillColor: { value: points.colors, size: 4, type: 'unorm8', normalized: true },
            getRadius: { value: radii, size: 1 },
          },
        },
        radiusUnits: 'meters',
        radiusMinPixels: 4,
        radiusMaxPixels: 11,
        getLineColor: [255, 255, 255, 235],
        lineWidthMinPixels: 1.5,
        stroked: true,
        pickable: true,
        onHover: ({ index, x, y }) => {
          if (index < 0) {
            setHover(null);
            return;
          }
          const type = TYPE_FROM_CODE[points.typeCodes[index]];
          setHover({
            x,
            y,
            title: points.postcodes[index],
            detail: `${money(points.prices[index])} · ${PROPERTY_TYPE_LABELS[type]} · ${isoDateFromEpochDay(points.dates[index])}`,
            tone: priceBand(points.prices[index]),
          });
        },
        onClick: ({ index }) => {
          if (index >= 0) onPostcodeSelect(points.postcodes[index]);
        },
      }));
    }
    overlayRef.current?.setProps({ layers });
  }, [choropleth, districts, highlightedDistrict, onPostcodeSelect, payload, stats]);

  return (
    <section className="map-stage" aria-label="London property map">
      <div ref={containerRef} className="map-canvas" />
      <div className="map-insights-toggle"><Sparkles size={15} /> Map insights <b>ON</b></div>
      <div className="map-mode-badge">
        {payload?.mode === 'points' ? 'Transactions' : 'Clusters'}
        {' · '}
        {payloadStatus(payload)}
      </div>
      {loading && <div className="map-status"><LoaderCircle className="spin" size={16} /> Loading map data</div>}
      {error && <div className="map-status error"><AlertCircle size={16} /> {error}</div>}
      {choropleth && districtError && <div className="map-status error"><AlertCircle size={16} /> {districtError}</div>}
      {hover && <div className={`map-tooltip ${hover.tone ?? ''}`} style={{ left: hover.x + 12, top: hover.y + 12 }}><strong>{hover.title}</strong><span>{hover.detail}</span></div>}
      {planningEnabled && (
        <div className="map-callout">
          <span><Sparkles size={14} /> AI insight</span>
          <strong>Undervalued pocket detected in SE1 near Borough station</strong>
          <button type="button" onClick={onViewMatchingAreas}>View matching areas</button>
        </div>
      )}
      <div className="map-legend" aria-label="Price legend">
        <div className="legend-title"><strong>Map legend</strong><Layers3 size={14} /></div>
        <span><i className="cluster-dot" /> <b>Clustered sales</b><small>Bubble size shows transaction volume.</small></span>
        <span><i className="zone-swatch" /> <b>Postcode zones</b><small>Selected districts and analysis areas.</small></span>
        <span><i className="price-bands" /> <b>Price bands</b><small>Green under £400k, blue £400k-£800k, coral over £800k.</small></span>
        {stationRadiusEnabled && <span><i className="station-dot" /> <b>Transport</b><small>Nearby rail and underground stations.</small></span>}
        <small>Points from zoom {CLUSTER_ZOOM_THRESHOLD}</small>
      </div>
      <footer className="source-strip">HM Land Registry Price Paid Data · OGL v3.0 · ONS postcode centroids · OGL v3.0</footer>
    </section>
  );
}
