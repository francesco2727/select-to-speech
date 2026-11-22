#!/usr/bin/env python3
"""Regenerate src/select_to_speech/data/piper_voices.json.

The catalog lists every Piper voice that sherpa-onnx publishes in its ``tts-models``
GitHub release, with the archive size of each precision variant (fp32, int8, fp16).
Speaker names of multi-speaker voices come from the upstream Piper catalog
(rhasspy/piper-voices ``voices.json``); voices missing from it are treated as
single-speaker until installed, when the bundled ``*.onnx.json`` is read instead.

The catalog ships with the app, so the voice list works offline. Run this script
again to pick up voices published after the last update:

    uv run python scripts/update_piper_catalog.py
"""

import datetime
import json
import re
import sys
from pathlib import Path

import requests

RELEASE_API = "https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/tts-models"
PIPER_VOICES_JSON = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "select_to_speech" / "data" / "piper_voices.json"

_ARCHIVE_RE = re.compile(r"^vits-piper-(?P<key>.+?)(?:-(?P<precision>int8|fp16))?\.tar\.bz2$")
_QUALITIES = ("x_low", "low", "medium", "high")


def _parse_key(key: str) -> dict:
    """Split a Piper voice key (``it_IT-paola-medium``) into locale, name and quality."""
    locale, _, rest = key.partition("-")
    language = re.split(r"[_-]", locale)[0].lower()
    quality = None
    name = rest
    for q in _QUALITIES:
        for sep in ("-", "_"):
            if rest.endswith(sep + q):
                quality = q
                name = rest[: -len(sep + q)]
                break
        if quality:
            break
    return {"language": language, "locale": locale, "name": name or key, "quality": quality}


def entry_is_standard(key: str, entry: dict) -> bool:
    """Whether the key uses Piper's standard `locale-name-quality` spelling."""
    return entry["quality"] is None or key.endswith("-" + entry["quality"])


def build_catalog(assets: list[dict], upstream: dict) -> dict:
    voices: dict[str, dict] = {}
    for asset in assets:
        match = _ARCHIVE_RE.match(asset["name"])
        if not match:
            continue
        key = match["key"]
        precision = match["precision"] or "fp32"
        entry = voices.setdefault(key, {**_parse_key(key), "sizes": {}, "speakers": []})
        entry["sizes"][precision] = asset["size"]

    # The release publishes a few voices twice, e.g. `…female-medium` and
    # `…female_medium`: keep the standard `-quality` spelling only.
    by_identity: dict[tuple, list[str]] = {}
    for key, entry in voices.items():
        by_identity.setdefault((entry["locale"], entry["name"], entry["quality"]), []).append(key)
    for keys in by_identity.values():
        if len(keys) > 1:
            keep = next((k for k in keys if entry_is_standard(k, voices[k])), sorted(keys)[0])
            for k in keys:
                if k != keep:
                    del voices[k]

    for key, entry in voices.items():
        info = upstream.get(key)
        if info and info.get("num_speakers", 1) > 1:
            id_map = info.get("speaker_id_map") or {}
            entry["speakers"] = [name for name, _ in sorted(id_map.items(), key=lambda kv: kv[1])]

    return {
        "generated": datetime.date.today().isoformat(),
        "voices": dict(sorted(voices.items())),
    }


def main() -> int:
    release = requests.get(RELEASE_API, timeout=60)
    release.raise_for_status()
    upstream = requests.get(PIPER_VOICES_JSON, timeout=60)
    upstream.raise_for_status()

    catalog = build_catalog(release.json().get("assets", []), upstream.json())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    languages = sorted({v["language"] for v in catalog["voices"].values()})
    print(f"Wrote {len(catalog['voices'])} voices in {len(languages)} languages to {OUTPUT}")
    print("Languages:", " ".join(languages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
