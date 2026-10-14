# 使用说明

命令均从源码根目录运行。开发依赖由 uv 和 `uv.lock` 管理：

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
```

只使用 SQLite 时可省略 `--extra duckdb`。运行游戏的方法见 [QUICKSTART](QUICKSTART.md)。

## 定义与编译规则

`.l` 描述派生规则，schema JSON 声明事实、导出关系、字段和可选主键。例如：

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

字段类型为 `text`、`integer`、`real`、`boolean`。事实字段不可为空，完整元组唯一，重复断言忽略。事实声明中可用 `"key": ["character"]` 定义主键；不同值违反主键时事务失败。更新单值事实应在同一 batch 内先删除再添加。

编译仓库中的 palace 规则：

```sh
uv run --locked python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json --output examples/palace/game/relations.rules.json
uv run --locked --extra duckdb python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json --backend duckdb \
  --output examples/palace/game/relations.duckdb.rules.json
```

`--backend` 可覆盖源文件的引擎选择。两后端分别生成 SQL，不能互换产物。未标记 backend 的旧规则集按 SQLite 解释。

编译器使用锁定版本 Logica 的解析器与 SQL 生成器。导出关系之间保留表引用，内部辅助谓词展开；事实由游戏提供，不能在 `.l` 中同时定义。产物包含声明、SQL、直接依赖、格式版本与源文件信息。输出列和 SQL 校验通过后才原子替换文件；编译失败或编译期间输入变化时保留旧产物。

支持范围为可编译成确定性单条 SELECT 的规则，包括适用的 WITH／递归 CTE。跨派生关系的循环依赖、UDF 和多步骤工作流不支持。时间和随机结果应由游戏写成事实，不能在查询中读取时钟或数据库随机数。后端专属函数及类型转换语义可能不同。

## 事实与查询

```python
from renpy_relations import LogicDB

logic = LogicDB("relations.rules.json", mode="cached")
try:
    with logic.batch():
        logic.add("Sponsor", character="hero", location="archive")
    assert logic.has("CanEnter", character="hero", location="archive")
    rows = logic.query("CanEnter", character="hero")
    logic.remove("Sponsor", character="hero")
finally:
    logic.close()
```

DuckDB 可使用 `LogicDB("relations.duckdb.rules.json")`，后端由产物选择。显式 `backend="duckdb"` 必须与产物一致。

| 接口 | 行为 |
| --- | --- |
| `add(name, **values)` | 添加完整事实；重复元组不产生变更 |
| `remove(name, **filters)` | 删除匹配的事实；必须提供至少一个过滤字段 |
| `batch()` | 合并一次行动的写入、提交和失效；异常时回滚 |
| `has(name, **filters)` | 判断是否存在匹配行 |
| `query(name, **filters)` | 返回独立的行字典列表，行顺序未定义 |
| `snapshot()` | 返回不可变事实镜像；事实未变化时复用镜像 |
| `restore(image)` | 原子恢复事实；`None` 表示空事实世界 |
| `reload_rules(rules=None)` | 从原文件或指定路径／RuleSet 加载新规则并保留事实 |
| `describe(name)` | 查看声明、SQL、派生依赖及直接读取 `reads` |
| `stats()` | 查看后端、缓存关系、惰性物化计数／耗时及已缓存镜像大小 |
| `close()` | 释放数据库资源 |

过滤值使用参数绑定，NULL 按 SQL 语义比较。派生输出按声明类型转换，布尔值归一化为 0／1，NULL 保留。派生关系只读，所有事实修改必须经过上述接口。

batch 内禁止查询、快照、恢复、重载和嵌套 batch。查询与剧情效果分开：先判断资格，再在行动事务中记录奖励、选择或事件结果。

## 查询模式

| 模式 | 计算时机 |
| --- | --- |
| `cached`（默认） | 首次读取时物化目标派生关系及所需依赖 |
| `live` | 通过 TEMP VIEW，每次查询执行 SQL |
| `materialized` | 初始化计算全部派生关系，提交时重建受影响的关系 |

`query` 和 `has` 共享完整关系的物化结果；没有按过滤参数保存的 Python 结果缓存。有效提交只使依赖于已修改事实关系的推导及后继失效。失败事务、重复添加和未匹配删除不失效。

失效以关系为单位。所有领域共用一个状态表时，局部行修改仍可能影响全部领域；分表可以缩小依赖范围，但会改变 schema。模式和布局的实际代价见 [Benchmark](benchmarks/README.md)。

## 快照与 Ren’Py

未绑定快照接收者时，普通提交不生成镜像。`snapshot()` 惰性生成原生数据库镜像，事实变化后失效。

独立调用可传入 `on_snapshot` 回调。回调应原子接收字节串；返回表示接受，抛错时恢复上一次已接受的事实状态。绑定后每次有效提交都发布完整镜像；空事务和无效变更不发布。

Ren’Py 接入方式：

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

数据库对象位于初始化变量中，store 保存快照字节串。绑定在有效提交时更新快照，在启动、读档和回退后恢复事实及派生对象；同一绑定重复安装不会重复注册回调。用 batch 合并一次玩家行动，避免为多个字段变化分别保存整库镜像。

快照格式为版本 2，只保存事实与内部元信息。不同后端、不同事实 schema，以及旧原型快照不兼容。规则版本不绑定存档；恢复旧事实时使用当前规则解释。

规则 JSON、以 Path 读取的数据和原生扩展必须作为实际文件打包，不能只放进资源归档。驱动须匹配 Ren’Py 内置 Python 的 ABI，安装与分发见 [QUICKSTART](QUICKSTART.md) 和 [RELEASE](RELEASE.md)。

## 开发重载

编译器可以观察 `.l` 及 schema：

```sh
uv run --locked python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json --output examples/palace/game/relations.rules.json --watch
```

`logic.reload_rules()` 构建候选数据库，使用当前事实预执行所有新推导，成功后才替换。失败保留当前世界。派生关系可增删改；事实 schema 变化需要新的 LogicDB 或新游戏，重载不能切换后端。

`logic.install_renpy(config, watch_rules=True)` 在开发模式的交互开始时检查编译产物。自动重载失败记录日志并通知，同一错误不重复通知。游戏中不运行编译器或后台观察线程。

样例开发模式下 F6 手动重载、F8 查看关系。规则重载不创建剧情历史，之后的回退和读档仍采用当前规则。
