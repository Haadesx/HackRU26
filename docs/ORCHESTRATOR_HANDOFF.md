# MedCheck — ORCHESTRATOR HANDOFF (authoritative, continuously maintained)

> **Audience:** ChatGPT and Hermes (senior technical review).
> **Maintainer:** Apollo (orchestrator) · **Canonical branch:** `feat/integration`
> **Repo:** https://github.com/Haadesx/HackRU26 · **Operator:** Varesh
> **Last updated:** 2026-10-11 ~01:10 UTC (post UI-pass dispatch, chain verification)
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
backend verification → dashboard feedback → explicit confirmation → persisted state — was
**independently verified** live this pass (see §G).

**Working and verified now:** scan → 9/9 fields from real inference (YOLO11n bottle detection,
RapidOCR, multi-frame fusion, Qwen3-VL escalation only when needed); duplicate add → 409; a scan
never records ingestion; dose confirm only when due; inventory/refill/adherence; dashboard
renders real backend data; local scanner console; ElevenLabs TTS sample.

**Suite status (independently re-run):** inference **522/522** (vision 118 · ocr 164 · vlm 134 ·
api 102 · integration 4); backend **76/76** (incl. 15 `/hub`).

**Critical open items (this pass):**
1. **New UI from Sinchana has not landed on the remote** (still `c733e0c`); the requested UI/UX
   design pass is running on the current UI in an isolated branch (portable to the new UI).
2. **P0/P1 stabilization items are owned by Hermes's mission** (`NEXT-MISSION-2-STABILIZATION.md`):
   schedule-interpretation safety, dose-unit/form correctness, launcher reliability, `/hub`
   exposure containment, dose-state consistency, real-photo corpus, iOS decision. The
   orchestrator's own P0 fix this pass: the macOS gunicorn fork crash that periodically killed
   the demo backend (§C).
3. **Real-photo accuracy is still synthetic-only** — no labeled real-label corpus yet.
4. Bad-image scan returns **502** (friendly message) rather than a 4xx — semantics issue, P2.

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

### Design pass (in progress at time of writing)
- Branch `feat/ui-design-pass`, worktree `.worktrees/ui-design`, agent **Athena**, dev server
  `:5299` against the live `/hub`.
- Brief: fix full-screen desktop composition (max-width containers, multi-column/grid layouts at
  ≥1280 px, consistent page shell); apply the skills' priority order (accessibility, touch
  targets, mobile-first responsiveness 390/768/1440/1920, typography scale, spacing rhythm,
  reduced motion, no horizontal scroll); preserve every route/API call/behavior; evidence =
  `npm run build` + before/after screenshots at 1920×1080, 1440×900, 390×844 for Home/Scan/
  Settings.
- **Before** screenshots captured by the orchestrator and committed:
  `docs/screenshots/ui/before-{home,scan,settings,history}-desktop.png`,
  `before-home-mobile.png`.
- **After** screenshots + commit SHA: **pending Athena's report**; this document will be updated
  with the verified screenshots and design decisions before the final handoff.
- Portability: because Sinchana's new UI will replace `frontend/`, the pass is deliberately
  scoped to layout/tokens/accessibility (no behavior change) so it can be ported or re-run with
  the same skills when the new UI lands.

---

## E. Git and code changes

- Remote branches: `feat/integration` (canonical, tip **`7e42ae1`** before this pass's commits),
  `feat/inference-medcheck`, `feat/backend-urvi`, `feat/frontend-ui`; `main` intentionally empty.
- New this pass: branch **`feat/ui-design-pass`** (worktree `.worktrees/ui-design`) — UI pass.
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

**Currently running (local Mac only):** inference `:8300` (real mode, YOLO+VLM enabled, via the
console daemon `:8400`); backend gunicorn `:8000` with `HUB_ENABLED=true` (localhost-only, single
master, fork-safety env); TimescaleDB container `:5433`; dashboard dev server `:5199`;
UI-pass dev server `:5299` (Athena's worktree, when running).

**Restrictions respected:**
- **Linux rig: untouched.** Only read-only SSH probes (`nvidia-smi`, `curl /v1/models`). No
  installs, no service restarts, no Docker/Tailscale/systemd/firewall changes, no model
  changes. VRAM snapshot during handoff: 32,607 MiB total / 18,847 used / 13,242 free.
- **No public exposure.** `/hub` is bound to `127.0.0.1`; CORS `*` is for the local dev origin
  only; no tunnels opened.
- **No startup/service-management script changes** beyond the project's own demo launcher
  (`scripts/run_ui_demo.sh`), where the only change is the macOS fork-safety env var and
  backend `/hub` flags needed to keep the demo alive. The rig-side startup scripts are
  untouched.
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

- Full chain: photo → real inference (YOLO11n + RapidOCR + optional Qwen3-VL) → `/hub` → Postgres
  → dashboard; verified live with 9/9 fields and persisted medications.
- Safety behaviors: scans never record ingestion; duplicate adds refused; dose confirm only when
  due; uncertainty and per-field sources preserved; backend owns prescriptions/doses/inventory.
- Test suites: **522 inference + 76 backend**, contract examples 4/4, frontend builds.
- Local console: live guidance, long-label rotation capture, debug bundles; ElevenLabs TTS sample.
- Fallback hub adapter for DB-less demos.

## WHAT IS STILL MISSING OR BROKEN

- Real-photo accuracy has not been measured (synthetic-only numbers).
- P0 items: schedule-interpretation safety, form/dose-unit correctness, launcher fail-loud
  semantics, `/hub` containment — **owned by Hermes's mission**, not yet landed.
- Sinchana's new UI is not on the remote; the design pass currently targets the old UI.
- Bad-image returns 502 instead of 4xx; alerts/events feed minimal; no auth/TLS (deliberate,
  local-only).
- iOS app absent (contracts ready).

## WHAT CHANGED IN THIS PASS

- Installed UI UX Pro Max v2.13.0 and Vercel Web Interface Guidelines project-locally
  (`.agents/skills/…`), committed with provenance.
- Fixed the demo backend crash (macOS gunicorn fork) and restored the whole stack.
- Dispatched the UI/UX design pass on `feat/ui-design-pass` (isolated worktree) with before
  screenshots captured; after-shots pending.
- Ran the complete-chain verification (success + failure paths) and re-ran both suites.
- Created this document.

## WHAT CHATGPT / HERMES NEED TO DECIDE NEXT

- Whether the design pass should be re-run on Sinchana's new UI or ported component-by-component
  (same skills, same brief).
- Priority between Hermes's P0 items and the deadline: which subset must land before the demo
  freeze, and what the demo script/freeze commit should be.
- iOS scope for the submission (excluded vs. contract-only mention).
- Whether to prepare (not apply) network exposure changes for a phone demo — any actual firewall/
  TLS/tailnet change requires operator approval.

## WHAT REQUIRES OPERATOR APPROVAL

- Creating/altering `main` or changing the GitHub default branch; opening the PR.
- Any network exposure of `/hub` or the inference gateway beyond localhost (TLS/reverse proxy/
  Tailscale routing) and any firewall or Docker/service changes.
- Anything on the Linux rig (currently untouched, read-only only).
- Spending ElevenLabs characters beyond smoke-test scale, Twilio/FCM credentials use.
