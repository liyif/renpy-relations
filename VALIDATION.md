# 验证记录

日期：2026-10-13（Asia/Singapore）。

## 环境

- uv 0.11.18；开发 Python 3.12.13；标准库 SQLite 3.50.4。
- SQLAlchemy 2.0.43；Logica 1.3.1415926535897；pytest 9.1.1，版本由 uv.lock 锁定。
- 官方 Ren’Py 8.5.3.26051504 Linux x86_64 SDK，内置 Python 3.12.8。
- SDK 运行依赖由 uv 从锁文件导出并按 Python 3.12／Linux ABI 安装；使用 pysqlite3-binary 0.5.4.post2（SQLite 3.51.1）。
- 真实引擎测试在 xvfb-run、X11、Mesa 软件渲染和 dummy 音频环境运行，存档使用独立临时目录。

## 后端与构建

在项目目录执行：

```sh
uv run --locked python -m pytest
uv run --locked python -m py_compile renpy_relations.py compile_rules.py check_renpy.py
```

结果：**68 项通过**（48 项后端／接入约定、8 项真实 Logica 编译与构建、4 项测试启动器检查、8 项基准检查）。原有三个模块的 Python 编译检查通过。

覆盖事实去重与主键冲突、三种执行模式、导出关系的依赖缓存、SQL 过滤语义、输出类型／NULL、事务失败、快照拒绝与恢复、异常数值快照、正确／错误热重载、schema 不兼容、编译失败保留旧产物、编辑途中不发布混合产物、构建观察、自动重载错误去重与开发模式开关，以及测试进程的成功／失败／超时／带颜色报告。

真实 Logica 编译产物已生成并提交到 `examples/palace/game/relations.rules.json`。构建阶段保留导出关系依赖：CanClaimReward → CanInvestigate → CanEnter。

## 真实 Ren’Py 引擎

```sh
/path/to/renpy-sdk/renpy.sh examples/palace lint
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode cached
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode live
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode materialized
```

Lint 通过，无脚本错误；SDK 仍输出常规的属性冲突检查建议。

| 模式 | 场景 | 钩子 | 断言 | 最终状态 |
| --- | --- | --- | --- | --- |
| cached | 7／7 | 15／15 | 43／43 | PASSED |
| live | 7／7 | 15／15 | 43／43 | PASSED |
| materialized | 7／7 | 15／15 | 43／43 | PASSED |

七个场景：

1. 阵营／担保／知识条件组合、事实撤销与一次性奖励。
2. 真实 Ren’Py 存档与读档，事实和派生关系同时恢复。
3. 真实 Ren’Py 回滚，撤销选择产生的事实。
4. 返回主菜单并开始新游戏，清除上次游戏状态。
5. 手动热重载保留事实，替换派生规则，再恢复原规则。
6. F8 关系检查屏幕可以实际打开、渲染和关闭。
7. 自动观察规则产物：有效修改生效；无效 JSON 保留旧规则；修复后再次生效。

测试使用真实 SDK 和实际编译 SQL，没有用模拟 Ren’Py 回调代替引擎验证。SDK 源码没有修改。本次 SDK 的测试结束阶段会在输出完整报告后继续循环并占用 CPU；`check_renpy.py` 收到最终 Status 后清理隔离进程组。启动器成功返回，最终未遗留 Ren’Py 测试进程。

## Standards

独立代码审查未发现硬性仓库标准违规或需要处理的结构性 smell。审查发现的快照恢复原子性问题已经修复：候选世界完成规范快照生成后才交换；复核和异常数值回归检查通过。

## Spec

设计符合性审查确认规则编译、关系级惰性物化、原子重载、事实快照及 uv 管理有实现与验证。复核发现的带颜色测试报告识别问题已修复，新增检查通过。真实引擎测试另外发现并修复了检查屏幕文本转义和 Python 模块中的 Ren’Py 日志命名空间问题。

基准脚本新增的独立 Standards／Spec 审查发现两类问题：中断后的旧结果可能被复用、子进程启动失败未写失败报告。现已在启动前清理目标记录、拒绝非空输出目录，并将启动异常记录为失败；新增回归检查和两轴复核通过。

