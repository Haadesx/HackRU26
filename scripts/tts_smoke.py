#!/usr/bin/env python3
"""ElevenLabs TTS smoke test — generates a real reminder line via the cloud API.

Reads ELEVENLABS_API_KEY (and optional ELEVENLABS_VOICE_ID / ELEVENLABS_MODEL_ID)
from the environment or the repo-root .env (never prints or commits secrets).

Usage:
    .venv-full/bin/python scripts/tts_smoke.py                      # default reminder line
    .venv-full/bin/python scripts/tts_smoke.py --text "..." --voice <id>
    .venv-full/bin/python scripts/tts_smoke.py --list-voices
    .venv-full/bin/python scripts/tts_smoke.py --out ~/Desktop/reminder.mp3 --play

Output: ~/.medcheck/voice/reminder-<timestamp>.mp3 (never committed).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.elevenlabs.io/v1"
DEFAULT_TEXT = "Time to take your Metformin, 500 milligrams. One tablet with breakfast."
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs public sample voice "Rachel"


def load_env() -> None:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def headers() -> dict:
    return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Accept": "audio/mpeg"}


def list_voices() -> int:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{BASE}/voices", headers=headers())
    resp.raise_for_status()
    voices = resp.json().get("voices", [])
    print(f"{len(voices)} voices on this account:")
    for v in voices:
        labels = v.get("labels") or {}
        desc = ", ".join(f"{k}={val}" for k, val in list(labels.items())[:3])
        print(f"  {v['voice_id']}  {v['name']:<20} {desc}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--voice", default=None, help="voice id (default: $ELEVENLABS_VOICE_ID or Rachel)")
    ap.add_argument("--model", default=None, help="default: $ELEVENLABS_MODEL_ID or eleven_multilingual_v2")
    ap.add_argument("--out", default=None)
    ap.add_argument("--play", action="store_true", help="play the file after generating (macOS afplay)")
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ELEVENLABS_API_KEY"):
        print("ELEVENLABS_API_KEY missing (env or repo-root .env)", file=sys.stderr)
        return 2
    if args.list_voices:
        return list_voices()

    voice = args.voice or os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
    model = args.model or os.environ.get("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2"
    out = Path(args.out) if args.out else Path.home() / ".medcheck" / "voice" / f"reminder-{datetime.now():%Y%m%d-%H%M%S}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    with httpx.Client(timeout=120) as client:
        resp = client.post(
            f"{BASE}/text-to-speech/{voice}",
            headers={**headers(), "Content-Type": "application/json"},
            json={"text": args.text, "model_id": model,
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
        )
    latency = (time.perf_counter() - started) * 1000
    if resp.status_code != 200:
        print(f"TTS failed: HTTP {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        return 1
    out.write_bytes(resp.content)
    print(f"text:    {args.text!r}")
    print(f"voice:   {voice}")
    print(f"model:   {model}")
    print(f"audio:   {out}  ({len(resp.content) / 1024:.1f} KiB, {latency:.0f} ms)")
    if args.play:
        os.system(f'afplay "{out}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
