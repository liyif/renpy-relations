# 验证记录

日期：2026-10-13（Asia/Singapore）。

## 环境

- uv 0.11.18；开发 Python 3.12.13；标准库 SQLite 3.50.4。
- SQLAlchemy 2.0.43；Logica 1.3.1415926535897；pytest 9.1.1，版本由 uv.lock 锁定。
- 官方 Ren’Py 8.5.3.26051504 Linux x86_64 SDK，内置 Python 3.12.8。
- SDK 运行依赖由 uv 从锁文件导出并按 Python 3.12／Linux ABI 安装；使用 pysqlite3-binary 0.5.4.post2（SQLite 3.51.1）。
- 真实引擎测试在 xvfb-run、X11、Mesa 软件渲染和 dummy 音频环境运行，存档使用独立临时目录。

## 后端与构建

在项目目录执行：

```sh
uv run --locked python -m pytest
uv run --locked python -m py_compile renpy_relations.py compile_rules.py check_renpy.py
```

结果：**60 项通过**（48 项后端／接入约定、8 项真实 Logica 编译与构建、4 项测试启动器检查），Python 编译检查通过。

覆盖事实去重与主键冲突、三种执行模式、导出关系的依赖缓存、SQL 过滤语义、输出类型／NULL、事务失败、快照拒绝与恢复、异常数值快照、正确／错误热重载、schema 不兼容、编译失败保留旧产物、编辑途中不发布混合产物、构建观察、自动重载错误去重与开发模式开关，以及测试进程的成功／失败／超时／带颜色报告。

真实 Logica 编译产物已生成并提交到 `examples/palace/game/relations.rules.json`。构建阶段保留导出关系依赖：CanClaimReward → CanInvestigate → CanEnter。

## 真实 Ren’Py 引擎

```sh
/path/to/renpy-sdk/renpy.sh examples/palace lint
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode cached
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode live
uv run --locked python check_renpy.py --sdk /path/to/renpy-sdk --headless --mode materialized
```

Lint 通过，无脚本错误；SDK 仍输出常规的属性冲突检查建议。

| 模式 | 场景 | 钩子 | 断言 | 最终状态 |
| --- | --- | --- | --- | --- |
| cached | 7／7 | 15／15 | 43／43 | PASSED |
| live | 7／7 | 15／15 | 43／43 | PASSED |
| materialized | 7／7 | 15／15 | 43／43 | PASSED |

七个场景：

1. 阵营／担保／知识条件组合、事实撤销与一次性奖励。
2. 真实 Ren’Py 存档与读档，事实和派生关系同时恢复。
3. 真实 Ren’Py 回滚，撤销选择产生的事实。
4. 返回主菜单并开始新游戏，清除上次游戏状态。
5. 手动热重载保留事实，替换派生规则，再恢复原规则。
6. F8 关系检查屏幕可以实际打开、渲染和关闭。
7. 自动观察规则产物：有效修改生效；无效 JSON 保留旧规则；修复后再次生效。

测试使用真实 SDK 和实际编译 SQL，没有用模拟 Ren’Py 回调代替引擎验证。SDK 源码没有修改。本次 SDK 的测试结束阶段会在输出完整报告后继续循环并占用 CPU；`check_renpy.py` 收到最终 Status 后清理隔离进程组。启动器成功返回，最终未遗留 Ren’Py 测试进程。

## Standards

独立代码审查未发现硬性仓库标准违规或需要处理的结构性 smell。审查发现的快照恢复原子性问题已经修复：候选世界完成规范快照生成后才交换；复核和异常数值回归检查通过。

## Spec

设计符合性审查确认规则编译、关系级惰性物化、原子重载、事实快照及 uv 管理有实现与验证。复核发现的带颜色测试报告识别问题已修复，新增检查通过。真实引擎测试另外发现并修复了检查屏幕文本转义和 Python 模块中的 Ren’Py 日志命名空间问题。

当前未处理的审查发现：Standards 0，Spec 0。

## 尚未验证

Windows、macOS、Android、iOS、Web 发行与打包；大事实集的快照开销；大规则集的性能；完整 Logica 功能覆盖。上述范围没有兼容性或性能结论。第一版不包含存档迁移、增量维护和自定义规则执行器。
