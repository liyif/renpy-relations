# Ren’Py Relations

在 Ren’Py 中使用关系事实与声明式规则的实验。

游戏脚本修改事实，Logica 描述派生关系，SQLite 执行查询。这个实验检验的是：复杂的资格、关系和剧情条件，能否通过很薄的集成获得成熟的关系计算能力。

运行时是一个 `renpy_relations.py`，依赖 SQLAlchemy 和 SQLite 驱动；Logica 只用于开发时编译。[设计与取舍见 DESIGN.md](DESIGN.md)。

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

编译器使用固定版本 Logica 的解析器和 SQL 生成器。导出关系之间保持外部表引用，内部辅助谓词正常展开；运行时由 SQLite 解析依赖并排序。事实属于外部数据，不能同时在 `.l` 中定义。

编译器校验所有查询、输出列和依赖，成功后原子替换产物。失败保留上一份可用规则。源文件／schema 在编译途中变化时也不发布产物。JSON 包含格式版本、关系声明、SQL、直接依赖清单和源文件信息，可直接交给后端。

`dependencies` 包含直接读取的事实／派生关系，由 SQLite 解析编译 SQL 时报告，包括否定和空表读取。运行时校验清单与 SQL 一致；手工修改 SQL 也必须更新依赖或重新编译。旧的无依赖清单产物仍可加载。

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

过滤值通过 SQLAlchemy 绑定，返回独立的行字典，行顺序未定义。修改只允许作用于事实；派生关系只读。事务内禁止 query、has、snapshot、restore、reload 和嵌套 batch。

独立接入可传入 `on_snapshot` 回调，它应原子接收字节串，成功返回表示接受；抛错时后端恢复上一份已接受的事实快照。Ren’Py 绑定自带该回调。

三种模式共享接口：

| 模式 | 计算与保存方式 |
| --- | --- |
| `cached`（默认） | 首次读取某派生关系时，在 SQLite TEMP TABLE 中物化该关系及其依赖 |
| `materialized` | 初始化时计算全部派生 TEMP TABLE；提交时只重建受影响的派生关系 |
| `live` | 使用 TEMP VIEW，每次读取由 SQLite 执行 |

派生输出按声明类型显式转换，布尔值归一化为 0／1，NULL 保留，三种模式使用相同投影。没有按过滤参数保存的 Python 查询结果缓存；has 和 query 复用完整关系。实际事实变更只使依赖于已修改事实关系的推导及其后继失效；失败事务、重复 add 和未匹配的 remove 保留原有缓存。

SQLite 执行依赖图的排序、循环检查和失效传播，Python 不遍历依赖图。当前精度到事实关系：通用状态表内互不相关的行仍会共享失效范围。加载时的祖先闭包成本见多规则基准的长链探针。

`describe(name)` 查看关系声明、SQL、派生依赖及包含事实的直接读取 `reads`，不执行规则查询。`stats()` 查看已缓存关系、成功的惰性物化次数、惰性物化总耗时以及当前快照字节数。它们用于观察实验，不是完整性能分析器。

## Ren’Py 接入与示例

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

在其他游戏中，将 `renpy_relations.py` 放入 `game/python-packages`，规则产物放在 `game`，然后：

```renpy
default logic_snapshot = None

init python:
    import os
    from renpy_relations import LogicDB
    logic = LogicDB(os.path.join(config.gamedir, "relations.rules.json"))
    logic.install_renpy(config)
```

数据库对象放在初始化变量中，store 只保存不可变快照字节串。提交事实时更新快照；启动、读档和回滚后恢复事实并重建派生对象。相同绑定重复安装不会重复注册回调。

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

- 接受确定性的单条 SQLite SELECT，包含适用的 WITH／递归 CTE；跨派生关系的循环依赖拒绝加载。
- 支持 SQLite 自带函数、JSON 表函数，以及 Logica 否定查询用的纯函数 MagicalEntangle。其他扩展函数、多语句工作流、外部执行器不在本轮支持范围。
- 规则不得读取系统时钟、数据库随机数或连接状态；相关函数拒绝加载。游戏需要随机或时间时，应把结果写成事实。
- 规则 SQL 是受信任的构建产物；校验不是针对任意恶意 SQL 的安全沙箱。
- 快照是带版本与事实 schema 标识的压缩 JSON，只保存事实。首次原型的 SQLite 内存镜像不兼容，本轮没有存档迁移。
- 所有事实修改必须经过后端接口。运行方式同步、单线程，按事实关系传播失效，未做元组级增量维护。
- 每次实际事实提交生成完整逻辑快照；使用 batch 合并一次游戏行动。大事实集上的成本见下述基准。

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

视觉小说的多条件负载另有基准：128／512 条事实，事实数:派生规则数为 1:1／1:10；每次行动只读 24 个条件。对照旧版全局失效与 SQL 依赖图失效，涵盖独立事实关系和通用状态表两种布局。

```sh
uv run --locked python benchmarks/rules.py \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages examples/palace/game/python-packages
```

[多规则协议](benchmarks/RULES_DESIGN.md) · [多规则结果解读](benchmarks/MANY_RULES.md) · [完整对照报告](benchmarks/results/2026-10-13-many-rules/REPORT.md)

## 验证

后端检查使用真实 SQLite；编译检查使用真实 Logica，覆盖三种模式、依赖缓存、事务失败、快照、热重载、编译失败和观察重建。

Ren’Py 自身的测试用例位于示例 `game/testcases.rpy`：

```sh
/path/to/renpy-sdk/renpy.sh examples/palace lint
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode live
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode materialized
```

`--headless` 需要 Linux 的 xvfb-run；省略时使用正常显示器。脚本以 SDK 输出的完整测试报告为结果，超时／崩溃／失败报告均返回失败，并回收隔离的测试进程与临时存档。Ren’Py 8.5.3 的测试结束阶段会继续循环，启动脚本在收到报告后终止该进程组；没有修改 SDK 源码。

可设置 `RELATIONS_MODE=live` 或 `RELATIONS_MODE=materialized` 交互运行同一示例。真实引擎验证结果记录在 [VALIDATION.md](VALIDATION.md)。

参考：[Logica](https://github.com/EvgSkv/logica)、[Ren’Py 回调](https://www.renpy.org/doc/html/config.html#var-config.after_default_callbacks)、[Python 包接入](https://www.renpy.org/doc/html/python.html#first-and-third-party-python-modules)、[存档与回滚](https://www.renpy.org/doc/html/save_load_rollback.html)。
