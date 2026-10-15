# 将 Python 包发布到 PyPI

[English](PUBLISHING.md) · [简体中文](PUBLISHING.zh-CN.md)

[pypi.yml](workflows/pypi.yml) 发布 `renpy-relations` 的 wheel 和 Python 源码发行包。Ren’Py SDK、运行时 ZIP 和可试玩游戏由[发行构建工具（英文）](../docs/maintaining.md#build-a-release-from-a-committed-checkout)单独处理。

## 首次配置账号

创建 PyPI 账号、验证邮箱并启用双重验证。在 GitHub 仓库的 **Settings → Environments** 中创建名为 `pypi` 的环境。

首次创建项目时，在 PyPI 账号的 **Publishing** 页面添加 pending GitHub publisher。如果已经拥有该项目，改用项目的 **Manage → Publishing** 页面。

| PyPI 字段 | 填写内容 |
| --- | --- |
| PyPI project name，仅 pending publisher 需要 | `renpy-relations` |
| Repository owner | `liyif` |
| Repository name | `renpy-relations` |
| Workflow filename | `pypi.yml` |
| Environment name | `pypi` |

工作流文件名只填 `pypi.yml`，不填 `.github/workflows/pypi.yml`。这些字段必须与工作流和仓库一致。Trusted Publishing 会提供短期凭据，这个工作流不需要保存 PyPI API Token。Pending publisher 在首次成功发布时创建项目，事先不会预留名称。官方说明见[新项目配置](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)和[已有项目配置](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)。

## 发布前检查工作流

将工作流合入 `main`。在 GitHub 的 **Actions → Publish Python package to PyPI → Run workflow** 中选择 `main`。这会运行完整 Python 测试，包括独立环境中的安装检查；构建 wheel 和源码发行包，检查元数据与 README 渲染，并在隔离环境中导入实际构建的包。两份文件会保存为工作流附件；针对分支运行时会跳过发布任务。

构建使用固定版本的 uv 和锁定的测试依赖。只有独立的发布任务获得 `id-token: write` 权限，它下载已经验证的构建产物，并用 `uv publish --trusted-publishing always` 上传。

## 发布一个版本

同步更新 `pyproject.toml`、`uv.lock`、示例版本字符串和发布说明，将目标版本提交并合入 `main`。创建与包版本一致的附注标签并推送；当前版本对应的命令是：

```sh
git switch main
git pull --ff-only
git tag -a v0.3.0 -m "Ren’Py Relations 0.3.0"
git push origin v0.3.0
```

`v*` 标签会触发工作流。标签名称不等于 `v<project.version>`，或对应提交不在 `origin/main` 历史中时，构建会失败。构建和检查通过后，才会使用 `pypi` 环境执行发布。

手动选择版本标签运行时，也会执行发布任务。只检查已有构建而不发布时，应选择分支。发布失败后，可以修正账号或环境配置，再重跑失败任务，使用已验证的产物。如果上传后需要修改代码或包内容，应发布新版本；PyPI 上已使用的发行文件名不能被替换。详见 [PyPI 文件名规则](https://pypi.org/help/#file-name-reuse)。

发布后检查 PyPI 项目页面，并在源码目录之外验证安装：

```sh
uv run --isolated --no-project --with renpy-relations==0.3.0 python -I -c \
  "from renpy_relations import LogicDB, RenpyLogicDB"
```

对外公告前，再验证已发布版本的 `compiler` 和 `duckdb` 可选依赖。GitHub 发布说明、游戏包和运行时附件应对应同一份源码提交。
