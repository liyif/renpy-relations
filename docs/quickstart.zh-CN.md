# 快速入门：Palace

[English](quickstart.md) · [简体中文](quickstart.zh-CN.md) · [项目概览](../README.zh-CN.md) · [参考手册](reference.zh-CN.md)

Palace 是一个小型世界，包含档案馆的访问权限、一个秘密，以及一项只能领取一次的奖励。本指南先在普通 Python 环境中运行它，再为 Ren’Py 准备同一个示例。只需掌握基础 Python，无须 SQL 或数据库经验。

## 事实、表与规则

**关系（relation）**是一种表格形状的数据。在这里，它并不局限于角色之间的关系数值：`Sponsor` 记录谁获得了进入哪个地点的担保。每一**行（row）**记录一个事实，每个有名称的**列（column）**存放该事实的一部分：

| character | location |
| --- | --- |
| hero | archive |

这一行表示 `hero` 获得了进入 `archive` 的担保。Python 用 `logic.add("Sponsor", character="hero", location="archive")` 记录它。**数据模式（schema）**声明有哪些关系，以及它们的列名和类型。[Palace 模式文件](../examples/palace/schema.json)中的这段内容声明了两个文本列：

```json
{
  "facts": {
    "Sponsor": {"columns": {"character": "text", "location": "text"}}
  }
}
```

这里只展示了片段，不要用它替换完整模式文件。完整文件还声明了另外四个事实关系和三个派生关系：

| 关系 | 含义 | 由谁提供 |
| --- | --- | --- |
| `Member` | 角色属于某个派系 | 游戏行动 |
| `FactionAccess` | 派系可以进入某个地点 | 游戏初始化或行动 |
| `Sponsor` | 角色获得了进入某个地点的担保 | 游戏行动 |
| `Knows` | 角色知道某个秘密 | 游戏行动 |
| `RewardClaimed` | 角色已经领取了某项奖励 | 游戏行动 |
| `CanEnter` | 角色当前拥有访问权限 | 规则 |
| `CanInvestigate` | 访问权限和已知信息允许角色展开调查 | 规则 |
| `CanClaimReward` | 调查奖励仍可领取 | 规则 |

事实是输入。**派生答案**由这些输入和规则推导而来；你应查询它们，而不是插入它们。**查询（query）**用于获取匹配的行，或判断是否存在匹配的行。模式也可以声明可选的键，用来唯一标识一个事实行；Palace 使用完整元组，没有额外声明键。

