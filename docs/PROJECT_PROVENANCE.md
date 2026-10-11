# MedCheck — Project Provenance Record

> Evidence-based record of the project's origin, direction, architecture, implementation, and
> integration. Every claim below is tied to a verifiable artifact (commit, file, timestamp) or is
> explicitly marked **uncertain**. Nothing here asserts legal ownership; see
> `docs/OWNERSHIP_PROPOSAL.md` for the (draft) discussion of agreements.
>
> **Compiled:** 2026-10-11 by the orchestrator agent (Apollo) at operator direction.
> **Canonical branch:** `feat/integration` · **Repo:** https://github.com/Haadesx/HackRU26

---

## 1. Conceptual origin and operator direction (evidence)

| Evidence | Timestamp (local, EDT) | What it shows |
|---|---|---|
| GitHub repository `Haadesx/HackRU26` created by account **Haadesx** (`gh api`, `created_at=2026-10-10T17:29:47Z`) | 13:29:47 | The operator's account originates the project repository (empty at creation; default branch then unset) |
| Project skeleton on disk (`.gitignore`, `.opencode/`, `opencode.json` mtimes) | ~13:45 | Work began in the operator's workspace before the first commit |
| Operator's initial mission brief delivered to the orchestrator session (`~/.pi/agent/sessions/--Volumes-Auxilary-Side_Projects-HackRU26--/2026-10-10T19-17-44-485Z_01a1273f-…jsonl`, first user message) | 15:17:44 | The operator defined the objective (inference subsystem), constraints (OCR-first, reuse the existing rig VLM, GPU limits), safety rules, five-agent structure, git/worktree policy, gate order, and reporting format |
| October canvas terminal creation (`/.october/canvas.json`) — Apollo 15:17:00, Atlas 15:19:04, Orion 15:19:32, Juno 15:21:14, Athena 15:21:56 | 15:17–15:22 | The operator stood up the five-agent fleet used for implementation |
| Operator-commissioned infrastructure missions (Hermes workspace, `/Volumes/Auxilary/Hermes/medcheck-hackru-infra-20261010/`): `EVIDENCE.md` (14:42), `NEXT-MISSION-20261010.md` (14:58), `NEXT-MISSION-2-STABILIZATION.md` (20:18) | 14:42–20:18 | The operator (via their personal agent Hermes) scoped the GPU/rig audit, the inference-foundation mission, and the final stabilization mission; these predate the first commit and direct the work |
| Subsequent operator briefs in the same session transcript: UI design/UX pass with named skills; final integration & demo completion; this provenance task | 20:5x–22:3x | Continued operator direction of architecture, UX, safety priorities, and submission constraints |

**Conclusion (supported):** the operator originated the project concept, established the
repository, defined the product vision, architecture constraints, safety invariants, team
structure, and the submission scope; the operator directed each subsequent phase. This is
demonstrable from operator-issued mission documents and session instructions, not inferred.

**Not evidenced:** any claim that the operator personally wrote a specific source file
(see §4 for actual authorship). No early commits were backdated; the first commit is the
repository skeleton from 15:30:53.

---

## 2. Initial product vision and requirements (as specified by the operator)

From the operator briefs (session transcript + Hermes missions), in the terms used at the time:

- **Problem:** medication-label reading for low-vision older adults (MedCheck caregiver
  dashboard + wearable concept).
- **Scope of this repository:** the AI inference subsystem plus integration with a web
  dashboard and a Flask/TimescaleDB backend.
- **Architecture (fixed by the operator):** **OCR-first with an optional existing-VLM
  fallback**; reuse the Qwen3-VL-8B-FP8 service already running on the home rig; do not launch
  another large model; keep combined GPU usage ≈26–27 GiB or less.
- **Required capabilities:** real-time bottle detection, frame-quality guidance, label OCR,
  structured medication extraction, optional Qwen3-VL interpretation, registered-candidate
  matching, uncertainty/rescan handling, a FastAPI gateway on port 8300, iOS/backend contracts,
  accuracy + latency benchmarking.
- **Safety invariants (operator-mandated):** never fabricate drug data; preserve raw source
  text; distinguish strength from per-dose quantity; a scan never implies ingestion; the
  backend owns schedules/doses/inventory; synthetic labels only.
