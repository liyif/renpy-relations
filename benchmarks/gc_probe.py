"""Diagnose GC pauses in one identical workload; automatic GC stays enabled."""

import argparse
import gc
import hashlib
import json
from pathlib import Path
from time import perf_counter

import rules
from run import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--shape", choices=["partitioned", "shared_table"], required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists")
    args.facts, args.ratio, args.mode, args.repeat = 512, 10, "cached", 0
    args.result = args.out.resolve()
    args.bundle = args.result.parent / ".work" / f"gc-{args.shape}.bundle.json"
    atomic_json(args.bundle, rules.dataset(args.facts, args.ratio, args.shape))
    events = []
    active_phase = None
    started = 0.0
    original = rules.atomic_json

    def checkpoint(path, record):
        nonlocal active_phase
        active_phase = None
        original(path, record)
        active_phase = record.get("current_phase")

    def collection(phase, info):
        nonlocal started
        if phase == "start":
            started = perf_counter()
        else:
            events.append({"phase": active_phase, "generation": info["generation"],
                           "seconds": perf_counter() - started})

    rules.atomic_json = checkpoint
    gc.callbacks.append(collection)
    try:
        status = rules.worker(args)
    finally:
        gc.callbacks.remove(collection)
        rules.atomic_json = original
    record = json.loads(args.result.read_text())
    record.update(gc_enabled=gc.isenabled(), gc_events=events,
                  probe="single observation with callbacks, separate from main benchmark",
                  runtime_sha256=hashlib.sha256((args.runtime / "renpy_relations.py").read_bytes()).hexdigest())
    atomic_json(args.result, record)
    print(json.dumps({"variant": args.variant, "shape": args.shape,
                      "generation_2": [e for e in events if e["generation"] == 2]}, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
