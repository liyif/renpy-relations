# Ren’Py Relations

在 Ren’Py 中使用关系事实与声明式规则的实验。

游戏脚本修改事实，Logica 描述派生关系，SQLite 或 DuckDB 执行查询。这个实验检验的是：复杂的资格、关系和剧情条件，能否通过很薄的集成获得成熟的关系计算能力。

运行时是一个 `renpy_relations.py`，依赖 SQLAlchemy 和所选数据库驱动；Logica 只用于开发时编译。[设计与取舍见 DESIGN.md](DESIGN.md)。

**0.1.0 实验版**：[直接试玩／五分钟上手](QUICKSTART.md) · [更新记录](CHANGELOG.md) · [发布构建与支持范围](RELEASE.md)。代码、文档和示例剧本采用 [MIT](LICENSE)，第三方组件见 [许可说明](THIRD_PARTY_NOTICES.md)。

可试玩发行包包含采用多种自由软件许可证（包括 LGPL）的 Ren’Py 组件；完整清单与源码入口见 [Ren’Py 许可说明](https://www.renpy.org/doc/html/license.html)，原始声明随游戏 `LICENSE.txt` 保留。

## 开发与编译

以下命令在 `RenpyRelations` 目录运行。依赖统一使用 uv 管理，提交 `pyproject.toml` 和 `uv.lock`；`.python-version` 选择 Python 3.12。

```sh
uv sync --locked
uv run --locked python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json \
  --output examples/palace/game/relations.rules.json
uv run --locked python -m pytest
```

编译输入是一份 `.l` 与一个关系声明文件：

```json
{
  "facts": {
    "Sponsor": {"columns": {"character": "text", "location": "text"}}
  },
  "derived": {
    "CanEnter": {"columns": {"character": "text", "location": "text"}}
  }
}
```

```prolog
@Engine("sqlite");
CanEnter(character: c, location: l) distinct :-
  Sponsor(character: c, location: l);
```

字段类型为 `text`、`integer`、`real`、`boolean`。事实字段不可为空，完整元组有唯一约束，重复断言忽略。可选 `"key": ["character"]` 定义事实主键；不同值违反主键时明确失败。替换单值事实可在一个 batch 中先 remove 再 add。

编译器使用固定版本 Logica 的解析器和 SQL 生成器。导出关系之间保持外部表引用，内部辅助谓词正常展开；运行时由所选数据库解析依赖并排序。事实属于外部数据，不能同时在 `.l` 中定义。

编译器校验所有查询、输出列和依赖，成功后原子替换产物。失败保留上一份可用规则。源文件／schema 在编译途中变化时也不发布产物。JSON 包含格式版本、关系声明、SQL、直接依赖清单和源文件信息，可直接交给后端。

`dependencies` 包含直接读取的事实／派生关系，由数据库原生解析编译 SQL 时报告，包括否定和空表读取。运行时校验清单与 SQL 一致；手工修改 SQL 也必须更新依赖或重新编译。旧的无依赖清单产物仍可加载。

选择 DuckDB 时安装可选依赖并生成对应 SQL，无需修改源文件：

```sh
uv sync --locked --extra duckdb
uv run --locked --extra duckdb python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json --backend duckdb \
  --output examples/palace/game/relations.duckdb.rules.json
```

也可在源文件声明 `@Engine("duckdb")`。产物带 `backend` 标识，缺省标识的旧产物按 SQLite 解释；不能把 SQLite SQL 产物直接交给 DuckDB。

## 后端接口

```python
from renpy_relations import LogicDB

logic = LogicDB("relations.rules.json", mode="cached")
with logic.batch():
    logic.add("Sponsor", character="hero", location="archive")

assert logic.has("CanEnter", character="hero", location="archive")
rows = logic.query("CanEnter", character="hero")
saved = logic.snapshot()
logic.remove("Sponsor", character="hero")
logic.restore(saved)
logic.reload_rules()
logic.close()
```

DuckDB 使用 `LogicDB("relations.duckdb.rules.json", backend="duckdb", mode="cached")`。省略 `backend` 时采用产物中的选择；显式选择与产物不符会报错。热重载不能切换后端。

过滤值通过 SQLAlchemy 绑定，返回独立的行字典，行顺序未定义。修改只允许作用于事实；派生关系只读。事务内禁止 query、has、snapshot、restore、reload 和嵌套 batch。

独立接入可传入 `on_snapshot` 回调，它应原子接收字节串，成功返回表示接受；抛错时后端恢复上一份已接受的事实快照。Ren’Py 绑定自带该回调。

未绑定快照接收者时，普通事实提交只执行数据库事务与依赖失效，不生成整库快照。显式 `snapshot()` 惰性生成并复用镜像；事实变化后失效。绑定接收者时，每次有效提交仍发布完整镜像，重复断言、空 batch 和未匹配删除不发布。

三种模式共享接口：

| 模式 | 计算与保存方式 |
| --- | --- |
| `cached`（默认） | 首次读取某派生关系时，在 TEMP TABLE 中物化该关系及其依赖 |
| `materialized` | 初始化时计算全部派生 TEMP TABLE；提交时只重建受影响的派生关系 |
| `live` | 使用 TEMP VIEW，每次读取由所选数据库执行 |

派生输出按声明类型显式转换，布尔值归一化为 0／1，NULL 保留，三种模式使用相同投影。没有按过滤参数保存的 Python 查询结果缓存；has 和 query 复用完整关系。实际事实变更只使依赖于已修改事实关系的推导及其后继失效；失败事务、重复 add 和未匹配的 remove 保留原有缓存。

数据库执行依赖图的排序、循环检查和失效传播，Python 不遍历依赖图。SQLite 使用 authorizer 报告读取，DuckDB 使用原生查询解析接口。当前精度到事实关系：通用状态表内互不相关的行仍会共享失效范围。加载时的祖先闭包成本见多规则基准的长链探针。

`describe(name)` 查看关系声明、SQL、派生依赖及包含事实的直接读取 `reads`，不执行规则查询。`stats()` 查看后端、已缓存关系、成功的惰性物化次数、惰性物化总耗时和缓存的镜像字节数（尚未生成时为 0）。它们用于观察实验，不是完整性能分析器。

## Ren’Py 接入与示例

[`examples/tidelight`：《潮汐替我们保管》](examples/tidelight/README.md) 是完整可玩的中文短篇 Galgame，包含三位成年女主角、19 个事件与五个结局。时间、人物行程、线索、物品、同意与约定共同决定当前相遇及结局；场景结束后统一重新查询，适合观察关系驱动的剧情编排。[完整剧本](examples/tidelight/game/story.rpy)与[含剧透的试玩路线](examples/tidelight/ROUTES.md)均在样例内。

`examples/palace` 是可运行的 Ren’Py 项目，展示阵营／担保两种访问资格、知识条件、一次性奖励、事实撤销、存读档和回滚。`baseline.py` 给出同一组条件的直接 Python 表达，便于比较规则修改成本。

本次实际验证的环境为 **Linux x86_64、Ren’Py 8.5.3（内置 Python 3.12.8）**。SDK 没有 sqlite3；示例使用单独安装的 pysqlite3-binary。其他发行平台需要验证其 SQLite 驱动与二进制打包，尚未验证。

为该环境安装锁定的运行依赖：

```sh
uv export --locked --no-dev --group renpy-linux \
  --format requirements-txt --output-file /tmp/renpy-relations-runtime.txt
uv pip install --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --only-binary :all: --require-hashes \
  --target examples/palace/game/python-packages \
  --requirements /tmp/renpy-relations-runtime.txt
/path/to/renpy-sdk/renpy.sh examples/palace
```

依赖必须匹配 **Ren’Py 内置 Python**，不能直接复制开发环境中其他 Python 版本的二进制包。SQLAlchemy 固定为实测兼容的 2.0.43；较新的 2.0.54／2.1 使用了该 SDK 裁剪掉的 sysconfig 接口。

DuckDB 示例使用同一安装流程，在 `uv export` 中额外加上 `--extra duckdb`。然后以 `RELATIONS_BACKEND=duckdb /path/to/renpy-sdk/renpy.sh examples/palace` 启动。DuckDB／duckdb-engine 的版本也由 uv 锁定。

在其他游戏中，将 `renpy_relations.py` 放入 `game/python-packages`，规则产物放在 `game`，然后：

```renpy
default logic_snapshot = None

init python:
    import os
    import sys
    sys.path.insert(0, os.path.join(config.gamedir, "python-packages"))
    from renpy_relations import LogicDB
    logic = LogicDB(os.path.join(config.gamedir, "relations.rules.json"))
    logic.install_renpy(config)
```

数据库对象放在初始化变量中，store 只保存不可变快照字节串。提交事实时更新快照；启动、读档和回滚后恢复事实并重建派生对象。相同绑定重复安装不会重复注册回调。

实际包目录搜索路径使 Python 能找到 DuckDB 的顶层原生扩展；该扩展必须随游戏作为实际文件部署，不能只放入资源归档。

规则负责条件判断；发放奖励、剧情跳转等由 Ren’Py 脚本执行，结果以事实记录。一次性奖励应检查资格，再写入 RewardClaimed，不能让条件查询本身发奖励。

## 热重载

构建阶段观察本地 `.l` 文件及 schema：

```sh
uv run --locked python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json \
  --output examples/palace/game/relations.rules.json --watch
```

运行时 `logic.reload_rules()` 重新读取原规则文件，也可以传入另一份规则集路径或 RuleSet。候选数据库用当前事实预执行所有新派生关系，全部成功后切换；失败时旧事实、旧规则与缓存继续可用。

`logic.install_renpy(config, watch_rules=True)` 在开发模式的交互开始时检查编译产物；发布模式不观察文件。自动重载错误写入 Ren’Py 日志并通知，同一错误不重复通知。游戏中没有编译器或后台观察线程。

示例中 F6 手动重载，F8 打开关系检查屏幕。修改规则并重新编译后，在下一次交互时生效；不是正在进行中的交互的实时文件监听。事实 schema 改变需要重新创建世界。规则重载不写入剧情历史，之后回滚／读旧档仍使用当前规则解释事实。

## 支持范围与实验边界

- 接受目标后端支持的确定性单条 SELECT，包含适用的 WITH／递归 CTE；跨派生关系的循环依赖拒绝加载。
- SQLite 支持自带函数、JSON 表函数和纯函数 MagicalEntangle。DuckDB 支持经原生函数目录检查的确定性函数，以及 unnest／range／generate_series／JSON 表函数；拒绝动态查询、外部文件读取和系统目录读取。复杂记录类型、UDF 与多语句 Logica 工作流不在本轮支持范围。
- 规则不得读取系统时钟、数据库随机数或连接状态；相关函数拒绝加载。游戏需要随机或时间时，应把结果写成事实。
- 规则 SQL 是受信任的构建产物；校验不是针对任意恶意 SQL 的安全沙箱。
- 快照是原生数据库镜像，仅保存事实和内部格式／版本／后端／事实 schema 元信息。SQLite 优先内存 serialize／deserialize，SDK pysqlite3 回退原生 backup；DuckDB 使用原生数据库复制与独立文件镜像。恢复验证候选 schema 和元信息后才替换当前世界。
- 新快照版本为 2，不接受旧压缩 JSON、无元信息原型镜像或另一后端的镜像。本轮不提供存档迁移。两个数据库的类型转换和函数语义仍有差异；游戏应按声明类型提供字段值。
- 所有事实修改必须经过后端接口。运行方式同步、单线程，按事实关系传播失效，未做元组级增量维护。
- Ren’Py 绑定每次实际事实提交生成完整镜像；使用 batch 合并一次游戏行动。镜像未额外压缩，通常比原压缩 JSON 大。尚未实现增量历史，数据库 checkpoint／MVCC 不能替代独立剧情历史。

## 提交与原生快照对照

```sh
uv run --locked --extra duckdb --group renpy-linux python benchmarks/snapshots.py \
  --sizes 10000 100000 --repetitions 3 --baseline-ref 45d0c21 \
  --out benchmarks/results/my-native-snapshots
```

分别测量普通提交、绑定历史接收者的提交、首次／重复快照和恢复，包含标准库序列化、pysqlite3 备份回退和 DuckDB 数据库复制。[实际结果与限制](benchmarks/results/2026-10-14-native-snapshots/REPORT.md)。它只隔离快照路径，不代表剧情查询速度。

## 大数据基准

基准复用 palace 的真实编译规则，比较三种模式在 1 万／10 万／100 万角色上的读取、提交、快照、恢复、规则重载和进程内存。默认每种条件三次独立进程重复，保留原始样本及失败记录。

```sh
uv run --locked python benchmarks/run.py
```

默认使用 uv 的 Python。指定 Ren’Py 内置运行时：

```sh
uv run --locked python benchmarks/run.py \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages examples/palace/game/python-packages
```

可用 `--sizes 1000 --repetitions 1` 做快速检查；`--out` 必须指向空目录。输出 JSON、CSV、Markdown，生成的大型快照不提交。SDK 后端测量不包含界面和回滚历史成本。

[测量协议](benchmarks/DESIGN.md) · [实测解读](benchmarks/README.md) · [完整基准报告](benchmarks/results/2026-10-13-sdk-baseline/REPORT.md)

多条件负载每轮实际读取 **1,000／3,000／10,000 个不同派生条件**，另有 64 个共享前置关系。事实数:总派生规则数为 1:1／约 1:10。对照旧版全局失效与 SQL 依赖图失效，涵盖独立事实关系和通用状态表两种布局、三模式、三次独立重复。

```sh
uv run --locked python benchmarks/conditions.py \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages examples/palace/game/python-packages
```

[千至万条件协议](benchmarks/CONDITIONS_DESIGN.md) · [结果解读](benchmarks/CONDITIONS.md) · [完整对照报告](benchmarks/results/2026-10-13-1000-10000-conditions/REPORT.md)

`--conditions` 可指定实际读取数；`--ratios`、`--shapes`、`--modes`、`--variants`、`--repetitions` 可缩小对照范围。旧 24 条件脚本与[历史结果](benchmarks/MANY_RULES.md)保留供复现。

## 验证

后端检查使用真实 SQLite／DuckDB；编译检查使用真实 Logica，覆盖三种模式、依赖缓存、事务失败、快照、热重载、编译失败和观察重建。完整双后端检查使用 `uv run --locked --extra duckdb --group renpy-linux pytest`；未安装可选依赖时跳过相关检查。

Ren’Py 自身的测试用例位于示例 `game/testcases.rpy`：

```sh
/path/to/renpy-sdk/renpy.sh examples/palace lint
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode live
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode materialized
uv run --locked --extra duckdb python check_renpy.py --sdk /path/to/renpy-sdk --headless --backend duckdb
```

`--headless` 需要 Linux 的 xvfb-run；省略时使用正常显示器。脚本以 SDK 输出的完整测试报告为结果，超时／崩溃／失败报告均返回失败，并回收隔离的测试进程与临时存档。Ren’Py 8.5.3 的测试结束阶段会继续循环，启动脚本在收到报告后终止该进程组；没有修改 SDK 源码。

可设置 `RELATIONS_MODE=live` 或 `RELATIONS_MODE=materialized` 交互运行同一示例。真实引擎验证结果记录在 [VALIDATION.md](VALIDATION.md)。

参考：[Logica](https://github.com/EvgSkv/logica)、[Ren’Py 回调](https://www.renpy.org/doc/html/config.html#var-config.after_default_callbacks)、[Python 包接入](https://www.renpy.org/doc/html/python.html#first-and-third-party-python-modules)、[存档与回滚](https://www.renpy.org/doc/html/save_load_rollback.html)。
