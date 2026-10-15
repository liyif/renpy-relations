# Ren’Py Relations

将关系事实与声明式规则接入 Ren’Py 的软件开发实验。游戏行动写入事实，Logica 在开发时编译规则，SQLite 或 DuckDB 在运行时回答查询。

这个实验探索两个问题：关系查询能否清楚地表达复杂的资格与剧情条件，以及它能否承担跨场景编排，同时与存档、回退和规则修改保持一致。

```prolog
CanEnter(character: c, location: l) distinct :-
  Sponsor(character: c, location: l);
```

```python
with logic.batch():
    logic.add("Sponsor", character="hero", location="archive")

if logic.has("CanEnter", character="hero", location="archive"):
    # 由游戏脚本提供行动或演出；查询本身没有剧情副作用。
    ...
```

运行时集中在 `renpy_relations.py`，使用 SQLAlchemy 和数据库驱动。Logica 仅用于构建，不随游戏运行；规则包携带 Logica 编译时输出的依赖边。

## 试玩与接入

[五分钟上手](QUICKSTART.md)包含直接试玩、从源码启动和接入自己的游戏。

- [palace](examples/palace/game/script.rpy)：小型接入样例，展示阵营、担保、知识、一次性奖励及事实撤销。
- [《潮汐替我们保管》](examples/tidelight/README.md)：完整中文短篇，19 个事件、三位成年女主角、五个结局。时间、位置、线索和双方约定决定当前相遇；场景结束后重新查询可发生的事件。

## 能力与边界

- SQLite 与可选 DuckDB 后端；`cached`、`live`、`materialized` 三种查询模式。
- Logica 在构建期把每条规则读取的关系写入规则包，运行时据此按已变更的事实关系传播缓存失效。
- 事实事务、原生数据库快照、原子恢复与规则热重载。
- Ren’Py 存读档和回退接入；开发模式可观察关系与重载规则。

0.2.0 是实验版本。验证环境为 **Linux x86_64、Ren’Py 8.5.3、内置 Python 3.12**；其他平台的驱动与打包尚未验证。API 和格式可能变化。

运行方式同步、单线程。失效粒度到关系，不到事实行；Ren’Py 每次有效提交保存完整事实镜像。规则 SQL 是可信构建产物，不是任意 SQL 的安全沙箱。不同后端或事实 schema 的快照不能互换，没有存档迁移工具。

## 性能实验

[Benchmark](benchmarks/README.md)分别测量千至万个派生条件、快照与历史提交、大事实集压力和依赖长链。报告记录当前源码与环境，区分普通事务和绑定历史的事务；后端测量不等同于完整游戏帧率。

各项结果具体测了什么，见[结果阅读说明](benchmarks/READING_RESULTS.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [QUICKSTART](QUICKSTART.md) | 试玩、安装与最小接入 |
| [USAGE](USAGE.md) | 规则编译、接口、查询模式和开发重载 |
| [DESIGN](DESIGN.md) | 当前架构、语义与取舍 |
| [CONTRIBUTING](CONTRIBUTING.md) | 开发环境、测试和修改样例 |
| [RELEASE](RELEASE.md) | 构建、校验与分发 |
| [MIGRATION](MIGRATION.md) | 规则依赖来自 Logica 编译 |
| [CHANGELOG](CHANGELOG.md) | 版本变化 |

代码、文档、示例剧本和原创数据使用 [MIT](LICENSE)。字体与依赖保留各自许可证，见 [第三方说明](THIRD_PARTY_NOTICES.md)。可试玩包保留 Ren’Py 的 `LICENSE.txt`；其组件许可与源码入口见 [Ren’Py 许可说明](https://www.renpy.org/doc/html/license.html)。
