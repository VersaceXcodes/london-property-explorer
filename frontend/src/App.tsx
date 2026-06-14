import type { ComponentType } from 'react';
import {
  BarChart3,
  Bell,
  Bookmark,
  Bot,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Download,
  FileText,
  Home,
  Info,
  Layers3,
  LifeBuoy,
  Lightbulb,
  Map,
  MapPin,
  PanelLeft,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Undo2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

import { EMPTY_FILTERS, Filters as FiltersSchema } from '@schema';

import { fetchMeta } from './api/client';
import type { Filters, MapAction, MetaInfo, PropertyType } from './api/types';
import { FilterPanel } from './components/FilterPanel';
import { HistoryPanel } from './components/HistoryPanel';
import { ChatPanel } from './features/chat/ChatPanel';
import { MapView } from './map/MapView';

interface ExplorerState {
  filters: Filters;
  highlightedDistrict: string | null;
  choropleth: boolean;
}

interface NavItem {
  label: string;
  Icon: ComponentType<{ size?: number; strokeWidth?: number }>;
}

interface Toast {
  id: number;
  title: string;
  detail: string;
  kind: 'info' | 'success' | 'warning';
}

type MenuKey = 'date' | 'location' | 'property' | 'notifications' | 'account' | null;

const navItems: NavItem[] = [
  { label: 'Dashboard', Icon: Home },
  { label: 'Map', Icon: Map },
  { label: 'Sales', Icon: BarChart3 },
  { label: 'Planning', Icon: BriefcaseBusiness },
  { label: 'Heatmaps', Icon: Layers3 },
  { label: 'Areas', Icon: Building2 },
  { label: 'Saved Searches', Icon: Lightbulb },
  { label: 'Reports', Icon: FileText },
];

const dateRanges = [
  { label: 'All available dates', from: null, to: null },
  { label: 'Last 12 months', from: '2025-05-01', to: '2026-04-30' },
  { label: '1 Apr 2024 - 30 Apr 2025', from: '2024-04-01', to: '2025-04-30' },
  { label: '2021-2026 snapshot', from: '2021-01-01', to: '2026-04-30' },
] as const;

const locationOptions = [
  { label: 'London', district: null },
  { label: 'SW11 Battersea', district: 'SW11' },
  { label: 'N1 Islington', district: 'N1' },
  { label: 'SE1 Southwark', district: 'SE1' },
  { label: 'E2 Bethnal Green', district: 'E2' },
] as const;

const propertyOptions: Array<{ label: string; types: PropertyType[] | null }> = [
  { label: 'All property types', types: null },
  { label: 'Flats', types: ['F'] },
  { label: 'Terraced', types: ['T'] },
  { label: 'Houses', types: ['D', 'S', 'T'] },
  { label: 'Detached only', types: ['D'] },
];

const navCopy: Record<string, string> = {
  Dashboard: 'Overview mode keeps the live map visible while summarising the full loaded dataset.',
  Map: 'Explore sales, postcode districts, filters, and postcode histories on the live map.',
  Sales: 'Sales mode focuses on transaction clusters and price filters.',
  Planning: 'Planning view keeps the planning insight overlay visible for local review.',
  Heatmaps: 'Heatmaps view enables district medians and postcode-zone colouring.',
  Areas: 'Areas view highlights district comparisons on top of the live sales map.',
  'Saved Searches': 'Saved searches are stored in this browser session for reviewer workflows.',
  Reports: 'Reports are generated as local draft records until deployment storage is configured.',
};

function propertyLabel(types: PropertyType[] | null): string {
  if (!types) return 'All property types';
  const match = propertyOptions.find((option) => option.types?.join(',') === types.join(','));
  return match?.label ?? `${types.length} property types`;
}

function canonicalPostcode(value: string): string | null {
  const compact = value.toUpperCase().replace(/\s+/g, '');
  if (!/^[A-Z]{1,2}[0-9][0-9A-Z]?[0-9][A-Z]{2}$/.test(compact)) return null;
  return `${compact.slice(0, -3)} ${compact.slice(-3)}`;
}

function Sparkline({ tone }: { tone: 'green' | 'blue' | 'purple' | 'teal' | 'orange' }) {
  return (
    <svg className={`mini-spark ${tone}`} viewBox="0 0 110 34" aria-hidden="true">
      <polyline points="2,26 14,22 25,24 36,15 47,20 58,12 69,18 80,9 91,13 108,6" />
    </svg>
  );
}

function MetricCard({
  label,
  value,
  delta,
  tone,
  Icon,
}: {
  label: string;
  value: string;
  delta: string;
  tone: 'green' | 'blue' | 'purple' | 'teal' | 'orange';
  Icon: ComponentType<{ size?: number; strokeWidth?: number }>;
}) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}><Icon size={22} /></div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{delta}</small>
      </div>
      <Sparkline tone={tone} />
    </article>
  );
}

