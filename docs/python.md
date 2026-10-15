# Use Ren’Py Relations in an ordinary Python application

Ren’Py Relations includes an engine-independent core for ordinary Python applications. It stores relational facts, evaluates compiled rules, invalidates affected cached answers, and captures/restores fact snapshots. Your application chooses what to do with those answers. No Ren’Py SDK, event loop, or game lifecycle is required.

## Install

The single Python distribution is named `renpy-relations`; the import is `relation_rules`. From the source checkout, build it with uv:

```sh
uv build --out-dir dist/python
```

This produces `renpy_relations-0.3.0-py3-none-any.whl` and `renpy_relations-0.3.0.tar.gz`. In your application's uv project, install the local wheel:

```sh
uv add /path/to/renpy_relations-0.3.0-py3-none-any.whl
```

These instructions use local artifacts; no package-index publication is assumed. You can also use `uv add /path/to/RenpyRelations` to install from a checkout.

| Installation | Dependencies |
| --- | --- |
| Default | SQLAlchemy; SQLite uses Python's `sqlite3`. |
| `--extra duckdb` | Also installs DuckDB and its SQLAlchemy dialect. |
| `--extra compiler` | Also installs Logica for development-time compilation. |

For example, `uv add --extra compiler --extra duckdb /path/to/renpy_relations-0.3.0-py3-none-any.whl` installs both optional features. The runtime uses precompiled JSON bundles and does not import Logica. The pure Python wheel contains the optional adapter code, which is inactive unless explicitly used; it does not install or import Ren’Py.

## Run the standalone example

The source archive includes [python_access](../examples/python_access/main.py), a permissions example. Membership or sponsorship creates candidate access; an explicit revocation removes it. Its [schema](../examples/python_access/schema.json) declares the facts and exported answers, and its [Logica source](../examples/python_access/world.l) defines:

```prolog
Candidate(user:, resource:) distinct :-
  Member(user:, role:), RoleAccess(role:, resource:);
Candidate(user:, resource:) distinct :- Sponsored(user:, resource:);

CanAccess(user:, resource:) distinct :-
  Candidate(user:, resource:), ~Revoked(user:, resource:);
```

Each rule reads relations; commas combine conditions, alternative rules contribute answers, and `~Revoked(...)` excludes revoked access. The [Palace quickstart](../QUICKSTART.md#facts-tables-and-rules) explains relations, schemas and Logica syntax from the beginning.

From the source root:

```sh
uv sync --locked --extra duckdb
uv run --locked python examples/python_access/main.py
uv run --locked --extra duckdb python examples/python_access/main.py --backend duckdb
```

Both runs print:

```text
Eligible: [{'user': 'alice', 'resource': 'drafts'}, {'user': 'bob', 'resource': 'drafts'}]
Alice after revocation: False
Alice after restore: True
```

The example ships both compiled bundles. To test the installed wheel, copy `examples/python_access` from the source archive into your application and run its `main.py`; no source-checkout imports are needed.

## Integrate the core

```python
from relation_rules import LogicDB

logic = LogicDB("access.sqlite.rules.json")
try:
    with logic.batch():
        logic.add("Member", user="alice", role="editor")
        logic.add("RoleAccess", role="editor", resource="drafts")

    if logic.has("CanAccess", user="alice", resource="drafts"):
        print("The application may offer access.")

    saved = logic.snapshot()
    logic.add("Revoked", user="alice", resource="drafts")
    logic.restore(saved)
finally:
    logic.close()
```

`LogicDB`, `RuleSet`, and `RuleError` are the public core imports. Choose `cached`, `live`, or `materialized` with the `mode` constructor argument. The backend comes from the compiled bundle. Use separate bundles for SQLite and DuckDB.

Queries return lists of row dictionaries; `has()` answers existence. Group related writes in `batch()`, then query after it exits. A failed batch rolls back. Queries do not perform application actions. See the [runtime reference](reference.md#runtime-api) for keys, filters, transaction restrictions, errors and diagnostics.

## Compile rules during development

Install the `compiler` extra in your development environment. The installed command and module entry point accept the same options:

```sh
uv run renpy-relations-compile world.l --schema schema.json --output access.sqlite.rules.json
uv run python -m relation_rules.compiler world.l --schema schema.json \
  --backend duckdb --output access.duckdb.rules.json
```

The DuckDB command also needs the `duckdb` extra. The compiler records SQL, dependencies and source identity, validates the result, then publishes the JSON atomically. Runtime processes need the JSON and corresponding database driver, without the compiler. Rules and SQL are trusted application build artifacts; field values passed to queries and mutations are bound parameters.

The source-checkout command `python compile_rules.py ...` remains supported.

## Manage application state

Each `LogicDB` owns one in-memory fact world. `snapshot()` returns native image bytes. Your application can retain or persist those bytes and later pass them to `restore()`. Snapshots contain facts and compatibility metadata; derived answers are rebuilt. Other application state must be saved separately.

Without a snapshot callback, ordinary commits invalidate a retained image and capture a new one only when `snapshot()` is requested. If your host needs a published image after each changed batch, pass `on_snapshot=callback` when constructing the core. This incurs a full native image per changed commit. See [snapshot sinks](reference.md#snapshot-sinks) for failure and reentrancy behavior.

`reload_rules()` preserves facts while replacing compatible rules; `reload_if_changed()` polls a bundle path when your application calls it. The core creates no polling thread or engine callback.

## Ren’Py compatibility and limits

Existing games can continue using `from renpy_relations import LogicDB` and `logic.install_renpy(config)`. That compatibility class is `relation_rules.renpy.RenpyLogicDB`, a subclass of the core. It owns the Ren’Py binding, store publication, lifecycle callbacks and developer notifications. The core `LogicDB` has no `install_renpy()` method or Ren’Py binding state. New Ren’Py integrations may import `RenpyLogicDB` explicitly.

The rule-bundle identifier `renpy-relations` and snapshot metadata remain unchanged to preserve existing data. These identifiers do not imply an engine dependency.

Use one world synchronously on its owning thread. Async access, concurrent sharing, arbitrary SQL, a persistent database connection supplied by the host, and distributed execution are outside the public interface. Native snapshots require the same backend and compatible fact schema; long-term portability across database versions is unverified. Python metadata permits >=3.11,<3.15; local installation and integration checks currently use Python 3.12 on Linux x86_64. The `py3-none-any` wheel contains Python code, while optional drivers have their own platform requirements.
