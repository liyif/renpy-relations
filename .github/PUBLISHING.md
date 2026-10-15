# Publish the Python package to PyPI

[English](PUBLISHING.md) · [简体中文](PUBLISHING.zh-CN.md)

[pypi.yml](workflows/pypi.yml) publishes the `renpy-relations` wheel and Python source distribution. The Ren’Py SDK, runtime ZIP and playable game are handled separately by the [release builder](../docs/maintaining.md#build-a-release-from-a-committed-checkout).

## One-time account configuration

Create a PyPI account, verify its email address, and enable two-factor authentication. In the GitHub repository's **Settings → Environments**, create an environment named `pypi`.

On PyPI, open your account's **Publishing** page and add a pending GitHub publisher for a new project. If you already own the project, use its **Manage → Publishing** page instead.

| PyPI field | Value |
| --- | --- |
| PyPI project name, for a pending publisher | `renpy-relations` |
| Repository owner | `liyif` |
| Repository name | `renpy-relations` |
| Workflow filename | `pypi.yml` |
| Environment name | `pypi` |

Use the filename alone, not `.github/workflows/pypi.yml`. These fields must match the workflow and repository. Trusted Publishing supplies short-lived credentials; this workflow needs no stored PyPI API token. A pending publisher creates the project on first successful publication and does not reserve the name beforehand. See the official [new-project setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) and [existing-project setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

## Check the workflow before publishing

Merge the workflow into `main`. Under GitHub **Actions → Publish Python package to PyPI → Run workflow**, select `main`. This runs the complete Python suite, including isolated package installations, builds the wheel and source distribution, checks metadata/README rendering, and imports the exact distributions in isolated environments. It saves the two files as a workflow artifact; the publishing job is skipped for a branch run.

The build uses the pinned uv version and locked test dependencies. Only the independent publishing job receives `id-token: write`; it downloads the tested artifacts and uploads them using `uv publish --trusted-publishing always`.

## Publish a version

Update `pyproject.toml`, `uv.lock`, example version strings and release notes together. Commit and merge the intended release into `main`. Create and push an annotated tag matching the package version; for the current version:

```sh
git switch main
git pull --ff-only
git tag -a v0.3.0 -m "Ren’Py Relations 0.3.0"
git push origin v0.3.0
```

A `v*` tag triggers the workflow. The build rejects a tag that differs from `v<project.version>` or whose commit is not in `origin/main`. Publication starts only after the build and checks pass, using the `pypi` environment.

Manually selecting a version tag also runs the publishing job. To inspect an already completed build without publishing, select a branch instead. For a failed publication, correct the account/environment setup and rerun the failed job using its verified artifacts. If code or package contents must change after upload, release a new version; uploaded PyPI filenames cannot be replaced. See [PyPI's filename policy](https://pypi.org/help/#file-name-reuse).

After publication, check the PyPI project page and verify installation outside the source checkout:

```sh
uv run --isolated --no-project --with renpy-relations==0.3.0 python -I -c \
  "from renpy_relations import LogicDB, RenpyLogicDB"
```

Test the `compiler` and `duckdb` extras for the published version before announcing it. Keep the GitHub release notes and any game/runtime attachments aligned with the same source commit.
