# Maintain and release Ren’Py Relations

Use the [quickstart](../QUICKSTART.md) to learn the working integration, the [reference](reference.md) for runtime/compiler contracts, and the [project introduction](../README.md) for scope. This page covers changing the source and producing verifiable Linux artifacts.

## Set up a contributor environment

Work from the source root with `uv`. `.python-version` selects Python 3.12; metadata permits Python >=3.11,<3.15, which is broader than the verified staging target. Keep `uv.lock` authoritative:

```sh
uv sync --locked --extra duckdb --group renpy-linux --group assets
```

The default `dev` group includes the pinned Logica compiler and pytest. `--extra duckdb` adds DuckDB and its SQLAlchemy dialect; `--group renpy-linux` adds the Linux x86_64 SQLite driver used in staged games; `--group assets` adds fontTools. The project sets `package = false`: contributors run its source files directly. A locked sync fails if metadata and lockfile disagree; change and review the lockfile deliberately when updating dependencies.

| Source area | Role |
| --- | --- |
| `renpy_relations.py` | RuleSet validation, database backends, transactions, query modes, native snapshots, reload, Ren’Py adapter. |
| `compile_rules.py` | Schema checks, Logica compilation, dependency extraction, bundle validation and publication. |
| `examples/palace/` | Small permissions and one-time reward exercise, with engine testcases. |
| `examples/tidelight/` | Narrative sample, data-driven actions, prose, rule bundles, font and font builder. |
| `tests/` | Focused compiler, runtime, backend, example, benchmark, staging and release checks. |
| `prepare_game.py`, `check_renpy.py`, `release.py` | Dependency staging, actual engine test runner, clean-source release builder. |
| `benchmarks/` | Isolated measurement tools and preserved historical results; see its [guide](../benchmarks/README.md). |

## Validate the part you change

Choose existing focused tests before broadening the run:

```sh
uv run --locked --extra duckdb pytest -q tests/test_compiler.py tests/test_dependencies.py
uv run --locked --extra duckdb pytest -q tests/test_relations.py tests/test_backends.py
uv run --locked --extra duckdb --group assets pytest -q tests/test_tidelight.py
uv run --locked --extra duckdb pytest -q tests/test_release.py tests/test_engine_runner.py
```

Compiler tests cover publication and rejection behavior. Runtime/backend tests exercise mutations, modes, snapshot/restore and reload. Tidelight tests also compare shipped bundles to fresh compilation. Staging/release tests check tooling contracts; they do not replace a real SDK build. Use the matching benchmark test modules for measurement/report changes; a full benchmark run is not a routine documentation check.

After editing an example's `world.l` or `schema.json`, regenerate both bundles. This example uses Palace; repeat with `examples/tidelight` when changing that world:

```sh
uv run --locked python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json --output examples/palace/game/relations.rules.json
uv run --locked --extra duckdb python compile_rules.py examples/palace/world.l \
  --schema examples/palace/schema.json --backend duckdb \
  --output examples/palace/game/relations.duckdb.rules.json
```

Review schema, SQL, dependencies, and source identity together. Staging copies shipped JSON; it does not quietly compile changes for you. Keep public snippets aligned with [reference.md](reference.md) and rerun their focused checks when a contract changes.

