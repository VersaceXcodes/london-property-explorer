/**
 * schema.js — frontend contract mirror for the London Property Explorer API.
 *
 * The authoritative contract is docs/openapi.yaml; the backend enforces it
 * with Pydantic. This module is the single place the frontend gets:
 *   - Zod schemas for every API payload (runtime-validated in dev builds,
 *     `parse` in tests, `safeParse`-and-log in production paths)
 *   - shared constants (zoom threshold, caps, debounce, binary layout)
 *   - the binary points decoder used by the web worker
 *
 * Imported via the Vite alias `@schema`. Keep field names in exact sync with
 * docs/openapi.yaml — if a field changes there, it changes here in the same
 * commit.
 */

import { z } from 'zod';

// ---------------------------------------------------------------------------
// Constants (mirrored in the backend's config.py — same names)
// ---------------------------------------------------------------------------

/** Zoom at and above which the API returns raw points instead of clusters. */
export const CLUSTER_ZOOM_THRESHOLD = 12;

/** Server-side row cap for points mode. */
export const MAX_POINTS = 25000;

/** moveend → fetch debounce. */
export const FETCH_DEBOUNCE_MS = 250;

/** Viewport bbox inflation ratio so small pans hit already-loaded data. */
export const BBOX_INFLATE_RATIO = 0.2;

/** LRU size for the transactions response cache. */
export const RESPONSE_CACHE_SIZE = 20;

/** Binary points wire constants. Bytes 0..3 spell "LPE1" on the wire. */
export const BINARY_MAGIC = 0x3145504c;
export const BINARY_HEADER_BYTES = 8;
export const BINARY_BYTES_PER_POINT = 23;
export const BINARY_POSTCODE_BYTES = 8;
export const BINARY_DATE_EPOCH_MS = Date.UTC(1970, 0, 1);

export const PROPERTY_TYPES = /** @type {const} */ (['D', 'S', 'T', 'F', 'O']);

export const PROPERTY_TYPE_LABELS = {
  D: 'Detached',
  S: 'Semi-detached',
  T: 'Terraced',
  F: 'Flat / maisonette',
  O: 'Other',
};

/** Binary typeCode order — fixed; index = Uint8 code on the wire. */
export const TYPE_FROM_CODE = /** @type {const} */ (['D', 'S', 'T', 'F', 'O']);

export const TENURE_LABELS = { F: 'Freehold', L: 'Leasehold' };
export const TENURES = /** @type {const} */ (['F', 'L']);

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

export const PropertyType = z.enum(PROPERTY_TYPES);
export const Tenure = z.enum(['F', 'L']);
export const Longitude = z.number().finite().min(-180).max(180);
export const Latitude = z.number().finite().min(-90).max(90);
export const SalePrice = z.number().int().min(10000).max(50000000);
export const CanonicalUuid = z
  .string()
  .regex(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/, 'expected canonical UUID/GUID');
export const IsoDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, 'expected YYYY-MM-DD')
  .refine((value) => {
    const parsed = new Date(`${value}T00:00:00.000Z`);
    return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
  }, 'invalid calendar date');
export const PostcodeDistrict = z.string().regex(/^[A-Z]{1,2}[0-9][0-9A-Z]?$/, 'expected UK postcode district');
export const Postcode = z.string().regex(/^[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}$/, 'expected canonical UK postcode');
export const MapZoom = z.number().finite().min(0).max(22);

/** [minLng, minLat, maxLng, maxLat], WGS84, min < max on both axes. */
export const BBox = z
  .tuple([
    Longitude,
    Latitude,
    Longitude,
    Latitude,
  ])
  .refine(([a, b, c, d]) => a < c && b < d, { message: 'bbox min must be < max' });

/** Serialise a BBox for the `bbox` query param (6 dp ≈ 0.1 m — plenty). */
export const bboxToParam = (bbox) => bbox.map((v) => v.toFixed(6)).join(',');

