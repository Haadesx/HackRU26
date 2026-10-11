# frontend/ — agent notes

This folder is Sinchana's React web UI (branch `feat/frontend-ui`).

- Keep `docs/ui-sinchana.md` (at the repo root) up to date in the same commit as any
  meaningful UI change: features, API calls, dependencies, test results, and a change-log
  row with the commit SHA.
- Push only to `feat/frontend-ui`. Never push to `main` or `feat/integration`, never force-push.
- The API seam is `src/api/client.js`; keep `src/api/mock.js` and `docs/api-contract.md` in sync
  with it.
