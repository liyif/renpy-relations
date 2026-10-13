# 多规则、少事实：实测与边界

2026-10-13，Ryzen 9 7900X，Ren’Py 8.5.3 内置 Python 3.12.8、pysqlite3／SQLite 3.51.1、SQLAlchemy 2.0.43。128／512 条事实，事实数:导出规则数为 1:1／1:10，最大 5120 个规则。两种布局、三种模式、两个版本，每个条件三次独立进程，共 **144 次全部成功**。

[协议](RULES_DESIGN.md) · [完整阶段报告](results/2026-10-13-many-rules/REPORT.md) · [原始数据](results/2026-10-13-many-rules/results.json)

## 可以确定的行为

当前屏幕读取 24 个条件，分布在 12 个剧情领域；条件有共享前置依赖、全局开关和否定条件。历史阶段访问所有规则，然后逐规则核对完整行集合，随后测局部／全局／无关事实变化。每次提交包含完整事实快照。

- 领域状态分表时，cached 的局部行动从重建 **48 个关系变为 4 个**，不受影响的缓存保留。
- 所有状态在同一通用事实表时，局部行动仍重建 **48 个**；关系级图不能区分不同 domain 的行。
- 全局开关是公共依赖，会影响大部分规则。新方案需要计算后继集合，可能增加提交延迟。
- 无规则读取的备注变化不再使 cached 失效，也不再触发 eager 重建。
- live 没有物化失效成本；在本轮最大档的少事实、简单 SQL 条件下，读取整个 24 条件屏幕的 warm 中位数约 3.6～3.8 ms，cached／materialized 约 2.7～2.8 ms。缓存的相对收益远小于百万事实测试。

## 延迟不是重建次数的简单倍数

以下为最大档的“局部提交＋随后 24 条件读取”，先在每次试验内相加，再取三个试验中位数，单位 ms；保留自动 GC。

| 布局 | 模式 | 旧版全局失效 | SQL 依赖图 |
| --- | --- | ---: | ---: |
| 领域分表 | cached | 104.063 | 11.728 |
| 领域分表 | materialized | 559.758 | 24.112 |
| 领域分表 | live | 12.342 | 12.292 |
| 通用状态表 | cached | 13.318 | 111.221 |
| 通用状态表 | materialized | 563.137 | 578.044 |
| 通用状态表 | live | 9.449 | 9.764 |

**不能把 104→12 ms 直接解释为图算法加速约九倍，也不能把 13→111 ms 全部归因于图查询。** 存在约 100 ms 的暂停落点变化。额外四次 SDK 诊断保留自动 GC，通过回调记录收集时间，捕捉到约 80～100 ms 的 generation 2 收集；诊断中这些暂停多在加载、历史遍历和未计时的校验／记录阶段，局部行动分别为分表旧版 15.423／新版 10.979 ms、通用表旧版 12.732／新版 20.438 ms。

诊断本身会改变分配时机，因此它只是解释暂停现象的证据，不能证明主试验某次暂停一定由 GC 导致，也不能替换三次主试验数据。主测试中的完整校验还会影响后续 GC 时机；这里是受控后端实验，尚不是完整游戏的尾延迟基准。后续应将全量正确性验证与长时间交互测量分进程，并测更多连续行动，才能比较稳定的交互分布。

诊断记录为同目录的 `gc-partitioned-baseline.json`、`gc-partitioned-native.json`、`gc-shared-baseline.json`、`gc-shared-native.json`。没有关闭 GC、扣除暂停或删除不利样本。

## 依赖信息已经随编译输出

Logica 官方编译器生成 SQL 后，构建验证中的 SQLite authorizer 报告直接读取关系。产物示例：

```json
"dependencies": {
  "CanClaimReward": ["CanInvestigate", "RewardClaimed"]
}
```

这是静态 SQL 依赖，包含 NOT EXISTS、空表和 count(*)，不取决于当前数据是否通过某分支。运行时核验它与 SQL 一致，避免手工编辑 SQL 留下旧元数据；旧产物仍支持。新基准生成受控 SQL，测后端运行成本；真正 Logica 编译输出由编译检查及示例覆盖，不把全量构建成本混入 load。

SQLite 执行循环检查、拓扑排序、读取祖先与失效后继计算；Python 不实现 SQL 文本解析器或递归图遍历。当前按祖先数排序需要祖先闭包。独立单次长链探针结果：128 层加载 24.463 ms，512 层 216.118 ms，1050 层 804.407 ms；1050 层首次读取 62.634 ms。长链虽不再受 Python 递归深度限制，加载仍呈现闭包成本，不能视为通用线性时间方案。[原始探针](results/2026-10-13-many-rules/chain-probe.json)

下一步值得把已验证的依赖顺序也保存到编译产物，减少加载／恢复时重复计算；同时保持直接边与顺序的一致性检查。这与按事实关系失效是不同的改进，需要单独对照。

## 复现

```sh
uv run --locked python benchmarks/rules.py \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages examples/palace/game/python-packages \
  --out benchmarks/results/my-many-rules
uv run --locked python benchmarks/graph.py \
  --python /path/to/renpy-sdk/lib/py3-linux-x86_64/python \
  --packages examples/palace/game/python-packages \
  --out benchmarks/results/my-many-rules/chain-probe.json
```

不传 SDK 参数时用 uv Python，报告会记录实际驱动。对照后端固定取 Git 的 `8827c21`；当前后端和对照源码复制到 `.work`，独立进程加载，摘要随结果保存。输出目录必须为空。

GC 单次诊断示例（先生成上述工作目录）：

```sh
uv run --locked /path/to/renpy-sdk/lib/py3-linux-x86_64/python benchmarks/gc_probe.py \
  --runtime benchmarks/results/my-many-rules/.work/native \
  --shape partitioned --variant native \
  --packages examples/palace/game/python-packages \
  --out benchmarks/results/my-many-rules/gc-partitioned-native.json
```

本轮没有进行 DuckDB 同负载对照。其官方文档说明 bulk operations 是主要目标，频繁小事务不是主要设计目标；是否改善此处的短查询、状态变更、快照和大量规则加载，应以同一负载实测判断。[DuckDB 并发与负载说明](https://duckdb.org/docs/lts/connect/concurrency)

## 检查与审查

78 项 Python 检查通过；真实 Ren’Py 三模式各 7 场景、15 钩子、43 断言通过。首次沙箱内启动因虚拟显示不可用失败，允许本地虚拟显示运行后通过；未修改 SDK。

Standards 审查发现并修复依赖导出反复复制整个规则包的问题，以及全量行集合校验缺口。Spec 审查发现的集合校验与长链实测缺口均已修复。两轴只读复核后当前未解决发现均为 0。
