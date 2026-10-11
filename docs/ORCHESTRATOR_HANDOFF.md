# MedCheck — ORCHESTRATOR HANDOFF (authoritative, continuously maintained)

> **Audience:** ChatGPT and Hermes (senior technical review).
> **Maintainer:** Apollo (orchestrator) · **Canonical branch:** `feat/integration`
> **Repo:** https://github.com/Haadesx/HackRU26 · **Operator:** Varesh
> **Last updated:** 2026-10-11 ~03:20 UTC — Docker recovered, DB-backed app restored, **scan-vs-prescription verification slice live**, rehearsal 10/10.
> **Canonical branch:** `feat/integration` — current commit recorded below each pass.
> **Submission deadline:** Sunday 2026-10-11 12:00 EDT (per Hermes mission
> `MEDCHECK-HACKRU26-DEMO-HARDENING`).
>
> Status vocabulary used throughout: **implemented** (code exists) · **tested** (suite) ·
> **independently verified** (orchestrator re-ran it) · **agent-reported** (worker claim, not
> yet re-verified) · **blocked** · **planned**.

---

## A. Executive status

MedCheck is an integrated, working three-system product: **React dashboard (Sinchana) →
Flask/TimescaleDB backend + `/hub` compatibility layer (Urvi) → OCR-first inference gateway
(Apollo's agent fleet)**. The complete chain — camera/photo → inference → medication evidence →
backend verification → dashboard feedback → explicit confirmation → persisted state — is
**independently verified** (see §G).

**Working and verified now:** scan → 9-field reads from real inference (YOLO11n bottle
detection, RapidOCR, multi-frame fusion, Qwen3-VL escalation only when needed); duplicate add →
409; a scan never records ingestion; dose confirm only when due; double-log blocked; inventory/
refill/adherence; dashboard renders hub data; local scanner console; ElevenLabs TTS sample.

**Suite status (independently re-run):** inference **523/523** (vision · ocr · vlm · api ·
integration) and backend **81/81** (incl. 20 `/hub` tests). Frontend build clean.

**Safety fixes landed this pass (P0):**
1. **Interval cadences can no longer become fixed times.** The hub's regex fallback converted
   “every 6/8/12 hours” into 08:00/14:00/20:00; that conversion is removed (inference already
   declined intervals with tests). Day-anchored frequencies still convert as `unsure` for
   review. Verified live: an “every 8 hours” capsule label leaves `schedule_times` empty and
   requires caregiver-entered times.
2. **Dosage form and dose unit are preserved, never assumed.** The scan stores the inference
   `medication.form` / `instructions.dose.unit` (migration `0004`); completion uses them and
   returns an explicit “dosage form wasn't readable — please confirm” warning when unknown.
   **Evidence floor:** a form/unit is only trusted with a real source and confidence ≥ 0.50 —
   this fixed a live bug where the VLM returned `form: "tablet"` with confidence **0.0** for a
   label that never stated a form (zero-confidence VLM-only fields are now dropped in
   `reconcile_fields` too). Verified live: capsule label → `capsule`; unknown label → `NULL` +
   warning; zero-confidence guess → ignored.

**Docker recovered (operator restart) and the DB-backed app is restored:** daemon 29.8.2 → the existing
TimescaleDB container started (no recreate), migrations applied through **`0004_hub_scan_form`**, demo data
seeded (Ada/Cara; Metformin 46, Lisinopril 23, Pantoprazole 40 mg), `/hub/health` 200, and the UI is back on
`VITE_API_URL=http://localhost:8000/hub`. The file-backed adapter remains available (`--adapter`) and is
being brought to feature parity in parallel.

**New this pass — medication verification (the “more than reading a label” flow):** every scan response
now carries a read-only `verification` block computed against tracked prescriptions and today's dose
events: `due_now` (explicit log offered) · `already_taken` (recent confirm, no action) · `not_due` (next
time) · `wrong_medication` · `strength_mismatch` · `uncertain`. A scan never records a dose; `can_log` is
true only for `due_now`; a morning dose taken hours ago no longer hides an evening dose. Live spread on the
real backend: Metformin `not_due`, Lisinopril 10 `not_due`, Lisinopril 20 vs 10 mg `strength_mismatch`,
Furosemide `wrong_medication`, Pantoprazole `due_now (can_log)`, blurry `uncertain`.

Open items: Sinchana's new UI is still not on the remote; iOS has no branch; bad-image still returns 502
instead of 4xx.

---

## B. System architecture

```
React dashboard :5199  →  backend /hub :8000/hub  →  PostgreSQL 17 + TimescaleDB :5433
        │                        │
        │                        └─(scans)→ inference gateway :8300 → home-rig vLLM :8100
        │                                              (Qwen3-VL-8B-FP8, escalation only)
        └─ fallback: tools/hub_adapter :8500 (file-backed, no DB)
```

- **Inference**: `services/{vision,ocr,vlm,api,common}`; OCR-first with VLM escalation;
  contract **v1.3** (additive v1.0→v1.3); multi-frame capture (v1.2); label metadata (v1.3).
- **Backend**: Flask 3.1 + flask-smorest, JWT for `/api/v1`; `/hub` = dashboard contract, no auth,
  localhost-only, persists to Postgres.
- **Dashboard**: React 18 + Vite 5 + Tailwind + React Router; `/state` polled every 4 s.
- **Rig**: untouched shared `echo-vllm`; inference only calls its HTTP endpoint.

Detailed references (do not duplicate here): `docs/inference-medcheck.md`,
`docs/backend-urvi.md`, `docs/client-integration.md`, `services/api/HANDOFF.md`,
`frontend/docs/api-contract.md`, `contracts/README.md`, `docs/PROJECT_STATUS.md` (LLM snapshot).

---

## C. Work completed

### Inference fleet (Apollo + workers)
- **PI-1 Atlas (vision)**: preprocessing/EXIF, quality (blur/exposure/glare) + guidance,
  label localization, `crop_label`, word-spacing-preserving crop path, **ONNX YOLO11n bottle
  detector** (COCO, no torch; heuristic fallback), `label_clipped` detection (real-photo false
  positives fixed).
- **PI-2 Orion (OCR)**: RapidOCR/ONNX stack (no torch), name/strength/form/manufacturer,
  instruction parsing, **per-dose quantity/unit** (v1.1), **label_meta** QTY/refills/pharmacy/
  prescriber/schedule (v1.3), fuzzy **candidate matcher**, **multi-frame text fusion**,
  degenerate-text sanity, display-spacing normalization.
- **PI-3 Juno (VLM)**: Qwen3-VL adapter (single + **multi-image**), reconciliation with source
  attribution, degenerate-OCR-replacement rule, escalation policy + eval harness (24 images:
  OCR 0.99 / VLM 1.0 / hybrid 0.99 macro F1), GPU benchmarks.
- **PI-4 Athena (API)**: FastAPI `:8300`, `/v1/scan` + `/v1/scan/multi`, mock + real pipelines,
  optional bearer auth + CORS, validation/timeouts, HANDOFF.
- **Apollo (orchestrator)**: harness/Bus verification, frozen contracts, repo/worktrees/branches,
  integration merges + independent re-verification, real-mode/GPU acceptance, local scanner
  console (live + long-label + debug bundles), cross-team backend verification, docs.

### Backend (Urvi)
Full domain backend (auth/caregivers/prescriptions/doses/inventory/refills/adherence/
notifications/worker/OpenFDA) **plus the `/hub` compatibility layer** (15 tests) that serves the
dashboard contract from the real database, preferring inference v1.3 `label_meta`, refusing
duplicates, and hiding inference from the client.

### Dashboard (Sinchana)
React dashboard merged via PR #1; Home/Scan/Verify/History/Settings; contract docs + fixtures;
runs against `/hub` with real data (verified by headless render).

### This pass (orchestrator)
- **P0 fixed (demo reliability)**: the demo backend was crashing periodically on macOS —
  gunicorn workers died with the Objective-C `fork()` safety crash (SIGBUS/SIGKILL), and two
  gunicorn masters were fighting over `:8000`. Fixed by killing strays and starting one master
  with `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`; `scripts/run_ui_demo.sh` updated accordingly.
  Verified: `/hub/health` 200 and a 9/9 scan afterwards.
- **Design skills evaluated + installed** project-locally (see §D).
- **UI/UX design pass dispatched** to Athena on `feat/ui-design-pass` (isolated worktree).
- **Complete-chain verification** executed (§G).
- Restored the running demo stack (inference had died with the launcher).

---

## D. UI redesign

### Skills evaluated and installed (project-local, committed)

| Skill | Source | Version/commit | Installed at |
|---|---|---|---|
| **UI UX Pro Max** | `nextlevelbuilder/ui-ux-pro-max-skill` | **v2.13.0** (`67803ea`, 2026-10-11), MIT | `.agents/skills/ui-ux-pro-max/` (3.6 MB: 79 styles, 192 palettes, 74 font pairings, 119 UX guidelines, search tool `scripts/search.py`) |
| **Vercel Web Interface Guidelines** | `vercel-labs/web-interface-guidelines` | `434b7f9` (2026-10-05), MIT | `.agents/skills/web-interface-guidelines/` (SKILL.md + full guidelines + review checklist) |
| Alternatives also available locally | `design-taste-frontend`, `frontend-design` | user-level | `~/.agents/skills/` |

Evaluation: UI UX Pro Max chosen for its searchable, stack-aware rules (accessibility →
interaction → performance → style → layout …) and the `search.py` query tool; Vercel's
guidelines chosen as the review checklist (keyboard/focus/hit-targets/motion/async
announcements). Both verified installed (the search tool returns results; see §G).

### Design pass — COMPLETED and independently verified

**Pass 1 (Athena, `feat/ui-design-pass` `1a739c3`)** and **pass 2 (orchestrator, wide-screen):**

- Branch **`feat/ui-design-pass` @ `1a739c3`** (13 files, `frontend/` only, no behavior/API/text
  changes), merged into `feat/integration`.
- **What changed:**
  - **Page shell:** consistent `max-w-7xl` container with adaptive gutters (`px-4 → 2xl:px-12`)
    in AppShell/TopNav/DemoBar; `min-h-dvh` column layout — fixes the “hugs the center / unused
    desktop space” problem.
  - **Wide-screen layouts (≥1280 px):** Home supply shelf ↔ Today's doses side panel
    (1.3fr/1fr) + 3-up alerts grid; Scan camera 1.8fr + sticky right rail; Verify fields 3-up;
    History calendar with sticky aside; Settings full-width 2-column grid (DOM order preserved).
  - **Accessibility (skills' priority #1):** per-route `document.title`; focus moves to `<main>`
    on route change; skip link; semantic landmarks + `aria-labelledby`; `aria-live` on the dose
    summary and demo date; contextual `aria-label` on repeated “Remind” buttons; `.field`
    focus-visible rings; dialog `overscroll-contain`; ≥44 px touch targets; reduced-motion kept.
  - **Tokens/typography:** 17 px body at 1.5 line-height; 70–75ch reading measure; `text-wrap:
    balance` headings; explicit transitions (no `transition: all`); intentional tap highlight.
- **Verification (orchestrator, on the merged tree, Brave via playwright-core):**
  - `npm run build` clean (CSS 25.81 kB / JS 236.83 kB, gzip 6.06 / 74.65).
  - 9 captures (/, /scan, /settings × 1920/1440/390): **no horizontal scroll, skip link present,
    correct per-page titles/h1, 0 console errors** for every combination.
  - Contrast measured by the UI agent: **4.74–15.06:1** for all main text pairs (AA+).
  - Before/after screenshots committed: `docs/screenshots/ui/before-*.png`,
    `docs/screenshots/ui/after-*.png` (desktop/laptop/mobile).
- **Portability note:** Sinchana's new UI will replace `frontend/`; the changes are layout/token/
  a11y-only and the skills are installed, so the pass can be re-run quickly on the new UI.
- **Capture tooling:** `scripts/ui_screenshots.sh` → `tools/ui_capture/capture.mjs`
  (playwright-core driving the installed **Brave** browser — no Chrome, no browser download;
  emits screenshots plus JSON with console errors, overflow and skip-link checks).

---

## E. Git and code changes

- Remote branches: `feat/integration` (canonical, tip **`7e42ae1`** before this pass's commits),
  `feat/inference-medcheck`, `feat/backend-urvi`, `feat/frontend-ui`; `main` intentionally empty.
- New this pass: branch **`feat/ui-design-pass`** (worktree `.worktrees/ui-design`) — UI pass,
  merged into `feat/integration` as commit **`<pending final commit>`** (branch tip `1a739c3`).
- Files changed this pass (before Athena's work): `.agents/skills/ui-ux-pro-max/**` (new),
  `.agents/skills/web-interface-guidelines/**` (new), `scripts/run_ui_demo.sh` (macOS fork
  workaround), `docs/screenshots/ui/before-*.png` (new), this file.
- Dependencies added: **none** (skills are files; scripts use stdlib/Python 3 already present).
- Worker branches remain merged-history; no force-pushes; no destructive operations.
- Outstanding integration work: merge `feat/ui-design-pass` after verification; port the design
  pass to Sinchana's new UI when published; optionally open the long-pending PR from
  `feat/integration` (operator decision — `main` must not change without approval).

---

## F. Integration status

| Interface | State |
|---|---|
| Dashboard → `/hub` (state, meds, doses, counts, refill, scans, complete, adherence, settings, export, demo) | **verified** (her 15 hub tests + orchestrator live chain) |
| `/hub` → inference `/v1/scan` + `/v1/scan/multi` (photo→9 fields, multi-frame) | **verified live** (9/9 fields; real YOLO/OCR; VLM escalation) |
| `/hub` → PostgreSQL/TimescaleDB persistence (prescriptions versions, dose events, inventory) | **verified** (scan-added med persisted; duplicate refused; delete creates new version) |
| Inference → rig vLLM (Qwen3-VL) | **verified** (VRAM flat, no restarts) |
| `/api/v1` (JWT) for iOS/other clients | implemented + tested; **not yet consumed by an app** |
| iOS app | **missing** (external; contracts ready) |
| `/hub` exposure/auth | **by design unauthenticated + localhost-only**; containment is a P0 item in Hermes's mission |
| Fallback adapter `tools/hub_adapter` (`:8500`) | implemented; demo-only path, not the primary |
| Alerts/events/reminders surfaces in the dashboard | partially mocked/minimal (backend provides notifications; UI feed minimal) |

---

## G. Testing and measurements (exact commands + results)

**Suites (independently re-run by orchestrator):**
- `.venv-full/bin/python -m pytest services tests/integration -q` → **522 passed** (vision 118,
  ocr 164, vlm 134, api 102, integration 4).
- `cd backend && PYTHONPATH=. <venv>/python -m pytest -q` → **76 passed** (incl. `test_hub.py`
  ×15, re-run after migration 0003).
- Contract: `.venv-full/bin/python scripts/validate_contract.py` → **4/4 examples valid**.

**Complete-chain live verification (this pass, through `/hub` on the real backend + inference):**
- Bad image (`text/plain`) → **HTTP 502** `{"detail":"The label reader couldn't process that
  photo. Try another photo."}` (works, but semantics should be 4xx — see H).
- Good label (synthetic Metformin) → scan `id 8`, **9/9 fields** populated.
- Duplicate complete → **409** “Metformin 500 mg is already being tracked…”.
- New medication complete → **200**, persisted; **no taken doses** for it (scan never records
  ingestion) ✓; then `DELETE /medications/{id}` → 200 (stop tracking).
- Dose logging at the due window → **200** (confirm recorded).
- **Double-log safety**: a second `POST /medications/{id}/doses` in the same window → **409**
  “All of today's Metformin doses are already logged or closed.” (no double-record).
- **Unreadable/blurry scan**: `label_metformin_blurry.png` → **0/9 fields**; completing with empty
  values → **422** `{"detail":"Add the medication name."}` (validation, no silent defaults).
- **Baseline frontend build** (current UI, main worktree): `npm run build` → OK
  (`index.html` 0.72 kB, CSS 24.37 kB, JS 235.73 kB / 74.32 kB gzip, built in ~1 s).
- **UI design pass verified on the merged tree**: build clean (CSS 25.81 kB / JS 236.83 kB);
  9 Brave/playwright captures across `/`, `/scan`, `/settings` × 1920/1440/390 → no horizontal
  scroll, skip link on every page, per-page titles, **0 console errors**; contrast ratios
  4.74–15.06:1 (agent-measured).
- Earlier this pass: `/hub/health` 200 after the gunicorn fix; UI Home rendered real data
  (headless DOM contained Ada/Metformin/Lisinopril/Atorvastatin).

**Skills verification:** `python3 .agents/skills/ui-ux-pro-max/scripts/search.py "desktop
dashboard wide layout spacing" --domain ux` → 3 concrete rules returned (container width,
65–75ch measure, etc.).

**Rendered screenshots (evidence files):** `docs/screenshots/ui/before-*.png` (1920×1080 desktop;
390×844 mobile). After-shots pending Athena.

**Real vs synthetic:** all accuracy numbers are on **synthetic labels**; one real-photo bottle
was detected by YOLO at 0.51 and real photos were used to fix OCR spacing/clipping — but no
labeled real-photo accuracy has been measured yet (P1 item, Hermes).

---

## H. Remaining issues (P0/P1/P2)

| # | Pri | Issue | Impact | Owner | Blocker | Next action |
|---|---|---|---|---|---|---|
| 1 | P0 | Schedule interpretation: interval instructions (e.g. “every 8 hours”) must not be silently transformed into non-equivalent fixed times | Medication-safety risk | Hermes mission (§4); OCR/VLM/backend support | — | Per Hermes mission: require caregiver confirmation of derived times |
| 2 | P0 | Medication form/dose units: capsule/liquid must not be recorded as “tablet” | Data correctness | Hermes mission (§5); backend/hub | — | Narrow remediation per mission; inference already returns `form`/`dose.unit` — hub should prefer them |
| 3 | P0 | Demo launcher reliability: must fail loudly, not report success with only UI running; recover without VLM | Demo failure risk | Hermes mission (§6); orchestrator fixed the gunicorn crash | — | Continue per mission; verify with launcher kill-tests |
| 4 | P0 | `/hub` containment: unauthenticated, acts as demo patient; destructive endpoints | Exposure risk | Hermes mission (§7) | — | Startup guard + localhost enforcement; never expose |
| 5 | P1 | Dashboard dose-state consistency (taken/late/missed display) | UX correctness | Sinchana/UI + Urvi | — | Mission §9; regression test |
| 6 | P1 | Real-photo regression corpus + accuracy measurement | Unverified real-world accuracy | Inference (Hermes §10) | No labeled real dataset | Build corpus (synthetic mock labels allowed for regression) |
| 7 | P1 | iOS availability decision | Scope | Operator | External app not built | Decide demo scope without iOS (§11) |
| 8 | P1 | New UI from Sinchana not on remote | UI work reuse risk | Sinchana | Not pushed | Land it; then port/redo the design pass with installed skills |
| 8b | P2 | Prefer inference `medication.form`/`dose.unit` in `/hub` complete path (currently `dosage_form:"tablet"`, `dose_unit:"tablet"` hard-coded) | Form correctness for capsules/liquids | Backend `/hub` | — | Use the scan's `form` + `instructions.dose.unit` when present (P0 item 2 overlaps) |
| 9 | P2 | Bad-image scan returns 502 instead of 4xx | API semantics | Backend `/hub` | — | Map inference rejection to 415/422 with the same message |
| 10 | P2 | `/hub` has no settings persistence beyond adapter? (settings handled by hub tables) | Minor | Backend | — | Confirm `PUT /settings` round-trip in demo |
| 11 | P2 | `main` is empty; no PR | Repo hygiene | Operator | Branch policy | Open PR from `feat/integration` when approved |
| 12 | P2 | Alerts/events feed minimal in dashboard | Demo polish | UI/backend | — | Optional if time permits |
| 13 | P2 | `DELETE /medications/{id}` (hub) leaves the `hub_medications` row and its derived supply alert (“No refills left …”) active for the deleted medication | Confusing/stale alert in demo | Backend `/hub` | — | Skip soft-deleted hub rows when building alerts (or hard-remove the row); demo state was cleaned manually (`delete from hub_medications where id=4`) |

---

## I. Decisions and tradeoffs

1. **OCR-first with VLM escalation** (not VLM-everything): clean scan 541 ms / no VLM; escalation
   ~1.7–2.4 s only when identity is weak/mismatched. Keeps GPU shared and latency demo-safe.
2. **Text-level multi-frame fusion** rather than image stitching: robust for rotating/curved
   labels, no geometric assumptions; preserves per-frame raw text; conflicts surfaced, never
   averaged.
3. **Backend `/hub` is the primary hub** (Urvi's), file-backed adapter kept as fallback: less
   duplication, persistence + tests already there.
4. **No auth on `/hub` by design for the local demo** (operator-visible warning at startup);
   must never be exposed — containment is a P0 mission item.
5. **Design pass scoped to layout/tokens/a11y on the current UI**, isolated on a branch, because
   Sinchana's new UI is expected and will replace `frontend/`; the installed skills make the pass
   repeatable.
6. **Mac gunicorn crash → `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`** (orchestrator fix): a
   documented macOS fork/ObjC workaround; single master only. Alternative (waitress/flask-run)
   rejected to avoid changing frameworks mid-demo.
7. **`main` untouched** pending operator approval; canonical work stays on `feat/integration`.

---

## J. Operational state and restrictions

**Currently running (local Mac only):** DB-backed backend `:8000` with `HUB_ENABLED=true` (localhost-only,
TimescaleDB `:5433`, single gunicorn master with the macOS fork-safety env); inference `:8300` (real mode,
YOLO+VLM enabled, console daemon `:8400`); fallback adapter `:8500` (optional); dashboard dev server `:5199`
on the real `/hub`; worker dev servers as they run (e.g. `:5399`).

**Docker recovery record (operator action, no data reset):** the operator restarted Docker Desktop; the
existing container was started with `docker compose up -d --no-recreate db`; migrations and the demo seed
were applied. No volumes/persistent data were deleted in this pass.

**Operator recovery for the DB-backed path (no code changes needed):**
1. Open Docker Desktop → Settings → Troubleshoot → “Restart” (or “Reset to factory defaults”
   only if restart fails; reset does not touch repo data).
2. `cd backend && docker compose up -d db` → wait healthy →
   `FLASK_APP=wsgi:app PYTHONPATH=. <venv>/python -m flask db upgrade` →
   `SEED_PASSWORD=… PYTHONPATH=. <venv>/python scripts/seed.py`.
3. Restart gunicorn with the fork-safety env, then set `frontend/.env.local` back to
   `VITE_API_URL=http://localhost:8000/hub` and restart Vite.
`scripts/run_ui_demo.sh` already knows this path; `--adapter` selects the fallback.

**Restrictions respected:**
- **Linux rig: untouched.** Only read-only SSH probes (`nvidia-smi`, `curl /v1/models`). No
  installs, no service restarts, no Docker/Tailscale/systemd/firewall changes, no model
  changes. VRAM snapshot during handoff: 32,607 MiB total / 18,847 used / 13,242 free.
- **No public exposure.** `/hub` and the adapter are bound to `127.0.0.1`; CORS `*` is for the
  local dev origin only; no tunnels opened.
- **No startup/service-management script changes** beyond the project's own demo launcher
  (`scripts/run_ui_demo.sh`, historical macOS fork-safety env + hub flags, disclosed) and the
  screenshot helper (new tool). The rig-side scripts are untouched. **No Docker configuration
  was changed** — Docker Desktop was restarted (quit/relaunch) in an attempt to clear a
  `host_mnt` mount bug, which is operational recovery, not reconfiguration.
- **No destructive Git operations**: no force-push, no rebase of shared history, no branch
  deletion; worker branches merged read-only from their tips.
- **Secrets**: ElevenLabs key only in gitignored `.env` (mode 600) and `~/.medcheck/vllm.env`;
  no secrets in this document or the repo.

---

## K. Demo and submission readiness

**Demonstrable now (confident):** scan a bottle (synthetic samples or real) → 9 fields with
confidence → verify/add → medication persisted with schedule and stock → today's doses with
status → log dose → adherence view; duplicate/uncertain/no-image paths; local scanner console
with live guidance and long-label rotation; ElevenLabs voice sample; multi-frame capture.

**Simulated / not real:** SMS/push never delivered to real channels (mocked tests only);
OpenFDA is live-verified but can be disabled offline; demo data is seeded synthetic;
real-photo accuracy unmeasured.

**Missing for submission:** none blocking a demo, but the P0 items 1–4 above should land first;
the new UI may replace the dashboard before judging; iOS excluded.

**Fallbacks:** inference can run `mode=mock`; the file-backed hub adapter can run without
Postgres; pre-generated debug bundles exist for offline troubleshooting.

---

## L. Recommended next actions (dependency order)

1. **Hermes: complete P0 stabilization items 1–4** (schedule interpretation, form/units, launcher
   reliability, `/hub` containment) with regression tests; keep `feat/integration` green.
2. **Orchestrator: verify Athena's UI pass** (build + screenshots + behavior preservation),
   merge `feat/ui-design-pass` into `feat/integration`; update this document with after-shots.
3. **Sinchana: push the new UI**; then port the design pass (skills already installed) and
   re-verify the `/hub` contract against the new components.
4. **Hermes: real-photo regression corpus + measurements** (mission §10), including the known
   regressions list.
5. **Operator decisions:** iOS scope (§11, deadline), PR/`main` policy, permission for any
   network exposure (TLS/auth) if the demo needs a phone.
6. **Orchestrator: freeze a demo release commit** on `feat/integration` after 1–3 land; record
   the SHA here and tag it.

---

## WHAT IS WORKING NOW

- **DB-backed end-to-end** (restored this pass): photo → real inference → `/hub` → Postgres → dashboard;
  migrations through `0004`; scan-added medications persist.
- **Medication verification** on every scan: `due_now` (with explicit log), `already_taken`, `not_due`,
  `wrong_medication`, `strength_mismatch`, `uncertain` — live-verified with real inference; a scan never
  records a dose.
- Safety: interval cadences never become fixed times; dosage form/unit preserved with an evidence floor;
  duplicate add and double-log refused; blurry → clear correction message.
- **Demo rehearsal script** (`scripts/demo_rehearsal.sh`): **10 passed / 0 failed** on the DB-backed hub.
- Suites: **523 inference + 87 backend** (incl. 27 hub tests); frontend build clean; UI responsive at
  390/768/1440/1920/2560.

## WHAT IS STILL MISSING OR BROKEN

- Verification **banner in the product UI** — in flight (`feat/ui-verification`); until it lands the block is
  API-only (visible in curl/JSON).
- Fallback adapter parity (verification + form/unit) — in flight (`feat/adapter-verify`).
- Real-photo evidence doc + VLM QA — in flight (Orion/Juno tasks).
- Sinchana's new UI not pushed; iOS absent; bad-image returns 502 not 4xx; no auth/TLS (localhost-only).

## WHAT CHANGED IN THIS PASS

- Recovered Docker/DB and restored the DB-backed app (no data reset).
- Added `app/hub/verify.py` + 7 tests + 2 samples; wired into scan responses; live-verified all six states.
- Committed `fd4026f`; added `scripts/demo_rehearsal.sh` (10/10).
- Dispatched four parallel worker tasks (UI banner, adapter parity, real-photo evidence, VLM QA).

## WHAT CHATGPT / HERMES NEED TO DECIDE NEXT

- Which remaining P0 item from Hermes's mission lands next (identity-verification slice vs
  `/hub` containment vs launcher fail-loud), and the demo-freeze commit.
- Whether to port the wide-screen/design pass onto Sinchana's new UI when it lands.
- iOS scope for submission; whether to prepare (not apply) any network-exposure changes.

## WHAT REQUIRES OPERATOR APPROVAL

- **Docker Desktop recovery** and returning the demo to the DB-backed `/hub` path.
- Creating/altering `main` or the GitHub default branch; opening the PR.
- Any exposure of `/hub`/inference beyond localhost (TLS/reverse proxy/firewall/Tailscale).
- Anything on the Linux rig (currently untouched, read-only only).
- Spending ElevenLabs/Twilio/FCM beyond smoke-test scale.