For Tidelight text or font edits, follow its [font provenance and rebuild instructions](../examples/tidelight/README.md#font-and-license). The coverage check requires the assets group, or pytest can skip it:

```sh
uv run --locked --group assets pytest -q tests/test_tidelight.py \
  -k shipped_font_contains_every_character
```

Retain the renamed font family and OFL.txt. A newly chosen upstream font needs a recorded version/hash; the original source-font identity remains unestablished.

## Check a real Ren’Py project

The automated deployment target is Linux x86_64 / CPython 3.12 with Ren’Py **8.5.3.26051504**. Obtain the SDK from Ren’Py's official distribution. The workflow pins the SDK archive SHA256 to `eb0a9be7f0fb13632fe25ceade9a8bed5a1b4d6b6e83bd19eeeb29e1a1bb4a45`. Verify the archive before extraction; `release.py` checks the installed SDK's version string but does not hash your original download.

On a headless Linux host, install `xvfb`, `xauth`, `libgl1`, and `libegl1` through the host's package manager. Stage into a new directory outside the example:

```sh
SDK=/path/to/renpy-8.5.3-sdk
GAME=/tmp/relations-palace-check
uv run --locked --extra duckdb python prepare_game.py \
  --game examples/palace --out "$GAME" --backend duckdb --sdk "$SDK"
SDL_AUDIODRIVER=dummy LIBGL_ALWAYS_SOFTWARE=1 \
  xvfb-run -a "$SDK/renpy.sh" "$GAME" lint
for backend in sqlite duckdb; do
  for mode in cached live materialized; do
    uv run --locked --extra duckdb python check_renpy.py \
      --sdk "$SDK" --game "$GAME" --headless \
      --backend "$backend" --mode "$mode" --timeout 180
  done
done
```

Repeat with a fresh Tidelight project. The runner selects the `relations` testcase suite by default, provides isolated temporary saves, reads Ren’Py's explicit completed test report, and terminates the isolated engine process group afterward. This handles SDK processes that continue spinning after the test report. An absent report fails the check. Use `--suite` for a focused testcase, and `--launcher` instead of `--sdk` when testing an extracted standalone game's own launcher in a disposable copy with testcases present.

Ordinary CI runs Python tests with both drivers and assets installed, then fresh staged projects for both examples/backends in the runner's default **cached** mode. It does not request all three engine modes there. The release builder explicitly checks all three modes for both examples/backends. Keep this distinction when describing coverage; the workflow file describes configured work, not proof that a particular run passed.

## Build a release from a committed checkout

The builder requires a **clean Git commit** and reads its source through `git archive HEAD`. A source archive may have no Git history. Before releasing, use or initialize a version-controlled checkout containing the intended committed files. Merely placing uncommitted files beside a parent repository does not make them release sources. Review the version, lockfile, generated bundles, documentation, and licenses before committing through your normal project workflow.

Choose an output directory that does not exist. From that clean checkout:

```sh
uv run --locked --extra duckdb --group renpy-linux --group assets \
  python release.py build --sdk "$SDK" --out /tmp/renpy-relations-release
uv run --locked python release.py verify /tmp/renpy-relations-release
```

The build is substantial: it tests an extracted source archive, stages both examples with locked hashed binary wheels, lints them, runs every example/backend/mode engine combination, builds Tidelight with the SDK, checks its payload, then tests a disposable extracted game with its bundled engine. It does not patch SDK source. A failed build can leave an output directory containing diagnostic logs; inspect those and use a new directory for another attempt.

Staging exports exact locked requirements with hashes, installs binary wheels for `x86_64-manylinux_2_28` and Python 3.12, and checks that installed distributions retain their license files. The resulting native driver payload is platform-specific. Other operating systems, architectures, Python ABIs, and long-term native-image portability remain unverified; metadata's Python range is not a claim that these release binaries work on every allowed interpreter.

| Generated artifact | Contents and evidence |
| --- | --- |
| `renpy-relations-<version>-source.tar.gz` | Files from the clean commit, including compiler, examples, tests, docs and lockfile. |
| `renpy-relations-<version>-linux-x86_64-runtime.zip` | `game/python-packages`, both database drivers, locked requirements, dependency inventory, license material, and installation instructions. |
| `tidelight-<version>-linux.tar.bz2` | Standalone Linux game with its engine, both drivers, story, rule bundles, font, and legal notices. |
| `RELEASE.json` | Commit, source hashes, SDK/uv identity, test evidence, and artifact sizes/hashes. |
| `SHA256SUMS` | Exactly the three artifacts and RELEASE.json. |
| `logs/` | Source tests, installation, lint, engine and distribution diagnostics. |

`verify` checks artifact existence, hashes and sizes against the manifest and exact checksum coverage. It does not rerun the build or engine tests. Keep its meaning separate from the builder's recorded test evidence. The standalone payload check rejects testcases, saves, unintended cache files and `.rpa` archives, and requires both native driver extensions, the font/OFL, dependency inventory, project notices and Ren’Py's LICENSE.txt.

Retain [LICENSE](../LICENSE), [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), dependency license files listed in `DEPENDENCIES.json`, and the engine/native-component notices. Runtime dependencies and Ren’Py have their own licenses; the project's MIT license does not replace them. Font notices remain with the font.

The workflow's release-candidate job runs on manual dispatch or a `v` tag after checks. A tag must match the version in pyproject.toml. It uploads candidate artifacts and logs to CI; there is no publication step. Publishing a public release is a separate maintainer action after reviewing the manifest, checksums, logs, licenses, and extracted-archive reading paths. Preserve generated evidence with that release instead of copying changing test counts into the introduction.
