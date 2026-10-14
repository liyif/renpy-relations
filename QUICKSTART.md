# 五分钟上手

当前版本为 **0.1.0 实验版**。已验证的平台是 Linux x86_64、Ren’Py 8.5.3（内置 Python 3.12）。

## 直接试玩

下载并解开 `tidelight-0.1.0-linux.tar.bz2`，进入解包目录运行：

```sh
./tidelight.sh
```

包含完整运行环境，无需安装 uv、Python 或 Ren’Py SDK。默认 SQLite。若要试 DuckDB：

```sh
RELATIONS_BACKEND=duckdb ./tidelight.sh
```

存档目录按后端隔离，首次切换后端后从新游戏开始。《潮汐替我们保管》是三位成年女主角、五个结局的完整文字短篇，地图根据当前关系呈现相遇。发行包关闭开发观察界面。

## 从源码运行和修改

需要 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和
[Ren’Py 8.5.3 SDK](https://www.renpy.org/release/8.5.3)。以下命令从本项目根目录运行，输出目录应当尚不存在：

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
uv run --locked python prepare_game.py --game examples/tidelight \
  --out /tmp/my-tidelight --backend duckdb --sdk /path/to/renpy-sdk
/path/to/renpy-sdk/renpy.sh /tmp/my-tidelight
```

`prepare_game.py` 复制样例、按锁文件安装对应 ABI 的依赖，并把运行时放入游戏自身的 `game/python-packages`。它拒绝覆盖已有目录，不依赖开发机的样例依赖链接。`--backend duckdb` 同时包含 SQLite 和 DuckDB；只需要 SQLite 时省略该参数即可。

运行时、编译器与样例的分工：

- `renpy_relations.py`：游戏实际加载的运行时。
- `compile_rules.py`：开发时把 `.l` 与 schema 编译成 JSON。
- `examples/palace`：较小的接入样例。
- `examples/tidelight`：完整的关系驱动叙事样例。

修改 `examples/tidelight/world.l` 后重新编译，再生成一个新的试玩目录：

```sh
uv run --locked python compile_rules.py examples/tidelight/world.l \
  --schema examples/tidelight/schema.json --output examples/tidelight/game/relations.rules.json
uv run --locked --extra duckdb python compile_rules.py examples/tidelight/world.l \
  --schema examples/tidelight/schema.json --backend duckdb \
  --output examples/tidelight/game/relations.duckdb.rules.json
```

修改中文正文后，需要按[字体说明](examples/tidelight/game/fonts/README.md)重建子集，并运行检查。

## 接入自己的游戏

`renpy-relations-0.1.0-linux-x86_64-runtime.zip` 包含锁定的两后端驱动与运行时。将其中 `game/python-packages` 的内容合入自己的同名目录。这个运行时包针对 Python 3.12／Linux x86_64，不能直接用于其他平台。

从源码包使用 `compile_rules.py` 编译自己的 `.l` 和 schema，把规则 JSON 放进自己的 `game`。Ren’Py 初始化示例：

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

脚本通过 `logic.batch()` 写事实，再使用 `logic.has()` 或 `logic.query()` 决定可选行动。完整可运行代码见 [palace](examples/palace/game/script.rpy)，接口契约见 [USAGE](USAGE.md)。规则 JSON、以 Path 读取的数据和原生扩展须作为实际文件打包。

## 验证下载文件

将三个发行包、`RELEASE.json` 和 `SHA256SUMS` 放在同一目录。从源码包根目录运行：

```sh
uv run --locked python release.py verify /path/to/downloads
```

也可在下载目录执行 `sha256sum --check SHA256SUMS`。校验用于确认文件完整性；请从可信发布位置获得校验文件。
