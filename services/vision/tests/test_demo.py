"""CLI demo tests."""
import json

from services.vision.demo import main


def test_demo_prints_summary_json(fixture_path, capsys):
    exit_code = main([str(fixture_path("sharp_bottle.png")), "--indent", "0"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {"file", "detector", "frame", "quality", "bottle", "label", "guidance", "timing"} <= set(payload)
    assert payload["quality"]["acceptable"] is True
    assert payload["bottle"]["detected"] is True
    assert payload["detector"] == "heuristic"
    assert payload["timing"]["total_ms"] >= 0


def test_demo_error_is_json_on_stderr(tmp_path, capsys):
    exit_code = main([str(tmp_path / "missing.png")])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"]
    assert "missing.png" in payload["file"]
