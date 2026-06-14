import { describe, expect, it } from 'vitest';

import { ViewportCache } from './cache';
import type { ClusterPayload, TransactionPayload } from './types';

const clusters: ClusterPayload = { mode: 'clusters', cells: [] };

describe('ViewportCache', () => {
  it('reuses an untruncated containing viewport', () => {
    const cache = new ViewportCache();
    cache.set({ bbox: [-1, 50, 1, 52], zoom: 10, filters: '{}', payload: clusters, exactKey: 'large' });
    expect(cache.get([-.5, 50.5, .5, 51.5], 10, '{}', 'small')).toBe(clusters);
  });

  it('does not reuse truncated points for a different viewport', () => {
    const payload: TransactionPayload = {
      mode: 'points',
      length: 0,
      positions: new Float32Array(),
      prices: new Uint32Array(),
      dates: new Uint16Array(),
      typeCodes: new Uint8Array(),
      colors: new Uint8Array(),
      postcodes: [],
      truncated: true,
    };
    const cache = new ViewportCache();
    cache.set({ bbox: [-1, 50, 1, 52], zoom: 13, filters: '{}', payload, exactKey: 'first' });
    expect(cache.get([-.5, 50.5, .5, 51.5], 13, '{}', 'second')).toBeNull();
    expect(cache.get([-.5, 50.5, .5, 51.5], 13, '{}', 'first')).toBe(payload);
  });
});
