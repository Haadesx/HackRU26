# MedCheck Release Manifest

Generated: `2026-10-11T02:46:01Z` by `scripts/release_manifest.sh` (regenerate after every release).

| Field | Value |
|---|---|
| Integration branch | `feat/integration` |
| Commit | `57eb80bbf9105de91e0c71bfb2628d264c98c172` (`57eb80b`) |
| Upstream | `origin/feat/integration` |
| Working tree | `0` uncommitted change(s) |
| Python (inference env) | 3.11 (uv-managed `.venv-full`) |
| Python (backend) | 3.11+ (see backend/requirements.txt) |
| Node | see frontend/package-lock.json |

## Artifact hashes (SHA-256)

| Artifact | SHA-256 |
|---|---|
| `contracts/v1/scan_request.schema.json` | `847987c801e4963efd8aba8439b38c39d701c85e5fc884a43837da0965ef88e1` |
| `contracts/v1/scan_response.schema.json` | `e1227905cb6ed93e174c078f8ebc4eddb301b1a12b49de6af224d47257791b6c` |
| `contracts/examples/ok_response.json` | `8ca8d607bc8579e0ea4a6a561908c51af1e5be83bde861a93aa3e302ec713204` |
| `contracts/examples/needs_rescan_response.json` | `22c2d4f24a7ba8c5eda96afbd6600615ce70a29234dea0796a6d78a0d9c93a04` |
| `contracts/examples/error_response.json` | `406fc6d642a1e19b776206b238d382b87bf2de5de3c9f53a5ffad156202ea989` |
| `contracts/examples/multi_frame_response.json` | `403a7815257c781ae988ff6e733a970cdcc1cf6eff459f7312385f8c8e459265` |
| `contracts/README.md` | `f3ce2e5acfaa24f024e121052aee49a870a5bccde320fb77276d6585729dee36` |
| `services/common/contract.py` | `b1682bb802c2a47e4a9eb5859c5f61840a9e809b4ec157fa748797df3f21a1a7` |
| `services/api/HANDOFF.md` | `7cdcaab26c6c0c9249702666eb38e25fe690399b365daab060d88022b7a17336` |
| `services/vlm/EVAL.md` | `08cd8cbd9e9cd903cd53fdfbd946983656cd2e847f91f480e5f7ba45d4d7a0bc` |
| `services/ocr/DECISION.md` | `06e6734064da502051146ef182d273fec86a588b17ea9e3e0ca91405c11d1d5b` |
| `backend/app/hub/labels.py` | `f3dbbc5752e966ec1fde92cda2f03b1fe1c214c756c18cc2b3304401d0136732` |
| `backend/app/hub/routes.py` | `9168712fc738e9ea868736ebc159fa67293a891d34d2344b5c192d5ee1bd7780` |
| `backend/migrations/versions/0004_hub_scan_form.py` | `2cfe739a74b6583f29723f48983b3767a6a0d47b9d4597a38bef0795f70364b0` |
| `frontend/docs/api-contract.md` | `b5feac30c1dce7efcca176206cacc027fc65edccc0f496df32661cb1f1a387cb` |
| `frontend/docs/inference-contract.md` | `c1b0a55fe9a2a257bcec8b4941d2fccdbfc0555505bd435f492d956aa1cc2d81` |
| `docs/PROJECT_STATUS.md` | `d6c61d8134197cb768bb6d627a6f84650dc5db8547041694af7ee579a4d74e4f` |
| `docs/ORCHESTRATOR_HANDOFF.md` | `174b4cde29fec39887df587cb6b366160e36a2c3af7f0bc1cf8389e378a14f5a` |
| `docs/PROJECT_PROVENANCE.md` | `4683fdc133febfe0bd50057f648c3047544bc479b91d33b67e5ea272d75fc560` |
| `docs/OWNERSHIP_PROPOSAL.md` | `ea537d83e456414a7478618b6a597bc42f2a05b3256dca7011a76dc63ff3d9ac` |
| `scripts/download_models.sh` | `81309c709640ac6f126f1c20ad2268cf065a7ec0a6ae1e9c8d04d177dc4e1695` |
| `scripts/run_ui_demo.sh` | `c9cbf5c7fe412ecb1eb30929c99e10c1ccfa724092d825973637819274fbfb01` |

## Model weights (not in git; downloaded by scripts/download_models.sh)

- `models/yolo11n.onnx` — SHA-256 `634279b40c07c6391472c51ad45b81ebc48706a9a1fe72dd3396322acd0c053b`
  (Ultralytics YOLO11n ONNX; **AGPL-3.0** unless an Ultralytics enterprise license is held)
- Qwen3-VL-8B-Instruct-FP8 — served by the shared rig (`echo-vllm`); not a project artifact.

## Reproduce

```bash
git checkout 57eb80b && git status --porcelain   # expect empty
scripts/setup_full_env.sh
.venv-full/bin/python -m pytest services tests/integration -q   # 523 passed
cd backend && PYTHONPATH=. <venv>/python -m pytest -q           # 81 passed
cd frontend && npm ci && npm run build
```

> A commit SHA and hashes above are factual build records. They do not by themselves
> grant or evidence legal ownership; see docs/PROJECT_PROVENANCE.md and
> docs/OWNERSHIP_PROPOSAL.md.
