export type PropertyType = 'D' | 'S' | 'T' | 'F' | 'O';
export type Tenure = 'F' | 'L';

export interface Filters {
  min_price: number | null;
  max_price: number | null;
  types: PropertyType[] | null;
  tenures: Tenure[] | null;
  from: string | null;
  to: string | null;
}

export interface ClusterCell {
  lng: number;
  lat: number;
  count: number;
  median_price: number;
}

export interface ClusterPayload {
  mode: 'clusters';
  cells: ClusterCell[];
}

export interface BinaryPoints {
  mode: 'points';
  length: number;
  positions: Float32Array;
  prices: Uint32Array;
  dates: Uint16Array;
  typeCodes: Uint8Array;
  colors: Uint8Array;
  postcodes: string[];
  truncated: boolean;
}

export type TransactionPayload = ClusterPayload | BinaryPoints;

export interface HistoryEntry {
  id: string;
  price: number;
  date: string;
  type: PropertyType;
  tenure: 'F' | 'L';
  is_new: boolean;
  paon: string | null;
  saon: string | null;
  street: string | null;
  town: string | null;
}

export interface PostcodeHistory {
  postcode: string;
  count: number;
  truncated: boolean;
  entries: HistoryEntry[];
}

export interface Citation {
  id: string;
  title: string;
  section: string | null;
  publisher: string;
  url: string;
  licence: string | null;
}

export type MapAction =
  | {
    kind: 'set_filters';
    payload: Partial<Filters>;
    label: string;
  }
  | {
    kind: 'highlight_district';
    payload: { district: string };
    label: string;
  };

export interface ChatStep {
  name: string;
  status: 'completed' | 'degraded' | 'failed';
  detail: string;
  duration_ms: number;
}

export interface ChatResponse {
  run_id: string;
  reply: string;
  citations: Citation[];
  steps: ChatStep[];
  map_action: MapAction | null;
  degraded: boolean;
  metrics: {
    route: 'sql' | 'rag' | 'hybrid' | 'map_action' | 'unsupported';
    latency_ms: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
    graph_version: string;
    prompt_hash: string;
    model: string;
    corpus_version: string | null;
  };
}

export interface Capabilities {
  chat: boolean;
  rag: boolean;
  tracing: boolean;
  streaming: boolean;
  feedback: boolean;
  graph_version: string;
  corpus_version: string | null;
}

export interface MetaInfo {
  total: number;
  from: string;
  to: string;
}
