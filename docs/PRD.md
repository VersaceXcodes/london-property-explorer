# Product Requirements Document — London Property Explorer

**Doc set:** PRD (this) · `FUNCTIONAL_REQUIREMENTS.md` (what it must do) · `UI_UX.md` (how it looks/feels) · `SYSTEM_DESIGN.md` (how it's built) · `../SPEC.md` (build plan & milestones).

---

## 1. Product summary

**London Property Explorer** is a public, single-page map application for exploring a reproducible snapshot of standard Category A HM Land Registry price-paid transactions in Greater London since January 2021 (~466,000 records in the validated June 2026 build). Users pan a fast labelled map; sales appear as price-coloured clusters that resolve into individual points; a choropleth shows district medians; clicking a point reveals postcode sale history; the grounded assistant answers analytic and methodology questions with explicit evidence.

One sentence: *"Zillow-grade map performance over open UK property data, built free-tier end to end."*

## 2. Why this exists (problem & context)

- **Product problem:** UK price-paid data is public but practically inaccessible — published as multi-gigabyte CSVs with no geography attached. There is no free, fast, map-first way to ask "what do homes actually sell for *around here*?"
- **Author's context (honest framing):** this is also a deliberate demonstration of map-heavy web performance engineering — viewport-bounded querying, zoom-dependent aggregation, binary transport — built as portfolio evidence. The product must therefore be judged **as a product**: it will be reviewed by people deciding whether its author can build production map software.

Both motivations point at the same bar: it has to feel like a real tool, not a demo.

## 3. Personas

| Persona | Who | What they need | Tolerance |
|---|---|---|---|
| **P1 — Technical reviewer** (primary) | Hiring manager / senior engineer at a map-heavy product company, opens the URL once from an email | Instant signal of quality: fast load, smooth pan at high point density, evidence of architectural judgment (README numbers, visible truncation honesty) | ~2 minutes; one jank or a blank map ends the session |
| **P2 — Recruiter / non-technical evaluator** | Forwards the link, may open it on a phone | Looks intentional and polished; obvious what it is within 5 seconds; works on mobile | ~30 seconds |
| **P3 — Curious Londoner** | Anyone interested in local prices | Find their street, see what sold nearby and for how much, trust the numbers | Casual; expects Google-Maps-grade interactions |

## 4. User stories (core release)

- **U1** (P1/P3) As a user, I see a map of London with sales data rendered within seconds of opening the URL, with zero configuration or sign-in.
- **U2** (P3) As a user, I can zoom from all-of-London (aggregated clusters with counts and median prices) down to individual sales, and the transition feels continuous.
- **U3** (P3) As a user, I can click any sale point and see that postcode's address and full sale history, including a price-over-time visual.
- **U4** (P3) As a user, I can switch on a district-level price view (choropleth) to compare areas at a glance, with a legend that tells me what the colours mean.
- **U5** (P3) As a user, I can filter what's shown by property type and price range.
- **U6** (P1) As a reviewer, I'm never lied to: when the view is capped at 25k points the UI says so; the README states the geocoding is postcode-centroid precision.
- **U7** (P1) As a reviewer, I can read a short README with a screenshot, the architecture in five lines, and one performance optimisation with real before/after numbers.
- **U8 (required M5)** (P1) As a user, I can ask grounded questions about transaction analytics and curated source documentation, inspect citations and execution facts, and explicitly Apply or Undo validated map proposals.

## 5. Scope

| MoSCoW | Items |
|---|---|
| **Must** | Cluster layer; viewport-bounded fetching; points layer at high zoom; choropleth (median price by district) with legend; click → property card with history sparkline; hover tooltips; type/price filters; truncation and postcode-centroid honesty; mobile usability; live URL surviving weeks of inactivity; README with measured perf numbers; required M5 grounded assistant with SQL/RAG routing, citations, reversible map proposals, traces, feedback, and regression gates |
| **Should** | Binary transport as the documented optimisation (it is the README centerpiece — only drops if measurements genuinely show no win, which is itself documented); status pill with counts; date-range filter params (API-level) |
| **Could** | Vector tiles (PMTiles); H3 hexagon layer; date-range UI; EPC floor-area join |
| **Won't (this release)** | Accounts/auth; saved searches; £/m² metric (no floor area in source data — see `DATA_MODEL.md` §7); rental data; England-wide coverage; real-time updates; native apps |

## 6. Success metrics

The product has no analytics (no tracking on a portfolio piece); success is measured by direct verification and by reviewer outcome.

| Metric | Target | How verified |
|---|---|---|
| Time to first rendered data layer | < 3.5 s broadband, < 8 s mobile 4G | DevTools, scripted runs (SPEC §6) |
| Interaction smoothness at full point load | no sustained drops below ~50 fps | DevTools trace while panning at zoom 13 |
| Reviewer journey completable in < 2 min | open → zoom → click card → toggle choropleth, no instructions needed | hallway test with one fresh user before sending |
| Cold open after ≥ 3 weeks idle | still works, first paint < 10 s worst case | calendar-scheduled re-check |
| README performance table | real measured numbers, before & after | SPEC §8 protocol |
| Agent task success | ≥90%, with numeric groundedness and citation validity at 100% | Pinned replay/live eval suites and LangSmith baseline comparison |
| Agent responsiveness and cost | first SSE p95 <1 s; full response p50 <6 s/p95 <14 s; typical ≤$0.02/p95 ≤$0.05 | Protected live-provider release workflow |
| **North-star proxy** | the reviewer reaches a property card (the "this is real" moment) | hallway test + journey design (UI/UX §3) |

## 7. Release plan

Maps 1:1 to SPEC.md milestones: **M1** data on map (internal) → **M2** viewport + aggregation (internal) → **M3** full feature set + polish (shareable beta) → **M4** performance optimisation + deploy + README (core public release) → **M5** required LangGraph/Pinecone/LangSmith quality milestone, started after M4. Optional vector-tile, H3, and EPC extensions remain post-release work.

## 8. Assumptions & dependencies

- Free tiers (Render, Supabase, Pinecone where enabled, and the OpenFreeMap basemap) remain available and within stated limits; the keep-alive pinger is part of the product because availability after idleness is a P1 requirement.
- HM Land Registry / ONS data licences (OGL) permit this use with attribution — they do.
- Postcode-centroid geocoding is sufficient for the product promise ("what sells around here"), not parcel-level mapping — stated in-product and in README.

## 9. Open questions

None blocking. Deferred decisions are encoded as Could-scope extensions and measured tunables such as cluster cell size and final colour thresholds.