数据库负责存储表并执行查询。SQL 是编译器生成的查询语言。[SQLite](https://www.sqlite.org/about.html) 运行在游戏进程内，因此不需要配置独立的数据库服务器。`LogicDB` 创建一个内存中的世界，并可将其中的事实捕获为原生数据库镜像以供保存。Python 修改事实，Logica 在开发阶段编译规则，SQLite 则在游玩时执行这些规则的 SQL。

## 准备环境

本教程需要 `uv`、源码检出目录和 Python 3.12。在包含 `pyproject.toml` 的项目根目录中运行以下命令：

```sh
uv sync --locked --python 3.12
PALACE_WORK="$(mktemp -d /tmp/renpy-relations-palace.XXXXXX)"
```

请保持当前 shell 打开，后续命令还会使用 `PALACE_WORK`。这个新建目录用于保存编译后的规则包和准备好的示例项目。锁定依赖的环境包含开发阶段使用的 Logica 编译器。最初的 Python 练习使用 Python 的 SQLite 驱动；Ren’Py 所需的原生驱动会在准备项目时另行安装。

## 读懂第一条规则

下面是 [world.l](../examples/palace/world.l) 中的一条规则：

```prolog
CanEnter(character: c, location: l) distinct :-
  Sponsor(character: c, location: l);
```

可以把它读作：“如果有匹配的担保，角色就可以进入这个地点。”`CanEnter` 和 `Sponsor` 是关系名，在 Logica 中也叫谓词名。`character:` 和 `location:` 表示命名列。变量 `c` 和 `l` 将条件中匹配的值传递到答案中。`:-` 表示“在右侧条件成立时成立”；`distinct` 要求答案行不重复；`;` 表示规则结束。`"hero"` 这样的带引号文本是字面值，而 `c` 是变量。

对于输入 `Sponsor(character="hero", location="archive")`，这条规则推导出 `CanEnter(character="hero", location="archive")`。Python 这样读取答案：

```python
logic.query("CanEnter", character="hero")
# [{'character': 'hero', 'location': 'archive'}]
```

进一步说明见官方 Logica 文档中的[规则](https://logica-lang.github.io/usrguide/rules.html)、[命名参数](https://logica-lang.github.io/usrguide/named-arguments.html)及[重复行与 distinct](https://logica-lang.github.io/usrguide/multi-semantics.html)。

Palace 还定义了第二种进入方式：

```prolog
CanEnter(character: c, location: l) distinct :-
  Member(character: c, faction: f),
  FactionAccess(faction: f, location: l);
```

逗号表示两个条件都必须成立。重复使用 `f`，会将成员关系中的派系与派系访问权限行中的派系匹配起来：这种关联称为**连接（join）**。例如，角色属于 `scholars`，而 `scholars` 可以进入 `archive`，二者结合就得到该角色的档案馆访问权限。两条 `CanEnter` 规则提供两种可选途径：担保**或**匹配的成员身份，满足任意一种即可。如果两种途径都成立，`distinct` 仍只保留一行答案。

调查同时要求访问权限和已知信息：

```prolog
CanInvestigate(character: c) distinct :-
  CanEnter(character: c, location: "archive"),
  Knows(character: c, secret: "forged_letter");
```

最后，只有尚未记录匹配的领取行为时，才有资格领取奖励：

```prolog
CanClaimReward(character: c, reward: "investigation") distinct :-
  CanInvestigate(character: c),
  ~RewardClaimed(character: c, reward: "investigation");
```

`~` 检查匹配的行是否不存在。这条规则描述的是条件；它不会执行调查、发放物品或插入领取记录。这些效果由你的脚本负责。

在本项目中，游戏事实在模式 JSON 中声明，并通过 `logic.add(...)` 插入；`.l` 用于定义推导规则。上游 [Logica 用户指南](https://logica-lang.github.io/usrguide/)也演示了直接在 Logica 源码中书写事实的方式。本项目的编译器会拒绝在源码中定义由游戏提供的事实关系，因为这些输入属于运行时的表。

## 编译为 SQLite 规则包

将项目自带的源码和完整模式编译到刚创建的工作目录中：

```sh
uv run --locked renpy-relations-compile examples/palace/world.l \
  --schema examples/palace/schema.json \
  --backend sqlite \
  --output "$PALACE_WORK/palace.rules.json"
```

命令会输出 `Built … (3 derived relations)`。JSON **规则包（rule bundle）**包含运行时需要的模式、编译后的 SQL 和依赖信息。编译在游玩之前完成。下一条命令会加载这里生成的这个文件。

## 运行 Python 世界

从源码根目录运行下面这段完整练习：

```sh
uv run --locked python - "$PALACE_WORK/palace.rules.json" <<'PY'
import sys
from renpy_relations import LogicDB

logic = LogicDB(sys.argv[1])
try:
    print("Initial access:", logic.has("CanEnter", character="hero"))

    logic.add("Sponsor", character="hero", location="archive")
    print("Sponsored access:", logic.query("CanEnter", character="hero"))

    with logic.batch():
        logic.add("Knows", character="hero", secret="forged_letter")
        logic.add("Member", character="hero", faction="scholars")
        logic.add("FactionAccess", faction="scholars", location="archive")
    print("Reward eligible:", logic.has("CanClaimReward", character="hero"))

    logic.remove("Sponsor", character="hero", location="archive")
    print("Access through membership:", logic.has("CanEnter", character="hero"))

    before_claim = logic.snapshot()
    # The application decides to grant the reward and records that decision.
    logic.add("RewardClaimed", character="hero", reward="investigation")
    print("Eligible after claim:", logic.has("CanClaimReward", character="hero"))

    logic.restore(before_claim)
    print("Eligible after restore:", logic.has("CanClaimReward", character="hero"))
finally:
    logic.close()
PY
```

预期输出：

```text
Initial access: False
Sponsored access: [{'character': 'hero', 'location': 'archive'}]
Reward eligible: True
Access through membership: True
Eligible after claim: False
Eligible after restore: True
```

`has(...)` 回答是或否；`query(...)` 返回匹配行的字典。关键字筛选参数使用相等比较。撤销担保后，成员身份提供的访问权限仍然有效，因为规则组合了相互独立的访问途径。

`batch()` 将多次修改组成一个事务：要么一起提交，要么在发生异常时一起回滚。退出批次后再读取；批次内的读取会被拒绝。`add` 要求提供每一列，并忽略完全相同的元组。`remove` 删除与筛选条件匹配的行，至少需要一个筛选条件。

如果你自己的模式为 `Member` 声明了 `"key": ["character"]`，那么每个角色只能记录一个派系。替换已有的带键记录时，应在同一个批次内先删除，再添加替代行：

```python
with logic.batch():
    logic.remove("Member", character="hero")
    logic.add("Member", character="hero", faction="scholars")
# Query after the batch exits.
```

这种写法也适用于 Palace 未额外声明键的模式，但它会有意删除该角色的全部成员关系。修改游戏的事实模式前，请查阅[参考手册](reference.zh-CN.md)。

上面的**快照（snapshot）**包含事实以及格式和模式元数据。恢复快照会还原领取奖励之前的事实，并根据当前加载的规则重新计算答案。它不会保存任意 Python 变量，也不会冻结规则源码。`restore(None)` 创建一个事实为空的世界。独立使用 `LogicDB` 时，完成后应将它关闭。

## 准备并运行 Palace

这条流程使用 Linux x86_64 平台、内含 Python 3.12 的 Ren’Py SDK。发布工具固定使用 SDK 版本 `8.5.3.26051504`。将 `RELATIONS_SDK` 设为包含 `renpy.sh` 的 SDK 目录，然后将项目准备到一个尚不存在的目标目录：

```sh
RELATIONS_SDK="/path/to/your/renpy-sdk"
PALACE_PROJECT="$PALACE_WORK/palace-game"
uv run --locked python -m tools.prepare_game \
  --game examples/palace \
  --out "$PALACE_PROJECT" \
  --backend sqlite \
  --sdk "$RELATIONS_SDK"
"$RELATIONS_SDK/renpy.sh" "$PALACE_PROJECT"
```

运行前请替换 SDK 路径占位符。准备过程会复制示例及其自带的规则包，将锁定的依赖安装到 `game/python-packages`，并使用 SDK 解释器检查导入。它**不会**使用 `$PALACE_WORK/palace.rules.json`；那个规则包已用于前面的独立 Python 练习。准备好的示例读取的是 `game/relations.rules.json`。

点击 **Start**（开始），推进到选项菜单。尝试以下操作：

1. 选择 **Ask for a sponsor**（请求担保），会使 **Enter the archive**（进入档案馆）变为可用。
2. 选择 **Learn about the forged letter**（了解伪造信件），会使 **Investigate and claim the reward**（调查并领取奖励）变为可用。
3. 选择 **Investigate and claim the reward**，会记录 `RewardClaimed`，领取选项随即消失。
4. 在新游戏中请求担保并选择 **Join the scholars**（加入学者派系），然后选择 **Revoke the sponsorship**（撤销担保）。成员身份仍会保留档案馆的访问权限。

获得担保后，使用顶部的 **Save**（保存）按钮存档，再撤销担保，然后点击 **Load**（读取）。存档中的担保事实及其派生访问权限会恢复。使用 **Rollback**（回滚）退回到请求担保的选择之前；如果需要，可以多次回滚，直到抵达更早的交互。此时担保和访问权限都会消失。这些控件用于体验 Ren’Py 的存档和回滚状态，其中也包含适配器管理的事实快照。在开发者模式下，**F8** 打开关系检查器。

## 接入自己的 Ren’Py 脚本

准备好的 [Palace 脚本](../examples/palace/game/script.rpy)包含完整示例。其集成方式如下：

```renpy
default logic_snapshot = None
default reward_points = 0

init python:
    import os
    import sys
    sys.path.insert(0, os.path.join(config.gamedir, "python-packages"))
    from renpy_relations import RenpyLogicDB as LogicDB

    logic = LogicDB(os.path.join(config.gamedir, "relations.rules.json"))
    logic.install_renpy(config)

    def seed_world():
        with logic.batch():
            logic.add("Member", character="hero", faction="visitors")
            logic.add("FactionAccess", faction="scholars", location="archive")

label start:
    $ seed_world()
    "The archive is restricted."
    jump court

label court:
    menu:
        "Ask for a sponsor" if not logic.has("Sponsor", character="hero", location="archive"):
            $ logic.add("Sponsor", character="hero", location="archive")
            "A courtier sponsors your visit."
        "Learn about the forged letter" if not logic.has("Knows", character="hero", secret="forged_letter"):
            $ logic.add("Knows", character="hero", secret="forged_letter")
            "You learn about a forgery in the archive."
        "Investigate and claim the reward" if logic.has("CanClaimReward", character="hero", reward="investigation"):
            $ logic.add("RewardClaimed", character="hero", reward="investigation")
            $ reward_points += 1
            "You receive one reward point."
        "Finish":
            return
    jump court
```

在已准备好运行时和规则包的游戏中使用这一方式。在初始化阶段安装适配器，在新游戏开始时的 `label start` 中写入初始事实。将 `logic_snapshot` 保持为 Ren’Py 的 `default` 变量。每次提交实际产生修改后，适配器都会发布事实快照，并通过 Ren’Py 的生命周期回调从该变量恢复数据库。`reward_points` 等普通游戏效果仍由你的脚本负责，应使用 Ren’Py 常规的存档和回滚变量。

不要把数据库对象赋给 `logic_snapshot`；该变量由适配器管理。生命周期细节和支持的重载行为，见[参考手册中的 Ren’Py 集成说明](reference.zh-CN.md)。

## 修改规则

编辑准备好的 `$PALACE_PROJECT/world.l`，即可尝试不同条件而不改动源码检出目录。例如，将其中的 `CanInvestigate` 规则替换为：

```prolog
CanInvestigate(character: c) distinct :-
  CanEnter(character: c, location: "archive");
```

现在，只要有访问权限就可以调查。请明确将编译结果写入准备好的游戏实际加载的规则包：

```sh
uv run --locked renpy-relations-compile "$PALACE_PROJECT/world.l" \
  --schema "$PALACE_PROJECT/schema.json" \
  --backend sqlite \
  --output "$PALACE_PROJECT/game/relations.rules.json"
```

重启游戏并开始新的一轮游玩。现在，请求担保后，即使还没了解秘密，也可以领取奖励。将原规则复制回去并重新编译，即可恢复原来的条件。改编这个世界时，新增事实类型需要修改模式声明，修改资格条件需要编辑 `.l` 规则，修改效果则需要编辑 Python/Ren’Py 行动。

Palace 也启用了开发阶段的规则监视：成功重新编译后，它可以在交互时加载变更后的规则包，也可以按 **F6** 重载。编译器的 `--watch` 根据源码变化重新编译；适配器的 `watch_rules=True` 加载变更后的规则包。这是两个独立步骤。规则重载会保留事实，并要求事实模式和数据库后端保持不变；重载后，旧快照也使用当前规则。完整约定见[快照与重载说明](reference.zh-CN.md)。

## 后续阅读

先使用 SQLite 完成这次练习。可选的 DuckDB 安装、针对不同后端的编译、查询模式和规则监视命令，见[参考手册](reference.zh-CN.md)。[Tidelight 指南（英文）](../examples/tidelight/README.md)展示了一个完整故事如何从符合条件的答案中选择事件。[基准测试指南（英文）](../benchmarks/README.md)介绍测量方法，[维护指南（英文）](maintaining.md)介绍修改和发布流程。
