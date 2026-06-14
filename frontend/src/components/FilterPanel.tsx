import type { ComponentType } from 'react';
import { Building, Building2, ChevronDown, CircleHelp, Home, House, RotateCcw, Warehouse } from 'lucide-react';

import { EMPTY_FILTERS, PROPERTY_TYPE_LABELS, PROPERTY_TYPES, TENURE_LABELS, TENURES } from '@schema';

import type { Filters, PropertyType, Tenure } from '../api/types';

interface FilterPanelProps {
  filters: Filters;
  onChange: (filters: Filters) => void;
  stationRadiusEnabled: boolean;
  planningEnabled: boolean;
  onStationRadiusChange: (enabled: boolean) => void;
  onPlanningChange: (enabled: boolean) => void;
  onApply: () => void;
}

const typeIcons: Record<PropertyType, ComponentType<{ size?: number; strokeWidth?: number }>> = {
  D: House,
  S: Home,
  T: Building2,
  F: Building,
  O: Warehouse,
};

function formatPrice(value: number | null, fallback: string) {
  if (value == null) return fallback;
  if (value >= 1_000_000) return `£${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`;
  return `£${Math.round(value / 1000)}K`;
}

export function FilterPanel({
  filters,
  onChange,
  stationRadiusEnabled,
  planningEnabled,
  onStationRadiusChange,
  onPlanningChange,
  onApply,
}: FilterPanelProps) {
  const setNumber = (field: 'min_price' | 'max_price', value: string) => {
    onChange({ ...filters, [field]: value === '' ? null : Number(value) });
  };
  const toggleType = (type: PropertyType) => {
    const current = filters.types ?? [];
    const next = current.includes(type) ? current.filter((value) => value !== type) : [...current, type];
    onChange({ ...filters, types: next.length === 0 || next.length === PROPERTY_TYPES.length ? null : next });
  };
  const toggleTenure = (tenure: Tenure) => {
    const current = filters.tenures ?? [];
    const next = current.includes(tenure) ? current.filter((value) => value !== tenure) : [...current, tenure];
    onChange({ ...filters, tenures: next.length === 0 || next.length === TENURES.length ? null : next });
  };
  return (
    <section className="control-section filter-panel" aria-labelledby="filter-heading">
      <div className="section-heading">
        <h2 id="filter-heading">Filters</h2>
        <button className="text-button" type="button" title="Reset filters" onClick={() => onChange({ ...EMPTY_FILTERS })}>
          Reset <RotateCcw size={14} />
        </button>
      </div>

      <div className="filter-block">
        <div className="filter-label-row">
          <span>Price range</span>
          <button className="select-chip" type="button" onClick={() => onChange({ ...filters, min_price: null, max_price: null })}>Any <ChevronDown size={14} /></button>
        </div>
        <div className="range-track" aria-hidden="true"><i /></div>
        <div className="range-values"><span>{formatPrice(filters.min_price, '£100K')}</span><span>{formatPrice(filters.max_price, '£2M+')}</span></div>
        <div className="field-row compact-inputs">
          <label>Minimum price<input inputMode="numeric" type="number" min="0" max="50000000" step="10000" value={filters.min_price ?? ''} onChange={(event) => setNumber('min_price', event.target.value)} /></label>
          <label>Maximum price<input inputMode="numeric" type="number" min="0" max="50000000" step="10000" value={filters.max_price ?? ''} onChange={(event) => setNumber('max_price', event.target.value)} /></label>
        </div>
      </div>

      <fieldset className="filter-block">
        <legend>Property type</legend>
        <div className="type-button-grid">
          {PROPERTY_TYPES.map((type: PropertyType) => {
            const Icon = typeIcons[type];
            const selected = filters.types === null || filters.types.includes(type);
            return (
              <button key={type} className={selected ? 'type-button active' : 'type-button'} type="button" aria-pressed={selected} title={PROPERTY_TYPE_LABELS[type]} onClick={() => toggleType(type)}>
                <Icon size={16} />
                <span>{PROPERTY_TYPE_LABELS[type]}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="filter-block">
        <div className="filter-label-row">
          <span>Tenure</span>
          <button className="select-chip" type="button" onClick={() => onChange({ ...filters, tenures: null })}>All <ChevronDown size={14} /></button>
        </div>
        <div className="pill-row" role="group" aria-label="Tenure">
          {TENURES.map((tenure: Tenure) => {
            const selected = filters.tenures === null || filters.tenures.includes(tenure);
            return (
              <button key={tenure} className={selected ? 'filter-pill active' : 'filter-pill'} type="button" aria-pressed={selected} onClick={() => toggleTenure(tenure)}>
                {TENURE_LABELS[tenure]}
              </button>
            );
          })}
        </div>
      </div>

      <div className="filter-block">
        <div className="filter-label-row">
          <span>Transaction date</span>
          <CircleHelp size={13} />
        </div>
        <div className="field-row">
          <label>From<input type="date" value={filters.from ?? ''} onChange={(event) => onChange({ ...filters, from: event.target.value || null })} /></label>
          <label>To<input type="date" value={filters.to ?? ''} onChange={(event) => onChange({ ...filters, to: event.target.value || null })} /></label>
        </div>
      </div>

      <div className="filter-block toggles">
        <label className="switch-row"><span>Radius near station</span><input type="checkbox" checked={stationRadiusEnabled} onChange={(event) => onStationRadiusChange(event.target.checked)} /></label>
        <label className="switch-row"><span>Planning applications</span><input type="checkbox" checked={planningEnabled} onChange={(event) => onPlanningChange(event.target.checked)} /></label>
        <div className="planning-options">
          <span><i className="green" /> Granted</span>
          <span><i className="orange" /> Pending</span>
          <span><i className="red" /> Refused</span>
        </div>
      </div>

      <div className="filter-actions">
        <button className="primary-action" type="button" onClick={onApply}>Apply filters</button>
        <span>Live results</span>
      </div>
    </section>
  );
}
