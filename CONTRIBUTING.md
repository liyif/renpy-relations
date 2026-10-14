# 开发与贡献

使用 uv 与仓库锁文件，默认开发 Python 为 3.12：

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
uv run --locked --extra duckdb --group renpy-linux --group assets pytest -q
```

修改规则后应重新编译两个后端的产物。修改中文样例后应重建字体；修改场景时保留标签、菜单与条件的缩进，并确认正文在不同合法相遇顺序下仍成立。

引擎检查使用真实 Ren’Py 8.5.3。先用 `prepare_game.py` 生成独立试玩目录，再运行 `check_renpy.py --sdk ... --game ... --headless`。Headless 检查需要 Xvfb／xauth 与软件 OpenGL。新功能应附上可复现的实际行为检查；只改文案时重点复核剧情前提和字库。

报告问题时，请提供版本、平台、SDK 版本、数据库后端、查询模式和最短复现步骤。涉及存档时说明是否换过后端或事实 schema。尚未承诺 Windows、macOS、移动端或 Web 的原生扩展打包。

本实验保持运行时接口小而明确；规则计算与游戏行动分开。设计边界见 [DESIGN.md](DESIGN.md)。
