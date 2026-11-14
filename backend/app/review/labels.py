"""Cached Vietnamese labels for review exports and user interfaces."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_labels():
    path = Path(__file__).resolve().parents[3] / "contracts" / "review" / "labels.vi.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def label(section, value):
    return load_labels().get(section, {}).get(value, value)
