"""Isolate native snapshot/commit costs; fixture setup is native SQL, untimed."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(args):
    if args.packages:
        sys.path.insert(0, str(args.packages.resolve()))
    spec = importlib.util.spec_from_file_location("snapshot_runtime", args.runtime)
    runtime = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runtime
    spec.loader.exec_module(runtime)
    if args.driver == "pysqlite3":
        import pysqlite3
        runtime.sqlite3 = pysqlite3
    elif args.driver == "sqlite3":
        import sqlite3
        runtime.sqlite3 = sqlite3
    document = {"format": "renpy-relations", "version": 1,
        "facts": {"Seed": {"columns": {"value": "text", "group_id": "integer"}}},
        "derived": {"Visible": {"columns": {"value": "text"}, "sql": "SELECT value FROM Seed"}}}
    if not args.legacy:
        document["backend"] = args.backend
        from rule_compiler import compile_document
        document = compile_document(document)
    rules = runtime.RuleSet(document)
    db = runtime.LogicDB(rules)
    bound = runtime.LogicDB(rules, on_snapshot=lambda image: None)
    samples = []
    try:
        with db._world.engine.begin() as conn:
            if args.backend == "duckdb":
                conn.exec_driver_sql("INSERT INTO Seed(value,group_id) SELECT printf('v%09d',i), i%32 FROM range(?) t(i)", (args.size,))
            else:
                conn.exec_driver_sql("""WITH RECURSIVE n(i) AS (
                    SELECT 0 UNION ALL SELECT i+1 FROM n WHERE i+1<?)
                    INSERT INTO Seed(value,group_id) SELECT 'v'||printf('%09d',i),i%32 FROM n""", (args.size,))
        for repetition in range(args.repetitions):
            def measured(operation):
                start = perf_counter()
                value = operation()
                return value, perf_counter() - start

            # Invalidate any reused image before timing an explicit full snapshot.
            db.add("Seed", value=f"snapshot-{repetition}", group_id=32)
            image, snapshot = measured(db.snapshot)
            reused, snapshot_reused = measured(db.snapshot)
            if not args.legacy:
                assert reused is image
            _, plain_commit = measured(lambda: db.add("Seed", value=f"plain-{repetition}", group_id=33))
            assert db.has("Seed", value=f"plain-{repetition}")
            bound.restore(image)
            _, history_commit = measured(lambda: bound.add("Seed", value=f"history-{repetition}", group_id=34))
            assert bound.has("Seed", value=f"history-{repetition}")
            _, restore = measured(lambda: db.restore(image))
            assert not db.has("Seed", value=f"plain-{repetition}")
            assert db.has("Seed", value=f"snapshot-{repetition}")
            with db._world.engine.begin() as conn:
                assert conn.exec_driver_sql("SELECT count(*) FROM Seed").scalar_one() == args.size + repetition + 1
            samples.append({"snapshot": snapshot, "snapshot_reused": snapshot_reused,
                "plain_commit": plain_commit, "history_commit": history_commit,
                "restore": restore, "snapshot_bytes": len(image)})
        import sqlalchemy
        driver_version = runtime.sqlite3.sqlite_version if args.backend == "sqlite" else __import__("duckdb").__version__
        return {"status": "ok", "backend": args.backend, "driver": args.driver,
            "process_repeat": args.process_repeat, "executable": sys.executable,
            "legacy": args.legacy, "size": args.size, "python": sys.version,
            "runtime_sha256": hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
            "platform": platform.platform(),
            "database_version": driver_version, "sqlalchemy": sqlalchemy.__version__, "samples": samples}
    finally:
        bound.close()
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 100000])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--process-repetitions", type=int, default=1, help="Independent fresh workers per configuration")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--drivers", nargs="+", choices=["sqlite3", "pysqlite3", "duckdb"], default=["sqlite3", "pysqlite3", "duckdb"])
    parser.add_argument("--baseline-ref", help="Optional historical SQLite runtime for comparison")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--size", type=int)
    parser.add_argument("--backend", default="sqlite")
    parser.add_argument("--driver", default="sqlite3")
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--process-repeat", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.repetitions, args.process_repetitions) < 1 or any(n < 1 for n in args.sizes) or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("sizes and repetitions must be positive")
    if args.worker:
        print(json.dumps(worker(args)))
        return 0
    if args.out is None:
        parser.error("--out is required")
    args.out.mkdir(parents=True, exist_ok=True)
    if any(args.out.iterdir()):
        parser.error("Output directory must be empty")
    records = []
    with tempfile.TemporaryDirectory(prefix="relations-snapshot-benchmark-") as directory:
        configs = [(ROOT / "renpy_relations.py", "sqlite", "sqlite3", False),
                   (ROOT / "renpy_relations.py", "sqlite", "pysqlite3", False),
                   (ROOT / "renpy_relations.py", "duckdb", "duckdb", False)]
        if args.baseline_ref:
            baseline = Path(directory) / "baseline.py"
            from baseline_sources import historical_runtime
            content = historical_runtime(args.baseline_ref)
            baseline.write_bytes(content)
            configs.insert(0, (baseline, "sqlite", "sqlite3", True))
            configs.insert(1, (baseline, "sqlite", "pysqlite3", True))
        configs = [configuration for configuration in configs if configuration[2] in args.drivers]
        for size in args.sizes:
            for process_repeat in range(args.process_repetitions):
                ordered = configs if process_repeat % 2 == 0 else list(reversed(configs))
                for runtime, backend, driver, legacy in ordered:
                    command = [str(args.python), str(Path(__file__).resolve()), "--worker", "--runtime", str(runtime),
                        "--size", str(size), "--backend", backend, "--driver", driver,
                        "--process-repeat", str(process_repeat), "--repetitions", str(args.repetitions)] + (["--legacy"] if legacy else [])
                    if args.packages:
                        command += ["--packages", str(args.packages.resolve())]
                    try:
                        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        record = {"status": "error", "size": size, "backend": backend, "driver": driver,
                                  "legacy": legacy, "process_repeat": process_repeat, "error": str(exc)}
                    else:
                        if result.returncode:
                            record = {"status": "error", "size": size, "backend": backend, "driver": driver,
                                      "legacy": legacy, "process_repeat": process_repeat, "error": result.stdout + result.stderr}
                        else:
                            record = json.loads(result.stdout)
                    records.append(record)
                    (args.out / "results.json").write_text(json.dumps({"baseline_ref": args.baseline_ref,
                    "parameters": {"sizes": args.sizes, "repetitions": args.repetitions,
                                   "process_repetitions": args.process_repetitions, "drivers": args.drivers,
                                   "timeout": args.timeout},
                        "file_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                        for name in ("benchmarks/snapshots.py", "uv.lock", "rule_compiler.py")},
                        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                        "runs": records}, ensure_ascii=False, indent=2) + "\n")
                    print(size, backend, driver, "legacy" if legacy else "native", record["status"], flush=True)
    lines = ["# 提交与原生快照对照", "", f"每配置 {args.process_repetitions} 个独立进程，进程内 {args.repetitions} 次顺序测量。单位：毫秒，各行是一个进程的样本中位数。", "",
        "| 事实数 | 实现／驱动 | 独立重复 | 普通提交 | 历史提交 | 完整快照 | 重复快照 | 恢复 | 镜像 MiB |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for record in records:
        label = ("旧 JSON" if record["legacy"] else record["backend"]) + "/" + record["driver"]
        if record["status"] != "ok":
            lines.append(f"| {record['size']} | {label} | {record['process_repeat'] + 1} | FAILED | | | | | |")
            continue
        values = [statistics.median(s[p] for s in record["samples"]) * 1000
                  for p in ("plain_commit", "history_commit", "snapshot", "snapshot_reused", "restore")]
        size = statistics.median(s["snapshot_bytes"] for s in record["samples"]) / 1024**2
        lines.append(f"| {record['size']} | {label} | {record['process_repeat'] + 1} | " + " | ".join(f"{v:.3f}" for v in values) + f" | {size:.3f} |")
    lines += ["", "仅测快照路径，不代表剧情条件查询速度。配置顺序在独立重复间反转，进程内顺序固定；无跨进程统计置信区间。",
        "事实为 value/text 与 group_id/integer；初始化使用原生 SQL，排除计时。实际提交使用公开 add 接口。",
        "历史提交绑定一个只接收最新镜像的回调；不模拟长期保留完整 Ren’Py 回滚历史。",
        "恢复后核验事实数与修改是否撤销。SQLite 驱动版本、Python 版本和每次原始样本见 results.json。",
        "pysqlite3 的备份回退及 DuckDB 复制包括临时文件开销；sqlite3 使用内存序列化。", ""]
    (args.out / "REPORT.md").write_text("\n".join(lines))
    return 0 if all(r["status"] == "ok" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
