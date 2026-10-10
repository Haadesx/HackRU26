# Synthetic vision fixtures

Generated deterministically by `generate_fixtures.py`; committed so the test
suite runs offline. All text on the labels is fictional ("EXAMPLEX"); no real
medication names and no patient data.

| File | Scene |
|---|---|
| `sharp_bottle.png` | Sharp, well-lit synthetic bottle with a readable label |
| `blurry_bottle.png` | Gaussian-blurred version (motion blur proxy) |
| `dark_bottle.png` | Underexposed version |
| `bright_bottle.png` | Overexposed version |
| `glare_bottle.png` | Specular highlight over the label |
| `no_bottle.png` | Background only (detector negative) |
| `labels.json` | Ground-truth normalized bottle/label boxes |

Regenerate (from the worktree root):

```bash
.venv/bin/python -m services.vision.tests.fixtures.generate_fixtures
```
