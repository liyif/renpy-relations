# Ren’Py Relations

[English](README.md) · [简体中文](README.zh-CN.md)

An embeddable Python library for relational facts and compiled Logica rules, with optional Ren’Py integration.

Story conditions often recur across encounters: access to a place, knowledge of a secret, or an earlier choice. Ren’Py Relations lets you name and compose those conditions as rules. Actions change facts; scripts query which actions or encounters are available. The same core works in ordinary Python applications.

[Logica](https://github.com/evgskv/logica) compiles rules to SQL during development. [SQLite](https://www.sqlite.org/about.html) or DuckDB stores facts and evaluates queries at runtime. The Ren’Py adapter connects fact snapshots to save, load, and rollback.

## A small example

The shipped [Palace rules](examples/palace/world.l) derive archive access from sponsorship or faction membership:

```python
from renpy_relations import LogicDB

logic = LogicDB("examples/palace/game/relations.rules.json")
try:
    logic.add("Sponsor", character="hero", location="archive")
    print(logic.query("CanEnter", character="hero"))
    # [{'character': 'hero', 'location': 'archive'}]
finally:
    logic.close()
```

Run from the source root after the [quickstart setup](docs/quickstart.md#prepare-the-environment). No hand-written SQL is needed for this example.

```text
world.l + schema.json
        │ renpy-relations-compile (during development)
        ▼
backend-specific JSON rule bundle
        │ LogicDB (during the game)
        ▼
facts → derived answers → script choices and effects
        │ Ren’Py adapter publishes fact snapshots
        ▼
Ren’Py snapshot variable → save / load / rollback
```

The runtime uses `cached` mode by default: it builds derived relations when first queried and invalidates affected results after fact changes. SQLite and DuckDB are available, with separate compiled bundles for each. The [reference](docs/reference.md) explains the other query modes and their tradeoffs.

## Choose a starting point

| Goal | Read |
| --- | --- |
| Embed the core in an ordinary Python application | [Python guide](docs/python.md) |
| Learn the concepts and run Palace in Python and Ren’Py | [Quickstart](docs/quickstart.md) |
| Integrate the runtime or check compiler, snapshot, and reload contracts | [Reference](docs/reference.md) |
| Play or study a complete Chinese-language narrative example | [Tidelight](examples/tidelight/README.md) |
| Understand workloads and reproduce a small performance run | [Benchmarks](benchmarks/README.md) |
| Change, verify, stage, or release the project | [Maintenance](docs/maintaining.md) |

## Installation

From a source checkout:

```sh
uv sync --locked
```

Follow the [Python guide](docs/python.md) to install a wheel or embed the library, or the [Ren’Py quickstart](docs/quickstart.md#stage-and-play-palace) to stage a game. Development uses Python 3.12; supported environments and driver versions are listed in the [reference](docs/reference.md#compatibility).

## Project layout

| Directory | Contents |
| --- | --- |
| `src/renpy_relations/` | Python package: runtime, compiler and Ren’Py adapter. |
| `docs/` | Tutorials, reference and maintenance guide. |
| `examples/` | Python permissions, Palace and Tidelight samples. |
| `tools/` | Game staging, engine checks and release tooling. |
| `tests/`, `benchmarks/` | Automated checks and performance experiments. |

## Foundations and license

Learn more through the official [Logica user guide](https://logica-lang.github.io/usrguide/) and [SQLite overview](https://www.sqlite.org/about.html). Logica compiles rules during development; games run the compiled SQL and do not need the Logica compiler.

Project code, example scripts, documentation, and original example data use the [MIT license](LICENSE). Dependencies, the Tidelight font, and distributed Ren’Py runtimes retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
