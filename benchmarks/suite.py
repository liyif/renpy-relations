"""Run current-runtime benchmarks serially, with explicit coverage and budgets."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
from time import perf_counter

from run import ROOT, CLIENT_TIMEZONE, atomic_json, memory, runtime_info


def plan(profile, python, packages, output, smoke=False):
    output = Path(output).resolve()
    # Resolving a venv interpreter symlink loses its environment and packages.
    worker = ["--python", str(Path(python).absolute())]
    if packages:
        worker += ["--packages", str(Path(packages).resolve())]
    tasks = []

    def task(name, script, options, *, probe=False):
        directory = output / name
        result = directory / "results.json"
        command = [str(python) if probe else sys.executable, str(ROOT / "benchmarks" / script)]
        command += options
        command += (["--packages", str(Path(packages).resolve())] if packages and probe else [])
        command += [] if probe else worker
        command += ["--out", str(result if script in ("graph.py", "suite.py") else directory)]
        def count(option, default):
            if option not in options:
                return default
            start = options.index(option) + 1
            end = next((i for i in range(start, len(options)) if options[i].startswith("--")), len(options))
            return len(options[start:end])

        def integer(option, default):
            return int(options[options.index(option) + 1]) if option in options else default

        if script == "conditions.py":
            configurations = count("--conditions", 3) * count("--ratios", 2) * count("--shapes", 2) * count("--backends", 2) * count("--modes", 3)
            expected = {"runs": configurations * integer("--repetitions", 3), "validations": configurations}
        elif script == "run.py":
            expected = {"runs": count("--sizes", 3) * count("--backends", 1) * (1 + count("--modes", 3) * integer("--repetitions", 3))}
        elif script == "snapshots.py":
            expected = {"runs": count("--sizes", 2) * count("--drivers", 3) * integer("--process-repetitions", 1)}
        elif script == "graph.py":
            expected = {"runs": count("--lengths", 3) * count("--backends", 1)}
        else:
            expected = {}
        tasks.append({"name": name, "command": command, "directory": str(directory), "expected": expected,
                      "result": str(result), "probe": probe, "timeout": 120 if probe else None})

    conditions = ["320"] if smoke else ["1000", "3000", "10000"]
    sizes = ["40"] if smoke else ["10000", "100000", "1000000"]
    repetitions = "1" if smoke else "3"
    condition_options = ["--conditions", *conditions, "--repetitions", repetitions, "--timeout", "300"]
    fact_options = ["--sizes", *sizes, "--repetitions", repetitions, "--queries", "12", "--batch-size", "3" if smoke else "100"]
    if profile == "full":
        task("conditions", "conditions.py", condition_options + ["--backends", "sqlite", "duckdb"])
        task("facts", "run.py", fact_options + ["--backends", "sqlite", "duckdb"])
    else:
        task("conditions-sqlite", "conditions.py", condition_options + ["--backends", "sqlite"])
        task("conditions-duckdb", "conditions.py", ["--conditions", conditions[0], "--ratios", "10",
             "--shapes", "partitioned", "--backends", "duckdb", "--repetitions", repetitions, "--timeout", "300"])
        task("facts-sqlite", "run.py", fact_options + ["--backends", "sqlite"])
        task("facts-duckdb", "run.py", ["--sizes", sizes[0], "--backends", "duckdb", "--repetitions", repetitions,
             "--queries", "12", "--batch-size", "3" if smoke else "100"])
    task("snapshots", "snapshots.py", ["--sizes", *sizes, "--drivers", "pysqlite3", "duckdb",
         "--process-repetitions", repetitions, "--repetitions", "1"])
    task("graph", "graph.py", ["--lengths", *(["8"] if smoke else ["128", "512", "1050"]),
         "--backends", "sqlite", "duckdb", "--timeout", "120"])
    if profile == "controlled":
        for count in ([320] if smoke else [3000, 10000]):
            task(f"duckdb-load-{count}", "suite.py", ["--probe", "--condition-count", str(count)], probe=True)
    return tasks


def load_result(task):
    destination = Path(task["result"])
    if not destination.exists():
        return None
    try:
        document = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("result must be a JSON object")
        return document
    except (OSError, ValueError) as exc:
        return {"status": "error", "error": f"Unreadable worker result: {exc}"}


def classify(document, task=None):
    if document is None:
        return "missing"
    records = document.get("runs", [document]) + document.get("validations", [])
    if not records:
        return "incomplete"
    if all(record.get("status") == "ok" for record in records):
        if task and any(len(document.get(key, [])) != count for key, count in task["expected"].items()):
            return "incomplete"
        return "completed"
    if any(record.get("status") == "timeout" or
           "timed out" in str(record.get("error", "")).lower() or
           "exceeded" in str(record.get("error", "")).lower() for record in records):
        return "budget_limited"
    if any(record.get("status") == "running" for record in records):
        return "incomplete"
    return "failed"


def current_source_identity():
    """A workspace identity; only the executor may label it as measured."""
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    files = [ROOT / "renpy_relations.py", ROOT / "compile_rules.py", ROOT / "uv.lock",
             *sorted((ROOT / "benchmarks").glob("*.py")),
             *sorted((ROOT / "relation_rules").glob("*.py"))]
    return {"captured_at": datetime.now(CLIENT_TIMEZONE).isoformat(), "git_commit": git.stdout.strip(),
            "git_dirty": bool(dirty.stdout),
            "sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}


def source_from_result(document):
    """Recover only hashes actually recorded by an independently run child."""
    if document is None:
        return None
    hashes = dict(document.get("source", {}).get("sha256", {}))
    conflicts = []

    def add(name, digest):
        if name in hashes and hashes[name] != digest:
            conflicts.append(name)
        hashes[name] = digest

    for name, digest in document.get("file_sha256", {}).items():
        add(name, digest)
    if "native" in document.get("source_sha256", {}):
        add(document.get("runtime_sources", {}).get("native", "renpy_relations.py"),
            document["source_sha256"]["native"])
    if document.get("runtime_sha256"):
        add(document.get("runtime_source", "renpy_relations.py"), document["runtime_sha256"])
    for record in document.get("runs", [document]) + document.get("validations", []):
        if record.get("runtime_sha256"):
            add(record.get("runtime_source", "renpy_relations.py"), record["runtime_sha256"])
    if not hashes:
        return None
    identity = {"origin": "child_result_hashes", "sha256": hashes, "conflicts": sorted(set(conflicts))}
    identity.update({key: document["source"][key] for key in ("git_commit", "git_dirty")
                     if key in document.get("source", {})})
    return identity


def revalidate_record(task, record):
    """Recheck existing output instead of trusting an old completed label."""
    document = load_result(task)
    status = classify(document, task)
    previous_status = record.get("status")
    if status == "incomplete" and previous_status == "budget_limited":
        status = "budget_limited"
    if status == "completed" and record.get("returncode") not in (None, 0):
        status = "failed"
    observed = source_from_result(document)
    measured = record.get("measured_source") or observed
    verification = {"observed": observed, "mismatches": [], "identity_available": measured is not None}
    if measured and observed:
        verification["mismatches"] = sorted(name for name, digest in observed["sha256"].items()
                                             if name in measured["sha256"] and measured["sha256"][name] != digest)
        verification["unverified_child_files"] = sorted(set(observed["sha256"]) - measured["sha256"].keys())
    if verification["mismatches"] or (observed and observed.get("conflicts")):
        status = "failed"
    if record.get("error", "").startswith("Unreadable execution record:"):
        status = "failed"
    return {**record, **{key: task[key] for key in ("directory", "result", "expected")},
            "status": status, "measured_source": measured,
            "result_validation": {"previous_status": previous_status, "status": status,
                                  "source_verification": verification}}


def execute_task(task):
    directory = Path(task["directory"])
    directory.mkdir(parents=True, exist_ok=True)
    log = directory.parent / (task["name"] + ".log")
    record = {**task, "started_at": datetime.now(CLIENT_TIMEZONE).isoformat(),
              "measured_source": {"origin": "captured_before_execution", **current_source_identity()}}
    # Child CLIs require an empty output directory. Keep the in-progress
    # identity beside it until the child has finished producing its results.
    pending = directory.parent / (task["name"] + ".running.json")
    atomic_json(pending, {**record, "status": "running"})
    start = perf_counter()
    try:
        with log.open("w", encoding="utf-8") as stream:
            completed = subprocess.run(task["command"], stdout=stream, stderr=stream, timeout=task["timeout"])
        record["returncode"] = completed.returncode
        record["status"] = classify(load_result(task), task)
        if completed.returncode and record["status"] == "completed":
            record["status"] = "failed"
    except subprocess.TimeoutExpired as exc:
        record.update(status="budget_limited", returncode=None, error=str(exc))
    except OSError as exc:
        record.update(status="failed", returncode=None, error=str(exc))
    record.update(seconds=perf_counter() - start, finished_at=datetime.now(CLIENT_TIMEZONE).isoformat(), log=str(log))
    record = revalidate_record(task, record)
    atomic_json(directory / "execution.json", record)
    pending.unlink(missing_ok=True)
    return record


def write_report(output, records, *, profile="controlled", python=sys.executable, packages=None, smoke=False):
    output = Path(output).resolve()
    records = [revalidate_record(record, record) for record in records]
    measured_hashes, source_conflicts, commits = {}, {}, set()
    for record in records:
        identity = record.get("measured_source")
        if identity is None:
            continue
        if identity.get("git_commit"):
            commits.add(identity["git_commit"])
        for name, digest in identity["sha256"].items():
            if name in measured_hashes and measured_hashes[name] != digest:
                source_conflicts.setdefault(name, set()).update((measured_hashes[name], digest))
            measured_hashes[name] = digest
    measured_source = {"origin": "per_task_execution_or_child_results", "sha256": measured_hashes,
                       "coverage": "Union of recorded hashes; per-task measured_source is authoritative for each workload",
                       "git_commits": sorted(commits),
                       "conflicts": {name: sorted(values) for name, values in source_conflicts.items()},
                       "unknown_tasks": [record["name"] for record in records if record.get("measured_source") is None]}
    unmeasured = ([] if profile == "full" else [
        "DuckDB 条件矩阵除 1000 条件、比例 1:10、分表、三模式以外的组合；3000/10000 仅做有时限加载探针。",
        "DuckDB 大事实集的 100000 与 1000000 角色。"])
    unmeasured += ["完整 Ren’Py 帧率、长期回退历史、存档归档、倾斜数据与跨硬件统计。"]
    if smoke:
        unmeasured.insert(0, "smoke 使用缩小数据验证工具，不作为正式性能结论。")
    document = {"format": "renpy-relations-benchmark-suite", "version": 1,
                "updated_at": datetime.now(CLIENT_TIMEZONE).isoformat(), "profile": profile, "smoke": smoke,
                "worker": {"python": str(python), "packages": str(packages) if packages else None},
                "host": {"platform": platform.platform(), "logical_cpus": os.cpu_count(),
                         "cpu": next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                                      if line.startswith("model name")), "unknown")},
                "source": measured_source, "measured_source": measured_source,
                "report_generation_source": current_source_identity(),
                "runs": records, "unmeasured": unmeasured}
    atomic_json(output / "results.json", document)
    lines = ["# 当前版本 Benchmark", "", f"配置：`{profile}`；smoke：`{smoke}`。所有任务串行执行，保留自动 GC。", "",
             "结果只覆盖下表实际执行范围。completed 表示该任务全部校验与测量完成；budget_limited 表示达到预算或保留了未完成阶段，不能视作通过。", "",
             "普通提交未绑定镜像接收者，历史绑定提交由快照任务单独测量。条件完整集合在独立进程校验；读取计时进程不提前执行全集合查询。", "",
             "measured_source 保留执行开始捕获的身份或子结果原有哈希；report_generation_source 仅表示生成报告时的源码。各任务分别保留身份与核验结果；未知来源不补写当前源码为已测来源。", "",
             "| 任务 | 状态 | 墙钟秒 | 报告／原始结果 |", "| --- | --- | ---: | --- |"]
    for record in records:
        directory = Path(record["directory"])
        relative = directory.relative_to(output).as_posix()
        report = f"[{record['name']}]({relative}/REPORT.md)" if (directory / "REPORT.md").exists() else "—"
        seconds = f"{record['seconds']:.3f}" if "seconds" in record else "—"
        lines.append(f"| {record['name']} | {record['status']} | {seconds} | {report} / [JSON]({relative}/results.json) |")
    lines += ["", "## 执行命令", ""]
    for record in records:
        key = "command" if "command" in record else "planned_command"
        suffix = "" if key == "command" else "（计划命令；未找到执行记录）"
        lines += [f"{record['name']}{suffix}：", "", "```sh", shlex.join(record[key]), "```", ""]
    lines += ["## 未测范围", "", *[f"- {item}" for item in unmeasured], "",
              "环境、源码哈希、具体命令与状态见根 results.json；各子目录保留阶段结果与正确性校验。失败样本不填零，不混入成功统计。", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return document


def probe(args):
    if args.packages:
        sys.path.insert(0, str(args.packages.resolve()))
    sys.path.insert(0, str(ROOT))
    from relation_rules import LogicDB, RuleSet
    from rules import dataset, populate

    facts = (args.condition_count + 73) // 10
    document = dataset(facts, 10, "partitioned", conditions=args.condition_count, backend="duckdb")
    record = {"status": "running", "kind": "load_probe", "backend": "duckdb", "conditions": args.condition_count,
              "facts": facts, "ratio": 10, "shape": "partitioned", "mode": "cached", "history_bound": False,
              "runtime": runtime_info("duckdb"),
              "runtime_source": "relation_rules/runtime.py",
              "runtime_sha256": hashlib.sha256((ROOT / "relation_rules/runtime.py").read_bytes()).hexdigest(),
              "bundle_sha256": hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest(), "phases": {}}
    db = None

    def measure(name, action):
        record["current_phase"] = name
        atomic_json(args.out, record)
        start = perf_counter()
        value = action()
        record["phases"][name] = {"seconds": perf_counter() - start, **memory()}
        record.pop("current_phase", None)
        atomic_json(args.out, record)
        return value

    try:
        db = measure("load", lambda: LogicDB(RuleSet(document)))
        measure("ingest", lambda: populate(db, facts, "partitioned"))
        assert measure("first_has", lambda: db.has("D0Rule3", flag="v0"))
        record["status"] = "ok"
    except Exception as exc:
        record.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        if db is not None:
            db.close()
        atomic_json(args.out, record)
    return 0 if record["status"] == "ok" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["controlled", "full"], default="controlled")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--collect", action="store_true", help="Read existing results without executing workloads")
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--condition-count", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe:
        if args.condition_count is None or args.condition_count < 320:
            parser.error("probe requires >=320 conditions")
        return probe(args)
    args.out = args.out.resolve()
    if not args.collect and args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        parser.error("Output directory must be empty")
    args.out.mkdir(parents=True, exist_ok=True)
    tasks = plan(args.profile, args.python, args.packages, args.out, args.smoke)
    records = []
    for task in tasks:
        print(task["name"], flush=True)
        if args.collect:
            execution = Path(task["directory"]) / "execution.json"
            try:
                record = json.loads(execution.read_text()) if execution.exists() else {
                **{key: value for key, value in task.items() if key != "command"},
                "planned_command": task["command"], "status": classify(load_result(task), task)}
            except (OSError, ValueError) as exc:
                record = {**{key: value for key, value in task.items() if key != "command"},
                          "planned_command": task["command"], "status": "failed", "error": f"Unreadable execution record: {exc}"}
            record = revalidate_record(task, record)
        else:
            record = execute_task(task)
        records.append(record)
        document = write_report(args.out, records, profile=args.profile, python=args.python, packages=args.packages, smoke=args.smoke)
    return 0 if all(record["status"] == "completed" for record in document["runs"]) and not document["measured_source"]["conflicts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
