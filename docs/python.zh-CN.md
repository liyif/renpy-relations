# 在普通 Python 应用中使用 Ren’Py Relations

[English](python.md) · [简体中文](python.zh-CN.md)

Ren’Py Relations 提供可用于普通 Python 应用的独立核心。它存储关系事实，执行编译后的规则，使受影响的缓存答案失效，并捕获或恢复事实快照。应用负责根据答案执行相应动作，无须 Ren’Py SDK、事件循环或游戏生命周期。

## 安装

安装 `renpy-relations`，从 `renpy_relations` 导入。在源码目录中用 uv 构建：

```sh
uv build --out-dir dist/python
```

这会生成 `renpy_relations-0.3.0-py3-none-any.whl` 和 `renpy_relations-0.3.0.tar.gz`。在你的应用所使用的 uv 项目中安装本地 wheel：

```sh
uv add /path/to/renpy_relations-0.3.0-py3-none-any.whl
```

上述步骤使用本地构建产物，不要求项目已发布到软件包索引。也可以用 `uv add /path/to/RenpyRelations` 从源码目录安装。

| 安装选项 | 依赖 |
| --- | --- |
| 默认 | SQLAlchemy；SQLite 使用 Python 的 `sqlite3`。 |
| `--extra duckdb` | 额外安装 DuckDB 及其 SQLAlchemy 方言。 |
| `--extra compiler` | 额外安装 Logica，用于开发阶段编译。 |

例如，`uv add --extra compiler --extra duckdb /path/to/renpy_relations-0.3.0-py3-none-any.whl` 会同时安装两组可选依赖。运行时读取预先编译的 JSON 规则包，不会导入 Logica。纯 Python wheel 包含可选的适配器代码，只有显式使用时才会启用；安装和导入这个包都不需要 Ren’Py。

## 需要维护的文件

| 文件 | 用途 | 由谁维护 |
| --- | --- | --- |
| `world.l` | 从事实推导答案的规则。 | 你。 |
| `schema.json` | 事实关系和导出结果的列声明。 | 你。 |
| `relations.rules.json` | 指定后端的 SQL、依赖和数据模式。 | 编译器生成。 |

逻辑部分需要两份手写文件，以及每个后端一份生成的规则包。宿主程序负责记录事实并使用查询答案。按常规方式安装库即可；Ren’Py 部署工具会将这个包及数据库依赖放入 `game/python-packages/`。库的实现文件保留在安装后的包内。

## 运行独立示例

源码包包含权限示例 [python_access](../examples/python_access/main.py)。成员身份或担保提供候选访问资格，明确的撤销记录会取消资格。[数据模式](../examples/python_access/schema.json)声明事实和导出的答案，[Logica 源码](../examples/python_access/world.l)定义以下规则：

```prolog
Candidate(user:, resource:) distinct :-
  Member(user:, role:), RoleAccess(role:, resource:);
Candidate(user:, resource:) distinct :- Sponsored(user:, resource:);

CanAccess(user:, resource:) distinct :-
  Candidate(user:, resource:), ~Revoked(user:, resource:);
```

每条规则读取关系；逗号组合条件，同名的多条规则提供不同途径，`~Revoked(...)` 排除已撤销的访问资格。[Palace 快速入门](quickstart.zh-CN.md#事实表与规则)从基础开始介绍关系、数据模式和 Logica 语法。

在源码根目录中运行：

```sh
uv sync --locked --extra duckdb
uv run --locked python examples/python_access/main.py
uv run --locked --extra duckdb python examples/python_access/main.py --backend duckdb
```

两次运行都会输出：

```text
Eligible: [{'user': 'alice', 'resource': 'drafts'}, {'user': 'bob', 'resource': 'drafts'}]
Alice after revocation: False
Alice after restore: True
```

示例自带两份编译后的规则包。要验证安装的 wheel，可以将源码包中的 `examples/python_access` 复制到你的应用中并运行其 `main.py`，无须从源码目录导入库。

## 接入核心

```python
from renpy_relations import LogicDB

logic = LogicDB("access.sqlite.rules.json")
try:
    with logic.batch():
        logic.add("Member", user="alice", role="editor")
        logic.add("RoleAccess", role="editor", resource="drafts")

    if logic.has("CanAccess", user="alice", resource="drafts"):
        print("The application may offer access.")

    saved = logic.snapshot()
    logic.add("Revoked", user="alice", resource="drafts")
    logic.restore(saved)
finally:
    logic.close()
```

核心公开导出 `LogicDB`、`RuleSet` 和 `RuleError`。构造时通过 `mode` 选择 `cached`、`live` 或 `materialized`。数据库后端由编译后的规则包决定，SQLite 和 DuckDB 分别使用对应的规则包。

查询返回由行字典组成的列表，`has()` 判断匹配行是否存在。用 `batch()` 组织相关写入，退出后再查询。失败的批事务会回滚；查询本身不会执行应用动作。键、过滤条件、事务限制、错误和诊断接口见[运行时参考](reference.zh-CN.md#运行时-api)。

## 在开发阶段编译规则

在开发环境中安装 `compiler` 可选依赖。安装后的命令和模块入口接受相同的选项：

```sh
uv run renpy-relations-compile world.l --schema schema.json --output access.sqlite.rules.json
uv run python -m renpy_relations.compiler world.l --schema schema.json \
  --backend duckdb --output access.duckdb.rules.json
```

DuckDB 命令还需要 `duckdb` 可选依赖。编译器记录 SQL、依赖和源码身份，验证结果后原子发布 JSON。运行时进程只需要 JSON 和对应的数据库驱动，无须编译器。规则和 SQL 是受信任的应用构建产物；传入查询和事实修改的字段值使用绑定参数。

在源码目录执行 `uv sync --locked` 后，也可以使用相同的编译命令。

## 管理应用状态

每个 `LogicDB` 拥有一个内存中的事实世界。`snapshot()` 返回原生镜像的字节数据。应用可以保存这些字节，随后传给 `restore()` 恢复。快照包含事实和兼容性元数据，派生答案会重新构建；其他应用状态需要单独保存。

未配置快照回调时，普通提交只会使已有镜像失效，直到调用 `snapshot()` 才捕获新镜像。如果宿主需要在每个有变更的批事务后接收镜像，可以在构造核心时传入 `on_snapshot=callback`。这会为每次有变更的提交生成完整的原生镜像。失败处理和重入限制见[快照接收函数](reference.zh-CN.md#快照接收函数)。

`reload_rules()` 在保留事实的同时替换兼容的规则；`reload_if_changed()` 在应用调用时检查规则包路径。核心不会创建轮询线程，也不会注册引擎回调。

## Ren’Py 集成

从 `renpy_relations` 导入 `RenpyLogicDB`，并在初始化阶段调用 `install_renpy(config)`。这个类在 `LogicDB` 之上增加 store 发布、存档／读档和回滚回调，以及开发提示。[快速入门](quickstart.zh-CN.md#准备并运行-palace)提供了完整接入示例。

规则包标识 `renpy-relations` 和快照元数据保持不变，以保留既有数据的兼容性。这些标识并不要求运行环境安装 Ren’Py。

一个事实世界应在所属线程中同步使用。异步访问、并发共享、任意 SQL、宿主提供的持久数据库连接和分布式执行均不属于公开接口。原生快照要求相同后端和兼容的事实数据模式，跨数据库版本的长期可移植性尚未验证。Python 元数据允许 >=3.11,<3.15，目前本地安装和集成检查使用 Linux x86_64 上的 Python 3.12。`py3-none-any` wheel 包含 Python 代码，可选驱动则有各自的平台要求。
