# 规则依赖：从运行时解析到 Logica 编译输出

说明规则包构建与运行时依赖处理。架构见 [DESIGN.md](DESIGN.md) 的「构建与运行的分界」。

## 结论

规则依赖是 **Logica 编译的产物**，不是运行时分析的结果。项目只保留两个生产文件：
`compile_rules.py`（构建期）与 `renpy_relations.py`（运行时）；没有独立的 SQL 分析模块。

## 数据流

- `compile_rules.py` 用 Logica 编译每条导出，读取 `program.execution.data_dependency_edges`
  （导出读到的表；其它导出保留为外部表，内部辅助谓词已展开），按大小写不敏感的名称映射到
  已声明关系后写入规则包的 `dependencies`。未声明的关系拒绝编译，不能静默丢弃。
- 构建期在空数据世界中验证输出列、引用、类型投影和循环依赖；失败保留最后正常产物。
- `renpy_relations.py` 只读取 `dependencies`：加载时由数据库原生计算执行顺序，按边传播缓存失效。
  它不解析 SQL、不检查函数或列、不做指纹。缺少 `dependencies` 的规则包在加载时被拒绝。

## 为什么不解析 SQL

- 依赖是编译器已知的信息，无需在运行时从生成的 SQL 重新收集。
- 单一来源：`compile_rules.py` 是依赖的唯一作者，运行时不再维护第二套机制。
- 运行时不依赖数据库目录反射或 SQL 文本解析，也不使用 Python 遍历依赖图。

## 迁移现有项目

旧规则包若包含 `plan` 或缺少 `dependencies`，请按 [USAGE](USAGE.md) 的编译步骤重新生成
两后端产物，并与新运行时一起更新。不要手工删字段或补写依赖。

`LogicDB` 的游戏接口和原生快照格式没有变化；同一后端、相同事实 schema 的快照仍可恢复。
直接构造规则包的开发工具需同步提供完整的 `dependencies`，执行顺序由运行时数据库计算。

## 基准

运行时加载仍需建立关系与依赖图，其成本随图规模和结构变化；省去的是从 SQL 重新收集依赖的
成本。历史 `baseline` 变体仍在加载时自行分析依赖，用于对照；`native` 变体直接读取包内依赖。
当前测量源码身份、环境与覆盖范围见 [Benchmark 报告](benchmarks/results/current/REPORT.md)。
