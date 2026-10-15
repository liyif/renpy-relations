# Ren’Py Relations

[English](README.md) · [简体中文](README.zh-CN.md)

Ren’Py Relations 是一项实验：用关系事实和声明式规则表达故事中共用的条件。设想一座档案馆，某个派系的成员或获得担保的人都可以进入。多个剧情事件也会依赖档案馆的访问权限、某个秘密以及先前行动的记录。为这些条件命名并加以组合，可以把修改集中在一处，而场景脚本只需查询当前有哪些行动或事件符合条件。

[Logica](https://github.com/evgskv/logica) 提供规则语言和 SQL 编译器。[SQLite](https://www.sqlite.org/about.html) 是默认的嵌入式数据库引擎，负责存储事实，并通过连接和筛选执行编译后的查询。行动改变事实，规则推导答案，脚本选择符合条件的事件并执行其效果。Ren’Py 负责对话、菜单、画面呈现和玩家交互。例如，奖励查询可以说明某项奖励现在可领取，但实际发放奖励并记录领取行为，仍要由脚本完成。

这项实验想探索：这样的做法能否让共用条件更容易理解和修改，能否让当前状态决定事件的发生顺序，同时在存档、回滚和规则变更后保持一致。尝试这一方案意味着为游戏增加编译器、数据库驱动和集成工作。[快速入门](QUICKSTART.zh-CN.md) 会带你实际走通流程；[基准测试指南（英文）](benchmarks/README.md) 则说明如何衡量它的成本。

## 一个小例子

项目自带的 [Palace 规则](examples/palace/world.l) 根据担保或派系成员身份推导档案馆的访问权限：

```python
from renpy_relations import LogicDB

logic = LogicDB("examples/palace/game/relations.rules.json")
try:
    logic.add("Sponsor", character="hero", location="archive")
    print(logic.query("CanEnter", character="hero"))
    # [{'character': 'hero', 'location': 'archive'}]
finally:
    logic.close()
```

完成[快速入门中的环境准备](QUICKSTART.zh-CN.md#准备环境)后，从源码根目录运行。这个例子不需要手写 SQL。

```text
world.l + schema.json
        │ compile_rules.py (during development)
        ▼
backend-specific JSON rule bundle
        │ LogicDB (during the game)
        ▼
facts → derived answers → script choices and effects
        │ Ren’Py adapter publishes fact snapshots
        ▼
Ren’Py snapshot variable → save / load / rollback
```

运行时默认使用 `cached` 模式：首次查询时构建派生关系，事实发生变化后使受影响的结果失效。你可以选择 SQLite 或 DuckDB，二者各自使用对应的编译规则包。[参考手册](docs/reference.zh-CN.md) 介绍了其他查询模式及其取舍。

## 选择入口

| 目标 | 阅读 |
| --- | --- |
| 学习概念，并在 Python 和 Ren’Py 中运行 Palace | [快速入门](QUICKSTART.zh-CN.md) |
| 集成运行时，或查阅编译器、快照和重载的行为约定 | [参考手册](docs/reference.zh-CN.md) |
| 游玩或研究一个完整的中文叙事示例 | [Tidelight 指南（英文）](examples/tidelight/README.md) |
| 理解测试负载，并复现一次小规模性能测试 | [基准测试指南（英文）](benchmarks/README.md) |
| 修改、验证、准备可运行项目或发布项目 | [维护指南（英文）](docs/maintaining.md) |

## 环境与安装

请使用源码检出目录及其 `uv.lock`；本项目没有定义通过已发布软件包进行安装的流程。项目元数据允许 Python `>=3.11,<3.15`，开发流程选择 Python 3.12。项目准备工具面向使用 Python 3.12 Ren’Py SDK 的 Linux x86_64 环境；发布工具固定使用 Ren’Py `8.5.3.26051504`。其他部署目标需要单独验证。具体范围见[兼容性说明](docs/reference.zh-CN.md)。

在 Ren’Py 中使用时，请按[准备并运行 Palace](QUICKSTART.zh-CN.md#准备并运行-palace)操作。准备过程会把运行时、SQLAlchemy 和所选数据库的原生驱动安装到 `game/python-packages`。如果运行时报出 **“No SQLite driver”**，请使用支持的 SDK 按此流程准备项目，而不要只把 `renpy_relations.py` 复制进游戏。

## 技术基础与许可证

进一步学习可阅读官方 [Logica 用户指南](https://logica-lang.github.io/usrguide/)和 [SQLite 概述](https://www.sqlite.org/about.html)。Logica 在开发阶段编译规则；游戏运行编译后的 SQL，不需要 Logica 编译器。

项目代码、示例脚本、文档和原创示例数据采用 [MIT 许可证](LICENSE)。依赖项、Tidelight 字体和随发行版分发的 Ren’Py 运行时保留各自的许可证，详见[第三方声明](THIRD_PARTY_NOTICES.md)。
