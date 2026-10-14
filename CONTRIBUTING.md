# 开发与贡献

## 环境与测试

依赖统一使用 uv，开发 Python 为 3.12：

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
uv run --locked --extra duckdb --group renpy-linux --group assets pytest -q
```

测试使用真实 SQLite、DuckDB 和 Logica，覆盖规则编译、三模式语义、依赖失效、事务失败、快照、恢复、规则重载与样例场景编排。省略可选依赖时相关测试可能跳过，双后端检查应安装上面的完整依赖组。

真实引擎检查需要 Ren’Py 8.5.3 SDK。先创建独立项目：

```sh
uv run --locked python prepare_game.py --game examples/tidelight \
  --out /tmp/tidelight-check --backend duckdb --sdk /path/to/renpy-sdk
/path/to/renpy-sdk/renpy.sh /tmp/tidelight-check lint
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk \
  --game /tmp/tidelight-check --headless --backend sqlite --mode cached --timeout 180
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk \
  --game /tmp/tidelight-check --headless --backend duckdb --mode cached --timeout 180
```

其他模式使用 `--mode live` 或 `--mode materialized`。检查小样例时，将 `prepare_game.py` 的 `--game` 改为 `examples/palace`，选择新的输出目录，再用该目录执行 lint 与引擎检查。`--headless` 需要 Xvfb、xauth 与软件 OpenGL，省略时使用正常显示器。

`check_renpy.py` 根据完整 SDK 测试报告判断结果，失败或超时返回非零，并回收测试进程与临时存档。Ren’Py 8.5.3 测试结束后的循环由外部启动器处理，SDK 源码不改动。

## 修改要求

- 运行时接口保持小而明确，查询与游戏行动分开；设计见 [DESIGN](DESIGN.md)。
- 修改规则后重新生成两后端产物；编译步骤见 [USAGE](USAGE.md)。
- 修改中文正文后重建字体子集。修改场景时检查标签、菜单和条件缩进，以及正文在不同合法相遇顺序下的前提。
- 行为变化应有可复现检查。性能变化使用 [Benchmark](benchmarks/README.md) 的相同负载和测量口径，不用单次最快值下结论。
- 文档描述当前接口、使用方式与实验边界。阶段进度、审查过程和本机状态留在提交说明或构建日志中。

报告问题请提供版本、平台、SDK、后端、模式和最短复现步骤。存档问题应说明是否换过后端或事实 schema。构建及分发步骤见 [RELEASE](RELEASE.md)。
