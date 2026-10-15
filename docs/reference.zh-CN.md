# 编译器与运行时参考

[English](reference.md) · [简体中文](reference.zh-CN.md)

[数据模型](#数据模型) · [编译规则](#编译规则) · [运行时 API](#运行时-api) · [查询模式](#查询模式) · [快照与重载](#快照与重载) · [Ren’Py 集成](#renpy-集成) · [兼容性](#兼容性) · [故障排查](#故障排查)

完整的入门练习请参阅 [Palace 快速入门](../QUICKSTART.zh-CN.md)。本页规定编译器、运行时、快照和 Ren’Py 适配器的接口契约。[Tidelight 指南（英文）](../examples/tidelight/README.md)介绍了一个基于这些接口构建的应用；[维护指南（英文）](maintaining.md)说明项目准备、验证和发布流程。

普通 Python 应用从 `relation_rules` 导入通用核心，安装和独立示例见 [Python 集成指南（英文）](python.md)。现有 Ren’Py 游戏仍使用 `from renpy_relations import LogicDB`；该兼容类即 `relation_rules.renpy.RenpyLogicDB`，在共享核心之上提供引擎适配。

## 数据模型

**关系**是具有命名**列**的表状数据。每一**行**为每列提供一个值。**数据模式（schema）**声明这些关系及其列类型。**事实**是游戏代码记录的一行数据；**规则**从事实和其他规则推导答案。**查询**读取符合条件的行。关系可以表示权限、知识、已完成的动作或分数；这个术语并不特指恋爱关系。

各组件的职责边界如下：

| 组件 | 职责 |
| --- | --- |
| `schema.json` | 声明可写的事实关系和导出的派生关系列。 |
| Logica 源码，通常是 `world.l` | 定义派生谓词以及可选的内部辅助谓词。 |
| `compile_rules.py` | 编译指定后端的 SQL，记录依赖，验证输出，并发布 JSON 规则包。 |
| `LogicDB` | 存储事实、计算派生答案、批量写入，以及捕获或恢复事实映像。 |
| 游戏代码 | 从符合条件的动作中作出选择，并记录其效果。 |
| Ren’Py 适配器 | 将事实映像发布到 store 变量，并在 Ren’Py 恢复该变量时恢复数据库。 |

是否符合条件是查询的结果。发放奖励或推进场景是应用执行的动作。查询本身不会施加这些效果。

### 数据模式声明

编译器的数据模式文件恰好有两个顶层键：`facts` 和 `derived`，二者均为字典。事实声明接受 `columns` 和可选的 `key`。派生声明只接受 `columns`；其 SQL 由编译器提供。

```json
{
  "facts": {
    "Member": {
      "columns": {"character": "text", "faction": "text"},
      "key": ["character"]
    }
  },
  "derived": {
    "Scholar": {"columns": {"character": "text"}}
  }
}
```

每个关系至少需要一列。关系名和列名必须以 ASCII 字母开头，且只能包含 ASCII 字母、数字和下划线。以 `sqlite_` 开头的名称是保留名称，不区分大小写。事实和派生输出之间的关系名必须在忽略大小写后保持唯一；同一关系内的列名也必须在忽略大小写后保持唯一。Python 调用必须使用声明中的准确拼写。

| 声明类型 | 常规 Python 值 | 契约 |
| --- | --- | --- |
| `text` | `str` | 文本值。 |
| `integer` | `int` | 数据库整数值；数值键不会启用自动编号。 |
| `real` | `float` | 浮点值。DuckDB 使用双精度。 |
| `boolean` | `bool` | 布尔值；派生的非空真值会被规范化为真或假。 |

事实不允许空值。即使关系声明了键，`add()` 仍要求提供每一列。派生列可以包含 `None`；在所有查询模式下，运行时都会将派生输出列转换为其声明类型。声明验证并非完整的 Python 值验证器：参数绑定、转换和约束检查由 SQLAlchemy 及所选数据库完成。请提供符合声明类型的值，避免依赖后端的隐式转换。

每个事实关系都对完整元组施加唯一约束。重复添加完全相同的元组不会产生效果。可选的 `key` 是由不同的已声明列名组成的非空列表，用于添加主键约束。如果新元组使用已有键，却具有不同的非键列值，操作会失败；`add()` 不会更新或替换原行。要替换带键的行，请在同一个批次中使用 `remove()` 和 `add()`。

派生输出通过此 API 只能读取。其行不会自动去重；如果规则应返回唯一的行，请使用 Logica 的 `distinct`。

### 编译规则包与 `RuleSet`

运行时接受编译后的 JSON 规则包或 `RuleSet`，不接受 Logica 源码。规则包包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `format` | 必须为 `"renpy-relations"`。 |
| `version` | 整数 `1`。 |
| `backend` | `"sqlite"` 或 `"duckdb"`；省略时使用 SQLite。 |
| `facts` | 上述事实声明。 |
| `derived` | 每个声明包含 `columns` 和非空的已编译 `sql` 字符串。 |
| `dependencies` | 将每个派生关系名映射到它读取的已声明事实或派生关系列表。有派生输出时必须提供。 |
| `source` | 可选的编译来源信息；生成的规则包会记录源码和输入的哈希值以及编译器版本。 |

未知的顶层字段或关系声明字段会被拒绝。依赖列表不能包含未知名称或重复名称。导出关系之间的依赖图必须无环；创建运行时会验证该图。

```python
from renpy_relations import RuleSet

rules = RuleSet.load("examples/palace/game/relations.rules.json")
print(rules.backend)                   # "sqlite"
print(rules.reads["CanInvestigate"])   # direct fact and exported-relation reads
document = rules.document             # independent JSON-compatible copy
```

| 公共接口 | 含义 |
| --- | --- |
| `RuleSet(document)` | 验证兼容 JSON 的规则包，并将其与随后对输入文档的修改隔离。 |
| `RuleSet.load(path)` | 从文件系统路径读取 UTF-8 JSON 规则包。 |
| `rules.document` | 返回新的独立副本，供检查或写出规则包使用。 |
| `rules.backend` | 所选数据库后端。 |
| `rules.fact_schema_id` | 事实声明的摘要，用于检查快照和重载兼容性。字典顺序不会影响它。 |
| `rules.reads` | 字典，记录每个派生关系直接读取的关系，值为排序后的元组。 |
| `rules.dependencies` | 字典，只包含这些读取中派生关系之间的依赖。 |

请将这些对象视为定义。要修改定义，请编辑 `document` 副本并构造新的 `RuleSet`。`RuleSet` 验证声明；它本身不会编译 Logica，也不会执行所有 SQL。

编译后的 SQL 和依赖边属于受信任的构建输出。运行时执行这些 SQL，并信任依赖边来确定计算顺序和失效范围；它不会分析 SQL 来重建依赖或实施沙箱限制。请使用由自己信任的规则构建的规则包。传给修改和查询方法的游戏数据值会作为绑定参数处理。

## 编译规则

在仓库根目录中，使用锁定依赖的开发环境运行命令：

```sh
uv run --locked python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json \
  --output /tmp/palace-relations.rules.json
```

| 参数 | 行为 |
| --- | --- |
| `source` | 必填的位置参数，指定 Logica 源码路径。其父目录是本地导入根目录。 |
| `--schema PATH` | 必填，指定模式 JSON 路径。 |
| `--output PATH` | 必填，指定编译规则包的目标路径；不存在的父目录会被创建。 |
| `--backend sqlite\|duckdb` | 覆盖源码的 `@Engine` 选择，不修改源码。 |
| `--watch` | 先构建一次，之后在检测到本地输入变化时重新构建，直到被中断。 |

没有覆盖参数时，源码必须选择 SQLite 或 DuckDB。编译或运行 DuckDB 规则包时，请安装 DuckDB 可选依赖，例如 `uv run --locked --extra duckdb python compile_rules.py … --backend duckdb`。一个规则包只面向一个后端；运行时选择其他后端不会转换其 SQL。

Python 入口是 `compile_rules.py` 中的 `compile_rules(source, schema, output, *, backend=None)`。成功发布后，它返回经过验证的 `RuleSet`。单次运行的命令行工具成功时退出码为 `0`，捕获到构建失败时为 `1`。

每个声明的派生输出都必须在 Logica 中定义。事实名称代表外部表：编译器会拒绝对这些名称的 Logica 定义，包括源码中的事实。读取未声明的外部关系也会被拒绝。未导出的辅助谓词可以由 Logica 内联。当一个导出谓词读取另一个导出的派生谓词时，后者仍保持为独立的关系边界，以便复用其带类型的结果和缓存计算。否定读取和聚合读取也参与依赖跟踪。

发布前，编译器会创建一个空的物化世界，按依赖顺序执行带类型的输出，并核对每个 SQL 输出的列名和列数是否与声明一致。这能发现无效引用、输出结构错误和导出关系间的依赖环，但不能证明未来所有游戏数据值都能成功求值；之后仍可能出现由具体数据触发的 SQL 错误。DuckDB 的多语句工作流和 UDF 定义会被拒绝。

运行时能够在单个输出内执行受支持的递归 SQL 查询，包括测试所覆盖的 SQLite 递归 CTE。这与导出关系之间的依赖环不同，后者会被拒绝。这并不意味着支持所有递归 Logica 程序或后端特性：所选后端上的编译和输出验证必须成功。

### 发布与监听

编译器先构建并验证，再替换输出。它在目标文件所在目录中写入临时文件，然后原子替换目标文件。构建失败会保留之前的规则包；生成内容没有变化时，文件也保持不变。编译器还会比较编译前后的输入哈希，如果输入在编译期间发生变化，就拒绝该次构建。

`--watch` 每 0.5 秒检查一次。其输入集合包括模式文件、源码文件，以及源码目录下的所有 `*.l` 文件，包括本地导入文件。外部导入根目录不在监听范围内。构建失败会报告到 stderr，监听仍会继续。只有观察到的输入状态发生变化时才会重试，不会针对未变化的失败状态反复构建。中断监听会正常退出。

此监听器负责发布规则包，不会更新已经运行的 `LogicDB`；请使用运行时重载，或下文介绍的适配器监听。准备示例项目时会复制其随附的规则包，因此编译到 `/tmp` 不会改变准备好的游戏。如何直接编译到准备好的游戏所选规则包，请参阅[快速入门](../QUICKSTART.zh-CN.md)。

## 运行时 API

```python
from relation_rules import LogicDB

logic = LogicDB("examples/palace/game/relations.rules.json")
try:
    logic.add("Sponsor", character="hero", location="archive")
    allowed = logic.has("CanEnter", character="hero", location="archive")
    rows = logic.query("CanEnter", character="hero")
finally:
    logic.close()
```

`LogicDB(rules, *, backend=None, mode="cached", on_snapshot=None)` 创建一个空的内存世界。`rules` 是规则包路径或 `RuleSet`。如果提供 `backend`，它会检查规则包是否面向该后端，而不会覆盖规则包的后端。`mode` 选择计算行为。`on_snapshot` 是可选的同步回调，在发生变更的提交之后接收映像 `bytes`。

一个 `LogicDB` 表示一个同步世界。请通过公共操作管理它；原始 SQL、访问私有引擎、异步访问以及跨线程共享世界均不属于公共契约。

### 事实与查询

| 方法 | 结果与行为 |
| --- | --- |
| `add(name, /, **values)` | 断言一个完整事实；返回 `None`。忽略重复元组；键冲突会失败。 |
| `remove(name, /, **filters)` | 删除所有匹配的事实；返回 `None`。至少需要一个筛选条件。 |
| `batch()` | 上下文管理器，产生同一个 `LogicDB`；将写入合并为一个事务，最多发布一次快照。 |
| `query(name, /, **filters)` | 返回由独立行字典组成的列表。不提供筛选条件时返回所有行。行顺序未作规定。 |
| `has(name, /, **filters)` | 使用一行的结果上限，返回是否存在匹配行。不提供筛选条件时检查该关系是否包含任何行。 |

这四个方法的关系名都只能按位置传入。因此 `name` 和 `self` 等列名仍可用作值或筛选条件：

```python
# For a schema declaring Person(name: text, self: text):
logic.add("Person", name="hero", self="origin")
assert logic.has("Person", name="hero", self="origin")
```

筛选条件使用 SQL 相等比较，并以逻辑 AND 组合。`None` 匹配派生结果中的空值。这些是数据库比较，而非 Python 缓存键比较。公共接口不提供排序、范围筛选、连接、更新或任意 SQL 参数；请将这些推导放入规则，在展示需要顺序时，由应用代码对返回的行排序。

只能添加或删除已声明的事实。未知关系、未知列、不完整的添加以及不带筛选条件的删除都会抛出 `ValueError`。将关系名作为关键字而不是位置参数传入，属于 Python 参数使用错误，会抛出 `TypeError`。

### 事务与无操作

在批次外，每次 `add()` 或 `remove()` 都会启动自己的批次。在批次内，写入会累积，直到上下文成功退出。请在进入批次前读取条件，然后在批次结束后查询已提交的世界：

```python
# For the keyed Member schema shown above:
with logic.batch():
    logic.remove("Member", character="hero")
    logic.add("Member", character="hero", faction="scholars")
members = logic.query("Member", character="hero")
```

如果异常传播到批次之外，该批次的事实写入和任何立即执行的输出重建都会回滚。请在批次外捕获数据库操作失败，而不是继续使用已经失败的事务。

没有 SQL 行发生变化的批次不会使输出失效，也不会发布快照。空批次、重新断言相同元组，以及删除不存在的匹配项都属于这种无操作。先更改行再撤销这些更改的序列仍然算作发生变更的批次；运行时不会比较最终事实集合来检测净变化为零的工作。

不允许嵌套批次。`query()`、`has()`、`snapshot()`、`restore()`、重载操作、`stats()`、`close()` 和适配器安装都要求世界处于空闲状态；在批次或快照发布期间调用会抛出 `RuntimeError`。快照回调不能重入这些操作，也不能开始新的写入。`describe()` 只检查声明，不会计算规则。

### 检查与关闭

| 方法 | 契约 |
| --- | --- |
| `describe(name)` | 返回独立的元数据：`name`、`kind`（`"facts"` 或 `"derived"`）、声明的列、存在时的键或 SQL、直接读取的 `reads`，以及只包含派生关系的 `dependencies`。不会计算规则。 |
| `stats()` | 返回 `mode`、`backend`、`cached_relations`、`materializations`、`materialization_seconds` 和 `snapshot_bytes`。不会执行规则查询或创建映像。 |
| `close()` | 释放世界和数据库资源。重复调用无害。之后，需要世界的操作会抛出 `RuntimeError`。 |

`cached_relations` 列出当前有效的惰性缓存输出。`materializations` 按关系统计成功完成的惰性物化次数；`materialization_seconds` 衡量惰性填充工作，可能包含失败尝试所做的工作。这些诊断值不统计所有立即执行或实时执行的 SQL。当没有保留映像时，`snapshot_bytes` 为零；它不估计进程总内存或 Ren’Py 回滚历史。诊断计数器属于 `LogicDB` 实例，不会随事实映像一起恢复。

## 查询模式

三种模式提供相同的事实和声明输出类型，但计算成本和数据相关错误出现的时点不同。

| 模式 | 准备阶段 | 事实变化后 | 读取行为 |
| --- | --- | --- | --- |
| `cached`（默认） | 准备声明和依赖图；派生表按需创建。 | 使受影响的派生关系失效。 | 构建请求的关系及其所需的失效依赖，然后复用有效结果。 |
| `materialized` | 按依赖顺序创建并填充所有派生表。 | 在事实所在的同一事务内重新填充受影响的输出。 | 读取已存储的派生行。 |
| `live` | 创建派生视图。 | 提交事实，不重建缓存输出。 | 每次读取时由数据库计算视图。 |

失效以**关系为粒度**。更改 `Sponsor` 的一行，可能使依赖 `Sponsor` 的输出的所有行及其下游输出失效。运行时不跟踪单个角色、筛选条件或发生变化的结果行。无关输出保持有效。已声明的否定依赖同样重要：添加一个原先不存在的阻断事实，也可能改变答案。

即使筛选范围很小，缓存模式下的 `has()` 仍会物化整个所需关系。之后使用不同筛选条件的查询会共享该物化结果。每次读取都在数据库中应用筛选条件；缓存不会为每组筛选条件单独存储答案。

在物化模式下，受影响输出的重建失败会拒绝事实事务。在缓存或实时模式下，事实提交可能成功，但之后读取新值时可能失败。失败的惰性读取不会将部分构建的依赖标记为有效，因此修正事实后可以再次尝试。重载在所有模式下都会基于当前事实预先验证每个输出。

工作负载测量及其局限请参阅[基准测试（英文）](../benchmarks/README.md)。

## 快照与重载

**快照**是原生数据库映像 `bytes`，包含事实以及格式和模式元数据。它不包含派生表、视图、缓存、规则 SQL 或其余游戏状态。SQLite 使用原生序列化或备份；DuckDB 复制原生事实数据库映像。两种实现都可能在复制时使用临时文件。

| 方法 | 契约 |
| --- | --- |
| `snapshot()` | 返回当前映像，必要时创建。没有发生变更的提交时，重复调用会复用保留的同一个 `bytes` 对象。 |
| `restore(image)` | 从快照 `bytes` 准备一个替代世界，验证后再切换到它。 |
| `restore(None)` | 在当前规则和模式下，将世界替换为空事实世界。具有常量输出的规则仍可返回行。 |
| `reload_rules(rules=None)` | 保留当前事实，验证并预检新规则，然后一起替换世界和规则。 |
| `reload_if_changed()` | 比较所选规则包文件的字节与上次加载的字节；成功安装替代规则时返回 `True`，否则返回 `False`。 |

```python
past = logic.snapshot()
logic.remove("Sponsor", character="hero", location="archive")
logic.restore(past)
assert logic.has("Sponsor", character="hero", location="archive")
```

没有快照接收函数的普通提交不会复制整个数据库。发生变更的提交会丢弃保留的映像，下一次显式调用 `snapshot()` 时才捕获新事实。读取和惰性物化不会改变事实映像。无操作提交会保留已有映像。

`restore()` 要求参数为 `bytes` 或 `None`；其他值会抛出 `TypeError`。无效映像、不兼容的元数据或不匹配的原生事实模式会抛出 `RuleError`，并保留当前世界。映像必须与后端和事实模式匹配，包括键和列类型。不支持自动迁移或跨后端交换。调整 JSON 字典顺序不会改变模式标识；更改键中列的声明顺序会改变其声明。

### 快照接收函数

使用 `on_snapshot=callback` 时，每个发生变更的批次都会提交事实、创建一个映像，并同步调用接收函数。如果创建映像或回调抛出异常，运行时会恢复之前保留的事实映像，并重新抛出错误。新建实例以空世界为初始基线。Ren’Py 安装过程会在绑定接收函数前捕获基线映像。

回调应将提供的映像作为一次发布来接收并存储。回调失败后，运行时能够恢复自身的事实，但无法撤销回调已执行的任意外部工作。显式 `restore()` 和规则重载不会调用接收函数；无操作批次也不会调用它。

### 替换规则

`reload_rules()` 接受新的规则包路径或 `RuleSet`。不传参数时，它会重新读取当前选择的路径。通过 `RuleSet` 创建的实例在显式提供路径之前没有路径；此时无参数重载和文件监听会抛出 `ValueError`。

重载要求后端和事实模式标识相同。它可以更改派生声明、SQL 和依赖。候选世界会先根据当前事实计算所有新输出，再替换当前活动世界。无效规则包和与具体数据相关的预检错误都会保留旧事实和旧规则。从路径成功重载后，该路径也会成为后续监听的路径；从 `RuleSet` 重载则会移除源码路径。

快照存储事实，不会冻结规则逻辑。成功重载后恢复较早的快照，会使用**当前**规则来计算该快照的事实。因此，快照兼容性允许派生规则变化，却不会保留旧版本故事的资格判断逻辑。规则更改和事实模式迁移是不同的操作；模式变化需要创建新世界，或由应用在此 API 之外管理转换。

`reload_if_changed()` 监听编译后的文件，而非规则源码。它比较的是内容，不是修改时间。重载失败会保留上次加载的内容标记，因此调用方修复文件后可以重试。文件系统错误会以 `OSError` 传播。

## Ren’Py 集成

请按[快速入门](../QUICKSTART.zh-CN.md)准备依赖和规则包。最小绑定使用一个 `default` store 变量，并在初始化期间安装一次：

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

准备好的游戏通过 `python-packages` 提供原生依赖；将它添加到 `sys.path` 后，Python 才能发现这些模块。应在新游戏开始时、默认变量处理已经恢复空事实世界之后记录初始事实。不要只在初始化阶段添加它们，因为默认变量处理后的回调可能会替换那个世界。

`install_renpy(config, snapshot_variable="logic_snapshot", *, watch_rules=False)` 接受以下参数：

| 参数 | 含义 |
| --- | --- |
| `config` | 用于接收生命周期回调的 Ren’Py 配置对象。 |
| `snapshot_variable` | `renpy.store` 上的属性名；请使用 `default … = None` 声明对应变量。 |
| `watch_rules` | 在交互时注册编译规则包的轮询；默认为 `False`。要求实例具有规则包路径。 |

安装过程会捕获当前基线映像，绑定一个向 `renpy.store.<snapshot_variable>` 赋值的快照接收函数，并向 `config.after_default_callbacks` 追加回调。该回调恢复当前 store 映像；如果变量不存在或为 `None`，则恢复空事实。Ren’Py 存档和回滚保留 store 的值；当其生命周期恢复该值时，回调会据此重建数据库。被保存的状态不是数据库连接本身。

使用相同配置、变量和监听设置重复安装无害。将同一实例重新绑定到不同设置会抛出 `RuntimeError`。已有 `on_snapshot` 接收函数的实例不能同时安装此适配器，否则会抛出 `ValueError`。没有公开的适配器卸载操作；请在游戏生命周期内保持绑定实例存活。

### 开发期间的监听

`watch_rules=True` 向 `config.interact_callbacks` 添加回调。它只在 `config.developer` 为真且实例具有源码路径时轮询。它调用 `reload_if_changed()`，不会编译 Logica，也不会使用后台定时器轮询。

请另行运行编译器的 `--watch`，将编辑内容转换为已验证的规则包。重载出现 `RuleError` 或 `OSError` 时，适配器会通过 Ren’Py 记录失败、通知开发者，并继续使用之前的世界。相同错误消息不会重复报告，直到一次成功轮询清除错误状态。该监听器不捕获其他异常类别。

[Palace 游戏](../examples/palace/game/script.rpy)演示了绑定和检查；其[引擎测试用例](../examples/palace/game/testcases.rpy)覆盖存档／读档、回滚、新游戏和重载。这些是适配器使用场景，并非无关游戏数据的自动存档格式。

## 兼容性

以下范围应分别理解：

| 范围 | 声明或选择的目标 |
| --- | --- |
| 核心项目元数据 | Python `>=3.11,<3.15`。 |
| 仓库开发解释器 | Python `3.12`，由 `.python-version` 选择。 |
| 项目准备工具 | Linux x86_64、Python `3.12`、面向 `x86_64-manylinux_2_28` 的 wheel；可选的 SDK 探测会检查其解释器。 |
| 发布构建工具 | 固定版本的 Ren’Py SDK `8.5.3.26051504`。 |

准备好的 Linux x86_64／Python 3.12 环境是自动化集成的目标。元数据中较宽的版本范围不代表已支持所有 Ren’Py 平台或 Python 版本的部署。其他操作系统、架构和 SDK 版本仍属于未经验证的目标。引擎检查和发布证据流程请参阅[维护指南（英文）](maintaining.md)。

运行时依赖 SQLAlchemy `2.0.43` 及兼容的 SQLite 驱动，或可选的 DuckDB `1.5.6` 与 duckdb-engine `0.17.0` 组合。SQLite 是默认后端。运行时先尝试 `sqlite3`，再尝试 `pysqlite3`；项目准备使用的依赖组提供固定版本的 Linux `pysqlite3-binary`。编译使用固定版本的 Logica `1.3.1415926535897`；执行编译后的规则包不需要 Logica。

规则包版本 `1` 和快照元数据版本 `2` 是不同的格式。快照是后端原生映像，因此规则包版本或 Python 元数据不能证明它能在数据库库版本变化后长期保持可移植性。应将后端／模式兼容性和部署版本验证，与普通规则重载分别考虑。

## 故障排查

`RuleError` 是 `ValueError` 的子类，用于表示无效或不兼容的规则包、编译失败，以及快照／重载准备失败。它不会包装所有运行时失败。恢复或重载的候选世界被拒绝时，现有世界会保留；普通数据库错误遵循上述事务和模式行为。

| 症状 | 原因与恢复方法 |
| --- | --- |
| `No SQLite driver` | 解释器既没有可用的 `sqlite3`，也没有可用的 `pysqlite3`。请使用[快速入门](../QUICKSTART.zh-CN.md)中的受支持项目准备流程，它会安装 Linux 驱动。 |
| `DuckDB backend requires the uv extra: --extra duckdb` | 使用 DuckDB 可选依赖运行，或使用 `--backend duckdb` 准备项目。`duckdb` 和 `duckdb-engine` 缺一不可。 |
| `Logica is not installed in this Python environment` | 请在锁定依赖的开发环境中编译，不要在只包含运行时依赖的准备好游戏中编译。 |
| 规则包后端与请求的后端不同 | 选择为该后端编译的规则包，或使用 `--backend` 重新编译。构造函数的 `backend` 参数只检查目标。 |
| `lacks dependencies`、未声明的关系或依赖环 | 使用 `compile_rules.py` 重新构建；修正关系拼写和导出关系间的依赖环。不要根据 SQL 猜测依赖边。 |
| 输出列导致构建失败 | 使派生模式列与 Logica 的命名输出列一致。修复源码／模式后重新构建；之前发布的规则包仍可使用。 |
| `add(...) requires every field` 或未知字段 | 使用声明中的准确列名提供完整事实。筛选条件可以只用部分列，添加则不可以。 |
| 已有键对应的不同元组触发数据库完整性错误 | 在同一个批次中删除旧的带键行并添加替代行。只有完全相同的元组才会被忽略。 |
| `remove() requires filters` | 至少提供一个已声明列的筛选条件；API 不提供无筛选条件的删除操作。 |
| 批次或快照发布期间禁止操作 | 将查询和生命周期操作移到批次前后。保持快照接收函数不可重入。 |
| 查询或提交时 SQL 失败 | 检查输入值和规则表达式。缓存／实时模式的错误可能在读取时出现；立即重建的错误会拒绝写入。这些异常可能来自 SQLAlchemy／数据库，而非 `RuleError`。 |
| `Hot reload cannot change the fact schema` | 使用新模式创建新世界。现有快照不会自动迁移。 |
| 无效映像，或快照模式／后端不匹配 | 恢复来自相同后端和事实模式的映像。验证拒绝映像时，当前世界会保留。 |
| 源码编辑未改变游戏 | 确认编译器构建的是游戏实际选择的规则包，再重载它。编译器监听和适配器监听是两个独立步骤。 |
| 监听中的构建／重载失败 | 查看编译器 stderr 或 Ren’Py 的 `log.txt`，修复源码／模式或规则包后重新构建。最后一次有效的规则包／规则会继续生效。适配器轮询要求开发者模式。 |
| `LogicDB is closed` | 创建新实例；已关闭的世界不能重新打开。 |

无效的方法参数通常抛出 `ValueError` 或 `TypeError`；不允许的生命周期操作抛出 `RuntimeError`；缺失驱动抛出 `ImportError`；文件系统访问可能抛出 `OSError`。请处理与具体操作相关的异常类别，而不是在每次调用外只捕获 `RuleError`。
