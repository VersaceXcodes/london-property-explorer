# UI/UX Document — London Property Explorer

Visual language, layout, component states, motion, and accessibility. Behavioural contracts (what triggers what) live in `FRONTEND_VIEWS.md`; this document defines how it all looks and feels. Requirements traceability: FR-# in `FUNCTIONAL_REQUIREMENTS.md`.

---

## 1. Design principles

1. **The map is the product.** The first screen is the usable map workbench; a compact top bar and narrow filter rail preserve most of the viewport for geography.
2. **Light, calm, data-forward.** The labelled basemap stays readable while restrained white and soft-grey operational surfaces keep controls easy to scan.
3. **Honest by design.** Counts, truncation, data precision, and NL-query interpretation are always visible. Never imply precision the data doesn't have.
4. **Fast is a feature.** Perceived performance is part of the design: skeletons over spinners, instant local feedback before network results, nothing blocks the map.
5. **Stable visual meaning.** Green/blue/red price bands keep the same meaning across viewports; teal is reserved for primary actions and amber for district highlight.

## 2. Design tokens

```css
:root {
  /* Surfaces above the OpenFreeMap Liberty basemap */
  --surface-0: #eef2ef;
  --surface-1: #ffffff;
  --surface-2: #f6f8f6;
  --border: #d9ded9;

  /* Text */
  --text-1: #17231d;
  --text-2: #56625b;
  --text-3: #7a857e;

  /* Stable price bands */
  --price-low: #1c8459;
  --price-mid: #1a69aa;
  --price-high: #be3f33;

  /* Functional */
  --accent: #16705a;
  --danger: #9d2f28;
  --highlight: #d97706;
  --neutral-geo: #dce5e0;

  /* Type */
  --font: "Inter", -apple-system, "Segoe UI", Roboto, sans-serif;
  --fs-xs: 11px; --fs-sm: 12.5px; --fs-md: 14px; --fs-lg: 17px; --fs-xl: 22px;
  --mono: ui-monospace, "SF Mono", monospace;   /* prices, counts */

  /* Geometry & motion */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 7px;
  --space: 4px;                    /* spacing unit; use 2–6× */
  --shadow: 0 8px 28px rgba(28,41,34,0.16);
  --ease: cubic-bezier(0.2, 0, 0, 1);
  --t-fast: 120ms; --t-med: 200ms; --t-slow: 320ms;
}
```

Numbers (prices, counts) always render in `--mono` with tabular figures — they change constantly and must not jitter the layout. Price formatting: `£485k`, `£1.2m` in dense contexts; full `£485,000` inside the card.

## 3. The reviewer journey (the 2-minute path the design optimises)

```
open URL ──▶ labelled London map + clusters (instant comprehension: title says what it is)
   └▶ scroll-zoom anywhere ──▶ clusters split, resolve to points (the "wow")
        └▶ hover a point (tooltip) ──▶ click ──▶ property card + sparkline (the "it's real")
             └▶ notices ControlPanel ──▶ toggles choropleth (the "it's a product")
```
Every default exists to keep this path frictionless: choropleth off (points are the hero), filters collapsed, no onboarding modals, nothing to dismiss.

## 4. Layout

### Desktop (≥ 768 px)

```
┌──────────────────────────────────────────────────────────────────┐
│ ◤ London Property Explorer      [Assistant — V6]                 │ top bar: title (left),
│   466,368 standard sales · Jan 2021–Apr 2026                     │ from /api/meta
│                                                                  │
│ ┌V2────────────┐                                                 │
│ │ LAYERS       │                    MAP                          │ V2: fixed top-left,
│ │ ◉ Sales      │                                  ┌V4──────────┐ │ 232px, --surface-1,
│ │ ○ Districts  │                                  │ 12 Maple Rd│ │ radius-lg, shadow
│ │ TYPE         │                                  │ SW11 4NB   │ │
│ │ [D][S][T][F][O]                                 │  ~~sparkline│ │ V4: right panel
│ │ PRICE        │                                  │ £850k 2024 │ │ 360px, full-height,
│ │ [min]–[max]  │                                  │ £610k 2019 │ │ slides in t-slow
│ │ Clear        │                                  │ …          │ │
│ └──────────────┘                                  └────────────┘ │
│ ┌V5──────────┐            ┌V3──────────────┐                     │ V5: bottom-left
│ │▮▮▮▮▮ legend│            │ 12,402 loaded  │                     │ V3: bottom-centre pill
│ └────────────┘            └────────────────┘                     │
│ V7 attribution · OGL · OpenFreeMap · © OSM ──────────────────────│ V7: one 11px line
└──────────────────────────────────────────────────────────────────┘
```

### Mobile (< 768 px)

