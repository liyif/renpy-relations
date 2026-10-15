# Ren’Py Relations

[English](README.md) · [简体中文](README.zh-CN.md)

一个支持关系事实与编译后 Logica 规则的可嵌入 Python 库，提供可选的 Ren’Py 集成。

故事中的条件常常被多个事件共用：进入某个地点的资格、对秘密的了解，或先前作出的选择。Ren’Py Relations 让你为这些条件命名，并用规则组合它们。行动改变事实，脚本查询当前可用的行动和事件。同一套核心也可以用于普通 Python 程序。

[Logica](https://github.com/evgskv/logica) 在开发阶段把规则编译成 SQL，[SQLite](https://www.sqlite.org/about.html) 或 DuckDB 在运行时存储事实并执行查询。Ren’Py 适配器将事实快照接入存档、读档和回滚。

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

完成[快速入门中的环境准备](docs/quickstart.zh-CN.md#准备环境)后，从源码根目录运行。这个例子不需要手写 SQL。

```text
world.l + schema.json
        │ renpy-relations-compile (during development)
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
| 嵌入普通 Python 程序 | [Python 集成指南](docs/python.zh-CN.md) |
| 学习概念，并在 Python 和 Ren’Py 中运行 Palace | [快速入门](docs/quickstart.zh-CN.md) |
| 集成运行时，或查阅编译器、快照和重载的行为约定 | [参考手册](docs/reference.zh-CN.md) |
| 游玩或研究一个完整的中文叙事示例 | [Tidelight 指南（英文）](examples/tidelight/README.md) |
| 理解测试负载，并复现一次小规模性能测试 | [基准测试指南（英文）](benchmarks/README.md) |
| 修改、验证、准备可运行项目或发布项目 | [维护指南（英文）](docs/maintaining.md) |

## 安装

在源码目录中运行：

```sh
uv sync --locked
```

安装 wheel 或嵌入普通应用，请阅读 [Python 指南](docs/python.zh-CN.md)；准备游戏项目，请按 [Ren’Py 快速入门](docs/quickstart.zh-CN.md#准备并运行-palace)操作。开发环境使用 Python 3.12，支持环境和驱动版本见[参考手册](docs/reference.zh-CN.md#兼容性)。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| `src/renpy_relations/` | Python 包：运行时、编译器和 Ren’Py 适配器。 |
| `docs/` | 教程、参考手册和维护指南。 |
| `examples/` | Python 权限、Palace 和 Tidelight 示例。 |
| `tools/` | 游戏部署、引擎检查和发布工具。 |
| `tests/`、`benchmarks/` | 自动检查和性能实验。 |

## 技术基础与许可证

进一步学习可阅读官方 [Logica 用户指南](https://logica-lang.github.io/usrguide/)和 [SQLite 概述](https://www.sqlite.org/about.html)。Logica 在开发阶段编译规则；游戏运行编译后的 SQL，不需要 Logica 编译器。

项目代码、示例脚本、文档和原创示例数据采用 [MIT 许可证](LICENSE)。依赖项、Tidelight 字体和随发行版分发的 Ren’Py 运行时保留各自的许可证，详见[第三方声明](THIRD_PARTY_NOTICES.md)。
