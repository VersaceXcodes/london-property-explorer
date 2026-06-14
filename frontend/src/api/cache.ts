import type { TransactionPayload } from './types';

type BBox = [number, number, number, number];

interface Entry {
  bbox: BBox;
  zoom: number;
  filters: string;
  payload: TransactionPayload;
  exactKey: string;
}

function contains(outer: BBox, inner: BBox): boolean {
  return outer[0] <= inner[0] && outer[1] <= inner[1] && outer[2] >= inner[2] && outer[3] >= inner[3];
}

export class ViewportCache {
  private readonly entries: Entry[] = [];

  constructor(private readonly capacity = 20) {}

  get(bbox: BBox, zoom: number, filters: string, exactKey: string): TransactionPayload | null {
    const index = this.entries.findIndex((entry) => {
      if (entry.zoom !== zoom || entry.filters !== filters) return false;
      if (entry.payload.mode === 'points' && entry.payload.truncated) return entry.exactKey === exactKey;
      return contains(entry.bbox, bbox);
    });
    if (index < 0) return null;
    const [entry] = this.entries.splice(index, 1);
    this.entries.unshift(entry);
    return entry.payload;
  }

  set(entry: Entry): void {
    this.entries.unshift(entry);
    if (this.entries.length > this.capacity) this.entries.pop();
  }

  clear(): void {
    this.entries.length = 0;
  }
}

