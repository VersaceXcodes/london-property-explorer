import { X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { PROPERTY_TYPE_LABELS, TENURE_LABELS } from '@schema';

import { fetchHistory } from '../api/client';
import type { PostcodeHistory } from '../api/types';

interface HistoryPanelProps {
  postcode: string;
  onClose: () => void;
}

function formatPrice(value: number): string {
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(value);
}

export function HistoryPanel({ postcode, onClose }: HistoryPanelProps) {
  const [history, setHistory] = useState<PostcodeHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);
  useEffect(() => {
    const controller = new AbortController();
    fetchHistory(postcode, controller.signal).then(setHistory).catch((caught) => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'History failed to load');
    });
    return () => controller.abort();
  }, [postcode]);
  const sparkline = useMemo(() => {
    const entries = history?.entries.slice().reverse() ?? [];
    if (entries.length < 2) return '';
    const prices = entries.map((entry) => entry.price);
    const minimum = Math.min(...prices);
    const maximum = Math.max(...prices);
    return prices.map((price, index) => {
      const x = (index / (prices.length - 1)) * 280;
      const y = 66 - ((price - minimum) / Math.max(1, maximum - minimum)) * 56;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
  }, [history]);
  return (
    <aside className="detail-panel" aria-label={`${postcode} sale history`}>
      <div className="detail-header">
        <div><span>Postcode history</span><h2>{postcode}</h2></div>
        <button className="icon-button" type="button" title="Close history" onClick={onClose}><X size={18} /></button>
      </div>
      {!history && !error && <p className="muted">Loading history…</p>}
      {error && <p className="error-copy">{error}</p>}
      {history && (
        <>
          {sparkline && <svg className="sparkline" viewBox="0 0 280 76" role="img" aria-label="Sale price history"><polyline points={sparkline} /></svg>}
          <div className="history-list">
            {history.entries.map((entry) => (
              <article key={entry.id} className="history-row">
                <div><strong>{formatPrice(entry.price)}</strong><span>{entry.date}</span></div>
                <div><span>{PROPERTY_TYPE_LABELS[entry.type]}</span><span>{TENURE_LABELS[entry.tenure]}</span></div>
                <p>{[entry.saon, entry.paon, entry.street, entry.town].filter(Boolean).join(', ')}</p>
              </article>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}