- **Execution rules:** one repository, five agents on `feat/integration`, per-worker branches and
  worktrees, no destructive Git operations, GPU experiments serialized, Linux rig untouched.
- **Deadline:** Sunday 2026-10-11 12:00 EDT (Hermes stabilization mission).

---

## 3. Architecture: original decisions and subsequent changes

| Decision | Origin | Evidence |
|---|---|---|
| OCR-first, VLM only on escalation | Operator brief | `docs/inference-medcheck.md` §C, `services/vlm/reconcile.py` policy, measured escalation |
| Frozen, versioned contract before implementation | Orchestrator under operator direction | `contracts/README.md` changelog v1.0 → v1.3; commit `51569fd` |
| RapidOCR/ONNX (no torch) for OCR | Worker PI-2 (Orion), accepted by orchestrator | `services/ocr/DECISION.md`, commit `987dd88` |
| CPU heuristic detector with optional ONNX YOLO | Worker PI-1 (Atlas), extended after real-photo evidence | commits `9d0b593`, `31c3634` |
| Text-level multi-frame fusion (not image stitching) | Orchestrator decision after operator described long-label rotation | contract v1.2 `600c52c`; `services/ocr/fuse.py` |
| Backend `/hub` compatibility layer as primary hub | Teammate Urvi (with orchestrator mapping docs); orchestrator kept the file-backed adapter as fallback | commits `35b8e50`, `e770889`; `tools/hub_adapter/` |
| Label metadata (QTY/refills/pharmacy/prescriber/schedule) — contract v1.3 | Orchestrator, driven by the dashboard's nine-field contract | `3bdea53`, `9ccf613`, `c470a11` |
| Interval cadences never converted to fixed clock times | Operator stabilization mission §4; implemented by orchestrator | commit `3369b10`, hub `_INTERVAL` guard |
| Dosage form/unit preserved with an evidence floor (≥0.50, real source) | Operator mission §5; live bug found and fixed by orchestrator | commit `3369b10`, migration `0004_hub_scan_form` |
| Wide-screen shell (80/96/112 rem) + balanced grids | Operator mission §3 (full-screen composition) | commit `f5dcd24` |
| Design skills installed project-locally (UI UX Pro Max v2.13.0, Vercel Web Interface Guidelines) | Operator instruction | `.agents/skills/…`, commit `a456343` |

Superseded/removed: the hub's regex conversion of interval cadences (removed); hard-coded
`dosage_form: "tablet"` (removed); the initial `max-w-7xl`-only shell (extended).

---

## 4. Implementation and integration authorship (what the Git history actually shows)

Author identities in this repository **do not map 1:1 to human authors**. Commit counts across
all branches (as of `0862268`):

| Git identity | Commits | Actual authorship (evidence) |
|---|---|---|
| `Apollo (Orchestrator) <orchestrator@medcheck.local>` | 80 | The **orchestrator agent** ("Apollo"): contracts, repo/worktrees, integration merges, documentation, local scanner console, hub adapter, cross-team verification, safety fixes, wide-screen UI changes, provenance docs. Local identity created for this work; commits were pushed by the operator's GitHub account. |
| `Haadesx <128777625+Haadesx@users.noreply.github.com>` | 36 | **Mixed / conflated.** By content these are worker-agent commits that used the machine's default Git identity, e.g. `db94131` (API multi-frame, PI-4 Athena), `569cdfb`/`c470a11` (API v1.3, PI-4), `2634807` (vision M8, PI-1), `b50a659` (VLM M8, PI-3), `1a739c3` (UI design pass by worker Athena). **Uncertainty:** the identity is the operator's, but the writes were agent-executed under operator direction; the operator is not evidenced as the line author. |
| `urvi <urvidesai02@gmail.com>` | 9 | **Urvi** (backend + `/hub`): `0c1a4fd` (Flask/TimescaleDB backend), `4a01a5b` (models package recovery), `35b8e50` (`/hub` layer), `e770889` (label_meta preference). |
| `Orion <orion@medcheck.local>` | 9 | **PI-2 worker agent (Orion)**: OCR stack, extraction, matcher, fusion, label_meta, real-photo quality fixes. The only worker that configured a local identity. |
| `SinchanaSArun <sinchana05arun@gmail.com>` / `Sinchana S Arun <…+SinchanaShylajaArun@users.noreply.github.com>` | 2 | **Sinchana** (dashboard): `c733e0c` (React/Vite/Tailwind UI + contract docs + fixtures) and the PR #1 merge `1744aad`. |
| GitHub merge artifact | 1 | `1744aad` merge performed via GitHub. |

