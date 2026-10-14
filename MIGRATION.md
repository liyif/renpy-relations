# 构建期规则计划（plan）迁移

本文记录把「规则 SQL 分析」从运行时移到构建期的迁移方案与执行状态。背景与动机见
[DESIGN.md](DESIGN.md) 的「构建与运行的分界」；测量口径见 [benchmarks/README.md](benchmarks/README.md)。

## 目标

1. 运行时零 SQL 分析：`renpy_relations.py` 只执行已密封的 `plan`，不再解析或反射规则 SQL。
2. 保持构建/运行边界：`rule_compiler.py` 只在构建期导入；随游戏分发的仍只有 `renpy_relations.py`。
3. 所有生产者都产出 `plan`：示例、基准生成物与测试夹具统一走构建期编译。
4. 可复现身份更新：`rule_compiler.py` 纳入基准的哈希集，旧报告标记失效。

## 规则包结构

构建期编译在原有字段上追加：

- `dependencies`：每个派生关系实际读取的关系（含否定、聚合、子查询与空表）。
- `plan`：`{"version": 1, "order": [...], "fingerprint": "<sha256>"}`。
  - `order` 是全部派生关系的拓扑序。
  - `fingerprint` 绑定 `content_id`、`dependencies` 与 `order`，防止手改 SQL 后复用旧计划。

运行时 `RuleSet` 会校验计划字段、拓扑序与指纹；缺少 `plan` 的规则包在加载时被拒绝，
并提示使用 `compile_rules.py` 或 `rule_compiler.prepare_rules()`。

## 入口

- `rule_compiler.compile_document(document) -> dict`：返回带 `dependencies` 与 `plan` 的纯字典。
- `rule_compiler.prepare_rules(document) -> RuleSet`：编译并返回可加载的密封规则集。
- `compile_rules.py` 使用 `prepare_rules`，行为与产物不变（只是产物多出 `plan`）。

## 执行状态

- [x] 修正 `rule_compiler.py` 未导入 `_VOLATILE_FUNCTIONS`（`_sqlite_reads` 会 `NameError`）。
- [x] `rule_compiler.py` 纳入版本控制（此前未跟踪，`git archive`/CI 取不到）。
- [x] `_duckdb_reads` 的错误判定改为只认显式 `$.error IS TRUE`。
- [x] `schema()` 不再隐式做完整性检查；恢复后显式 `check()`。
- [x] 验证 DuckDB `COPY FROM DATABASE` 不复制 TEMP 派生表（镜像只含事实与元数据）。
- [x] 示例规则包重新编译，补上 `plan`。
- [x] 测试夹具统一走 `prepare_rules`；SQL 校验类断言前移到构建期。
- [x] 基准工具生成/加载编译后的规则包（baseline 变体保留未编译包）。
- [x] `rule_compiler.py` 加入基准哈希集与文档说明。
- [x] 完整重跑 `controlled` 基准并替换 `benchmarks/results/current/`。运行时 DuckDB 1000 条件加载由约 83.8s 降到约 0.55s，3000/10000 条件加载探针由预算超时变为完成。本次重跑使用开发 venv（Python 3.12.13），与 0.1.0 报告的 SDK 解释器不同，环境以报告记录为准。

## baseline 兼容

历史实现（`benchmarks/baselines/8827c21`、`45d0c21`）的 `RuleSet` 不认识 `plan`/`backend` 字段。
基准中的 `baseline` 变体因此继续使用未编译的规则包；`native` 变体使用编译后的包。
