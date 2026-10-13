# Ren’Py Relations：设计

这是把关系推导接入 Ren’Py 的小型实验。目标是检验规则表达与集成成本，运行时保持一个 Python 文件，Logica 只在构建阶段使用。

## 1. 模块与接口

- `renpy_relations.py`：规则集读取与校验、事实事务、派生查询、快照、规则重载、Ren’Py 接入。
- `compile_rules.py`：调用真正的 Logica 编译器，把 `.l` 与关系声明编译成可直接加载的 JSON 规则集。
- `check_renpy.py`：启动真实 SDK 的示例测试、读取完整结果并回收测试进程；处理 8.5.3 测试结束后的循环问题，不修改 SDK。
- `examples/palace`：阵营／担保／知识／奖励组成的完整示例，同时是接入验证载体。

调用方使用关系名，不必在脚本中再定义一遍 SQLAlchemy Table：

```python
logic = LogicDB("game/relations.rules.json", mode="cached")
with logic.batch():
    logic.add("Member", character="hero", faction="scholars")
logic.has("CanEnter", character="hero", location="archive")
logic.query("CanEnter", character="hero")
logic.reload_rules()  # 从原文件重新读取
```

SQLAlchemy Core 用于数据库定义和参数绑定；不提供可写的公开 engine 接口。事实修改必须经过事务接口，才能保证缓存和存档一致。

## 2. 规则集

构建输入分为 `.l` 和一个小型 schema JSON。Schema 声明事实、导出关系、字段类型及可选事实主键；事实默认按完整元组去重，事实字段不可为空。第一版类型为 `text`、`integer`、`real`、`boolean`。

编译脚本使用固定版本 Logica 的官方解析器和 SQL 生成器。每个导出谓词单独编译，其他导出谓词按外部关系处理，内部辅助谓词正常展开。这样导出关系之间的依赖会留在 SQL 中，能够共享缓存与类型投影。事实不能同时在 `.l` 中定义。构建前后检查本地输入内容，避免编辑途中发布混合版本。

产物包含格式名称、格式版本、事实 schema、派生关系 schema 与各自的 SQL，附带源文件及编译器信息。运行时不依赖 Logica，不从规则集中加载 Python 代码。

第一版接受能编译成单条、确定性的 SQLite SELECT 的规则，包括适用的 WITH 查询。支持 SQLite 自带函数／JSON 表函数，以及 Logica 否定查询使用的纯函数 `MagicalEntangle(x, y) = x`。其他自定义 SQLite 函数或多步执行输出会给出错误；不承诺完整 Logica 支持。时钟与随机结果由游戏写成事实，规则不能直接读取系统时钟或数据库随机数。

派生输出按声明类型显式转换；TEMP VIEW 与 TEMP TABLE 使用相同的投影，避免查询比较语义因物化模式不同而变化。布尔输出归一化为 0／1，NULL 保留。

运行时使用 SQLite 自身解析查询，检查输出列、函数和实际读取的关系，建立派生关系依赖顺序。不手写 SQL 依赖解析器；跨派生关系的循环依赖拒绝加载。查询内部的递归 CTE 由 SQLite 执行。

## 3. 缓存重写

删除 Python 查询结果字典和过滤参数缓存键。三个模式共用相同关系接口：

| 模式 | 派生数据位置 | 计算时机 |
| --- | --- | --- |
| `live` | SQLite TEMP VIEW | 每次查询 |
| `materialized` | SQLite TEMP TABLE | 初始化和事实提交时 |
| `cached`（默认） | SQLite TEMP TABLE | 某派生关系首次被读取时 |

`cached` 按完整派生关系缓存，先准备其派生依赖，再计算目标关系。过滤、NULL 比较、类型转换和存在性判断统一交给 SQLite；`query()` 与 `has()` 共享缓存。

- 有实际事实变更的成功事务：所有派生缓存失效。
- 失败事务：事实、物化结果及原有缓存有效性一起保留。
- 恢复快照、成功重载规则：缓存重新建立。
- 查询返回独立的 Python 行字典，调用方修改结果不影响缓存。
- 缓存大小由各派生关系的数据量决定，不随过滤条件的组合数量增长。

