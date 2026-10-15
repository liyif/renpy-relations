# Ren’Py Relations

[English](README.md) · [简体中文](README.zh-CN.md)

**Ren’Py Relations also works without Ren’Py.** The single `renpy-relations` Python distribution includes an embeddable core for relational facts and compiled declarative rules. Import `LogicDB` from `relation_rules` to use that core in an ordinary Python application. The core runtime does not depend on Ren’Py or Logica; Logica is an optional development-time compiler. Start with the [Python integration guide](docs/python.md) for installation and a standalone permissions example.

Ren’Py Relations is an experiment in writing shared story conditions as relational facts and declarative rules. Imagine an archive that admits members of a faction or anyone with a sponsor. Several encounters also require archive access, a secret, and a record of earlier actions. Naming and composing those conditions gives them one place to change, while scene scripts ask which actions or encounters are currently eligible.

[Logica](https://github.com/evgskv/logica) supplies the rule language and SQL compiler. [SQLite](https://www.sqlite.org/about.html), the default embedded database engine, stores the facts and evaluates the compiled queries using joins and filtering. Actions change facts; rules derive answers; your script chooses an eligible event and performs its effects. Ren’Py handles dialogue, menus, presentation, and player interaction. For example, a reward query can say that a reward is available, but the script must grant it and record the claim.

The experiment asks whether this makes shared conditions easier to understand and revise, and whether it supports encounter orders driven by current state while remaining coherent through saves, rollback, and rule changes. Trying it adds a compiler, database driver, and integration work to a game. The [quickstart](QUICKSTART.md) makes that workflow concrete; the [benchmark guide](benchmarks/README.md) explains how its costs are measured.

## A small example

The shipped [Palace rules](examples/palace/world.l) derive archive access from sponsorship or faction membership:

```python
from relation_rules import LogicDB

logic = LogicDB("examples/palace/game/relations.rules.json")
try:
    logic.add("Sponsor", character="hero", location="archive")
    print(logic.query("CanEnter", character="hero"))
    # [{'character': 'hero', 'location': 'archive'}]
finally:
    logic.close()
```

Run from the source root after the [quickstart setup](QUICKSTART.md#prepare-the-environment). No hand-written SQL is needed for this example.

```text
world.l + schema.json
        │ compile_rules.py (during development)
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
| Learn the concepts and run Palace in Python and Ren’Py | [Quickstart](QUICKSTART.md) |
| Integrate the runtime or check compiler, snapshot, and reload contracts | [Reference](docs/reference.md) |
| Play or study a complete Chinese-language narrative example | [Tidelight](examples/tidelight/README.md) |
| Understand workloads and reproduce a small performance run | [Benchmarks](benchmarks/README.md) |
| Change, verify, stage, or release the project | [Maintenance](docs/maintaining.md) |

## Environment and installation

Build an installable wheel and source distribution with `uv build`; see the [Python guide](docs/python.md). Local wheel and checkout installation are supported; no package-index publication is assumed. Contributors use the source checkout and its `uv.lock`. Project metadata permits Python `>=3.11,<3.15`, and the development workflow selects Python 3.12. The staging tool targets Linux x86_64 with a Python 3.12 Ren’Py SDK; release tooling pins Ren’Py `8.5.3.26051504`. Other deployment targets require their own validation. See [compatibility](docs/reference.md) for the precise scope.

For Ren’Py, follow [Stage and play Palace](QUICKSTART.md#stage-and-play-palace). Staging installs the runtime, SQLAlchemy, and the selected native database drivers into `game/python-packages`. If the runtime reports **“No SQLite driver”**, use this staging route with the supported SDK so that both `renpy_relations.py` and the shared `relation_rules` package are installed.

## Foundations and license

Learn more through the official [Logica user guide](https://logica-lang.github.io/usrguide/) and [SQLite overview](https://www.sqlite.org/about.html). Logica compiles rules during development; games run the compiled SQL and do not need the Logica compiler.

Project code, example scripts, documentation, and original example data use the [MIT license](LICENSE). Dependencies, the Tidelight font, and distributed Ren’Py runtimes retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
