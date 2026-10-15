"""Measure the unmodified backend at scale, using isolated serial workers."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
from itertools import islice
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter, process_time
import traceback


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODES = ("cached", "live", "materialized")
LOCATIONS = ("archive", "garden", "hall", "tower")
CLIENT_TIMEZONE = timezone(timedelta(hours=8), "Asia/Singapore")


def character(number):
    return f"c{number:08d}"


def ceil_div(number, divisor):
    return (number + divisor - 1) // divisor


def cardinalities(size):
    facts = {"Member": size, "FactionAccess": 128, "Sponsor": ceil_div(size, 10),
             "Knows": ceil_div(size, 3), "RewardClaimed": ceil_div(size, 11)}
    derived = {"CanEnter": 4 * size + ceil_div(size, 10),
               "CanInvestigate": ceil_div(size, 3),
               "CanClaimReward": ceil_div(size, 3) - ceil_div(size, 33)}
    return {"facts_by_relation": facts, "facts": sum(facts.values()),
            "expected_derived_rows": derived}


def populate(db, size):
    """Exercise the production mutation interface without a history receiver."""
    with db.batch():
        for faction in range(32):
            for location in LOCATIONS:
                db.add("FactionAccess", faction=f"f{faction}", location=location)
        for number in range(size):
            person = character(number)
            db.add("Member", character=person, faction=f"f{number % 32}")
            if number % 10 == 0:
                db.add("Sponsor", character=person, location="vault")
            if number % 3 == 0:
                db.add("Knows", character=person, secret="forged_letter")
            if number % 11 == 0:
                db.add("RewardClaimed", character=person, reward="investigation")


def eligible(number, size, added=()):
    return 0 <= number < size and (number % 3 == 0 or number in added) and number % 11 != 0


def access_rows(number, size):
    if not 0 <= number < size:
        return set()
    locations = set(LOCATIONS)
    if number % 10 == 0:
        locations.add("vault")
    return {(character(number), location) for location in locations}


def probes(size, count):
    initial = [3, 0, 1, size - 1, size // 2, size + 17]
    return (initial + [(i * 2654435761) % size for i in range(count)])[:count]


def new_knowledge(size, count):
    return list(islice((n for n in range(size) if n % 3 != 0 and n % 11 != 0), count))


def memory():
    """Linux RSS and process lifetime high-water mark, both in bytes."""
    values = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                values[line.split(":")[0]] = int(line.split()[1]) * 1024
    except OSError:
        pass
    return {"rss_bytes": values.get("VmRSS"), "peak_rss_bytes": values.get("VmHWM")}


def atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def runtime_info(backend="sqlite"):
    import renpy_relations
    import sqlalchemy

    driver = renpy_relations.sqlite3
    connection = driver.connect(":memory:")
    try:
        temporary_store = connection.execute("PRAGMA temp_store").fetchone()[0]
        options = [r[0] for r in connection.execute("PRAGMA compile_options")]
    finally:
        connection.close()
    info = {"python": sys.version, "executable": sys.executable, "backend": backend,
            "driver": driver.__name__, "sqlite": driver.sqlite_version,
            "sqlalchemy": sqlalchemy.__version__, "temp_store_default": temporary_store,
            "sqlite_compile_options": options}
    if backend == "duckdb":
        import duckdb
        info["duckdb"] = duckdb.__version__
    return info


def assert_samples(db, size, numbers, added=()):
    for number in numbers:
        actual = db.has("CanClaimReward", character=character(number), reward="investigation")
        if actual != eligible(number, size, added):
            raise AssertionError(f"Incorrect reward eligibility for {number}: {actual}")


def worker(args):
    if args.packages is not None:
        sys.path.insert(0, str(args.packages.resolve()))
    sys.path.insert(0, str(ROOT))
    from relation_rules import LogicDB

    result = {"kind": args.worker, "size": args.size, "mode": args.mode, "backend": args.backend,
              "history_bound": False,
              "repeat": args.repeat, "status": "running", "phases": {},
              "cardinalities": cardinalities(args.size), "runtime": runtime_info(args.backend)}
    db = None

    def measure(name, operation):
        result["current_phase"] = name
        atomic_json(args.result, result)
        before = memory()
        cpu_start, start = process_time(), perf_counter()
        value = operation()
        elapsed, cpu = perf_counter() - start, process_time() - cpu_start
        result["phases"][name] = {"seconds": elapsed, "cpu_seconds": cpu,
                                  "rss_before_bytes": before["rss_bytes"], **memory()}
        result.pop("current_phase", None)
        atomic_json(args.result, result)
        return value

    def requests(name, numbers, query):
        samples = []

        def execute():
            values = []
            for number in numbers:
                started = perf_counter()
                values.append(query(number))
                samples.append(perf_counter() - started)
            return values

        values = measure(name, execute)
        result["phases"][name].update(requests=len(numbers), samples_seconds=samples)
        atomic_json(args.result, result)
        return values

    try:
        db = measure("init_empty", lambda: LogicDB(args.bundle, mode=args.mode))
        if args.worker == "seed":
            measure("public_ingest", lambda: populate(db, args.size))
            # No on_snapshot receiver is bound, so public_ingest only commits;
            # explicit native serialization is measured separately.
            snapshot = measure("snapshot", db.snapshot)
            args.fixture.write_bytes(snapshot)
            result.update(snapshot_bytes=len(snapshot), fixture_sha256=hashlib.sha256(snapshot).hexdigest())
            assert_samples(db, args.size, probes(args.size, 6))
        else:
            snapshot = args.fixture.read_bytes()
            result.update(snapshot_bytes=len(snapshot), fixture_sha256=hashlib.sha256(snapshot).hexdigest())
            measure("restore_initial", lambda: db.restore(snapshot))
            value = measure("first_has", lambda: db.has(
                "CanClaimReward", character=character(3), reward="investigation"))
            if not value:
                raise AssertionError("Cold read returned incorrect reward eligibility")
            numbers = probes(args.size, args.queries)
            values = requests("warm_has", numbers, lambda n: db.has(
                "CanClaimReward", character=character(n), reward="investigation"))
            if values != [eligible(n, args.size) for n in numbers]:
                raise AssertionError("Warm has results differ from the Python oracle")
            rows = requests("warm_query", numbers, lambda n: db.query("CanEnter", character=character(n)))
            for number, actual in zip(numbers, rows):
                if {(r["character"], r["location"]) for r in actual} != access_rows(number, args.size):
                    raise AssertionError(f"Incorrect access rows for {number}")
            saved = measure("snapshot", db.snapshot)
            result["snapshot_bytes"] = len(saved)
            del saved
            targets = new_knowledge(args.size, args.batch_size + 1)
            added = set()
            measure("single_commit", lambda: db.add(
                "Knows", character=character(targets[0]), secret="forged_letter"))
            added.add(targets[0])
            value = measure("first_has_after_single", lambda: db.has(
                "CanClaimReward", character=character(targets[0]), reward="investigation"))
            if value is not True:
                raise AssertionError("Single fact change did not update derived eligibility")

            def add_batch():
                with db.batch():
                    for number in targets[1:]:
                        db.add("Knows", character=character(number), secret="forged_letter")

            measure("batch_commit", add_batch)
            added.update(targets[1:])
            result["batch_changes"] = len(targets) - 1
            if targets[1:]:
                value = measure("first_has_after_batch", lambda: db.has(
                    "CanClaimReward", character=character(targets[-1]), reward="investigation"))
                if not value:
                    raise AssertionError("Batch fact changes did not update derived eligibility")
            measure("reload_same_rules", db.reload_rules)
            value = measure("first_has_after_reload", lambda: db.has(
                "CanClaimReward", character=character(targets[0]), reward="investigation"))
            if not value:
                raise AssertionError("Rule reload lost facts or returned stale derived results")
            assert_samples(db, args.size, numbers, added)
            measure("restore_after_edits", lambda: db.restore(snapshot))
            value = measure("first_has_after_restore", lambda: db.has(
                "CanClaimReward", character=character(targets[0]), reward="investigation"))
            if value:
                raise AssertionError("Snapshot restore failed to retract changed knowledge")
            result["cache_stats"] = db.stats()
        result.update(status="ok", **memory())
    except Exception as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        if db is not None:
            db.close()
        atomic_json(args.result, result)
    return 0 if result["status"] == "ok" else 1


def launch(args, work, bundle, size, kind, *, backend="sqlite", mode="cached", repeat=0):
    stem = f"{kind}-{size}-{backend}-{mode}-{repeat}"
    destination = work / (stem + ".json")
    destination.unlink(missing_ok=True)
    command = [str(args.python), str(Path(__file__).resolve()), "--worker", kind,
               "--bundle", str(bundle), "--fixture", str(work / f"world-{size}-{backend}.snapshot"),
               "--result", str(destination), "--size", str(size), "--mode", mode,
               "--repeat", str(repeat), "--backend", backend, "--queries", str(args.queries),
               "--batch-size", str(args.batch_size)]
    if args.packages is not None:
        command += ["--packages", str(args.packages.resolve())]
    print(f"{kind}: characters={size:,}, backend={backend}, mode={mode}, repeat={repeat + 1}", flush=True)
    failure = None
    with (work / (stem + ".log")).open("w", encoding="utf-8") as log:
        try:
            completed = subprocess.run(command, stdout=log, stderr=log, timeout=args.timeout)
            if completed.returncode:
                failure = ("error", f"Worker exited with status {completed.returncode}")
        except subprocess.TimeoutExpired:
            failure = ("timeout", f"Exceeded {args.timeout:g}s worker limit")
        except OSError as exc:
            failure = ("error", f"Could not start worker: {exc}")
    if destination.exists():
        result = json.loads(destination.read_text(encoding="utf-8"))
    else:
        result = {"kind": kind, "size": size, "mode": mode, "backend": backend, "repeat": repeat, "phases": {},
                  "status": "error", "error": "Worker produced no result"}
    if failure:
        result.update(status=failure[0], error=failure[1])
    if result["status"] == "running":
        result.update(status="error", error="Worker did not complete its result")
    print(f"  {result['status']}: {result.get('current_phase', 'complete')}", flush=True)
    return result


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(results):
    groups = {}
    for result in results:
        if result["kind"] != "measure":
            continue
        key = (result["size"], result["mode"], result.get("backend", "sqlite"))
        group = groups.setdefault(key, {"size": key[0], "mode": key[1], "attempted": 0,
                                        "backend": key[2], "successful": 0, "phases": {}})
        group["attempted"] += 1
        if result["status"] != "ok":
            continue
        group["successful"] += 1
        group.setdefault("snapshot_bytes", []).append(result["snapshot_bytes"])
        if result.get("peak_rss_bytes") is not None:
            group.setdefault("peak_rss_bytes", []).append(result["peak_rss_bytes"])
        for name, phase in result["phases"].items():
            group["phases"].setdefault(name, []).extend(phase.get("samples_seconds", [phase["seconds"]]))
    for group in groups.values():
        for name, samples in group["phases"].items():
            group["phases"][name] = {"n": len(samples), "median_seconds": statistics.median(samples),
                                      "p95_seconds": percentile(samples, 0.95)}
        for field in ("snapshot_bytes", "peak_rss_bytes"):
            if field in group:
                group[field] = max(group[field])
    return list(groups.values())


def write_report(output, document):
    atomic_json(output / "results.json", document)
    fields = ["kind", "size", "backend", "mode", "repeat", "status", "phase", "seconds", "cpu_seconds",
              "rss_before_bytes", "rss_bytes", "peak_rss_bytes", "requests", "snapshot_bytes"]
    with (output / "phases.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for result in document["runs"]:
            for name, phase in result["phases"].items():
                writer.writerow({**result, "phase": name, **phase})
    lines = ["# 大规模后端基准", "", f"运行时间：{document['started_at']}。", "",
             "测量当前后端；不含 Ren’Py 界面、交互调度、回滚历史追踪和存档归档成本。", "",
             f"CPU：{document['host']['cpu']}；逻辑 CPU：{document['host']['logical_cpus']}。", "",
             f"重复：{document['parameters']['repetitions']}；每轮 warm 请求各 {document['parameters']['queries']} 次；"
             f"batch 上限 {document['parameters']['batch_size']} 条。", ""]
    environments = {f"Python {run['runtime']['python'].split()[0]}，SQLAlchemy {run['runtime']['sqlalchemy']}，" +
                    (f"DuckDB {run['runtime']['duckdb']}" if run['backend'] == 'duckdb' else
                     f"{run['runtime']['driver']}／SQLite {run['runtime']['sqlite']}；temp_store={run['runtime']['temp_store_default']}")
                    for run in document["runs"] if "runtime" in run}
    if environments:
        lines += ["子进程：" + "；".join(sorted(environments)) + "。", ""]
    lines += [
             "## 数据与导入", "",
             "每档导入通过公开 add，在一个 batch 中完成；包含数据生成、绑定和提交；没有历史接收者，提交不生成快照。每档只测一次，不能当作重复样本中位数。", "",
             "| 角色 | 后端 | 事实 | 预期 CanEnter 行数 | 公开导入（秒） |", "| ---: | --- | ---: | ---: | ---: |"]
    for run in document["runs"]:
        if run["kind"] == "seed":
            counts = cardinalities(run["size"])
            seconds = run["phases"].get("public_ingest", {}).get("seconds")
            lines.append(f"| {run['size']:,} | {run['backend']} | {counts['facts']:,} | {counts['expected_derived_rows']['CanEnter']:,} | "
                         + (f"{seconds:.3f}" if seconds is not None else run["status"]) + " |")
    lines += ["", "派生行数按固定数据生成公式计算；大规模使用分散样本校验，完整集合核对在小规模测试中进行。", "",
              "## 读取延迟", "", "单位：毫秒。first 为恢复后首次读取；warm 为同一实例内分散角色的逐请求样本。", "",
              "| 角色 | 后端 | 模式 | 完整成功/尝试 | 首次 has 中位数 | warm has 中位数 / p95 | warm query 中位数 / p95 |",
              "| ---: | --- | --- | ---: | ---: | ---: | ---: |"]

    def value(group, phase, *, p95=False):
        item = group["phases"].get(phase)
        if item is None:
            return "—"
        text = f"{item['median_seconds'] * 1000:.3f}"
        return text + f" / {item['p95_seconds'] * 1000:.3f}" if p95 else text

    for group in document["summary"]:
        lines.append(f"| {group['size']:,} | {group['backend']} | {group['mode']} | {group['successful']}/{group['attempted']} | "
                     f"{value(group, 'first_has')} | {value(group, 'warm_has', p95=True)} | {value(group, 'warm_query', p95=True)} |")
    lines += ["", "## 修改与生命周期", "", "单位：毫秒，中位数；提交未绑定历史接收者，不生成快照；快照单独计时。历史绑定开销由 snapshots.py 单独测量。batch 实际变更数量见 JSON。", "",
              "| 角色 | 后端 | 模式 | 单条提交 | 其后首次读 | batch 提交 | 其后首次读 | 快照 | 初始恢复 | 修改后恢复 | 规则重载 | 重载后首次读 |",
              "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    phases = ("single_commit", "first_has_after_single", "batch_commit", "first_has_after_batch",
              "snapshot", "restore_initial", "restore_after_edits", "reload_same_rules", "first_has_after_reload")
    for group in document["summary"]:
        lines.append(f"| {group['size']:,} | {group['backend']} | {group['mode']} | " + " | ".join(value(group, p) for p in phases) + " |")
    lines += ["", "## 大小与内存", "", "进程峰值 RSS 为完整成功试验的最大值，包括数据读取、快照、候选世界与验证，不是某一查询的独立增量。", "",
              "| 角色 | 后端 | 模式 | 原生快照 MiB | 进程峰值 RSS MiB |", "| ---: | --- | --- | ---: | ---: |"]
    for group in document["summary"]:
        snapshot = f"{group['snapshot_bytes'] / 2**20:.3f}" if "snapshot_bytes" in group else "—"
        peak = f"{group['peak_rss_bytes'] / 2**20:.1f}" if "peak_rss_bytes" in group else "—"
        lines.append(f"| {group['size']:,} | {group['backend']} | {group['mode']} | {snapshot} | {peak} |")
    lines += ["", "## 限制与原始数据", "",
              "- 新进程隔离 Python／数据库状态；没有清空操作系统页缓存，不能称为物理冷启动。",
              "- p95 只描述本次有限样本；串行运行，顺序轮换；没有应用帧率保证或跨硬件结论。",
              "- 数据库采用内存模式，派生结果及临时数据可能落盘，RSS 不是全部存储大小。",
              "- 缺失／失败值不填零；汇总仅使用完整通过结果，超时前已完成的阶段保留在原始 JSON／CSV。",
              "- 环境、源码摘要、Git 状态、fixture SHA256、逐请求样本和阶段 CPU／RSS 在 results.json；阶段表见 phases.csv。"]
    failed = [run for run in document["runs"] if run["status"] != "ok"]
    if failed:
        lines += ["", "## 未完成／失败", ""]
        lines += [f"- {run['kind']} {run['size']:,} {run['backend']} {run['mode']}: {run['status']}, "
                  f"{run.get('current_phase', 'unknown phase')}: {run.get('error', '')}" for run in failed]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[10_000, 100_000, 1_000_000], help="Number of characters")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--backends", nargs="+", choices=["sqlite", "duckdb"], default=["sqlite"])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--queries", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=1800, help="Per-worker seconds; failures retain partial results")
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Worker Python, optionally SDK interpreter")
    parser.add_argument("--packages", type=Path, help="Worker runtime dependencies, e.g. Ren'Py game/python-packages")
    parser.add_argument("--out", type=Path, help="New output directory")
    parser.add_argument("--worker", choices=("seed", "measure"), help=argparse.SUPPRESS)
    parser.add_argument("--size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=MODES, default="cached", help=argparse.SUPPRESS)
    parser.add_argument("--backend", choices=["sqlite", "duckdb"], default="sqlite", help=argparse.SUPPRESS)
    parser.add_argument("--repeat", type=int, default=0, help=argparse.SUPPRESS)
    for field in ("bundle", "fixture", "result"):
        parser.add_argument(f"--{field}", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (min(args.sizes) < 4 or min(args.repetitions, args.queries, args.batch_size) < 1
            or not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error("sizes must be >=4; repetitions, queries, batch-size and timeout must be positive")
    if args.worker:
        return worker(args)
    from compile_rules import compile_rules

    started = datetime.now(CLIENT_TIMEZONE).isoformat()
    output = (args.out or ROOT / "benchmarks" / "results" / datetime.now(CLIENT_TIMEZONE).strftime("%Y%m%d-%H%M%S%z")).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("Output directory must be empty; choose a new --out directory")
    work = output / ".work"
    work.mkdir(parents=True, exist_ok=True)
    begin = perf_counter()
    bundles = {}
    for backend in args.backends:
        bundles[backend] = work / f"relations-{backend}.rules.json"
        compile_rules(ROOT / "examples/palace/world.l", ROOT / "examples/palace/schema.json", bundles[backend], backend=backend)
    compile_seconds = perf_counter() - begin
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), "unknown")
    document = {"format": "renpy-relations-benchmark", "version": 1, "started_at": started,
                "parameters": {"sizes": args.sizes, "modes": args.modes, "backends": args.backends,
                               "history_bound": False, "repetitions": args.repetitions,
                               "queries": args.queries, "batch_size": args.batch_size, "timeout": args.timeout},
                "host": {"platform": platform.platform(), "cpu": cpu, "logical_cpus": os.cpu_count()},
                "source": {"git_commit": git.stdout.strip(), "git_dirty": bool(dirty.stdout),
                           "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                      for name in ("renpy_relations.py", "compile_rules.py", "relation_rules/runtime.py",
                                                   "relation_rules/compiler.py", "relation_rules/__init__.py", "benchmarks/run.py", "uv.lock")}},
                "compiler": {"logica": version("logica"), "seconds": compile_seconds}, "runs": [], "summary": []}
    for size in args.sizes:
        seeds = {}
        for backend in args.backends:
            seeds[backend] = launch(args, work, bundles[backend], size, "seed", backend=backend)
            document["runs"].append(seeds[backend])
        if any(seed["status"] == "ok" for seed in seeds.values()):
            for repeat in range(args.repetitions):
                offset = repeat % len(args.modes)
                for mode in args.modes[offset:] + args.modes[:offset]:
                    backends = args.backends if repeat % 2 == 0 else list(reversed(args.backends))
                    for backend in backends:
                        if seeds[backend]["status"] == "ok":
                            document["runs"].append(launch(args, work, bundles[backend], size, "measure", backend=backend, mode=mode, repeat=repeat))
                            document["summary"] = summarize(document["runs"])
                            write_report(output, document)
        document["summary"] = summarize(document["runs"])
        write_report(output, document)
    document["finished_at"] = datetime.now(CLIENT_TIMEZONE).isoformat()
    write_report(output, document)
    print(f"Report: {output / 'REPORT.md'}", flush=True)
    return 0 if all(run["status"] == "ok" for run in document["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