当前未处理的审查发现：Standards 0，Spec 0。

## 大数据基准

```sh
uv run --locked python benchmarks/run.py \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages examples/palace/game/python-packages \
  --out benchmarks/results/2026-10-13-sdk-baseline
uv run --locked python -m py_compile benchmarks/run.py
```

在上述 SDK 环境中，10,000／100,000／1,000,000 角色、三模式、三次重复的 **27 次模式测试及 3 次公开导入全部成功**。每种条件 36 个 warm has／query 样本；最大档 1,524,372 条事实，预期 CanEnter 4,100,000 行。

原始 JSON 与 CSV 的 387 个阶段逐项对应；所有条件的成功次数、逐请求样本数、同规模 fixture 摘要一致，四份被测源码／锁文件 SHA256 与运行后的文件一致。基准 Python 编译检查通过。运行时与 `c583618` 相同，本轮未改后端。

[完整报告](benchmarks/results/2026-10-13-sdk-baseline/REPORT.md)与[实测解读](benchmarks/README.md)已保存。此次测量直接调用 SDK Python 中的后端；完整 Ren’Py 引擎测试结果仍为前述三模式各 7 个场景，本轮没有将百万事实灌入界面或回滚历史。

## 多规则与依赖失效补充

本轮 Python 检查 **78 项通过**：在原 68 项上增加 5 项依赖图／元数据／长链检查和 5 项多规则基准检查。示例重新编译，产物附带事实／派生直接依赖；手工热重载用例同时更新 SQL 和依赖清单。真实引擎三模式重新各通过 7 场景、15 钩子、43 断言。

SDK 运行时中，128／512 事实、1:1／1:10、两布局、三模式、新旧版本各三次重复共 **144 次全部成功**。逐规则完整行集合由独立公式核对；长链 128／512／1050 单次探针均通过。另有四次保留自动 GC 的单次诊断，原始记录独立保存，不加入主试验中位数。详见[测量解读](benchmarks/MANY_RULES.md)。

Standards／Spec 复核所发现的导出整包复制、集合验证、长链测量缺口已修复，当前未解决发现两轴均为 0。依赖图算法由 SQLite 执行，没有新增依赖包。

## 千至万条件读取补充

本轮 Python 检查 **85 项通过**，增加三档精确条件数、实际SQL结果的语义见证、两布局初始及修改后完整结果检查，以及完整轮次实际请求数与分位数检查。计时负载每轮实际读取1000／3000／10000个不同派生条件，另有64个共享前置关系；完整行集合校验在独立检查中进行。

运行时、编译器、Ren’Py接入与uv锁文件均保持9aa06a9版本，本轮只扩展基准，没有再次运行界面场景测试。协议见[CONDITIONS_DESIGN.md](benchmarks/CONDITIONS_DESIGN.md)，实测记录与口径见[CONDITIONS.md](benchmarks/CONDITIONS.md)。

SDK正式矩阵于2026-10-13 23:30至2026-10-14 00:18（Asia/Singapore）完成：72种配置各三次重复，**216次全部成功**；1080个计时轮次共核对**5,040,000次条件读取**。每种配置成功次数、各轮请求数和分位数顺序、事实／总派生关系比例、cached的局部／全局／无关修改重建计数均核对通过。12种输入在两版后端间摘要一致，运行时和所有被测脚本／锁文件摘要与记录一致；Python编译检查通过。

Standards／Spec复核所指出的周期重复表达式和修改后完整集合检查缺口均已修复，未解决发现两轴均为0。

## 尚未验证（当前范围）

Windows、macOS、Android、iOS、Web 发行与打包；大规则集的性能；完整 Logica 功能覆盖；大数据下完整 Ren’Py 界面、回滚历史与存档归档成本。上述范围没有兼容性或性能结论。第一版不包含存档迁移、增量维护和自定义规则执行器。


## 2026-10-14：可选 DuckDB 与原生快照

