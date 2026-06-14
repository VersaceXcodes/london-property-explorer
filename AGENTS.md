# Repository Agent Instructions

Before changing this repository, read `agent.md`, `progress.md`, `tasks.json`, and the relevant specifications under `docs/`.

- `SPEC.md` defines delivery order and product constraints.
- `docs/openapi.yaml` is the authoritative HTTP contract; Pydantic models and `schema.js` must remain synchronized with it.
- `docs/DATABASE_REQUIREMENTS.md` owns canonical SQL and DDL.
- Never commit the multi-gigabyte source CSVs or generated transaction exports.
- Never invent test, performance, cost, or deployment evidence.
- Update `tasks.json` and `progress.md` in the same change whenever a task is completed, blocked, or materially re-scoped.
- A task is complete only after its acceptance criteria have been run and evidence has been recorded.
- Preserve user changes and keep unrelated refactors out of task-focused work.
- Use Node 22.16 or newer for frontend commands (`nvm use` reads `.nvmrc`); the system Node may be too old for Vite 8.
