import { describe, expect, it } from 'vitest';

import { ChatResponse, decodePointsBinary, isoDateFromEpochDay, postcodeAt, transactionsParams } from '@schema';

describe('shared API contract', () => {
  it('decodes the LPE1 binary layout', () => {
    const buffer = new ArrayBuffer(31);
    const view = new DataView(buffer);
    view.setUint32(0, 0x3145504c, true);
    view.setUint32(4, 1, true);
    view.setFloat32(8, -0.16, true);
    view.setFloat32(12, 51.47, true);
    view.setUint32(16, 485_000, true);
    view.setUint16(20, 19_783, true);
    view.setUint8(22, 3);
    new Uint8Array(buffer, 23).set(new TextEncoder().encode('SW11 4NB'));
    const result = decodePointsBinary(buffer);
    expect(result.length).toBe(1);
    expect(result.price[0]).toBe(485_000);
    expect(postcodeAt(result, 0)).toBe('SW11 4NB');
    expect(isoDateFromEpochDay(result.dateDays[0])).toBe('2024-03-01');
  });

  it('validates the full chat response', () => {
    const response = ChatResponse.parse({
      run_id: '00000000-0000-4000-8000-000000000001',
      reply: 'Grounded response',
      citations: [],
      steps: [],
      map_action: null,
      degraded: false,
      metrics: {
        route: 'sql',
        latency_ms: 20,
        input_tokens: 10,
        output_tokens: 5,
        estimated_cost_usd: 0.001,
        graph_version: 'lpe-agent-v1',
        prompt_hash: 'abc',
        model: 'test',
        corpus_version: null,
      },
    });
    expect(response.metrics.route).toBe('sql');
  });

  it('serialises map filters into transaction query params', () => {
    const params = transactionsParams({
      bbox: [-0.2, 51.4, 0.1, 51.6],
      zoom: 12.8,
      filters: {
        min_price: 400000,
        max_price: 900000,
        types: ['T'],
        tenures: ['L'],
        from: '2024-01-01',
        to: '2025-04-30',
      },
      format: 'bin',
    });
    expect(params.get('zoom')).toBe('12');
    expect(params.get('types')).toBe('T');
    expect(params.get('tenures')).toBe('L');
    expect(params.get('format')).toBe('bin');
  });
});
