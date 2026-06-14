# Engineering Handoff

## Objective

Build London Property Explorer as a reproducible geospatial product and production-quality agentic AI portfolio project. The core system is a React/MapLibre/deck.gl client over a FastAPI/PostGIS API. The capabilities endpoint reports availability for the required final AI milestone using LangGraph, Claude, Pinecone, and LangSmith.

## Read Order

1. `progress.md` for current state and verified evidence.
2. `tasks.json` for executable work and dependencies.
3. `SPEC.md` for delivery order and hard constraints.
4. The relevant subsystem document in `docs/`.
5. `docs/openapi.yaml`, then `schema.js`, for public contract work.

## Non-Negotiable Invariants

- Matching source hashes produce 466,368 final transactions; see `docs/SOURCE_DATA_PROFILE.md`.
- Process PPD and ONSPD as streams. Never load either source fully into memory.
- Postcode identity comes from the selected row, never reverse geocoding a centroid.
- Raw point responses are viewport-bounded, deterministically selected, and capped at 25,000.
- `LPE1` binary changes require a new magic/version and synchronized API, JS, Python, and tests.
- Numerical AI answers come from parameterized SQL tools. Pinecone stores explanatory evidence, never transaction rows.
- Map actions are proposals applied by the client through validated filter state.

## Working Protocol

1. Select the next dependency-ready task in `tasks.json`.
2. Mark only that task `in_progress` and update `progress.md`.
3. Implement within the documented ownership boundaries.
4. Run the task's validation commands plus relevant regression tests.
5. Record concrete evidence and mark the task `completed`, or record the blocker.

## Quality Bar

- Python: typed public functions, Pydantic boundaries, parameterized SQL, `ruff`, `mypy`, `pytest`.
- TypeScript: strict mode, runtime response validation, Vitest, Playwright, no `any` at API boundaries.
- Frontend runtime: Node 22.16+ and npm 10.9+; run `nvm use` before npm commands when the shell is not already on `.nvmrc`.
- UI: mobile at 375 px, keyboard-accessible controls, no misleading counts, stable layout.
- AI: trace every node, validate all tool inputs, cite retrieved claims, enforce latency/cost caps, and turn reviewed failures into regression cases.

## Safety

Do not overwrite user work, expose secrets, log raw IP addresses or complete conversations, run destructive git commands, or mark deployment/performance tasks complete without live evidence.
