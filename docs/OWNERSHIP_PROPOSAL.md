# MedCheck — Ownership & Licensing Discussion Proposal (DRAFT)

> **Status: DRAFT FOR DISCUSSION ONLY.** This document is not an agreement, no terms are
> accepted, and nothing here is signed or should be represented as agreed by any contributor.
> It exists so the operator can decide, with counsel, how to approach contributors. Prepared
> by the orchestrator agent at operator request; the operator reviews and owns any next step.
>
> Companion: `docs/PROJECT_PROVENANCE.md` (evidence record) · `docs/RELEASE_MANIFEST.md`
> (release snapshot).

## 1. Why this is needed

- The repository has **no project license** (`gh api … license: null`) and **no contributor
  agreements** (no CLA, DCO sign-off, or `CONTRIBUTING.md`).
- Several people and agent fleets contributed to the combined work:
  **Urvi** (backend + `/hub`), **Sinchana** (dashboard), plus operator-directed **agent work**
  (orchestrator + four worker agents). **Aparajita** (iOS) has no commits here.
- Under default copyright rules, each contributor owns their contributions. Redistributing or
  commercially exploiting the combined work, or offering it under a single license, needs
  permission from each rights-holder. A hackathon submission does not by itself grant that.
- A **signed tag or commit** proves integrity of a snapshot; it does **not** establish legal
  ownership. Ownership comes from agreements, not from Git.

## 2. Goal (as understood)

Let the operator continue and commercialize MedCheck (or offer it under a chosen license) while
**preserving accurate historical credit** for every contributor and complying with third-party
licenses. "Exclusive ownership" is one option, not a given.

## 3. Third-party constraints to resolve first

1. **YOLO11n weights are AGPL-3.0** (Ultralytics) — using them in a closed commercial product
   requires an Ultralytics enterprise license, or replacing the detector (e.g. a self-trained
   or permissively licensed model). **This is independent of contributor agreements.**
2. **Qwen3-VL-8B-Instruct-FP8** — published model license (Apache-2.0 per its model card) must
   be verified, including the FP8 conversion's provenance; it is served, not redistributed.
3. Vendored design skills and dev tools are MIT/Apache-2.0 (attribution kept in
   `.agents/skills/*/LICENSE`); keep those notices in any distribution.
4. **No secrets, patient data, or real medication data** are in the repository (synthetic labels
   only) — keep it that way in any commercial fork.

## 4. Options for contributor arrangements

| Option | What it does | Pros | Cons / notes |
|---|---|---|---|
| **A. Copyright assignment (CLA)** | Each contributor assigns copyright in their contributions to the operator (or an entity), often with a license-back for their own use | Cleanest basis for exclusive commercialization and re-licensing | Requires each person to sign and understand it; some contributors decline assignments |
| **B. Broad perpetual license** | Contributors grant the operator a perpetual, worldwide, royalty-free, sublicensable right to use/modify/distribute/commercialize, while they keep copyright | Lighter than assignment; enables commercialization | Operator does not "own" the code; diligence should cover sublicensing and patent terms |
| **C. Scope-limited license** | Same as B but restricted to this project or field of use | Easier to agree | May not cover spin-offs or re-licensing under a proprietary EULA |
| **D. Open-source publication** | Publish under a permissive license (e.g. MIT/Apache-2.0) with attribution | Simplest, keeps community goodwill | No exclusivity; competitors may commercialize too |
| **E. Do nothing** | Rely on default copyright | Zero effort | No one may safely commercialize the combined work; submission-only |

A practical path many teams use: **B/C now, revisit A later**, plus a short `CONTRIBUTING.md`
with DCO sign-off so future contributions carry explicit permission.

## 5. Who would be asked, and for what

| Contributor | Evidence of contribution | Agreement would cover |
|---|---|---|
| **Urvi** | `0c1a4fd`, `4a01a5b`, `35b8e50`, `e770889` — backend + `/hub` | Her backend and hub code, and her OpenFDA/dose/inventory logic |
| **Sinchana** | `c733e0c`, PR #1 — dashboard, contract docs, fixtures | Her React UI, design decisions, fixtures |
| **Aparajita** (iOS) | No commits in this repository | Nothing yet; a future contribution would need the same treatment |
| **Agent-assisted contributions** (orchestrator + workers, under operator direction) | `Apollo (Orchestrator)` commits; worker commits (`Haadesx`-conflated and `Orion`) | Note: agent output is generally treated as work of the operator who directed it, but the exact position depends on the operator's arrangements with the agent providers and on local law; flag for counsel. The provenance doc documents this explicitly. |

## 6. Open questions for the operator

1. Is the goal exclusive commercialization, or open-source publication with credit?
2. Would the operator accept option B/C (license) if assignment (A) is declined?
3. Who is the intended rights-holding entity (personal or a company) before signing anything?
4. Will the hackathon rules permit post-event relicensing (check the event's terms)?
5. How should the AGPL YOLO question be resolved — buy a license, or retrain/replace the
   detector? (Affects any commercial plan more than the contributor paperwork.)
6. Is a lawyer engaged for the CLA/license text and for the event's IP terms?

## 7. Proposed next steps (operator review required before anything is sent)

1. **Operator decides** the target option (§4) and the rights-holding entity.
2. **Counsel review** of the chosen CLA/license wording and the hackathon terms.
3. **Operator contacts each human contributor** with the provenance record attached; asks for
   agreement (and signatures only after review). Do not send on the operator's behalf.
4. **Add `CONTRIBUTING.md`** with the selected sign-off mechanism before accepting new outside
   contributions.
5. **Resolve third-party licensing** (YOLO AGPL first) before any commercial distribution.
6. **Tag a release** (`v0.x.0` or `v1.0.0-demo`) with a signed tag once development freezes; keep
   `docs/RELEASE_MANIFEST.md` current with it.

Nothing in this document is legal advice; it is a work plan for the operator and their counsel.
