---
inclusion: always
---

# Backend documentation rule (Urvi, backend + database)

- Work on branch `feat/backend-urvi`; never commit to or merge into `main`.
- `docs/backend-urvi.md` is the single source of truth for the backend. Update it in the same task as any feature, API, schema, dependency, config, or decision change, following `practices.md` (sections A–K, append-only change log).
- Keep `db.md` in sync with `backend/app/models` and migrations.
- Do not edit teammates' docs or code outside `backend/`, `docs/backend-urvi.md`, and `db.md`/`plan.md`.
- Never mark something verified unless it was actually run. Never put secret values in docs.
