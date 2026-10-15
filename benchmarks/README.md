# Benchmark

测量当前实现的加载、查询、事实提交和快照成本。主负载是大量派生规则对应少量事实；大事实集与长链是独立压力测试。当前数据与测量范围见 [报告](results/current/REPORT.md)。

当前归档数据测于 `name`／`self` 字段参数冲突修复之前；该接口修复后未重新测量，测量源码以报告内 SHA-256 为准。

[结果阅读说明](READING_RESULTS.md)逐项解释各列与原始阶段的计时边界、数据规模、三种查询模式，以及这些数值能回答什么问题。

生产规则包的依赖来自 Logica 编译；条件与长链生成器同步生成已知 SQL 和依赖边，不包含 Logica 编译时间。`native` 变体读取包内依赖，由数据库计算执行顺序；历史 `baseline` 变体在加载时从 SQL 收集依赖。运行时不解析或核验 SQL 依赖；迁移说明见 [MIGRATION](../MIGRATION.md)。

## 运行

开发依赖由根目录 `uv.lock` 锁定。默认使用 uv Python；若要测游戏运行环境，先准备匹配 SDK 的独立依赖目录：

```sh
uv sync --locked --extra duckdb --group renpy-linux
uv run --locked python prepare_game.py --game examples/palace \
  --out /tmp/relations-benchmark-game --backend duckdb --sdk /path/to/renpy-sdk
uv run --locked --extra duckdb --group renpy-linux python benchmarks/suite.py \
  --profile controlled \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages /tmp/relations-benchmark-game/game/python-packages \
  --out /tmp/relations-benchmark
uv run --locked python benchmarks/report.py /tmp/relations-benchmark
```

输出目录不得覆盖已有结果。任务串行运行，保留自动 GC；不要同时运行其他重负载。SDK 的后端测试直接调用其 Python，不启动游戏窗口。

`controlled` 是受控完整报告：SQLite 覆盖主矩阵，DuckDB 覆盖代表配置与加载上限。`full` 扩展 DuckDB 到全部条件及大事实矩阵，可能需要数小时。`--smoke` 用小数据检查整套流程，不产生规模结论。实际执行范围、失败、超时和未测配置都由报告列明。任务失败或达到预算时套件返回非零；仍可用 `report.py` 汇总已保存的数据，并生成报告和原始数据的 `SHA256SUMS`。

## 四类负载

### 派生条件

`conditions.py` 每轮实际读取 1,000／3,000／10,000 个不同条件，另有 64 个共享前置关系。事实数:总派生关系数为 1:1 或约 1:10。条件包含共享前提、否定、领域状态、全局开关和混合真假结果。

两种布局分别使用领域分表和共用状态表，以观察关系级失效的范围。每个配置测加载、首轮、重复轮，以及局部／全局／无关事实修改后的“提交＋完整读取”。三种模式均覆盖，各做三次独立进程重复。

受控范围：

| 后端 | 规模与布局 | 计时进程 | 独立集合校验 |
| --- | --- | ---: | ---: |
| SQLite | 3 档 × 2 比例 × 2 布局 × 3 模式 | 108 | 36 |
| DuckDB | 1,000 条件、约 1:10、领域分表、3 模式 | 9 | 3 |
| DuckDB 加载探针 | 3,000／10,000 条件、约 1:10、领域分表、cached | 各一次，上限 120 秒 | 不代替主矩阵 |

每个计时请求都与独立公式核对。全部行集合另在独立进程核对初始、局部、全局、无关和阻断五种状态，不提前预热计时实例。生成 SQL 控制负载形态，未测大规则集的 Logica 编译成本。

主矩阵**未绑定历史接收者**，提交不生成快照。Ren’Py 历史绑定的成本由快照负载单独测量；不能将两类提交混为同一口径。

单独运行 SQLite 主矩阵：

```sh
uv run --locked python benchmarks/conditions.py --backends sqlite --out /tmp/conditions-sqlite
```

### 大事实集

`run.py` 使用 palace 的实际编译规则，生成 1 万／10 万／100 万角色。测公开接口导入、恢复后的首次查询、分散角色的 warm has／query、单条与 batch 提交、显式快照、恢复和规则重载。每档导入一次，每模式三次独立重复。

受控范围包含 SQLite 全部三档及 DuckDB 一万角色。百万档是压力测试，不代表典型视觉小说的事实规模。

measure 进程的 `snapshot` 阶段在恢复后读取已缓存镜像，测的是复用，不是完整导出；首次生成由 seed 的显式快照及独立快照负载测量。

事实数与派生行数由生成公式给出。小规模测试核对完整集合，大规模使用分散正负样本核对。导入使用公开 add 与一个 batch，不能当作原生批量导入成绩；导入与普通提交均无历史接收者，快照单独计时。

### 快照与历史提交

`snapshots.py` 在 1 万／10 万／100 万事实下分别测普通提交、历史绑定提交、首次快照、镜像复用与恢复。SDK 使用 pysqlite3 backup 路径和 DuckDB 复制路径；标准 Python 可另选 sqlite3 serialize 路径。

初始化使用原生 SQL，排除计时；实际修改使用公开接口。受控配置每种驱动、规模各三个独立进程，每进程一次顺序测量。历史回调只接收最新镜像，不模拟 Ren’Py 长期回滚历史、存档压缩或界面成本。

### 依赖长链

`graph.py` 对 128／512／1,050 层依赖测加载和首次读取，检查事实撤销后的结果。两后端分别执行，每档一次，进程上限 120 秒。单次探针用于暴露闭包与结构成本，不能当作重复测量的中位数或一般剧情表现。

## 统计与复现身份

- 墙钟时间包含实际接口调用与测量记录开销；阶段 CPU、RSS 和峰值 RSS 保存在 JSON 中。
- 条件负载的整轮时间直接测量。“提交＋读取”先在同一试验内相加，再跨试验取中位数。
- 条件单次中位数／p95 先在每个试验内计算，再取跨试验中位数；不是合并请求分位数。大事实 warm 请求保留逐请求样本，子报告明确其聚合方式。
- 新进程隔离 Python 与数据库状态，但不清空操作系统页缓存，不能称为物理冷启动。
- 失败和超时保留阶段与错误，不填零，不进入成功样本统计。未测组合单独列出，不算通过。
- 源码与锁文件 SHA-256、实际解释器、驱动、硬件、参数和输出记录共同定义测量身份；文档提交不改变既有测量的身份。

只保留一组当前报告与必要原始数据。大型镜像、临时运行时副本和逐 worker 日志位于 `.work`，不提交。旧测量记录可从 Git 历史取得。

`baselines/` 中的历史源码带原提交和 SHA-256，是可选对照输入，不是当前运行时。显式 `conditions.py --variants baseline native --backends sqlite` 或 `snapshots.py --baseline-ref 45d0c21` 才运行旧版；当前报告默认只测当前实现。