本节为最新结果；上文保留 2026-10-13 历史实现的验证记录。运行依赖仍为 SQLAlchemy 2.0.43，新增可选 DuckDB 1.5.6／duckdb-engine 0.17.0，由 uv.lock 锁定。开发 Python 3.12.13；真实 SDK 为 Ren’Py 8.5.3／Python 3.12.8，Linux x86_64。

```sh
uv run --locked --extra duckdb --group renpy-linux pytest -q
uv run --locked --extra duckdb python -m py_compile renpy_relations.py compile_rules.py check_renpy.py benchmarks/snapshots.py
/path/to/renpy-sdk/renpy.sh examples/palace lint
```

最终 **132 项通过**，Python 编译与 Ren’Py lint 通过。测试包括两后端的真实 Logica 编译、引擎标识匹配、三模式、事务撤销、重复事实与数值主键冲突、64 位整数／实数精度、选择性失效和否定、原生镜像／pysqlite3 备份回退、损坏镜像拒绝、发布及备份失败恢复、旧快照按新规则解释、声明重排兼容、Ren’Py 接入约定，以及基准启动失败／超时记录。未绑定与空操作提交不生成镜像；未变事实重复 snapshot 复用同一字节串。

SDK 依赖经 uv 导出，额外包含 --extra duckdb，并按 Python 3.12／Linux ABI 安装到示例的实际 python-packages 目录。DuckDB 顶层原生扩展通过显式实际目录搜索路径加载，不修改 SDK。

对 SQLite／DuckDB 各运行 cached、live、materialized：

```sh
uv run --locked --extra duckdb python check_renpy.py \
  --sdk /path/to/renpy-sdk --headless --backend duckdb --mode cached
```

| 后端 | 模式 | 场景 | 钩子 | 断言 | 状态 |
| --- | --- | --- | --- | --- | --- |
| SQLite | cached | 7/7 | 15/15 | 43/43 | PASSED |
| SQLite | live | 7/7 | 15/15 | 43/43 | PASSED |
| SQLite | materialized | 7/7 | 15/15 | 43/43 | PASSED |
| DuckDB | cached | 7/7 | 15/15 | 43/43 | PASSED |
| DuckDB | live | 7/7 | 15/15 | 43/43 | PASSED |
| DuckDB | materialized | 7/7 | 15/15 | 43/43 | PASSED |

包含真实存读档、回滚、新游戏、手动／自动热重载与检查屏幕。SQLite 实际运行 pysqlite3 的原生 backup 回退，DuckDB 实际运行原生数据库复制。进程均由启动器清理。

快照对照使用开发 Python，分别测标准 sqlite3、pysqlite3 和 DuckDB；pysqlite3 是 SDK 相同驱动，但性能数据不冒充真实 SDK 测量。10 个独立进程配置、每配置 3 次，共 30 个样本。最终 runtime 源文件 SHA-256 与所有新版测量记录匹配。

[完整快照报告](benchmarks/results/2026-10-14-native-snapshots/REPORT.md)及同目录 results.json 保留原始数据。10 万事实下，pysqlite3 的完整快照由约 184.4 ms 降至 4.0 ms，普通提交由约 187.0 ms 降至 0.36 ms；绑定历史接收者的提交约 3.8 ms。未压缩 SQLite 镜像约 4.15 MiB，旧压缩 JSON 约 0.31 MiB。DuckDB 完整镜像约 99.4 ms、5.26 MiB；这项负载没有显示其快照更快，也不能据此推断剧情查询速度。

Standards 独立审查发现 SQLite 批量删除为兼容 DuckDB 使用 RETURNING、造成无用返回缓冲；已改成后端内的变更检测，SQLite rowcount，DuckDB RETURNING 常量，并补回归检查。复核无遗留问题。

Spec 独立审查发现字典字段重排不改变 schema 标识，却被原生 DDL 比较误判；已稳定事实字段和唯一约束顺序，补充两后端重载／恢复回归。复核无遗留问题。

快照版本现为 2，旧压缩 JSON 与无元信息原型镜像不兼容；不提供跨后端存档迁移。Ren’Py 仍按有效提交保存完整镜像，尚未实现增量历史。其他发行平台未验证。
