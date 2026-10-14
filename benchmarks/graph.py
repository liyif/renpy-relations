"""One-off isolated long-chain loading probes; separate from gameplay ratios."""

import argparse
import hashlib
import json
import math
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
    parser.add_argument("--backends", nargs="+", choices=["sqlite", "duckdb"], default=["sqlite"])
    parser.add_argument("--backend", choices=["sqlite", "duckdb"], default="sqlite", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.lengths) < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("lengths must be positive")
    if args.worker:
        if args.packages:
            sys.path.insert(0, str(args.packages.resolve()))
        sys.path.insert(0, str(ROOT))
        from renpy_relations import LogicDB, RuleSet

        count = args.lengths[0]
        document = {"format": "renpy-relations", "version": 1, "backend": args.backend,
                    "facts": {"Seed": {"columns": {"value": "text"}}}, "derived": {}}
        for i in range(count):
            source = "Seed" if i == 0 else f"Rule{i-1}"
            document["derived"][f"Rule{i}"] = {"columns": {"value": "text"}, "sql": f"SELECT value FROM {source}"}
        record = {"length": count, "backend": args.backend, "status": "running", "current_phase": "load",
                  "runtime": runtime_info(args.backend)}
        atomic_json(args.out, record)
        db = None
        try:
            start, cpu = perf_counter(), process_time()
            db = LogicDB(RuleSet(document))
            record.update(load_seconds=perf_counter() - start, cpu_seconds=process_time() - cpu, **memory())
            record["current_phase"] = "read_and_invalidate"
            atomic_json(args.out, record)
            db.add("Seed", value="yes")
            start = perf_counter()
            assert db.has(f"Rule{count-1}", value="yes")
            record["first_read_seconds"] = perf_counter() - start
            db.remove("Seed", value="yes")
            assert not db.has(f"Rule{count-1}", value="yes")
            record["status"] = "ok"
            record.pop("current_phase", None)
        except Exception as exc:
            record.update(status="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            if db is not None:
                db.close()
            atomic_json(args.out, record)
        return 0 if record["status"] == "ok" else 1
    if args.out.exists():
        parser.error("Output already exists")
    document = {"description": "One observation per chain, not gameplay workload or repeated median",
                "backends": args.backends, "timeout": args.timeout,
                "runtime_sha256": hashlib.sha256((ROOT / "renpy_relations.py").read_bytes()).hexdigest(), "runs": []}
    for length in args.lengths:
        for backend in args.backends:
            destination = args.out.parent / ".work" / f"chain-{length}-{backend}.json"
            destination.unlink(missing_ok=True)
            command = [str(args.python), str(Path(__file__).resolve()), "--worker", "--lengths", str(length),
                       "--backend", backend, "--out", str(destination)]
            if args.packages:
                command += ["--packages", str(args.packages.resolve())]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
                record = json.loads(destination.read_text()) if destination.exists() else {
                    "length": length, "backend": backend, "status": "error", "error": "Worker produced no result"}
                if completed.returncode:
                    record.update(status="error", error=record.get("error", f"Worker exited {completed.returncode}"),
                                  output=completed.stdout + completed.stderr)
            except (OSError, subprocess.TimeoutExpired) as exc:
                record = json.loads(destination.read_text()) if destination.exists() else {"length": length, "backend": backend}
                record.update(status="error", error=str(exc))
            if record["status"] == "running":
                record.update(status="error", error="Worker did not complete its result")
            document["runs"].append(record)
            atomic_json(args.out, document)
    return 0 if all(r["status"] == "ok" for r in document["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
