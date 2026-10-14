"""Many derived conditions over sparse facts; compare pinned and current runtimes."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter, process_time
import traceback

from run import ROOT, CLIENT_TIMEZONE, atomic_json, memory, runtime_info


def dataset(facts, ratio, shape, *, conditions=None, backend="sqlite"):
    columns = {"flag": "text", "enabled": "integer"}
    declarations = {"GlobalState": {"columns": {"enabled": "integer"}},
                    "Blocked": {"columns": {"flag": "text"}},
                    "Note": {"columns": {"text": "text"}}}
    if shape == "shared_table":
        declarations["State"] = {"columns": {"domain": "integer", **columns}}
    else:
        declarations.update({f"State{d}": {"columns": columns} for d in range(32)})
    derived = {}
    for domain in range(32):
        per_domain = (facts * ratio // 32 if conditions is None else
                      2 + conditions // 32 + int(domain < conditions % 32))
        for i in range(per_domain):
            name = f"D{domain}Rule{i}"
            if i == 0:
                source = "State" if shape == "shared_table" else f"State{domain}"
                sql = f"SELECT flag FROM {source} WHERE enabled=1"
                if shape == "shared_table":
                    sql += f" AND domain={domain}"
            elif i == 1:
                sql = f"SELECT flag FROM D{domain}Rule0 WHERE flag != 'blocked'"
            else:
                sql = (f"SELECT flag FROM D{domain}Rule1 r WHERE EXISTS "
                       "(SELECT 1 FROM GlobalState WHERE enabled=1) AND NOT EXISTS "
                       "(SELECT 1 FROM Blocked b WHERE b.flag=r.flag)")
                if conditions is not None:
                    ordinal = i - 2
                    modulus = ordinal + 2
                    forbidden = ordinal % 2
                    sql += f" AND CAST(substr(r.flag,2) AS INTEGER) % {modulus} != {forbidden}"
            derived[name] = {"columns": {"flag": "text"}, "sql": sql}
    document = {"format": "renpy-relations", "version": 1, "facts": declarations, "derived": derived}
    if backend != "sqlite":
        document["backend"] = backend
    return document


def populate(db, facts, shape):
    with db.batch():
        db.add("GlobalState", enabled=1)
        db.add("Note", text="initial")
        for i in range(facts - 2):
            domain, flag = i % 32, f"v{i // 32}"
            if shape == "shared_table":
                db.add("State", domain=domain, flag=flag, enabled=1)
            else:
                db.add(f"State{domain}", flag=flag, enabled=1)


def worker(args):
    if args.packages:
        sys.path.insert(0, str(args.packages.resolve()))
    sys.path.insert(0, str(args.runtime.resolve()))
    from renpy_relations import LogicDB, RuleSet

    record = {"facts": args.facts, "ratio": args.ratio, "rules": args.facts * args.ratio,
              "shape": args.shape, "mode": args.mode, "variant": args.variant,
              "repeat": args.repeat, "backend": args.backend, "history_bound": False,
              "status": "running", "phases": {}, "runtime": runtime_info(args.backend)}
    db = None

    def measure(name, action):
        record["current_phase"] = name
        atomic_json(args.result, record)
        cpu, start = process_time(), perf_counter()
        value = action()
        record["phases"][name] = {"seconds": perf_counter() - start,
                                  "cpu_seconds": process_time() - cpu, **memory()}
        record.pop("current_phase", None)
        atomic_json(args.result, record)
        return value

    condition_count = getattr(args, "condition_count", None)
    panel = ([(d, f"D{d}Rule{i}", i - 2) for d in range(12) for i in (2, 3)]
             if condition_count is None else
             [(d, f"D{d}Rule{i+2}", i) for d in range(32)
              for i in range(condition_count // 32 + int(d < condition_count % 32))])
    record["conditions"] = len(panel)
    if condition_count is not None:
        record["rules"] = condition_count + 64

    def read_panel(local=False, global_off=False):
        samples = []
        for domain, name, ordinal in panel:
            start = perf_counter()
            actual = db.has(name, flag="v0")
            samples.append(perf_counter() - start)
            expected = not global_off and not (local and domain == 0)
            if condition_count is not None:
                expected = expected and 0 != ordinal % 2
            assert actual == expected, name
        return samples

    def save_samples(phase, samples):
        if condition_count is None:
            record["phases"][phase]["samples_seconds"] = samples
        else:
            ordered = sorted(samples)
            record["phases"][phase].update(
                request_count=len(samples), request_median_seconds=statistics.median(samples),
                request_p95_seconds=ordered[(len(ordered)*95+99)//100-1],
                request_min_seconds=ordered[0], request_max_seconds=ordered[-1])

    def change(domain=False, global_off=False, note=False):
        with db.batch():
            if domain:
                name = "State" if args.shape == "shared_table" else "State0"
                fields = {"flag": "v0"}
                if args.shape == "shared_table":
                    fields["domain"] = 0
                db.remove(name, **fields)
                db.add(name, **fields, enabled=0)
            if global_off:
                db.remove("GlobalState", enabled=1)
                db.add("GlobalState", enabled=0)
            if note:
                db.remove("Note", text="initial")
                db.add("Note", text="changed")

    def verify_full(local=False, global_off=False, blocked=False):
        checked = 0
        for domain, name, ordinal in panel:
            expected = {f"v{i // 32}" for i in range(domain, args.facts - 2, 32)
                        if not global_off and not (local and domain == 0 and i // 32 == 0)
                        and not (blocked and i // 32 == 0)
                        and (i // 32) % (ordinal + 2) != ordinal % 2}
            rows = db.query(name)
            assert len(rows) == len(expected), name
            assert {r["flag"] for r in rows} == expected, name
            checked += 1
        record["validated_full_relations"] = record.get("validated_full_relations", 0) + checked

    try:
        document = json.loads(args.bundle.read_text())
        record["bundle_sha256"] = hashlib.sha256(args.bundle.read_bytes()).hexdigest()
        db = measure("load", lambda: LogicDB(RuleSet(document), mode=args.mode))
        measure("ingest", lambda: populate(db, args.facts, args.shape))
        if args.validate_only:
            verify_full()
            change(domain=True)
            verify_full(local=True)
            change(global_off=True)
            verify_full(local=True, global_off=True)
            change(note=True)
            verify_full(local=True, global_off=True)
            with db.batch():
                db.remove("GlobalState", enabled=0)
                db.add("GlobalState", enabled=1)
                db.add("Blocked", flag="v0")
            verify_full(local=True, blocked=True)
            record.update(status="ok", validation_only=True, **memory())
            return 0
        for phase in ("cold_panel", "warm_panel"):
            samples = measure(phase, read_panel)
            save_samples(phase, samples)
        if condition_count is None:
            measure("history_all", lambda: [db.has(n, flag="v0") for n in document["derived"]])
        # Full independent oracle, after the timed history pass has already
        # visited all rules: validation does not warm additional relations.
        for domain in range(32) if condition_count is None else ():
            expected = {f"v{i // 32}" for i in range(domain, args.facts - 2, 32)}
            for i in range(args.facts * args.ratio // 32):
                rows = db.query(f"D{domain}Rule{i}")
                assert len(rows) == len(expected)
                assert {r["flag"] for r in rows} == expected
        for phase, edits, local, global_off in (
                ("local", {"domain": True}, True, False),
                ("global", {"global_off": True}, True, True),
                ("unrelated", {"note": True}, True, True)):
            before = db.stats()
            measure(phase + "_commit", lambda: change(**edits))
            after = db.stats()
            record[phase + "_invalidated"] = len(before["cached_relations"]) - len(after["cached_relations"])
            samples = measure(phase + "_panel", lambda: read_panel(local, global_off))
            save_samples(phase + "_panel", samples)
            record[phase + "_rebuilt"] = sum(db.stats()["materializations"].values()) - sum(after["materializations"].values())
        assert sum(len(db.query(n)) for n in document["facts"]) == args.facts
        record.update(status="ok", **memory())
    except Exception as exc:
        record.update(status="error", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        if db is not None:
            db.close()
        atomic_json(args.result, record)
    return 0 if record["status"] == "ok" else 1


def report(output, document):
    atomic_json(output / "results.json", document)
    runtime = next((r['runtime'] for r in document['runs'] if 'runtime' in r), None)
    environment = (f"Python {runtime['python'].split()[0]}／{runtime['driver']}／SQLite {runtime['sqlite']}"
                   if runtime else "未取得子进程环境")
    lines = ["# 多规则交互基准", "", f"时间：{document['started_at']}。每种条件 {document['repetitions']} 次独立重复。", "",
             f"事实档：{document['facts']}；规则倍数：{document['ratios']}；每个 panel 包含 24 次 has。时间为完整成功试验的中位数，单位 ms。", "",
             f"对照：{document['baseline_ref']}；native 为 SQLite 解析与 SQL 图算法。不含 Ren’Py 界面／历史。", "",
             f"CPU：{document['cpu']}；{environment}。", "",
             "| 事实 | 规则 | 布局 | 模式 | 版本 | 成功/尝试 | 加载 | 冷 panel | warm panel | 局部提交 | 局部 panel | 全局提交 | 全局 panel | 无关提交 | 无关 panel | 局部重建数 |",
             "| ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    groups = {}
    for run in document["runs"]:
        key = (run["facts"], run["rules"], run["shape"], run["mode"], run["variant"])
        groups.setdefault(key, []).append(run)
    phases = ("load", "cold_panel", "warm_panel", "local_commit", "local_panel", "global_commit", "global_panel", "unrelated_commit", "unrelated_panel")
    for key, runs in groups.items():
        good = [r for r in runs if r["status"] == "ok"]
        values = [f"{statistics.median(r['phases'][p]['seconds'] for r in good)*1000:.3f}" if good else "—" for p in phases]
        rebuilt = str(statistics.median(r["local_rebuilt"] for r in good)) if good and key[3] == "cached" else "—"
        lines.append("| " + " | ".join(map(str, key)) + f" | {len(good)}/{len(runs)} | " + " | ".join(values) + f" | {rebuilt} |")
    lines += ["", "原始阶段 CPU、RSS、逐查询样本、cached 失效／重建数、驱动编译选项、源码摘要在 results.json。", "",
              "生成受控 SQL，未测全量 Logica 编译。关系级失效无法识别共享事实表中互不相关的行。load 包含完整规则验证和拓扑分析。", "",
              "失败／超时不填零，不加入成功汇总；没有清空 OS 页缓存。history_all 与运行内存记录见原始数据。"]
    for r in document["runs"]:
        if r["status"] != "ok":
            lines.append(f"- 失败：{r['facts']} {r['shape']} {r['mode']} {r['variant']}：{r.get('error')}")
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--facts", nargs="+", type=int, default=[128, 512])
    p.add_argument("--ratios", nargs="+", type=int, default=[1, 10])
    p.add_argument("--shapes", nargs="+", choices=["partitioned", "shared_table"], default=["partitioned", "shared_table"])
    p.add_argument("--modes", nargs="+", choices=["cached", "materialized", "live"], default=["cached", "materialized", "live"])
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--python", type=Path, default=Path(sys.executable))
    p.add_argument("--packages", type=Path)
    p.add_argument("--baseline-ref", default="8827c21")
    p.add_argument("--out", type=Path)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    for field in ("runtime", "bundle", "result"):
        p.add_argument("--" + field, type=Path, help=argparse.SUPPRESS)
    p.add_argument("--ratio", type=int, help=argparse.SUPPRESS)
    p.add_argument("--shape", help=argparse.SUPPRESS)
    p.add_argument("--mode", help=argparse.SUPPRESS)
    p.add_argument("--variant", help=argparse.SUPPRESS)
    p.add_argument("--repeat", type=int, help=argparse.SUPPRESS)
    p.add_argument("--condition-count", type=int, help=argparse.SUPPRESS)
    p.add_argument("--backend", choices=["sqlite", "duckdb"], default="sqlite", help=argparse.SUPPRESS)
    p.add_argument("--validate-only", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker and args.condition_count is not None:
        if len(args.facts) != 1 or args.facts[0] < 34 or args.condition_count < 32:
            p.error("condition worker requires >=34 facts and >=32 conditions")
        args.facts = args.facts[0]
        return worker(args)
    if min(args.facts) < 128 or any(n % 32 for n in args.facts) or min(args.ratios) < 1 or args.repetitions < 1:
        p.error("facts must be multiples of 32 >=128; ratios and repetitions must be positive")
    if args.worker:
        args.facts = args.facts[0]
        return worker(args)
    output = (args.out or ROOT / "benchmarks/results" / datetime.now(CLIENT_TIMEZONE).strftime("rules-%Y%m%d-%H%M%S")).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        p.error("Output directory must be empty")
    from baseline_sources import historical_runtime
    baseline = historical_runtime(args.baseline_ref)
    work = output / ".work"
    sources = {"baseline": baseline, "native": (ROOT / "renpy_relations.py").read_bytes()}
    for name, source in sources.items():
        folder = work / name
        folder.mkdir(parents=True)
        (folder / "renpy_relations.py").write_bytes(source)
    document = {"started_at": datetime.now(CLIENT_TIMEZONE).isoformat(), "baseline_ref": args.baseline_ref,
                "repetitions": args.repetitions, "facts": args.facts, "ratios": args.ratios,
                "cpu": next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                             if line.startswith("model name")), "unknown"),
                "source_sha256": {n: hashlib.sha256(s).hexdigest() for n, s in sources.items()},
                "file_sha256": {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                                for n in ("benchmarks/rules.py", "benchmarks/graph.py", "benchmarks/run.py", "uv.lock", "compile_rules.py")},
                "runs": []}
    for facts in args.facts:
        for ratio in args.ratios:
            for shape in args.shapes:
                bundle = work / f"{facts}-{ratio}-{shape}.json"
                atomic_json(bundle, dataset(facts, ratio, shape))
                for mode in args.modes:
                    for repeat in range(args.repetitions):
                        for variant in (["baseline", "native"] if repeat % 2 == 0 else ["native", "baseline"]):
                            stem = f"{facts}-{ratio}-{shape}-{mode}-{repeat}-{variant}"
                            destination = work / (stem + ".json")
                            cmd = [str(args.python), str(Path(__file__).resolve()), "--worker", "--facts", str(facts),
                                   "--ratio", str(ratio), "--shape", shape, "--mode", mode, "--repeat", str(repeat),
                                   "--variant", variant, "--runtime", str(work / variant), "--bundle", str(bundle), "--result", str(destination)]
                            if args.packages:
                                cmd += ["--packages", str(args.packages.resolve())]
                            print(stem, flush=True)
                            failure = None
                            with (work / (stem + ".log")).open("w") as log:
                                try:
                                    finished = subprocess.run(cmd, stdout=log, stderr=log, timeout=300)
                                    if finished.returncode:
                                        failure = f"Worker exited {finished.returncode}"
                                except (OSError, subprocess.TimeoutExpired) as exc:
                                    failure = str(exc)
                            run = json.loads(destination.read_text()) if destination.exists() else {
                                "facts": facts, "rules": facts * ratio, "ratio": ratio, "shape": shape,
                                "mode": mode, "variant": variant, "repeat": repeat, "status": "error", "phases": {}}
                            if failure or run["status"] != "ok":
                                run.update(status="error", error=run.get("error", failure or "No complete result"))
                            document["runs"].append(run)
                            report(output, document)
    document["finished_at"] = datetime.now(CLIENT_TIMEZONE).isoformat()
    report(output, document)
    return 0 if all(r["status"] == "ok" for r in document["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
