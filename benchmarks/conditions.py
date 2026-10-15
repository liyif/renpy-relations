"""Evaluate 1,000–10,000 distinct generated conditions in every measured round."""

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

from rules import dataset
from run import ROOT, CLIENT_TIMEZONE, atomic_json


def report(output, document):
    atomic_json(output / "results.json", document)
    groups = {}
    for run in document["runs"]:
        key = (run["conditions"], run["facts"], run["rules"], run["shape"], run["backend"], run["mode"], run["variant"])
        groups.setdefault(key, []).append(run)
    environments = {f"Python {r['runtime']['python'].split()[0]}／SQLAlchemy {r['runtime']['sqlalchemy']}／" +
                    (f"DuckDB {r['runtime']['duckdb']}" if r['backend'] == 'duckdb' else
                     f"{r['runtime']['driver']}／SQLite {r['runtime']['sqlite']}")
                    for r in document["runs"] if "runtime" in r}
    environment = "；".join(sorted(environments)) or "尚无子进程环境"
    lines = ["# 1000～10000 条件读取基准", "", f"开始：{document['started_at']}；CPU：{document['cpu']}。", "",
             f"每种配置 {document['repetitions']} 次独立进程重复；后端 {document['backends']}；版本 {document['variants']}。", "",
             f"子进程：{environment}。", "",
             "每轮实际调用不同派生条件各一次。条件数不含64个共享前置关系。时间为整轮中位数，单位ms；动作含提交和随后完整读取。", "",
             "| 条件 | 事实 | 总派生关系 | 布局 | 后端 | 模式 | 版本 | 成功/尝试 | 加载 | 首轮 | 重复轮 | 局部动作 | 全局动作 | 无关动作 | 局部重建数 | warm单次中位数/p95 µs |",
             "| ---: | ---: | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, runs in groups.items():
        good = [r for r in runs if r["status"] == "ok"]

        def median(function, multiplier=1000):
            return f"{statistics.median(function(r) for r in good)*multiplier:.3f}" if good else "—"

        columns = [median(lambda r, p=p: r["phases"][p]["seconds"]) for p in ("load", "cold_panel", "warm_panel")]
        columns += [median(lambda r, a=a: r["phases"][a+"_commit"]["seconds"] + r["phases"][a+"_panel"]["seconds"])
                    for a in ("local", "global", "unrelated")]
        rebuilt = median(lambda r: r["local_rebuilt"], 1) if key[5] == "cached" else "—"
        request = "/".join(median(lambda r, f=f: r["phases"]["warm_panel"][f], 1e6)
                           for f in ("request_median_seconds", "request_p95_seconds"))
        lines.append("| " + " | ".join(map(str, key)) + f" | {len(good)}/{len(runs)} | " + " | ".join(columns) + f" | {rebuilt} | {request} |")
    lines += ["", "单次列是各试验的单次中位数/p95再取跨试验中位数，不是合并请求分位数。", "",
              "原始阶段墙钟/CPU/RSS、逐轮请求数和分布摘要、驱动信息、源码与fixture SHA256见results.json；不保存海量逐请求向量。", "",
              "保留自动GC；加载后直接测读取及三种动作，中间不插入历史遍历或全量行集合校验。每次条件结果均与独立公式核对。", "",
              "未绑定历史镜像接收者，提交不生成快照；历史绑定开销由 snapshots.py 单独测量。全量结果集在独立校验进程中核对五种状态，避免提前预热计时进程。", "",
              "生成SQL，未测Logica全量编译或完整Ren’Py界面。失败不填零、不加入成功中位数；新进程隔离但没有清空OS页缓存。"]
    validations = document.get("validations", [])
    lines += ["", f"完整集合校验：{sum(r['status'] == 'ok' for r in validations)}/{len(validations)} 个独立进程通过。"]
    for run in document["runs"] + validations:
        if run["status"] != "ok":
            lines.append(f"- 失败：{run['conditions']} {run['shape']} {run['backend']} {run['mode']} {run['variant']}：{run.get('error')}")
    (output / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditions", nargs="+", type=int, default=[1000, 3000, 10000])
    parser.add_argument("--ratios", nargs="+", type=int, choices=[1, 10], default=[1, 10])
    parser.add_argument("--shapes", nargs="+", choices=["partitioned", "shared_table"], default=["partitioned", "shared_table"])
    parser.add_argument("--modes", nargs="+", choices=["cached", "materialized", "live"], default=["cached", "materialized", "live"])
    parser.add_argument("--variants", nargs="+", choices=["baseline", "native"], default=["native"])
    parser.add_argument("--backends", nargs="+", choices=["sqlite", "duckdb"], default=["sqlite", "duckdb"])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--baseline-ref", default="8827c21")
    parser.add_argument("--timeout", type=float, default=300, help="Seconds per timing or validation worker")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if min(args.conditions) < 320 or args.repetitions < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("conditions must be >=320 and repetitions positive")
    output = (args.out or ROOT / "benchmarks/results" / datetime.now(CLIENT_TIMEZONE).strftime("conditions-%Y%m%d-%H%M%S")).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("Output directory must be empty")
    work = output / ".work"
    from baseline_sources import historical_runtime
    sources = {variant: (historical_runtime(args.baseline_ref) if variant == "baseline" else
                        (ROOT / "relation_rules/runtime.py").read_bytes()) for variant in args.variants}
    for variant, content in sources.items():
        folder = work / variant
        folder.mkdir(parents=True)
        (folder / "renpy_relations.py").write_bytes(content)
    document = {"started_at": datetime.now(CLIENT_TIMEZONE).isoformat(), "baseline_ref": args.baseline_ref,
                "conditions": args.conditions, "ratios": args.ratios, "shapes": args.shapes, "modes": args.modes,
                "variants": args.variants, "backends": args.backends, "repetitions": args.repetitions,
                "timeout": args.timeout, "history_bound": False,
                "cpu": next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                             if line.startswith("model name")), "unknown"),
                "runtime_sources": {"native": "relation_rules/runtime.py"},
                "source_sha256": {n: hashlib.sha256(c).hexdigest() for n, c in sources.items()},
                "file_sha256": {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                                for n in ("benchmarks/conditions.py", "benchmarks/rules.py", "benchmarks/run.py", "uv.lock")},
                "runs": [], "validations": []}

    def execute(count, facts, ratio, shape, backend, mode, repeat, variant, bundle, *, validation=False):
        stem = f"{count}-{ratio}-{shape}-{backend}-{mode}-{repeat}-{variant}" + ("-validation" if validation else "")
        destination = work / (stem+".json")
        command = [str(args.python), str(ROOT / "benchmarks/rules.py"), "--worker",
                   "--facts", str(facts), "--condition-count", str(count), "--ratio", str(ratio),
                   "--shape", shape, "--backend", backend, "--mode", mode, "--repeat", str(repeat), "--variant", variant,
                   "--runtime", str(work / variant), "--bundle", str(bundle), "--result", str(destination)]
        if validation:
            command.append("--validate-only")
        if args.packages:
            command += ["--packages", str(args.packages.resolve())]
        print(stem, flush=True)
        failure = None
        with (work / (stem+".log")).open("w") as stream:
            try:
                finished = subprocess.run(command, stdout=stream, stderr=stream, timeout=args.timeout)
                if finished.returncode:
                    failure = f"Worker exited {finished.returncode}"
            except (OSError, subprocess.TimeoutExpired) as exc:
                failure = str(exc)
        run = json.loads(destination.read_text()) if destination.exists() else {
            "facts": facts, "rules": count+64, "conditions": count, "ratio": ratio, "shape": shape,
            "backend": backend, "mode": mode, "variant": variant, "repeat": repeat, "status": "error", "phases": {}}
        if failure or run["status"] != "ok":
            run.update(status="error", error=run.get("error", failure or "No complete result"))
        document["validations" if validation else "runs"].append(run)
        report(output, document)

    for count in args.conditions:
        for ratio in args.ratios:
            facts = (count + 64 + ratio - 1) // ratio
            for shape in args.shapes:
                bundles = {}
                for backend in args.backends:
                    declarations = dataset(facts, ratio, shape, conditions=count, backend=backend)
                    plain = {key: value for key, value in declarations.items() if key != "dependencies"}
                    bundles[backend] = {
                        "baseline": work / f"{count}-{ratio}-{shape}-{backend}-baseline.json",
                        "native": work / f"{count}-{ratio}-{shape}-{backend}-native.json",
                    }
                    atomic_json(bundles[backend]["baseline"], plain)
                    atomic_json(bundles[backend]["native"], declarations)
                for mode in args.modes:
                    for backend in args.backends:
                        for variant in args.variants:
                            if variant == "baseline" and backend != "sqlite":
                                continue
                            execute(count, facts, ratio, shape, backend, mode, 0, variant, bundles[backend][variant], validation=True)
                    for repeat in range(args.repetitions):
                        variants = args.variants if repeat % 2 == 0 else list(reversed(args.variants))
                        backends = args.backends if repeat % 2 == 0 else list(reversed(args.backends))
                        for backend in backends:
                            for variant in variants:
                                if variant == "baseline" and backend != "sqlite":
                                    continue
                                execute(count, facts, ratio, shape, backend, mode, repeat, variant, bundles[backend][variant])
    document["finished_at"] = datetime.now(CLIENT_TIMEZONE).isoformat()
    report(output, document)
    return 0 if all(r["status"] == "ok" for r in document["runs"] + document["validations"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