// ---------------------------------------------------------------------------
// Client-side filter state (maps 1:1 onto /api/transactions query params)
// ---------------------------------------------------------------------------

const PropertyTypeList = z
  .array(PropertyType)
  .min(1)
  .max(5)
  .refine((values) => new Set(values).size === values.length, 'property types must be unique');
const TenureList = z
  .array(Tenure)
  .min(1)
  .max(2)
  .refine((values) => new Set(values).size === values.length, 'tenures must be unique');

const FilterFields = {
  min_price: z.number().int().min(0).max(50000000).nullable(),
  max_price: z.number().int().min(0).max(50000000).nullable(),
  types: PropertyTypeList.nullable(), // null = all types
  tenures: TenureList.nullable(), // null = all tenures
  from: IsoDate.nullable(),
  to: IsoDate.nullable(),
};

function validateFilterRanges(value, ctx) {
  if (value.min_price != null && value.max_price != null && value.min_price > value.max_price) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['max_price'], message: 'max_price must be >= min_price' });
  }
  if (value.from != null && value.to != null && value.from > value.to) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['to'], message: 'to must be >= from' });
  }
}

export const Filters = z.object(FilterFields).superRefine(validateFilterRanges);

export const EMPTY_FILTERS = Object.freeze({
  min_price: null,
  max_price: null,
  types: null,
  tenures: null,
  from: null,
  to: null,
});

/** Build /api/transactions query params from viewport + filters. */
export function transactionsParams({ bbox, zoom, filters = EMPTY_FILTERS, format = 'json' }) {
  const validBbox = BBox.parse(bbox);
  const validZoom = Math.floor(MapZoom.parse(zoom));
  const validFilters = Filters.parse(filters);
  if (format !== 'json' && format !== 'bin') throw new TypeError('format must be json or bin');
  const p = new URLSearchParams({ bbox: bboxToParam(validBbox), zoom: String(validZoom) });
  if (validFilters.min_price != null) p.set('min_price', String(validFilters.min_price));
  if (validFilters.max_price != null) p.set('max_price', String(validFilters.max_price));
  if (validFilters.types?.length) p.set('types', validFilters.types.join(','));
  if (validFilters.tenures?.length) p.set('tenures', validFilters.tenures.join(','));
  if (validFilters.from) p.set('from', validFilters.from);
  if (validFilters.to) p.set('to', validFilters.to);
  if (format === 'bin') p.set('format', 'bin');
  return p;
}

// ---------------------------------------------------------------------------
// /api/transactions responses
// ---------------------------------------------------------------------------

export const ClusterCell = z.object({
  lng: Longitude,
  lat: Latitude,
  count: z.number().int().positive(),
  median_price: SalePrice,
});

export const ClustersResponse = z.object({
  mode: z.literal('clusters'),
  cells: z.array(ClusterCell),
});

export const TransactionPoint = z.object({
  id: CanonicalUuid,
  lng: Longitude,
  lat: Latitude,
  price: SalePrice,
  type: PropertyType,
  date: IsoDate,
  postcode: Postcode,
});

export const PointsResponse = z.object({
  mode: z.literal('points'),
  truncated: z.boolean(),
  points: z.array(TransactionPoint).max(MAX_POINTS),
});

export const TransactionsResponse = z.discriminatedUnion('mode', [
  ClustersResponse,
  PointsResponse,
]);

// ---------------------------------------------------------------------------
// Districts / choropleth
// ---------------------------------------------------------------------------

export const DistrictStats = z.object({
  district: PostcodeDistrict,
  sales: z.number().int().positive(),
  median_price: SalePrice,
});

export const DistrictStatsResponse = z.array(DistrictStats);

/** Loose GeoJSON check — geometry internals are deck.gl's problem. */
export const DistrictFeatureCollection = z.object({
  type: z.literal('FeatureCollection'),
  features: z.array(
    z.object({
      type: z.literal('Feature'),
      properties: z.object({ code: PostcodeDistrict }),
      geometry: z.object({ type: z.literal('MultiPolygon'), coordinates: z.array(z.any()) }),
    }),
  ),
});