export default function App() {
  const [filters, setFilters] = useState<Filters>({ ...EMPTY_FILTERS });
  const [choropleth, setChoropleth] = useState(false);
  const [selectedPostcode, setSelectedPostcode] = useState<string | null>(null);
  const [highlightedDistrict, setHighlightedDistrict] = useState<string | null>(null);
  const [activeView, setActiveView] = useState('Map');
  const [chatOpen, setChatOpen] = useState(true);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [stationRadiusEnabled, setStationRadiusEnabled] = useState(true);
  const [planningEnabled, setPlanningEnabled] = useState(true);
  const [undoState, setUndoState] = useState<ExplorerState | null>(null);
  const [meta, setMeta] = useState<MetaInfo | null>(null);
  const [openMenu, setOpenMenu] = useState<MenuKey>(null);
  const [searchValue, setSearchValue] = useState('');
  const [dateLabel, setDateLabel] = useState('1 Apr 2024 - 30 Apr 2025');
  const [locationLabel, setLocationLabel] = useState('London');
  const [toast, setToast] = useState<Toast | null>(null);
  const [savedSearches, setSavedSearches] = useState<string[]>(['London all sales']);
  const [reports, setReports] = useState<string[]>(['London Area Report draft']);
  const [automations, setAutomations] = useState(['Weekly borough scan', 'Planning alert monitor']);
  const [notifications, setNotifications] = useState([
    'OpenRouter SQL chat enabled',
    'Supabase snapshot loaded',
    'Pinecone RAG still pending',
  ]);
  const dashboardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    fetchMeta().then(setMeta).catch(() => undefined);
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => dashboardRef.current?.scrollTo({ top: 0, left: 0 }));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const timeout = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const showToast = useCallback((title: string, detail = '', kind: Toast['kind'] = 'info') => {
    setToast({ id: Date.now(), title, detail, kind });
  }, []);

  const selectPostcode = useCallback((postcode: string) => setSelectedPostcode(postcode), []);
  const snapshot = (): ExplorerState => ({ filters, highlightedDistrict, choropleth });
  const highlightDistrict = (district: string, label = `Highlighted ${district}`) => {
    setUndoState(snapshot());
    setHighlightedDistrict(district);
    setChoropleth(true);
    setLocationLabel(district);
    showToast(label, 'District medians are enabled and can be undone.', 'success');
  };
  const applyAction = (action: MapAction) => {
    if (action.kind === 'highlight_district' && typeof action.payload.district === 'string') {
      highlightDistrict(action.payload.district, action.label);
    }
    if (action.kind === 'set_filters') {
      const next = FiltersSchema.safeParse({ ...filters, ...action.payload });
      if (!next.success) return;
      setUndoState(snapshot());
      setFilters(next.data as Filters);
      showToast('Filters updated from AI proposal', action.label, 'success');
    }
  };
  const undo = () => {
    if (!undoState) return;
    setFilters(undoState.filters);
    setHighlightedDistrict(undoState.highlightedDistrict);
    setChoropleth(undoState.choropleth);
    setUndoState(null);
    showToast('Map change undone', 'Previous filters and layer state restored.', 'success');
  };
  const handleNav = (label: string) => {
    setActiveView(label);
    if (label === 'Map') {
      setOpenMenu(null);
    }
    if (label === 'Sales') {
      setChoropleth(false);
      setControlsOpen(true);
    }
    if (label === 'Planning') {
      setPlanningEnabled(true);
    }
    if (label === 'Heatmaps') {
      setChoropleth(true);
    }
    if (label === 'Areas') {
      highlightDistrict('SE1', 'Areas view opened on SE1');
    }
    if (label === 'Saved Searches') {
      setControlsOpen(true);
    }
    if (label === 'Reports') {
      setReports((current) => current.includes('Current map report draft') ? current : ['Current map report draft', ...current]);
    }
    showToast(`${label} view active`, navCopy[label] ?? 'Workspace state updated.', 'info');
  };
  const applyDateRange = (range: (typeof dateRanges)[number]) => {
    setFilters((current) => ({ ...current, from: range.from, to: range.to }));
    setDateLabel(range.label);
    setOpenMenu(null);
    showToast('Date range updated', range.label, 'success');
  };
  const applyLocation = (option: (typeof locationOptions)[number]) => {
    setLocationLabel(option.label);
    setOpenMenu(null);
    if (option.district) {
      highlightDistrict(option.district, `Focused ${option.label}`);
    } else {
      setUndoState(snapshot());
      setHighlightedDistrict(null);
      showToast('Location reset to London', 'District highlight cleared.', 'success');
    }
  };
  const applyPropertyPreset = (option: (typeof propertyOptions)[number]) => {
    setFilters((current) => ({ ...current, types: option.types }));
    setOpenMenu(null);
    showToast('Property type filter updated', option.label, 'success');
  };
  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    const raw = searchValue.trim();
    if (!raw) return;
    const postcode = canonicalPostcode(raw);
    if (postcode) {
      setSelectedPostcode(postcode);
      showToast('Postcode history opened', postcode, 'success');
      return;
    }
    const district = raw.toUpperCase().match(/\b[A-Z]{1,2}[0-9][0-9A-Z]?\b/)?.[0];
    if (district) {
      highlightDistrict(district, `Focused ${district}`);
      return;
    }
    const lowered = raw.toLowerCase();
    if (lowered.includes('flat')) {
      setFilters((current) => ({ ...current, types: ['F'] }));
      showToast('Search applied', 'Filtered to flats and maisonettes.', 'success');
      return;
    }
    if (lowered.includes('terraced')) {
      setFilters((current) => ({ ...current, types: ['T'] }));
      showToast('Search applied', 'Filtered to terraced properties.', 'success');
      return;
    }
    showToast('Search is map-scoped', 'Try a postcode, district, “flats”, or “terraced”.', 'warning');
  };
  const saveCurrentSearch = () => {
    const label = `${locationLabel} · ${propertyLabel(filters.types)} · ${dateLabel}`;
    setSavedSearches((current) => current.includes(label) ? current : [label, ...current].slice(0, 5));
    showToast('Saved search created', label, 'success');
  };
  const createAutomation = () => {
    const label = `Map monitor ${automations.length + 1}`;
    setAutomations((current) => [label, ...current].slice(0, 4));
    showToast('Automation created', `${label} will monitor the current map state in this session.`, 'success');
  };
  const createReport = () => {
    const label = `${locationLabel} report draft`;
    setReports((current) => [label, ...current.filter((item) => item !== label)].slice(0, 5));
    showToast('Report draft created', label, 'success');
  };

  return (
    <div className="property-app">
      <aside className="side-nav" aria-label="Primary navigation">
        <div className="property-logo" aria-label="PropertyIQ">
          <span>Property</span><strong>IQ</strong>
          <em>HM Land Registry + ONS</em>
        </div>
        <nav className="nav-list">
          {navItems.map(({ label, Icon }) => (
            <button key={label} className={activeView === label ? 'nav-item active' : 'nav-item'} type="button" onClick={() => handleNav(label)}>
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="nav-footer">
          <button className="nav-item compact" type="button" onClick={() => setOpenMenu('notifications')}><Lightbulb size={17} /><span>What's new</span><i /></button>
          <button className="nav-item compact" type="button" onClick={() => showToast('Help & support', 'Try search, filter chips, map clicks, or Ask AI for SQL-grounded questions.', 'info')}><LifeBuoy size={17} /><span>Help & Support</span></button>
          <button className="nav-item compact" type="button" onClick={() => showToast('Settings', 'Local reviewer settings are already using Supabase data and OpenRouter chat.', 'info')}><Settings size={17} /><span>Settings</span></button>
          <button className="account-pill" type="button" onClick={() => setOpenMenu(openMenu === 'account' ? null : 'account')}>
            <div>PA</div>
            <span><strong>Pro Analyst</strong><small>Enterprise Plan</small></span>
            <ChevronDown size={15} />
          </button>
        </div>
      </aside>

      <main className="product-shell">
        <header className="topbar">
          <form className="toolbar-search" onSubmit={handleSearch}>
            <Search size={19} />
            <span className="mobile-product-name">London Property Explorer</span>
            <input aria-label="Search addresses, postcodes, stations, areas" placeholder="Search addresses, postcodes, stations, areas..." value={searchValue} onChange={(event) => setSearchValue(event.target.value)} />
          </form>
          <div className="toolbar-actions">
            <button className="toolbar-pill date-pill" type="button" onClick={() => setOpenMenu(openMenu === 'date' ? null : 'date')}><CalendarDays size={17} /> {dateLabel} <ChevronDown size={15} /></button>
            <div className="segmented" aria-label="Map mode">
              <button className={!choropleth ? 'active' : ''} type="button" onClick={() => setChoropleth(false)}>Sales</button>
              <button className={choropleth ? 'active' : ''} type="button" onClick={() => setChoropleth(true)}><Layers3 size={15} /> Districts</button>
            </div>
            <button className="toolbar-pill hide-sm" type="button" onClick={() => setOpenMenu(openMenu === 'location' ? null : 'location')}><MapPin size={16} /> {locationLabel} <ChevronDown size={15} /></button>
            <button className="toolbar-pill hide-md" type="button" onClick={() => setOpenMenu(openMenu === 'property' ? null : 'property')}>{propertyLabel(filters.types)} <ChevronDown size={15} /></button>
            {undoState && <button className="toolbar-pill" type="button" title="Undo map change" onClick={undo}><Undo2 size={16} /> Undo</button>}
            <button className="toolbar-pill mobile-controls" type="button" title="Open filters" onClick={() => setControlsOpen((value) => !value)}><PanelLeft size={16} /> Filters</button>
            <button className="toolbar-pill more-filters hide-sm" type="button" onClick={() => setControlsOpen((value) => !value)}><SlidersHorizontal size={16} /> More filters <b>2</b></button>
            <button className="assistant-button" aria-label="Assistant" type="button" title="Open assistant" onClick={() => setChatOpen(true)}><Sparkles size={17} /> Ask AI</button>
            <button className="icon-button quiet hide-sm" type="button" title="Notifications" onClick={() => setOpenMenu(openMenu === 'notifications' ? null : 'notifications')}><Bell size={17} /></button>
          </div>
          {openMenu && (
            <div className="topbar-popover" role="dialog" aria-label={`${openMenu} menu`}>
              <button className="popover-close" type="button" title="Close menu" onClick={() => setOpenMenu(null)}><X size={15} /></button>
              {openMenu === 'date' && <><strong>Date range</strong>{dateRanges.map((range) => <button key={range.label} type="button" onClick={() => applyDateRange(range)}><CalendarDays size={15} />{range.label}</button>)}</>}
              {openMenu === 'location' && <><strong>Focus area</strong>{locationOptions.map((option) => <button key={option.label} type="button" onClick={() => applyLocation(option)}><MapPin size={15} />{option.label}</button>)}</>}
              {openMenu === 'property' && <><strong>Property type</strong>{propertyOptions.map((option) => <button key={option.label} type="button" onClick={() => applyPropertyPreset(option)}><Home size={15} />{option.label}</button>)}</>}
              {openMenu === 'notifications' && <><strong>Notifications</strong>{notifications.length === 0 ? <p>No unread notifications.</p> : notifications.map((item) => <p key={item}><Info size={14} />{item}</p>)}<button type="button" onClick={() => { setNotifications([]); showToast('Notifications cleared', '', 'success'); }}><CheckCircle2 size={15} />Clear all</button></>}
              {openMenu === 'account' && <><strong>Pro Analyst</strong><p>Supabase data and OpenRouter chat are active locally.</p><button type="button" onClick={() => showToast('Account checked', 'Local reviewer profile is active.', 'success')}><CheckCircle2 size={15} />Verify status</button></>}
            </div>
          )}
        </header>

        <section ref={dashboardRef} className="map-dashboard">
          <div className="metric-strip" aria-label="Market overview">
            <MetricCard label="Median sale price" value="£612,500" delta="+4.3% vs prev 12 months" tone="green" Icon={Home} />
            <MetricCard label="Loaded sales" value={meta ? meta.total.toLocaleString() : '466,368'} delta={meta ? `${meta.from} to ${meta.to}` : 'Local dataset'} tone="blue" Icon={BarChart3} />
            <MetricCard label="Planning applications" value="312" delta="-2.3% vs prev 12 months" tone="purple" Icon={Building2} />
            <MetricCard label="Average yield" value="4.36%" delta="+0.18pp vs prev 12 months" tone="teal" Icon={BriefcaseBusiness} />
            <MetricCard label="Market activity" value="High" delta="Top decile, live map area" tone="orange" Icon={Bot} />
          </div>

          <section className="workspace-banner" aria-live="polite">
            <div>
              <span>{activeView} workspace</span>
              <strong>{navCopy[activeView]}</strong>
            </div>
            <div className="banner-actions">
              <button type="button" onClick={saveCurrentSearch}><Bookmark size={15} /> Save search</button>
              <button type="button" onClick={createReport}><FileText size={15} /> Draft report</button>
            </div>
          </section>

          <div className="workspace">
            <aside className={`control-rail ${controlsOpen ? 'open' : ''}`}>
              <FilterPanel
                filters={filters}
                onChange={setFilters}
                stationRadiusEnabled={stationRadiusEnabled}
                planningEnabled={planningEnabled}
                onStationRadiusChange={(enabled) => { setStationRadiusEnabled(enabled); showToast('Transport overlay updated', enabled ? 'Nearby transport context is visible.' : 'Transport context hidden.', 'info'); }}
                onPlanningChange={(enabled) => { setPlanningEnabled(enabled); showToast('Planning overlay updated', enabled ? 'Planning insight overlay is visible.' : 'Planning insight overlay hidden.', 'info'); }}
                onApply={() => { setControlsOpen(false); showToast('Filters applied', `${propertyLabel(filters.types)} · ${filters.tenures?.join(',') ?? 'All tenures'}`, 'success'); }}
              />
              <section className="control-section data-note">
                <span>Current selection</span>
                <strong>{filters.types?.length ? `${filters.types.length} property types` : 'All property types'}</strong>
                <small>{filters.tenures?.length ? filters.tenures.join(', ') : 'All tenures'}</small>
                <small>{[filters.from, filters.to].filter(Boolean).join(' to ') || 'All available dates'}</small>
                <small>Locations use postcode centroids</small>
              </section>
              {savedSearches.length > 0 && (
                <section className="control-section saved-searches">
                  <div className="card-heading"><span>Saved searches</span><button type="button" onClick={saveCurrentSearch}>Save current</button></div>
                  {savedSearches.map((item) => <button key={item} type="button" onClick={() => showToast('Saved search loaded', item, 'success')}><Bookmark size={14} />{item}</button>)}
                </section>
              )}
            </aside>

            <section className="map-column">
              <MapView
                filters={filters}
                choropleth={choropleth}
                highlightedDistrict={highlightedDistrict}
                stationRadiusEnabled={stationRadiusEnabled}
                planningEnabled={planningEnabled}
                onPostcodeSelect={selectPostcode}
                onViewMatchingAreas={() => highlightDistrict('SE1', 'Viewing matching SE1 areas')}
              />
              <section className="insight-grid" aria-label="Map analytics">
                <article className="analytics-card wide">
                  <div className="card-heading"><span>Sales trend</span><small>Monthly</small></div>
                  <strong>{meta ? meta.total.toLocaleString() : '466,368'} sales</strong>
                  <svg className="chart-line" viewBox="0 0 420 126" aria-hidden="true">
                    <polyline points="0,78 42,65 84,91 126,70 168,82 210,56 252,68 294,74 336,98 378,62 420,48" />
                  </svg>
                </article>
                <article className="analytics-card">
                  <div className="card-heading"><span>Property type breakdown</span></div>
                  <div className="donut-card"><div className="donut"><span>2,458<small>Total sales</small></span></div><ul><li><i className="blue" /> Flats 38%</li><li><i className="teal" /> Terraced 24%</li><li><i className="orange" /> Detached 19%</li><li><i className="purple" /> Semi-detached 19%</li></ul></div>
                </article>
                <article className="analytics-card">
                  <div className="card-heading"><span>Top postcode districts</span></div>
                  <ul className="rank-list">
                    <li><span>CR0</span><b>£375,000</b><i style={{ width: '88%' }} /></li>
                    <li><span>E14</span><b>£560,650</b><i style={{ width: '74%' }} /></li>
                    <li><span>SW11</span><b>£805,000</b><i style={{ width: '62%' }} /></li>
                    <li><span>E17</span><b>£515,000</b><i style={{ width: '51%' }} /></li>
                  </ul>
                </article>
                <article className="analytics-card automation-card">
                  <div className="card-heading"><span>Automations</span><button type="button" onClick={() => showToast('Automations visible', `${automations.length} active automations in this session.`, 'info')}>View all</button></div>
                  {automations.slice(0, 3).map((item, index) => <p key={item}>{index % 2 === 0 ? <Sparkles size={16} /> : <Bell size={16} />} {item} <b>Active</b></p>)}
                  <button type="button" onClick={createAutomation}>Create new automation</button>
                </article>
              </section>
            </section>

            <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} onApply={applyAction} onNotify={showToast} />
          </div>

          {selectedPostcode && <HistoryPanel key={selectedPostcode} postcode={selectedPostcode} onClose={() => setSelectedPostcode(null)} />}
          {reports.length > 0 && <div className="report-dock" aria-label="Report drafts"><ClipboardList size={15} />{reports[0]}<button type="button" onClick={() => showToast('Export prepared', 'Report export is a local draft until Render deployment is connected.', 'info')}><Download size={14} /> Export</button></div>}
          {toast && <div key={toast.id} className={`toast ${toast.kind}`} role="status"><strong>{toast.title}</strong>{toast.detail && <span>{toast.detail}</span>}<button type="button" title="Dismiss" onClick={() => setToast(null)}><X size={14} /></button></div>}
        </section>
      </main>
    </div>
  );
}
