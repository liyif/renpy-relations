# 0.1.0 发布准备与构建

本次交付为实验性开源首版：完整源码、Linux x86_64 两后端运行时包，以及《潮汐替我们保管》可试玩发行包。代码、文档、示例与剧本文字采用 MIT；字体和第三方组件保留原许可证。

## 已支持范围

| 项目 | 范围 |
| --- | --- |
| 开发环境 | uv 锁定依赖；Python 3.12 |
| 游戏环境 | Linux x86_64，Ren’Py 8.5.3.26051504，内置 Python 3.12.8 |
| 后端 | SQLite（pysqlite3-binary 0.5.4.post2）与 DuckDB 1.5.6 |
| 查询模式 | cached、live、materialized |
| 存档 | 同一后端、同一事实 schema 的格式 2 快照 |

其他平台尚未验证，不在本次二进制发布范围。新版本变更事实 schema 或快照格式时，应说明存档兼容性；没有迁移承诺。规则 SQL 是可信构建产物，不是任意 SQL 的安全沙箱。

样例按后端隔离存档目录，避免两种原生镜像混用。此首版使用新的保存目录，开发阶段旧样例的存档不会自动导入。

## 构建

需要 Git、uv、Linux x86_64、Xvfb、xauth、软件 OpenGL 与原版 Ren’Py 8.5.3 SDK。从干净且已提交的仓库运行：

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
uv run --locked --extra duckdb --group renpy-linux --group assets python release.py build \
  --sdk /path/to/renpy-8.5.3-sdk --out dist/0.1.0
uv run --locked python release.py verify dist/0.1.0
```

输出目录必须尚不存在。失败时保留日志，不覆盖以前的产物。重新构建请选一个新目录。

构建流程会：

1. 从固定 Git 提交导出源码，生成源码包，再解包并执行全套 Python 检查。
2. 在独立目录按锁文件和 wheel 哈希安装两种驱动，使用 SDK Python 验证加载。
3. 对两个独立样例执行 lint，以及两后端三模式的完整真实引擎测试。
4. 生成运行时 ZIP，保留依赖许可证并输出实际安装清单。
5. 使用 Ren’Py 官方构建器生成 Linux 游戏，关闭开发模式、排除测试与本地历史文件。
6. 检查归档必需文件，解包后用发行包自带的引擎测试两后端。测试脚本只注入临时解包副本；下载包不包含测试。
7. 记录提交、源码文件哈希、SDK 与产物信息，生成 SHA-256 校验文件并验证。

归档检查允许 SDK 生成的生产用字节码与构建元信息；本地存档、测试脚本与其余项目缓存不进入下载包。Ren’Py 的完整 `LICENSE.txt` 显式加入游戏，第三方声明与源码入口同时保留在 README。

流程可复现；Ren’Py 写入的构建时间等元数据可能导致不同构建的字节哈希不同，不承诺逐字节确定性。

## 交付文件

- `renpy-relations-0.1.0-source.tar.gz`：完整源码、测试、规则、文档与基准。
- `renpy-relations-0.1.0-linux-x86_64-runtime.zip`：可合入其他游戏的运行时与两后端驱动。
- `tidelight-0.1.0-linux.tar.bz2`：解压即可玩的完整文字样例。
- `RELEASE.json`：实际构建提交、源码哈希、检查范围与产物清单。
- `SHA256SUMS`：三个包与构建清单的校验值。
- `logs/`：安装、测试、lint、构建与发行包检查的完整输出。

源码包包含两份带原提交与校验值的历史基准对照，默认基准不依赖 `.git`；其他自选历史版本仍需 Git checkout。

玩法与接入入口见 [QUICKSTART.md](QUICKSTART.md)。`DEPENDENCIES.json` 在运行时包及游戏内记录实际依赖版本、许可证文件路径。原生扩展、规则 JSON 和剧情 JSON 保持为实际文件。

## CI 与公开发布

GitHub Actions 在 push／pull request 时检查 Python 与独立样例；手动触发或推送版本标签时构建完整候选产物。CI 固定 uv、SDK 下载校验值及第三方 Action 提交。工作流只上传构建附件，不创建公开 Release。

公开前检查 `RELEASE.json` 对应准备发布的提交、所有日志成功、校验通过，并确认下载说明与版本一致。发布时将标签指向该构建提交，并把上述三个包、清单、校验文件和本版 [CHANGELOG](CHANGELOG.md) 一同提供。当前仓库尚未配置远端；公开位置与上传属于下一步发布操作。

参考：[Ren’Py 命令行构建](https://www.renpy.org/doc/html/cli.html)、[发行文件分类](https://www.renpy.org/doc/html/build.html)、[官方 8.5.3 校验值](https://www.renpy.org/dl/8.5.3/checksums.txt)。
