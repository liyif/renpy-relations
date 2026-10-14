"""Load immutable benchmark controls from source archives or additional Git history."""

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASELINES = Path(__file__).resolve().parent / "baselines"


def historical_runtime(ref):
    manifest = json.loads((BASELINES / "manifest.json").read_text())
    for short, entry in manifest.items():
        if ref in (short, entry["commit"]):
            content = (BASELINES / short / "renpy_relations.py").read_bytes()
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError(f"Bundled benchmark baseline checksum mismatch: {short}")
            return content
    try:
        return subprocess.check_output(["git", "show", f"{ref}:renpy_relations.py"],
                                       cwd=ROOT, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Baseline {ref!r} is not bundled; use a checkout containing that Git history") from exc