**Not present:** any commit by Aparajita (iOS); no `feat/ios-aparajita` branch. The iOS app does
not exist in this repository.

**How to verify authorship beyond commit identities** (recommended for any future provenance
review): the agents' own session transcripts under
`~/.pi/agent/sessions/--Volumes-Auxilary-Side_Projects-HackRU26--/` (per-agent JSONL with file
edits and test runs), the per-lane merge commit messages that name the worker tips, and the
contract/ownership tables in `AGENTS.md`. No Git authorships were rewritten for this record.

### Chronological development record (milestones, with evidence)

| Time (EDT, 2026-10-10) | Milestone | Evidence |
|---|---|---|
| 13:29 | GitHub repository created (empty) by Haadesx | GitHub API `created_at` |
| ~13:45 | Workspace scaffolding (`.opencode`, `opencode.json`, `.gitignore`) | file mtimes |
| 14:42–14:58 | Operator rig audit + inference-foundation mission authored | Hermes `EVIDENCE.md`, `NEXT-MISSION-20261010.md` |
| 15:17–15:22 | Five-agent fleet stood up (Apollo, Atlas, Orion, Juno, Athena) | `.october/canvas.json` `createdAt` |
| 15:30:53 | **First commit `51569fd`**: frozen v1 contract, AGENTS.md, service skeleton | git |
| 15:36–15:45 | PI-1 vision, PI-2 OCR, PI-3 VLM, PI-4 mock API delivered on worker branches | commits `9d0b593`, `987dd88`, `b475ea8`, `a855318` |
| 16:00–16:30 | M2 real pipeline, matcher, handoff, escalation triggers; cross-service regression found and fixed | merges `2ba5a12`…`4c5513f`, `34480c3` |
| 16:37–16:53 | Urvi's backend first push (Flask/TimescaleDB, 76 tests) | commits `0c1a4fd`, `85fc33f` |
| 17:03–17:20 | Contract v1.1 `dose`, ONNX YOLO, auth/CORS, multi-frame capture (v1.2), label_meta (v1.3) | `3bdea53`, `31c3634`, `db94131`, `9ccf613` |
| 17:40–17:41 | Sinchana's dashboard merged via PR #1 | `c733e0c`, `1744aad` |
| 17:55–18:33 | Models-package gitignore blocker fixed; `/hub` compatibility layer built and merged | `179c4d6`, `4a01a5b`, `35b8e50`, `e770889` |
| 19:00–19:56 | Full-stack verification (UI → `/hub` → inference), hub adapter, PROJECT_STATUS handoff | commits `ed021d0`, `7e42ae1` |
| 20:18 | Operator stabilisation mission authored | Hermes `NEXT-MISSION-2-STABILIZATION.md` |
| 20:50–21:45 | Design skills installed; UI design pass; demo crash fixed; safety P0 fixes; wide-screen pass | `a456343`, `1a739c3`, `3369b10`, `f5dcd24` |
| 22:08 | This provenance pass; integration tip `0862268` | git |

---

## 5. Contributions by component (summary, with ownership as recorded)

- **Contracts & integration:** orchestrator agent (Apollo) — frozen v1.0→v1.3, merges, gate
  verification, docs, adapter, safety fixes.
- **Vision (PI-1):** worker agent Atlas — quality, detection, label localization, clipping;
  commits mostly under the conflated `Haadesx` identity plus merge records by the orchestrator.
- **OCR (PI-2):** worker agent Orion — RapidOCR stack, extraction, matcher, fusion, label_meta.
- **VLM (PI-3):** worker agent Juno — adapter, evaluation, escalation policy, multi-image.
- **API (PI-4):** worker agent Athena — gateway, mock/real pipelines, auth/CORS, endpoints;
  plus the UI design pass on `feat/ui-design-pass`.
- **Backend + `/hub`:** Urvi (human) — full domain backend and the dashboard compatibility layer.
- **Dashboard:** Sinchana (human) — React/Vite/Tailwind UI, contract docs, fixtures.
- **iOS:** Aparajita (human) — **no artifact in this repository**; contracts are ready.
- **Operator:** concept, requirements, architecture constraints, safety invariants, mission
  scoping, agent fleet, deadline, and final submission direction.