```
┌──────────────────────┐   V2 collapses to a ⚙ FAB (bottom-right) opening a
│ ◤ Title (compact)    │   sheet with the same controls. V4 becomes a bottom
│                      │   sheet: peek 35% → drag to 85%, swipe-down dismiss.
│        MAP           │   V3 pill top-centre under the title. V5 legend
│                      │   collapses to a tappable swatch strip. Hover doesn't
│  [V3 pill]           │   exist: tap = select (tooltip step skipped).
│ ┌V4 sheet ▔▔▔▔▔▔▔▔┐  │   Touch targets ≥ 44×44 px everywhere.
│ │ 12 Maple Rd  ✕   │  │
└─┴──────────────────┴──┘
```

Breakpoints: 768 px (layout switch), 1280 px (V4 grows to 400 px). Map fills 100 dvh; UI is absolutely positioned over it.

## 5. Component specs

### V2 Control panel
- Sections: LAYERS (two toggle rows with switch control), TYPE (5 chips), TENURE (Freehold/Leasehold chips), PRICE (two numeric inputs), DATE (from/to inputs), Clear (text button, visible only when filters active).
- Chip states: default (`--surface-2`, `--text-2`) · selected (`--accent` 18 % bg, `--accent` text+border) · pressed scale 0.97. No-selection = all property types / all tenures.
- Price inputs commit on blur/Enter; values must be whole pounds in £0–£50,000,000 and min ≤ max. Date inputs must be real ISO dates with from ≤ to. Invalid input shows inline error styling and keeps the previous valid filters — never sends a bad request.
- Choropleth row carries the permanent caption: "District medians · all sales" (FR-304).

### V3 Status pill
Pill, bottom-centre, `--surface-1`, `--fs-sm`, content per the five states in `FRONTEND_VIEWS.md` §8. Count changes animate by text swap only — reserve enough width for `25,000+ loaded — zoom in`. Loading state prepends a 12 px spinner. Error state turns the border `--danger`.

### V4 Property card
- Header: address line 1 (`--fs-lg`, weight 600), postcode + town (`--text-2`), ✕ top-right.
- Sparkline: full-width, 64 px tall, inline SVG over returned entries; line `--ramp-4`, dots on each sale, area fill 8 % opacity; min/max price labels at the ends; single-sale postcodes show "1 recorded sale" instead (FR-502).
- History list: rows of `date · £price (mono) · type label · tenure`, `NEW` badge (`--accent` outline) for new builds; newest first; scroll within card. When `truncated`, append "Showing latest 200 sales; older records are not displayed."
- Skeleton state: header from local data immediately, three shimmer rows (--t-med pulse) until history arrives.
- Footnote (always): "Location shown is the postcode centroid." — honesty requirement (FR-604, DATA_MODEL §6).

### V5 Legend
Horizontal swatch bar (5 cells of the ramp) with min/max edge labels and per-bin tooltips. Title states the active layer's metric: "Sale price (this view)" or "District median price". Updates with the topmost visible layer (`FRONTEND_VIEWS` §7).

### Tooltip (hover, pointer devices only)
Single floating div, `--surface-2`, radius-sm, `--fs-sm`, 8 px padding, positioned 12 px from cursor, flipping at viewport edges. Content: points → `£485,000 · Flat · Mar 2024`; clusters → `1,843 sales · median £612k`; districts → `SW11 · median £740k · 4,102 sales`. No animation (it must track at 60 fps — FR-207).

### V6 Chat panel — grounded property assistant (required M5; behaviour: `AGENTIC_AI.md`)
- **Collapsed:** icon-and-text Assistant command in the desktop header and an icon command on mobile. Capability state comes from `/api/capabilities`; when disabled, the panel can still explain availability but its input cannot submit.
- **Open (desktop):** 380 px right-side panel beneath the app header with a fixed composer. **Mobile:** a responsive full-width panel that does not cover essential map commands.
- **Empty state:** a compact "No conversation yet" state. The interface does not claim capabilities until the server capability response arrives.
- **Bubbles:** user right-aligned `--surface-2`; agent left-aligned, no bubble bg (text on panel), `--fs-md`. Figures inherit `--mono` via inline code styling.
- **Working state:** SSE events update a short execution-status line (starting, running analysis, current completed fact). The first event has a p95 release budget below one second.
- **Steps and citations (transparency, FR-702):** citations are external links below the reply; execution facts are collapsed by default and expand to named operations, status, detail, and duration. Hidden model reasoning is never displayed.
- **Map action:** a proposal button such as "Apply proposed filters" or "Highlight E8". The map remains unchanged until Apply; the global Undo command then restores the previous state.
- **Feedback:** thumbs up/down controls appear only when the server reports feedback capability. They attach to the reply's root trace.
- **Input:** 500-character textarea with an icon Send button. It is locked while a request is active so transcript roles remain deterministic.
- Conversation is session-only; no history affordance.