第一版采用全局失效；不做 IVM 或按事实变化推导精确失效范围。事务内禁止读取派生结果，避免读取处于中间状态的世界。

## 4. 原子性与快照

事实事务包含事实写入以及 eager 模式的派生重建。事务失败时一起回滚；成功后发布新的事实快照。快照发布失败则恢复最后接受的事实状态。

快照保存事实及事实 schema 标识，不保存 TEMP 数据。采用带格式版本的压缩 JSON 字节串，而非 SQLite 原始内存镜像：真实 Ren’Py 8.5.3 SDK 没有 sqlite3，外置 pysqlite3 驱动也没有 serialize／deserialize。逻辑事实快照避免依赖这一驱动扩展。恢复前校验 schema；本轮不做存档迁移。规则版本不绑定存档：相同事实可以由修改后的规则重新解释。

恢复和重载都先构建候选内存数据库，成功后替换现有数据库。失败时当前数据库继续可用。事实 schema 不变时允许派生关系增加、删除和修改；事实 schema 改变需要新游戏／新的 LogicDB。

## 5. 规则热重载

`reload_rules(path=None)` 保留当前事实，读取并验证完整新规则集，在当前事实上预执行所有派生关系，全部成功才切换。事务中禁止重载。编译器也采用临时文件加原子替换，失败不覆盖上一次可用产物。

开发时可以启用编译器 `--watch`，观察规则目录下 `.l` 与 schema 变化。Ren’Py 可以在开发模式的交互开始时检查编译产物变化，也可以手动触发重载。观察的是编译产物；游戏中不启动编译器或后台线程。自动重载失败保留旧规则并报告错误。

规则重载不改变事实，也不创建剧情历史记录。之后回滚或读旧档时使用当前规则解释恢复的事实。

## 6. Ren’Py 接入

Ren’Py store 中只保存 `default logic_snapshot = None` 对应的不可变字节串；数据库对象放在初始化变量中。每次事实提交更新该字节串。

`after_default_callbacks` 在启动、读档及回滚后恢复事实，重建派生对象。绑定需要可重复调用而不重复注册。开发观察回调只在显式启用且开发模式开启时运行。

规则只计算条件。剧情跳转、奖励发放和一次性效果由脚本执行，并以事实记录结果。查询不能触发这些效果。

## 7. 验证范围

通过公开接口验证：三种模式结果一致；缓存失效与回滚；批量事务失败；快照恢复；正确／错误规则热重载；schema 不兼容；真实 Logica 编译产物加载；构建失败保留旧文件；Ren’Py 启动／读档／回滚的状态同步。

示例展示多个规则组合、事实撤销、一次性奖励和回滚。记录在实际可用的 Ren’Py 环境中完成了哪些验证，不把模拟回调等同于真实引擎验证。

## 8. 本轮范围

补充上述能力、运行说明、uv 项目声明／锁文件与针对关键行为的测试。保留实验性质，不添加 CI、发布流水线、独立规则编辑器、增量维护或存档迁移框架。旧 `LogicaBackendForRenpy` 更名为 `RenpyRelations`，原型接口允许随本轮设计调整。

开发使用 Python 3.12，与本次 Ren’Py SDK 一致。SQLAlchemy 固定为验证过的 2.0.43：较新的 2.0.54 与 2.1 均使用了 SDK 裁剪掉的 sysconfig 接口。标准 Python 优先用 sqlite3；缺少时加载 pysqlite3 并显式传给 SQLAlchemy。本次验证 Linux x86_64 的外置驱动，不把这等同于所有 Ren’Py 发行平台都已兼容。

参考：

- [Logica 官方仓库](https://github.com/EvgSkv/logica)
- [Ren’Py after_default_callbacks](https://www.renpy.org/doc/html/config.html#var-config.after_default_callbacks)
- [Ren’Py 存档、读档与回滚](https://www.renpy.org/doc/html/save_load_rollback.html)
