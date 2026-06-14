import {
  Capabilities as CapabilitiesSchema,
  ChatRequest,
  ChatResponse as ChatResponseSchema,
  ClustersResponse,
  DistrictFeatureCollection,
  DistrictStatsResponse,
  Meta,
  PostcodeHistory as PostcodeHistorySchema,
  parseChatStreamEvent,
  transactionsParams,
} from '@schema';

import type {
  BinaryPoints,
  Capabilities,
  ChatResponse,
  ClusterPayload,
  Filters,
  MetaInfo,
  PostcodeHistory,
  TransactionPayload,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

async function parseJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) {
    const message = typeof payload === 'object' && payload && 'error' in payload
      ? String((payload as { error: { message?: string } }).error.message ?? 'Request failed')
      : response.status >= 500 ? 'Data service is temporarily unavailable' : 'Request failed';
    throw new Error(message);
  }
  return payload;
}

function decodeBinary(buffer: ArrayBuffer): Promise<Omit<BinaryPoints, 'mode' | 'truncated'>> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('../workers/points.worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (event) => {
      worker.terminate();
      if (!event.data.ok) {
        reject(new Error(event.data.message));
        return;
      }
      resolve(event.data);
    };
    worker.onerror = (event) => {
      worker.terminate();
      reject(new Error(event.message));
    };
    worker.postMessage(buffer, [buffer]);
  });
}

export async function fetchTransactions(
  bbox: [number, number, number, number],
  zoom: number,
  filters: Filters,
  signal: AbortSignal,
): Promise<TransactionPayload> {
  const binary = zoom >= 12;
  const params = transactionsParams({ bbox, zoom, filters, format: binary ? 'bin' : 'json' });
  const response = await fetch(`${API_BASE}/api/transactions?${params}`, {
    signal,
    headers: { Accept: binary ? 'application/vnd.lpe.points+binary' : 'application/json' },
  });
  if (!response.ok) {
    await parseJson(response);
    throw new Error('Data service is temporarily unavailable');
  }
  if (!binary) return ClustersResponse.parse(await response.json()) as ClusterPayload;
  const decoded = await decodeBinary(await response.arrayBuffer());
  return {
    mode: 'points',
    ...decoded,
    truncated: response.headers.get('X-Truncated') === 'true',
  };
}

export async function fetchDistricts(signal: AbortSignal): Promise<unknown> {
  const response = await fetch(`${API_BASE}/api/districts`, { signal });
  return DistrictFeatureCollection.parse(await parseJson(response));
}

export async function fetchDistrictStats(signal: AbortSignal): Promise<unknown[]> {
  const response = await fetch(`${API_BASE}/api/district-stats`, { signal });
  return DistrictStatsResponse.parse(await parseJson(response));
}

export async function fetchHistory(postcode: string, signal: AbortSignal): Promise<PostcodeHistory> {
  const response = await fetch(`${API_BASE}/api/postcode/${encodeURIComponent(postcode)}/history`, { signal });
  return PostcodeHistorySchema.parse(await parseJson(response)) as PostcodeHistory;
}

export async function fetchCapabilities(): Promise<Capabilities> {
  const response = await fetch(`${API_BASE}/api/capabilities`);
  return CapabilitiesSchema.parse(await parseJson(response)) as Capabilities;
}

export async function fetchMeta(): Promise<MetaInfo> {
  const response = await fetch(`${API_BASE}/api/meta`);
  return Meta.parse(await parseJson(response)) as MetaInfo;
}

export async function streamChat(
  messages: Array<{ role: 'user' | 'assistant'; content: string }>,
  onEvent: (event: string, payload: unknown) => void,
  signal: AbortSignal,
): Promise<ChatResponse> {
  const body = ChatRequest.parse({ messages });
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    await parseJson(response);
    throw new Error('Streaming response was unavailable');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: ChatResponse | null = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let boundary = buffer.indexOf('\n\n');
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = block.match(/^event:\s*(.+)$/m)?.[1] ?? 'message';
      const data = block.match(/^data:\s*(.+)$/m)?.[1];
      if (data) {
        const payload = parseChatStreamEvent(event, JSON.parse(data));
        onEvent(event, payload);
        if (event === 'error') throw new Error((payload as { message: string }).message);
        if (event === 'final') final = ChatResponseSchema.parse(payload) as ChatResponse;
      }
      boundary = buffer.indexOf('\n\n');
    }
  }
  if (!final) throw new Error('Assistant stream ended without a final response');
  return final;
}

export async function sendFeedback(runId: string, score: -1 | 1): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat/${runId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ score }),
  });
  await parseJson(response);
}