### Toast
Bottom-right (desktop) / above sheet (mobile), `--surface-2` with `--danger` border for errors, auto-dismiss 6 s, max one visible, action slot ("Retry").

## 6. Map & data styling

- Basemap: OpenFreeMap Liberty, labels kept; OpenMapTiles/OpenStreetMap attribution remains visible through the MapLibre attribution control.
- Points: circular, anti-aliased, radius 2→6 px (zoom 12→16), 1 px darkened stroke at radius ≥ 4 px, opacity 0.85; hover: radius ×1.5 via deck `autoHighlight` (no relayout).
- Clusters: opacity 0.85, white count labels (`--fs-xs`, weight 600) on cells radius ≥ 14 px; subtle 1 px stroke `--border`.
- Choropleth: alpha 0.6 under points; hovered district stroke brightens to 60 % white.
- Camera: `flyTo` 600 ms ease for programmatic moves (cluster drill-down, NL query); user gestures never animated.

## 7. Motion & responsiveness rules

- Durations: micro-feedback `--t-fast`, panel/sheet enter `--t-med`–`--t-slow`, all with `--ease`. Nothing animates continuously while idle.
- `prefers-reduced-motion`: all non-essential transitions drop to 0 ms; `flyTo` becomes `jumpTo`.
- Layer data swaps (cluster↔points) use a 150 ms opacity cross-fade — masks the mode switch (FR-203).

## 8. Copy (microcopy table)

| Context | Copy |
|---|---|
| Title block | **London Property Explorer** / `"{total} standard sales · {from}–{to}"` formatted from `/api/meta` (validated snapshot: "466,368 standard sales · Jan 2021–Apr 2026") |
| Truncation | "25,000+ loaded — zoom in" |
| Cold start | "Waking the server… free hosting takes a moment after a quiet spell." |
| Fetch error toast | "Couldn't load sales for this area." + **Retry** |
| Choropleth caption | "District medians · all sales" |
| Card footnote | "Location shown is the postcode centroid." |
| Chat empty state | "Ask about London sale prices" |
| Chat error | "I couldn't answer that — try e.g. 'median price in SW11?'" |
| Chat rate limit | "Hold on — too many questions, try again in a minute." |
| Map-action chip | "Map updated: {explanation}" |
| Empty viewport (0 results) | "No sales match here — widen the filters or pan the map." |

Tone: factual, brief, slightly warm; no exclamation marks; en-GB spelling; "sales" not "transactions" in user-facing copy.

## 9. Accessibility

- **Contrast:** primary and secondary text on white/soft-grey surfaces must meet WCAG AA. Price meaning is redundant through the ordered legend labels, not colour alone.
- **Keyboard:** logical tab order (title → chat pill → control panel → map); all controls operable by keyboard, including the chat transcript and input; visible 2 px `--accent` focus ring; Esc closes card/sheet/chat. Map keyboard nav = MapLibre defaults (arrows/±).
- **Screen readers:** landmarks (`header`, `main`, `aside` for card); pill is `aria-live="polite"` (announces count/truncation changes); card opens with focus moved to its heading; toggles are real `<button role="switch">`; the canvas gets `aria-label="Map of London property sales"` — full SR map exploration is out of scope, but all *data* reachable via the card is reachable by keyboard.
- **Touch:** 44×44 px minimum targets; point picking uses a 6 px touch slop radius.
- **Motion/vestibular:** §7 reduced-motion rule.

## 10. States checklist (every view, designed not improvised)

| View | Loading | Empty | Error |
|---|---|---|---|
| Map layers | previous data stays + pill spinner | "No sales match here…" pill | toast + last good data (FR-602) |
| Card | header + shimmer rows | n/a (only opens on data) | inline "Couldn't load history" + Retry |
| Choropleth | toggle spinner | missing districts → `--neutral-geo` | toggle reverts + toast |
| Chat panel | muted step lines in transcript | suggestion chips | system bubble with example hint |
| Footer/meta | em-dashes until `/api/meta` | n/a | silently omit counts |

## 11. Asset & quality bar

- Favicon + social card (og:image = the README screenshot). Title tag: "London Property Explorer — London sale prices on one map".
- The M3 polish pass checks this document end-to-end: tokens applied, all §10 states reachable, mobile layout per §4, copy per §8 verbatim.
- Lighthouse (mobile): Performance ≥ 80, Accessibility ≥ 95 on the deployed URL — recorded at M4 alongside the SPEC §8 numbers.
