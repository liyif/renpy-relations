"""One-off isolated long-chain loading probes; separate from gameplay ratios."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter, process_time

from run import ROOT, atomic_json, memory, runtime_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lengths", nargs="+", type=int, default=[128, 512, 1050])
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.lengths) < 1:
        parser.error("lengths must be positive")
    if args.worker:
        if args.packages:
            sys.path.insert(0, str(args.packages.resolve()))
        from renpy_relations import LogicDB, RuleSet

        count = args.lengths[0]
        document = {"format": "renpy-relations", "version": 1,
                    "facts": {"Seed": {"columns": {"value": "text"}}}, "derived": {}}
        for i in range(count):
            source = "Seed" if i == 0 else f"Rule{i-1}"
            document["derived"][f"Rule{i}"] = {"columns": {"value": "text"}, "sql": f"SELECT value FROM {source}"}
        start, cpu = perf_counter(), process_time()
        db = LogicDB(RuleSet(document))
        record = {"length": count, "load_seconds": perf_counter() - start,
                  "cpu_seconds": process_time() - cpu, **memory(), "runtime": runtime_info()}
        try:
            db.add("Seed", value="yes")
            start = perf_counter()
            assert db.has(f"Rule{count-1}", value="yes")
            record["first_read_seconds"] = perf_counter() - start
            db.remove("Seed", value="yes")
            assert not db.has(f"Rule{count-1}", value="yes")
            record["status"] = "ok"
        finally:
            db.close()
        atomic_json(args.out, record)
        return 0
    if args.out.exists():
        parser.error("Output already exists")
    document = {"description": "One observation per chain, not gameplay workload or repeated median",
                "runtime_sha256": hashlib.sha256((ROOT / "renpy_relations.py").read_bytes()).hexdigest(), "runs": []}
    for length in args.lengths:
        destination = args.out.parent / ".work" / f"chain-{length}.json"
        destination.unlink(missing_ok=True)
        command = [str(args.python), str(Path(__file__).resolve()), "--worker", "--lengths", str(length), "--out", str(destination)]
        if args.packages:
            command += ["--packages", str(args.packages.resolve())]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            record = json.loads(destination.read_text())
        except (OSError, subprocess.SubprocessError) as exc:
            record = {"length": length, "status": "error", "error": str(exc)}
        document["runs"].append(record)
        atomic_json(args.out, document)
    return 0 if all(r["status"] == "ok" for r in document["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