---

## 6. Uncertainty register

1. **Agent commits under the operator's Git identity** (`Haadesx`) — authorship is evidenced by
   content, lane merges and session transcripts, not by the commit identity. Do not cite those
   commits as the operator's personal line authorship without further evidence.
2. **Orchestrator commits** (`Apollo (Orchestrator)`) include substantive code (hub safety,
   adapter, UI shell, reconcile guard) written by the orchestrator agent at operator direction;
   the operator's role is direction/review, not keystrokes, unless separately evidenced.
3. **`models/Qwen3-VL-8B-FP8` license** — the model is served from the rig container; the host
   path exposed no license file. Qwen3-VL is published under Apache-2.0 per its model card
   (**verify before commercial use**, including the FP8 conversion's provenance).
4. **`yolo11n.onnx`** — downloaded from the official Ultralytics assets release
   (`scripts/download_models.sh`, SHA-256 `634279b4…`). Ultralytics YOLO models are
   **AGPL-3.0** unless an enterprise license is held — a commercial-use constraint (see the
   proposal).
5. **Timestamps** in Hermes mission files are filesystem mtimes; session timestamps come from
   the JSONL records; both are local evidence, not externally attested.

---

## 7. Verifiable Git history and release evidence

- History is intact: no rebases of shared history, no force-pushes, no author rewrites, no
  fabricated commits. All worker branches remain reachable on `origin`.
- Per-lane merges name the worker tip SHAs (e.g. `merge(vlm): … (9ac2305)`), providing a second
  independent record of authorship.
- **Release manifest:** `docs/RELEASE_MANIFEST.md` (regenerate with
  `scripts/release_manifest.sh`) records the integration commit, SHA-256 of contract/source
  artifacts and the model file, environment versions, and reproduction commands.
- **Recommended (future, needs operator):** signed tags for release commits
  (`git tag -s vX.Y.Z -m …`) or signed commits; note that signatures prove integrity/provenance
  of a snapshot, **not** legal ownership.

---

## 8. Licensing and ownership status (current facts)

- **No project license file** exists in the repository (`gh api … license: null`). Absent a
  license, default copyright law applies: each contributor holds rights in their own
  contributions, and no one may redistribute the combined work without permission.
- **No contributor agreements** exist in the repo: no CLA/Copyright assignment, no DCO
  sign-off, no `CONTRIBUTING.md`. Contributions were made directly to branches.
- **Third-party dependencies** in use and their licenses (verified from installed package
  metadata where available):

| Dependency | License | Notes |
|---|---|---|
| `rapidocr-onnxruntime`, `onnxruntime` | Apache-2.0 / MIT | OCR inference |
| `opencv-python` | Apache-2.0 | vision |
| React, ReactDOM, React Router, Tailwind, Vite | MIT | dashboard |
| Flask, flask-smorest, APScheduler, Twilio SDK | MIT* | backend (*verify exact license text per package in `backend/requirements.txt`) |
| `firebase-admin` | Apache-2.0 | push |
| UI UX Pro Max skill (vendored) | MIT | `.agents/skills/ui-ux-pro-max/` |
| Vercel Web Interface Guidelines (vendored) | MIT | `.agents/skills/web-interface-guidelines/` |
| `playwright-core` (dev tool) | Apache-2.0 | screenshot tooling |
| **Ultralytics YOLO11n weights** | **AGPL-3.0** (or enterprise license) | **commercial-use blocker** unless licensed from Ultralytics |
| Qwen3-VL-8B-Instruct-FP8 | Apache-2.0 (verify) | served from the rig; not distributed by this repo |

- The public repository contains the operator's account as owner; teammates contributed via
  forks/branches and PRs.

## 9. What this record does and does not establish

**Establishes (evidence-based):** concept, requirements, architecture direction, safety rules,
mission scoping, and integration leadership by the operator; per-component implementation by the
named teammates/agents; intact Git history; the current licensing gaps.

**Does not establish:** exclusive copyright ownership; a contributor agreement; the right to
commercialize the combined work; or the right to use AGPL-3.0 YOLO weights commercially.
Those require the agreements discussed in `docs/OWNERSHIP_PROPOSAL.md`.