// ---------------------------------------------------------------------------
// Postcode history (property card)
// ---------------------------------------------------------------------------

export const HistoryEntry = z.object({
  id: CanonicalUuid,
  price: SalePrice,
  date: IsoDate,
  type: PropertyType,
  tenure: Tenure,
  is_new: z.boolean(),
  paon: z.string().nullable(),
  saon: z.string().nullable(),
  street: z.string().nullable(),
  town: z.string().nullable(),
});

export const PostcodeHistory = z
  .object({
    postcode: Postcode,
    count: z.number().int().min(1).max(200),
    truncated: z.boolean(),
    entries: z.array(HistoryEntry).min(1).max(200),
  })
  .superRefine((value, ctx) => {
    if (value.count !== value.entries.length) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['count'], message: 'count must equal entries.length' });
    }
    if (value.truncated && value.count !== 200) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['truncated'], message: 'truncated requires 200 returned entries' });
    }
  });

// ---------------------------------------------------------------------------
// Meta, errors
// ---------------------------------------------------------------------------

export const Health = z.object({ status: z.literal('ok') });

export const Meta = z
  .object({ total: z.number().int().positive(), from: IsoDate, to: IsoDate })
  .refine((value) => value.from <= value.to, { path: ['to'], message: 'to must be >= from' });

export const ApiError = z.object({
  error: z.object({
    code: z.enum([
      'BAD_REQUEST',
      'BAD_BBOX',
      'NOT_FOUND',
      'RATE_LIMITED',
      'DB_TIMEOUT',
      'QUERY_FAILED',
      'NOT_ENABLED',
      'AI_UNAVAILABLE',
      'AI_TIMEOUT',
      'AI_FAILED',
      'AI_COST_LIMIT',
      'AI_GROUNDING_FAILED',
      'UNSUPPORTED_QUERY',
      'FEEDBACK_UNAVAILABLE',
      'RUN_NOT_FOUND',
      'INTERNAL',
    ]),
    message: z.string(),
  }),
});

// ---------------------------------------------------------------------------
// Required M5 conversational data agent — docs/AGENTIC_AI.md.
// The client holds the transcript, streams each turn, validates the final
// contract, and treats MapAction as an inert proposal until Apply.
// ---------------------------------------------------------------------------

/** Transcript caps (server rejects beyond these — keep in sync with B-27). */
export const CHAT_MAX_MESSAGES = 12;
export const CHAT_MAX_USER_CHARS = 500;
export const CHAT_MAX_TOTAL_CHARS = 6000;

export const ChatMessage = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string().min(1).max(2000),
});

export const ChatRequest = z
  .object({ messages: z.array(ChatMessage).min(1).max(CHAT_MAX_MESSAGES) })
  .superRefine((request, ctx) => {
    const { messages } = request;
    if (messages[0].role !== 'user') {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['messages', 0, 'role'], message: 'first message must be user' });
    }
    if (messages[messages.length - 1].role !== 'user') {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['messages'], message: 'last message must be the new user turn' });
    }
    const totalChars = messages.reduce((sum, message) => sum + message.content.length, 0);
    if (totalChars > CHAT_MAX_TOTAL_CHARS) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['messages'], message: `transcript exceeds ${CHAT_MAX_TOTAL_CHARS} characters` });
    }
    messages.forEach((message, index) => {
      if (message.role === 'user' && message.content.length > CHAT_MAX_USER_CHARS) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['messages', index, 'content'], message: `user message exceeds ${CHAT_MAX_USER_CHARS} characters` });
      }
      if (index > 0 && message.role === messages[index - 1].role) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['messages', index, 'role'], message: 'message roles must alternate' });
      }
    });
  });

