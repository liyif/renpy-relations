# 构建与分发

维护者使用 `release.py` 从干净 Git 提交生成源码包、运行时包和可试玩样例。首次使用见 [QUICKSTART](QUICKSTART.md)。

## 目标环境与兼容性

| 项目 | 0.1.0 的构建目标 |
| --- | --- |
| 开发 | uv 锁定依赖，Python 3.12 |
| 游戏 | Linux x86_64，Ren’Py 8.5.3.26051504，内置 Python 3.12.8 |
| SQLite 驱动 | pysqlite3-binary 0.5.4.post2 |
| DuckDB | DuckDB 1.5.6、duckdb-engine 0.17.0 |
| 查询模式 | cached、live、materialized |
| 快照 | 格式 2，同一后端及事实 schema |

其他平台的原生扩展与打包尚未验证。API 和格式可能在实验版本间变化；影响 schema 或快照格式的变更需要在 CHANGELOG 中说明，没有自动迁移。

SQLAlchemy 固定为 2.0.43，以适配该 SDK 的 Python 模块集合。依赖二进制必须匹配 SDK Python 的 ABI；不能直接复制其他版本 Python 的开发环境。

样例按后端隔离存档目录，首次切换后端应开始新游戏。编译产物按后端分别生成。

## 构建

需要 Git、uv、Linux x86_64、Xvfb、xauth、软件 OpenGL，以及原版 Ren’Py 8.5.3 SDK。先提交所有源码修改，再运行：

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
uv run --locked --extra duckdb --group renpy-linux --group assets python release.py build \
  --sdk /path/to/renpy-8.5.3-sdk --out dist/0.1.0
uv run --locked python release.py verify dist/0.1.0
```

输出目录必须尚不存在，失败保留日志。重建时选择新目录。

构建器执行以下检查：

1. 从固定 Git 提交导出源码，解包后执行 Python 测试。
2. 根据锁文件和 wheel 哈希安装独立样例依赖，用 SDK Python 检查加载。
3. 对两个样例执行 lint 和两后端三模式的真实引擎测试。
4. 使用官方构建器生成 Linux 游戏，关闭开发模式，排除测试、本地存档和开发缓存。
5. 解包游戏，用它自带的引擎测试两后端；测试脚本只注入临时副本。
6. 记录提交、源码哈希、实际检查与产物信息，生成并验证 SHA-256 清单。

规则 JSON、剧情 JSON 和原生扩展保持实际文件。SDK 生成的生产字节码与构建元信息保留；许可证和依赖清单随包分发。Ren’Py 写入构建时间等元数据，流程不承诺逐字节确定性。

## 产物

| 文件 | 内容 |
| --- | --- |
| `renpy-relations-0.1.0-source.tar.gz` | 源码、测试、规则、文档与 Benchmark 工具 |
| `renpy-relations-0.1.0-linux-x86_64-runtime.zip` | 可合入其他游戏的运行时、两后端驱动与安装说明 |
| `tidelight-0.1.0-linux.tar.bz2` | 自带引擎的中文短篇样例 |
| `RELEASE.json` | 构建提交、源码哈希、测试范围、产物大小与哈希 |
| `SHA256SUMS` | 三个归档和构建清单的 SHA-256 |
| `logs/` | 安装、测试、lint 与构建输出 |

`DEPENDENCIES.json` 记录安装的版本及许可证路径。项目内容采用 MIT，字体采用 OFL，第三方软件保留原许可；可试玩包必须保留 SDK 的完整 `LICENSE.txt` 和官方源码入口。

## CI 与发布

GitHub Actions 在 push／pull request 时检查 Python 与独立样例。手动触发或版本标签触发完整候选构建，上传附件，不自动创建公开 Release。工作流固定 uv、SDK 校验值和 Action 提交。

发布前核对清单提交与版本、检查日志、校验下载包，再将版本标签指向该提交。分发三个归档、`RELEASE.json`、`SHA256SUMS` 及对应 CHANGELOG。Benchmark 报告应保留其自己的测量源码身份，不用后续文档提交替换测量身份。

参考：[Ren’Py 命令行构建](https://www.renpy.org/doc/html/cli.html)、[发行文件分类](https://www.renpy.org/doc/html/build.html)、[组件许可与源码](https://www.renpy.org/doc/html/license.html)。
