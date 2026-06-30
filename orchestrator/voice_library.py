"""Preset narrator-voice library (by country) for single-voice dubbing.

Each preset is a short reference clip (generated from a high-quality neural voice) plus its
transcript. In single-voice mode the user can pick one to clone for the whole video; if none is
picked the dub clones the video's own main speaker (the default).
"""
import os
import json
from functools import lru_cache

# voices/ sits at the project root (sibling of orchestrator/ and data/).
_VOICES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "voices")


@lru_cache(maxsize=1)
def _manifest() -> list:
    try:
        with open(os.path.join(_VOICES_DIR, "voices.json"), encoding="utf-8") as f:
            return json.load(f).get("voices", [])
    except Exception:
        return []


def list_voices() -> list:
    """Public manifest (no filesystem paths) for the UI picker."""
    return [
        {k: v.get(k) for k in ("id", "name", "country", "flag", "lang", "gender")}
        for v in _manifest()
    ]


def get_voice_ref(voice_id: str):
    """Return (absolute_wav_path, ref_text) for a preset id, or None if unknown / file missing."""
    if not voice_id:
        return None
    for v in _manifest():
        if v.get("id") == voice_id:
            path = os.path.join(_VOICES_DIR, v.get("file", ""))
            return (path, v.get("ref_text") or None) if os.path.exists(path) else None
    return None