export const ChatStep = z.object({
  name: z.string().min(1).max(80),
  status: z.enum(['completed', 'degraded', 'failed']),
  detail: z.string().min(1).max(300),
  duration_ms: z.number().int().nonnegative(),
});

export const Citation = z.object({
  id: z.string().min(1).max(128),
  title: z.string().min(1).max(300),
  section: z.string().max(300).nullable(),
  publisher: z.string().min(1).max(200),
  url: z.string().url(),
  licence: z.string().max(200).nullable(),
});

const MapFilterPayload = z
  .object(FilterFields)
  .partial()
  .strict()
  .superRefine(validateFilterRanges)
  .refine((value) => Object.keys(value).length > 0, 'at least one filter is required');

export const MapAction = z.discriminatedUnion('kind', [
  z.object({
    kind: z.literal('set_filters'),
    payload: MapFilterPayload,
    label: z.string().min(1).max(120),
  }).strict(),
  z.object({
    kind: z.literal('highlight_district'),
    payload: z.object({ district: PostcodeDistrict }).strict(),
    label: z.string().min(1).max(120),
  }).strict(),
]);

export const AgentMetrics = z.object({
  route: z.enum(['sql', 'rag', 'hybrid', 'map_action', 'unsupported']),
  latency_ms: z.number().int().nonnegative(),
  input_tokens: z.number().int().nonnegative(),
  output_tokens: z.number().int().nonnegative(),
  estimated_cost_usd: z.number().nonnegative(),
  graph_version: z.string(),
  prompt_hash: z.string(),
  model: z.string(),
  corpus_version: z.string().nullable(),
});

export const ChatResponse = z.object({
  run_id: CanonicalUuid,
  reply: z.string().min(1).max(8000),
  citations: z.array(Citation).max(10),
  steps: z.array(ChatStep),
  map_action: MapAction.nullable(),
  degraded: z.boolean(),
  metrics: AgentMetrics,
});

export const Capabilities = z.object({
  chat: z.boolean(),
  rag: z.boolean(),
  tracing: z.boolean(),
  streaming: z.boolean(),
  feedback: z.boolean(),
  graph_version: z.string(),
  corpus_version: z.string().nullable(),
});

export const FeedbackRequest = z.object({
  score: z.union([z.literal(-1), z.literal(1)]),
  reason: z.string().max(500).nullable().optional(),
  correction: z.string().max(2000).nullable().optional(),
});

export const FeedbackResponse = z.object({
  accepted: z.boolean(),
  trace_attached: z.boolean(),
});

export const ChatStreamPayloads = {
  run_started: z.object({ run_id: CanonicalUuid }).strict(),
  step_started: z.object({ name: z.string().min(1).max(80) }).strict(),
  step_completed: ChatStep,
  citation: Citation,
  final: ChatResponse,
  error: z.object({ code: ApiError.shape.error.shape.code, message: z.string() }).strict(),
};

export function parseChatStreamEvent(event, payload) {
  const schema = ChatStreamPayloads[event];
  if (!schema) return payload;
  return schema.parse(payload);
}

// ---------------------------------------------------------------------------
// Binary points payload (format=bin) — layout per docs/openapi.yaml.
//
//   offset 0       : Uint8[4]   ASCII "LPE1"
//   offset 4       : Uint32     N (little-endian)
//   offset 8       : Float32[N] longitude
//   offset 8 + 4N  : Float32[N] latitude
//   offset 8 + 8N  : Uint32[N]  price (GBP)
//   offset 8 + 12N : Uint16[N]  days since 1970-01-01 UTC
//   offset 8 + 14N : Uint8[N]   typeCode (index into TYPE_FROM_CODE)
//   offset 8 + 15N : Uint8[8N]  canonical postcode, null-padded ASCII
//
// Total = 8 + 23N bytes. Truncation flag arrives as the X-Truncated header.
// ---------------------------------------------------------------------------

