#!/usr/bin/env python3
"""Render the existing suite and child JSON as a concise, data-backed report.

This script reads measurements; it never imports or executes benchmark workers.
Usage: python benchmarks/report.py OUTPUT_DIRECTORY
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def read_json(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def number(value, scale=1, digits=3):
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value * scale:,.{digits}f}"


def median(values):
    values = list(values)
    return statistics.median(values) if values else None


def phase(row, name):
    return row.get("phases", {}).get(name, {}).get("seconds")


def grouped(rows, fields):
    result = {}
    for row in rows:
        result.setdefault(tuple(row.get(field) for field in fields), []).append(row)
    return result


def successful_group(rows, expected):
    good = [row for row in rows if row.get("status") == "ok"]
    repeats = [row.get("repeat", row.get("process_repeat")) for row in good]
    complete = len(rows) == expected == len(good) and len(set(repeats)) == len(repeats)
    return good if complete else [], f"{len(good)}/{expected}" + (" 完成" if complete else " 不完整")


def mean_phase(rows, name):
    values = [phase(row, name) for row in rows]
    return median(values) if values and all(value is not None for value in values) else None


def action(rows, prefix):
    values = [(phase(row, prefix + "_commit"), phase(row, prefix + "_panel")) for row in rows]
    return median(a + b for a, b in values) if values and all(a is not None and b is not None for a, b in values) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    suite = read_json(root / "results.json")
    if not suite:
        parser.error("The suite results.json is required")
    tasks = suite.get("runs", [])
    documents = {task["name"]: read_json(root / task["name"] / "results.json") for task in tasks}
    all_rows = [row for doc in documents.values() for row in doc.get("runs", []) + doc.get("validations", [])]
    host = suite.get("host", {})
    source = suite.get("measured_source", suite.get("source", {}))
    hashes = source.get("sha256", {})
    lines = ["# 当前实现的 Benchmark", "",
             f"测量配置为 `{cell(suite.get('profile', 'unknown'))}`。本报告汇总已保存的实际结果，全部数值取自各子任务 JSON；测量方法见 [Benchmark 说明](../../README.md)。", "",
             "实验分别观察大量派生条件、事实规模、原生快照与依赖长链。条件负载为主要工作负载；大事实集和长链用于观察边界。后端调用测量不等同于游戏帧率、完整存读档或长期回退历史。", ""]
    if suite.get("smoke"):
        lines += ["**本次为 smoke 检查，缩小数据仅验证工具流程，不支持规模或性能结论。**", ""]
    completed = {task["name"] for task in tasks if task.get("status") == "completed"}
    if not suite.get("smoke") and {"conditions-sqlite", "conditions-duckdb", "snapshots"} <= completed:
        lines += ["## 本次观察", "",
                  "- 关系级失效的收益取决于事实布局。共享状态表会扩大重建范围；减少重建也不消除逐条件查询成本。",
                  "- 生产规则的依赖由 Logica 编译时提供，条件生成器同步生成已知依赖。运行时不从 SQL 收集依赖；数据库根据包内边计算执行顺序，其成本仍取决于图的规模与结构。",
                  "- 普通事务与历史保存的代价需要分开判断。Ren’Py 行动仍承担完整事实镜像的发布成本。", ""]
    lines += ["## 环境与测量身份", "",
              f"CPU：{cell(host.get('cpu', '未记录'))}；逻辑 CPU：{cell(host.get('logical_cpus', '未记录'))}。平台：{cell(host.get('platform', '未记录'))}。", ""]
    environments = set()
    for doc in documents.values():
        records = doc.get("runs", [doc]) + doc.get("validations", [])
        for row in records:
            runtime = row.get("runtime", {})
            backend = row.get("backend", runtime.get("backend"))
            python = runtime.get("python", row.get("python", ""))
            sqlalchemy = runtime.get("sqlalchemy", row.get("sqlalchemy"))
            driver = row.get("driver", runtime.get("driver")) if backend == "sqlite" else "duckdb"
            database = runtime.get("sqlite") if backend == "sqlite" else runtime.get("duckdb")
            database = database or row.get("database_version")
            if python and backend:
                environments.add((backend, str(python).split()[0], str(driver), str(database), str(sqlalchemy)))
    lines += ["| 后端 | 实际 Python | 驱动 | 数据库版本 | SQLAlchemy |", "| --- | --- | --- | --- | --- |"]
    for values in sorted(environments):
        lines.append("| " + " | ".join(map(cell, values)) + " |")
    lines += ["", "解释器完整版本、安装目录、精确命令和驱动选项保存在 [原始清单](results.json) 及各子结果中。任务串行执行，保留自动 GC；没有清空操作系统页缓存。", ""]
    commits = source.get("git_commits", []) or ([source["git_commit"]] if source.get("git_commit") else [])
    if commits:
        lines += ["测量记录关联的基础提交（工作树工具变更以记录的 SHA-256 为准）：" + "、".join(f"`{cell(commit)}`" for commit in commits) + "。", ""]
    lines += ["| 测量输入 | SHA-256 |", "| --- | --- |"]
    for name in ("relation_rules/runtime.py", "renpy_relations.py", "uv.lock"):
        if name == "relation_rules/runtime.py" and name not in hashes:
            continue
        lines.append(f"| `{name}` | `{cell(hashes.get(name, '未记录'))}` |")
    renderer_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    lines.append(f"| `benchmarks/report.py`（报告呈现，未参与计时） | `{renderer_hash}` |")
    lines += ["", "完整工具哈希及每个任务的 `measured_source` 见原始清单；`report_generation_source` 只描述生成报告时的文件，不替换已测源码身份。", ""]
    if source.get("conflicts"):
        lines += ["**测量身份存在差异，不能将全部任务视为同一源码版本。** 差异文件：" + "、".join(f"`{cell(name)}`" for name in sorted(source["conflicts"])) + "；各任务自身的来源记录为准。", ""]
    if source.get("unknown_tasks"):
        lines += ["来源身份未完整记录的任务：" + "、".join(map(cell, source["unknown_tasks"])) + "。", ""]

    lines += ["## 实际覆盖与状态", "",
              "`completed` 表示任务内预期测量与校验均完成；`budget_limited` 表示达到时限，不能计作通过。以下成功数来自实际子结果；不完整配置不进入本报告的数值汇总。", "",
              "| 任务 | 状态 | 成功／预期测量记录 | 成功／预期集合校验 | 墙钟秒 | 数据 |",
              "| --- | --- | ---: | ---: | ---: | --- |"]
    for task in tasks:
        name = task["name"]
        doc = documents[name]
        expected = task.get("expected", {})
        rows = doc.get("runs", [doc] if doc else [])
        validations = doc.get("validations", [])
        count = sum(row.get("status") == "ok" for row in rows)
        total = expected.get("runs", 1 if task.get("probe") else len(rows))
        checked = sum(row.get("status") == "ok" for row in validations)
        check_total = expected.get("validations", len(validations))
        links = [f"[JSON]({name}/results.json)"]
        if (root / name / "REPORT.md").is_file():
            links.insert(0, f"[报告]({name}/REPORT.md)")
        lines.append(f"| {cell(name)} | `{cell(task.get('status', 'unknown'))}` | {count}/{total} | {checked}/{check_total} | {number(task.get('seconds'))} | {' · '.join(links)} |")
    for name, doc in documents.items():
        if isinstance(doc.get("conditions"), list):
            lines += ["", f"`{name}`：每轮读取 " + "／".join(f"{count:,}" for count in doc["conditions"]) + " 个不同条件；事实:总派生关系配比 " + "／".join("1:1" if ratio == 1 else "约 1:10" for ratio in doc.get("ratios", [])) + "；布局 " + "／".join({"partitioned": "领域分表", "shared_table": "通用状态表"}.get(shape, shape) for shape in doc.get("shapes", [])) + "；模式 " + "／".join(doc.get("modes", [])) + f"；各配置 {doc.get('repetitions')} 次独立重复。"]
    lines += [""]

    lines += ["## 派生条件", "",
              "下表展示 SQLite 的 cached 模式、约 1:10 配比、两种事实布局，以及 DuckDB 已测的代表配置。时间单位为 **毫秒**；首轮、warm 轮和动作按整轮计，加载按实例计。一次整轮读取每个不同条件一次。“动作”先在同一试验中相加提交与随后读取，再跨独立进程取中位数。", "",
              "| 后端 | 条件／事实 | 布局 | 模式 | 重复 | 加载 | 首轮 | warm 轮 | 局部动作 | 全局动作 | 无关动作 |",
              "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    condition_groups = []
    for name, doc in documents.items():
        if not isinstance(doc.get("conditions"), list):
            continue
        groups = grouped(doc.get("runs", []), ("backend", "conditions", "ratio", "shape", "mode", "variant"))
        validation_groups = grouped(doc.get("validations", []), ("backend", "conditions", "ratio", "shape", "mode", "variant"))
        for key, rows in groups.items():
            backend, count, ratio, shape, mode, variant = key
            if variant != "native":
                continue
            good, status = successful_group(rows, doc.get("repetitions", 0))
            validations = validation_groups.get(key, [])
            if len(validations) != 1 or validations[0].get("status") != "ok":
                good, status = [], status + "；集合校验不完整"
            condition_groups.append((key, good, status))
            if ratio != 10 or (backend == "sqlite" and mode != "cached"):
                continue
            facts = rows[0].get("facts", "?")
            values = [mean_phase(good, phase_name) for phase_name in ("load", "cold_panel", "warm_panel")]
            values += [action(good, prefix) for prefix in ("local", "global", "unrelated")]
            lines.append(f"| {cell(backend)} | {count:,}/{facts:,} | {cell(shape)} | {cell(mode)} | {cell(status)} | " + " | ".join(number(value, 1000) for value in values) + " |")
    lines += ["", "条件主矩阵没有绑定历史接收者，普通提交不生成镜像。每次计时读取核对真假；另用独立进程核对初始、局部修改、全局修改、无关修改与阻断五种状态的完整行集合。全部模式和配比详见子报告。", ""]
    sqlite_counts = sorted({key[1] for key, good, status in condition_groups if key[0] == "sqlite" and key[2] == 1 and key[4] == "cached" and good})
    if sqlite_counts:
        largest = sqlite_counts[-1]
        pairs = {key[3]: good for key, good, status in condition_groups if key[0] == "sqlite" and key[1] == largest and key[2] == 1 and key[4] == "cached" and good}
        if "partitioned" in pairs and "shared_table" in pairs:
            rebuilds = {shape: {row.get("local_rebuilt") for row in rows} for shape, rows in pairs.items()}
            if all(len(values) == 1 and None not in values for values in rebuilds.values()):
                partitioned = next(iter(rebuilds["partitioned"]))
                shared = next(iter(rebuilds["shared_table"]))
                lines += [f"在 SQLite、{largest:,} 条件、1:1 配比、cached 的完整重复中，局部修改后领域分表重建 **{partitioned:,}** 个关系，共用状态表重建 **{shared:,}** 个关系。这是关系级失效对 schema 布局的差异；不能据重建数量直接推断延迟倍数。", ""]

    lines += ["## 大事实集压力", "",
              "以下为 cached 模式。时间单位为 **毫秒**；warm has／query 合并该配置完整成功进程的逐请求样本取中位数，其余时间先每进程测量再取跨进程中位数。峰值 RSS 取这些进程的最大值。", "",
              "| 后端 | 角色 | 重复 | warm has | warm query | 单条普通提交 | 复用镜像 | 修改后恢复 | 峰值 RSS MiB |",
              "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, doc in documents.items():
        if doc.get("format") != "renpy-relations-benchmark":
            continue
        groups = grouped([row for row in doc.get("runs", []) if row.get("kind") == "measure" and row.get("mode") == "cached"], ("backend", "size"))
        for (backend, size), rows in sorted(groups.items()):
            good, status = successful_group(rows, doc.get("parameters", {}).get("repetitions", 0))
            warm = []
            for phase_name in ("warm_has", "warm_query"):
                warm.append(median(sample for row in good for sample in row.get("phases", {}).get(phase_name, {}).get("samples_seconds", [])))
            values = warm + [mean_phase(good, phase_name) for phase_name in ("single_commit", "snapshot", "restore_after_edits")]
            peak = max((row.get("peak_rss_bytes", 0) for row in good), default=None)
            lines.append(f"| {cell(backend)} | {size:,} | {cell(status)} | " + " | ".join(number(value, 1000) for value in values) + f" | {number(peak, 1 / 2**20, 1)} |")
    lines += ["", "此负载未绑定历史接收者，提交时间不含历史镜像发布。恢复后的 `snapshot` 复用已缓存输入，**不是完整镜像生成时间**；首次生成见 seed 原始阶段及下节。RSS 为整个进程高水位，包含读取、验证和候选世界，不能当作单次查询内存。角色数、事实数及派生行数分别列在子报告；百万角色属于压力测试。", ""]

    lines += ["## 原生快照与历史提交", "",
              "按配置汇总独立进程：每进程先对自己的顺序样本取中位数，再取跨进程中位数。时间单位为 **毫秒**，镜像大小单位为 **MiB**。没有把失败或缺失样本补零。", "",
              "| 驱动 | 初始事实 | 独立重复 | 普通提交 | 历史提交 | 首次镜像 | 复用镜像 | 恢复 | 镜像 MiB |",
              "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, doc in documents.items():
        if "process_repetitions" not in doc.get("parameters", {}):
            continue
        groups = grouped(doc["runs"], ("driver", "size", "legacy"))
        for (driver, size, legacy), rows in sorted(groups.items()):
            good, status = successful_group(rows, doc["parameters"]["process_repetitions"])
            values = []
            for key in ("plain_commit", "history_commit", "snapshot", "snapshot_reused", "restore", "snapshot_bytes"):
                per_process = [median(sample[key] for sample in row.get("samples", []) if key in sample) for row in good]
                values.append(median(per_process) if per_process and all(value is not None for value in per_process) else None)
            label = str(driver) + ("（历史对照）" if legacy else "")
            lines.append(f"| {cell(label)} | {size:,} | {cell(status)} | " + " | ".join(number(value, 1000) for value in values[:-1]) + f" | {number(values[-1], 1 / 2**20)} |")
    lines += ["", "初始化使用原生 SQL 且不计时；实际修改使用公开接口。普通与历史提交在不同数据库实例上测量，历史回调接收完整镜像。该回调不保留长期回退历史，也不包含 Ren’Py 存档归档或 UI 成本。驱动路径见方法说明，不能把不同后端的结果视为只更换同一种序列化器。", ""]

    lines += ["## 依赖长链与加载上限", "",
              "以下为单次探针，不能当作重复测量中位数。超时只说明在本机和给定预算下未完成该阶段，不给出通过结论或精确完成时间。", "",
              "| 探针 | 后端 | 规模 | 状态 | 时限秒 | 加载毫秒 | 首次读取毫秒 | 中止阶段／错误 |",
              "| --- | --- | ---: | --- | ---: | ---: | ---: | --- |"]
    for task in tasks:
        name = task["name"]
        doc = documents[name]
        is_graph = name == "graph" or ("backends" in doc and "runtime_sha256" in doc and "conditions" not in doc)
        if not is_graph and not task.get("probe"):
            continue
        rows = doc.get("runs", [doc] if doc else [{}])
        for row in rows:
            state = row.get("status", task.get("status", "missing"))
            budget = task.get("timeout") or doc.get("timeout")
            if state == "ok":
                detail = "完成"
            else:
                detail = row.get("current_phase", "未记录阶段")
                error = row.get("error") or task.get("error")
                if task.get("status") == "budget_limited":
                    error = "达到进程时间预算；详细命令与异常见 JSON"
                if error:
                    detail += "；" + str(error)[:240] + ("…详见 JSON" if len(str(error)) > 240 else "")
            load = row.get("load_seconds", phase(row, "load"))
            first = row.get("first_read_seconds", phase(row, "first_has"))
            lines.append(f"| {cell(name)} | {cell(row.get('backend', '未记录'))} | {cell(row.get('length', row.get('conditions', '未记录')))} | `{cell(state)}` / `{cell(task.get('status', 'unknown'))}` | {number(budget, digits=0)} | {number(load, 1000)} | {number(first, 1000)} | {cell(detail)} |")
    lines += ["", "长链同时检查修改后的失效结果。达到时限的进程已由启动器停止；原始阶段状态 running 是最后检查点，不表示仍在运行。探针使用生成器提供的 SQL 与依赖；“加载”包含规则包构造、数据库初始化和原生图排序，不含 Logica 编译。较大条件探针只覆盖加载、导入与一次指定读取，不能代替全部条件的读取矩阵。", "",
              "## 结论的范围", "",
              "本报告展示已测配置的加载、整轮查询、事务与镜像成本。模式、事实布局、共享依赖、结果行数和驱动路径都可能改变这些成本；单一配置不构成数据库选择或游戏帧率保证。", "",
              "未测范围：", ""]
    unmeasured = suite.get("unmeasured", [])
    for item in unmeasured:
        lines.append("- " + cell(item))
    if not unmeasured:
        lines.append("- 原始清单未记录额外范围；这不等同于所有负载均已验证。")
    lines += ["", "完整组别、阶段 CPU／RSS、逐请求统计口径、校验结果与失败记录见各子报告及 JSON。根报告仅选取关键数值，失败和不完整配置均不作为成功总体。", "",
              "报告与原始数据的文件校验见 [SHA256SUMS](SHA256SUMS)。", ""]
    (root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    files = sorted(path for path in root.rglob("*")
                   if path.is_file() and path.suffix in (".md", ".json", ".csv")
                   and ".work" not in path.relative_to(root).parts
                   and not path.name.endswith(".running.json"))
    (root / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n"
        for path in files), encoding="utf-8")


if __name__ == "__main__":
    main()