/**
 * Decode the binary points payload. Runs in the web worker; the returned
 * TypedArrays view the input buffer (zero-copy) and are posted back as
 * transferables.
 *
 * @param {ArrayBuffer} buffer
 * @returns {{ length: number, lng: Float32Array, lat: Float32Array,
 *             price: Uint32Array, dateDays: Uint16Array,
 *             typeCode: Uint8Array, postcodeBytes: Uint8Array }}
 */
export function decodePointsBinary(buffer) {
  if (buffer.byteLength < BINARY_HEADER_BYTES) {
    throw new Error(`binary points: header requires ${BINARY_HEADER_BYTES} bytes, got ${buffer.byteLength}`);
  }
  const view = new DataView(buffer);
  const magic = view.getUint32(0, true);
  if (magic !== BINARY_MAGIC) {
    throw new Error(`binary points: unsupported magic/version 0x${magic.toString(16)}`);
  }
  const n = view.getUint32(4, true);
  if (n > MAX_POINTS) {
    throw new Error(`binary points: count ${n} exceeds MAX_POINTS=${MAX_POINTS}`);
  }
  const expected = BINARY_HEADER_BYTES + BINARY_BYTES_PER_POINT * n;
  if (buffer.byteLength !== expected) {
    throw new Error(`binary points: expected ${expected} bytes for n=${n}, got ${buffer.byteLength}`);
  }
  const lngOffset = BINARY_HEADER_BYTES;
  const latOffset = lngOffset + 4 * n;
  const priceOffset = latOffset + 4 * n;
  const dateOffset = priceOffset + 4 * n;
  const typeOffset = dateOffset + 2 * n;
  const postcodeOffset = typeOffset + n;
  const decoded = {
    length: n,
    lng: new Float32Array(buffer, lngOffset, n),
    lat: new Float32Array(buffer, latOffset, n),
    price: new Uint32Array(buffer, priceOffset, n),
    dateDays: new Uint16Array(buffer, dateOffset, n),
    typeCode: new Uint8Array(buffer, typeOffset, n),
    postcodeBytes: new Uint8Array(buffer, postcodeOffset, BINARY_POSTCODE_BYTES * n),
  };
  for (let i = 0; i < decoded.typeCode.length; i++) {
    if (decoded.typeCode[i] >= TYPE_FROM_CODE.length) {
      throw new Error(`binary points: invalid typeCode=${decoded.typeCode[i]} at index ${i}`);
    }
  }
  return decoded;
}

const POSTCODE_DECODER = new TextDecoder('ascii');

/** Decode one fixed-width postcode from a binary points result. */
export function postcodeAt({ length, postcodeBytes }, index) {
  if (!Number.isInteger(index) || index < 0 || index >= length) throw new RangeError('postcode index out of range');
  const start = index * BINARY_POSTCODE_BYTES;
  const postcode = POSTCODE_DECODER
    .decode(postcodeBytes.subarray(start, start + BINARY_POSTCODE_BYTES))
    .replace(/\0+$/, '');
  return Postcode.parse(postcode);
}

/** Convert a Uint16 epoch-day value to YYYY-MM-DD without local-time drift. */
export function isoDateFromEpochDay(days) {
  if (!Number.isInteger(days) || days < 0 || days > 0xffff) throw new RangeError('invalid epoch day');
  return new Date(BINARY_DATE_EPOCH_MS + days * 86400000).toISOString().slice(0, 10);
}

/**
 * Interleave lng/lat into the single positions array deck.gl binary
 * attributes expect ({size: 2}).
 *
 * @param {{ length: number, lng: Float32Array, lat: Float32Array }} cols
 * @returns {Float32Array} [lng0, lat0, lng1, lat1, …]
 */
export function interleavePositions({ length, lng, lat }) {
  const out = new Float32Array(length * 2);
  for (let i = 0; i < length; i++) {
    out[2 * i] = lng[i];
    out[2 * i + 1] = lat[i];
  }
  return out;
}
