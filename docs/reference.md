# Compiler and runtime reference

[English](reference.md) · [简体中文](reference.zh-CN.md)

[Data model](#data-model) · [Compile rules](#compile-rules) · [Runtime API](#runtime-api) · [Query modes](#query-modes) · [Snapshots and reload](#snapshots-and-reload) · [Ren’Py integration](#renpy-integration) · [Compatibility](#compatibility) · [Troubleshooting](#troubleshooting)

Use the [Palace quickstart](quickstart.md) for a complete first exercise. This page defines the compiler, runtime, snapshot, and Ren’Py adapter contracts. The [Tidelight guide](../examples/tidelight/README.md) explains one application built on them; [maintenance](maintaining.md) covers staging, verification, and releases.

Import `LogicDB`, `RenpyLogicDB`, `RuleSet`, and `RuleError` from `renpy_relations`. Ordinary Python applications use `LogicDB`; Ren’Py projects use `RenpyLogicDB`. See the [Python guide](python.md) for standalone installation.

## Data model

A **relation** is table-shaped data with named **columns**. A **row** supplies one value for each column. A **schema** declares those relations and their column types. A **fact** is a row recorded by game code; a **rule** derives answers from facts and other rules. A **query** reads matching rows. Relations can represent permissions, knowledge, completed actions, or scores; the word does not imply a romantic relationship.

The boundary between components is deliberate:

| Component | Responsibility |
| --- | --- |
| `schema.json` | Declare writable fact relations and exported derived relation columns. |
| Logica source, usually `world.l` | Define derived predicates and optional internal helpers. |
| `renpy-relations-compile` | Compile backend-specific SQL, record dependencies, validate outputs, and publish a JSON rule bundle. |
| `LogicDB` | Store facts, evaluate derived answers, group writes, and capture or restore fact images. |
| Game code | Choose among eligible actions and record their effects. |
| Ren’Py adapter | Publish fact images to a store variable and restore the database when Ren’Py restores that variable. |

Eligibility is a query result. Granting a reward or advancing a scene is an application action. Queries do not apply those effects.

### Schema declarations

A compiler schema has exactly two top-level keys, `facts` and `derived`, both dictionaries. A fact declaration accepts `columns` and an optional `key`. A derived declaration accepts only `columns`; the compiler supplies its SQL.

```json
{
  "facts": {
    "Member": {
      "columns": {"character": "text", "faction": "text"},
      "key": ["character"]
    }
  },
  "derived": {
    "Scholar": {"columns": {"character": "text"}}
  }
}
```

Each relation needs at least one column. Relation and column identifiers start with an ASCII letter and contain only ASCII letters, digits, and underscores. Names beginning with `sqlite_`, in any letter case, are reserved. Relation names must be unique across facts and derived outputs ignoring case; column names within a relation must also be unique ignoring case. Python calls use the exact declared spelling.

| Declared type | Normal Python value | Contract |
| --- | --- | --- |
| `text` | `str` | Text values. |
| `integer` | `int` | Database integer values; numeric keys do not request automatic numbering. |
| `real` | `float` | Floating-point values. DuckDB uses double precision. |
| `boolean` | `bool` | Boolean values; derived non-null truth values are normalized to true or false. |

Facts are non-nullable. `add()` requires every column, even when the relation has a key. Derived columns may contain `None`; the runtime casts derived output columns to their declared types in all query modes. Declaration validation is not a complete Python value validator: SQLAlchemy and the selected database perform binding, conversion, and constraint checks. Supply values of the declared type rather than relying on backend coercion.

Every fact relation has uniqueness over its complete tuple. Adding the identical tuple again has no effect. An optional `key` is a non-empty list of distinct declared column names and adds a primary-key constraint. A new tuple with an existing key and different non-key values fails; `add()` does not update or replace it. Replace a keyed row with `remove()` and `add()` in one batch.

Derived outputs are read-only through this API. Their rows are not automatically made unique; use Logica’s `distinct` when the rule should return unique rows.

### Compiled rule bundle and `RuleSet`

The runtime consumes a compiled JSON bundle or a `RuleSet`, not Logica source. A bundle has these fields:

| Field | Meaning |
| --- | --- |
| `format` | Exactly `"renpy-relations"`. |
| `version` | Integer `1`. |
| `backend` | `"sqlite"` or `"duckdb"`; omitted means SQLite. |
| `facts` | Fact declarations as above. |
| `derived` | Each declaration has `columns` and a non-empty compiled `sql` string. |
| `dependencies` | Every derived name maps to a list of the declared fact or derived relations it reads. Required when there are derived outputs. |
| `source` | Optional compiler provenance; generated bundles record source and input hashes and compiler version. |

Unknown top-level or relation-declaration fields are rejected. Dependency lists cannot contain unknown or duplicate names. The dependency graph between exported relations must be acyclic; constructing a runtime validates that graph.

```python
from renpy_relations import RuleSet

rules = RuleSet.load("examples/palace/game/relations.rules.json")
print(rules.backend)                   # "sqlite"
print(rules.reads["CanInvestigate"])   # direct fact and exported-relation reads
document = rules.document             # independent JSON-compatible copy
```

| Public interface | Meaning |
| --- | --- |
| `RuleSet(document)` | Validate a JSON-compatible bundle and isolate it from later edits to the input document. |
| `RuleSet.load(path)` | Read a UTF-8 JSON bundle from a filesystem path. |
| `rules.document` | Return a new independent copy, suitable for inspection or writing a bundle. |
| `rules.backend` | Selected database backend. |
| `rules.fact_schema_id` | Digest of fact declarations used to check snapshot and reload compatibility. Dictionary order does not affect it. |
| `rules.reads` | Dictionary of direct reads, as sorted tuples, for each derived relation. |
| `rules.dependencies` | Dictionary containing only the derived-to-derived subset of those reads. |

Treat these objects as definitions. To change them, edit a `document` copy and construct a new `RuleSet`. `RuleSet` validates declarations; it does not compile Logica or execute all SQL by itself.

Compiled SQL and dependency edges are trusted build output. The runtime executes that SQL and trusts its edges for evaluation order and invalidation; it does not inspect SQL to reconstruct dependencies or enforce a sandbox. Use bundles built from your own trusted rules. Gameplay values passed to mutation and query methods are bound parameters.

## Compile rules

Run commands from the repository root in its locked development environment:

```sh
uv run --locked renpy-relations-compile examples/palace/world.l \
  --schema examples/palace/schema.json \
  --output /tmp/palace-relations.rules.json
```

| Argument | Behavior |
| --- | --- |
| `source` | Required positional Logica source path. Its parent is the local import root. |
| `--schema PATH` | Required schema JSON path. |
| `--output PATH` | Required compiled bundle destination; missing parent directories are created. |
| `--backend sqlite\|duckdb` | Override the source’s `@Engine` selection without editing the source. |
| `--watch` | Build initially, then rebuild after detected local input changes until interrupted. |

Without an override, the source must select SQLite or DuckDB. Install the DuckDB extra when compiling or running DuckDB bundles, for example `uv run --locked --extra duckdb renpy-relations-compile … --backend duckdb`. A bundle targets one backend; selecting a different backend at runtime does not translate its SQL.

The Python entry point is `compile_rules(source, schema, output, *, backend=None)` in `renpy_relations.compiler`. It returns the validated `RuleSet` after successful publication. The one-shot CLI exits `0` on success and `1` on a handled build failure.

Every declared derived output must be defined in Logica. Fact names are external tables: the compiler rejects Logica definitions of those names, including source facts. Undeclared external relation reads are rejected. Helpers that are not exported may be inlined by Logica. An exported derived predicate remains a relation boundary when another export reads it; this makes its typed result and cached work reusable. Negative and aggregate reads also participate in dependency tracking.

Before publication, the compiler creates an empty materialized world, executes typed outputs in dependency order, and checks each SQL output’s column names and count against the declaration. This catches invalid references, output shapes, and exported dependency cycles. It does not prove that every future gameplay value will evaluate successfully; a data-dependent SQL error may still occur later. DuckDB multi-statement workflows and UDF definitions are rejected.

The runtime can execute a supported recursive SQL query within a single output, including the SQLite recursive CTE covered by tests. That is separate from a cycle between exported relations, which is rejected. This is not a promise that every recursive Logica program or backend feature is supported: compilation and output validation must succeed for the chosen backend.

### Publication and watching

The compiler builds and validates before replacing the output. It writes beside the destination and atomically replaces the destination file. A failed build leaves the previous bundle intact; unchanged generated content leaves it untouched. It also compares input hashes before and after compilation and rejects a build if the inputs changed during it.

`--watch` checks every 0.5 seconds. Its input set includes the schema, the source, and all `*.l` files below the source directory, including local imports. External import roots are outside its watch scope. A failed build is reported to stderr and the watcher continues. It retries when the observed input state changes; it does not repeatedly rebuild an unchanged failing state. Interrupting the watcher exits normally.

This watcher publishes a bundle. It does not update an already-running `LogicDB`; use runtime reload or the adapter watcher described below. Staging an example copies its shipped bundles, so compiling to `/tmp` does not change the staged game. See the [quickstart](quickstart.md) for compiling directly to a staged game’s selected bundle.

## Runtime API

```python
from renpy_relations import LogicDB

logic = LogicDB("examples/palace/game/relations.rules.json")
try:
    logic.add("Sponsor", character="hero", location="archive")
    allowed = logic.has("CanEnter", character="hero", location="archive")
    rows = logic.query("CanEnter", character="hero")
finally:
    logic.close()
```

`LogicDB(rules, *, backend=None, mode="cached", on_snapshot=None)` creates an empty in-memory world. `rules` is a bundle path or `RuleSet`. `backend`, when supplied, checks that the bundle targets that backend; it does not override it. `mode` selects evaluation behavior. `on_snapshot` is an optional synchronous callback receiving image `bytes` after a changed commit.

One `LogicDB` represents one synchronous world. Use the public operations to manage it; direct connection access, asynchronous access, and sharing a world across threads are not public contracts.

### Facts and queries

| Method | Result and behavior |
| --- | --- |
| `add(name, /, **values)` | Assert one complete fact; returns `None`. Duplicate tuples are ignored; key conflicts fail. |
| `remove(name, /, **filters)` | Remove all matching facts; returns `None`. At least one filter is required. |
| `batch()` | Context manager yielding the same `LogicDB`; group writes into one transaction and at most one snapshot publication. |
| `query(name, /, **filters)` | Return a list of independent row dictionaries. No filters means all rows. Row order is unspecified. |
| `has(name, /, **filters)` | Return whether any row matches, using a result limit of one. No filters tests whether the relation has any rows. |
| `query_sql(sql, params=None, *, reads)` | Execute one read-only SQL query with named values and explicit relation reads; see below. |

The relation name is positional-only in `add()`, `remove()`, `query()`, and `has()`. Column names such as `name` and `self` remain available as values or filters:

```python
# For a schema declaring Person(name: text, self: text):
logic.add("Person", name="hero", self="origin")
assert logic.has("Person", name="hero", self="origin")
```

Filters combine with SQL equality and logical AND. `None` matches a null derived value. Use `query_sql()` for ordering, range filters, joins, and aggregation, or define reusable derivations in Logica.

Only declared facts can be added or removed. Unknown relations, unknown columns, incomplete additions, and unfiltered removals raise `ValueError`. Passing the relation as a keyword rather than positionally is Python argument misuse and raises `TypeError`.

### SQL queries

`query_sql(sql, params=None, *, reads)` executes one read-only query and returns independent row dictionaries. SELECT queries, CTEs, named parameters, comments, and a trailing semicolon are supported:

```python
rows = logic.query_sql(
    """
    SELECT location, COUNT(*) AS characters
    FROM CanEnter
    GROUP BY location
    ORDER BY characters DESC, location
    LIMIT :limit
    """,
    {"limit": 10},
    reads=("CanEnter",),
)
```

`reads` is a required list or tuple naming every directly referenced fact or derived relation. Indirect dependencies come from the compiled bundle; do not list them again. Use `reads=()` for queries that read no relations. In cached mode, only the requested derived relations and their dependencies are prepared, once per query. Subsequent queries reuse valid relation tables, but SQL result lists are never cached.

The runtime validates the names in `reads`; it does not infer or verify them against SQL. An omitted relation can be absent on its first use or contain stale cached rows after a fact change. Keep this declaration with the SQL, including relations read by subqueries and CTEs. It has the same meaning in all three modes.

`params` is a mapping of names to bound values, using `:name` placeholders. Values are not SQL fragments or identifiers. SQL uses the selected backend's dialect, and output values use its native driver types, without the schema conversions performed by `query()`. Give duplicate output columns distinct `AS` aliases; ambiguous names raise `ValueError`.

Writes, DDL, transaction commands, and multiple statements are rejected. SQLite uses its native authorizer, and DuckDB uses native statement classification; neither parses SQL in Python. Fact writes continue through `add()` and `remove()`. SQL is trusted application code, like compiled rules; this interface is not a sandbox for user-supplied SQL or external-resource access. Empty or non-string SQL and unknown relation names raise `ValueError`; invalid `params` or `reads` container types raise `TypeError`; syntax, binding, and execution errors retain backend exceptions. Failed queries roll back their cache preparation and leave the world usable. No connection or cursor escapes the call.

### Transactions and no-ops

Outside a batch, each `add()` or `remove()` starts its own batch. Inside one, writes accumulate until the context exits successfully. Read conditions before entering the batch, then query the committed world afterward:

```python
# For the keyed Member schema shown above:
with logic.batch():
    logic.remove("Member", character="hero")
    logic.add("Member", character="hero", faction="scholars")
members = logic.query("Member", character="hero")
```

An exception escaping the batch rolls back its fact writes and any eager output rebuilding. Catch a failed database operation outside the batch rather than continuing to use a failed transaction.

A batch with no changed SQL rows does not invalidate outputs or publish a snapshot. Empty batches, reasserting an identical tuple, and removing a nonexistent match are such no-ops. A sequence that changes rows and then reverses those changes is still a changed batch; the runtime does not compare final fact sets to detect net-zero work.

Nested batches are forbidden. `query()`, `query_sql()`, `has()`, `snapshot()`, `restore()`, reload operations, `stats()`, `close()`, and adapter installation require an idle world and raise `RuntimeError` during a batch or snapshot publication. A snapshot callback cannot reenter these operations or start another write. `describe()` only inspects the declaration and does not evaluate rules.

### Inspection and closure

| Method | Contract |
| --- | --- |
| `describe(name)` | Return independent metadata: `name`, `kind` (`"facts"` or `"derived"`), declared columns, key or SQL when present, direct `reads`, and derived-only `dependencies`. Does not evaluate rules. |
| `stats()` | Return `mode`, `backend`, `cached_relations`, `materializations`, `materialization_seconds`, and `snapshot_bytes`. Does not execute rule queries or create an image. |
| `close()` | Dispose of the world and release database resources. Repeated calls are harmless. Operations needing the world then raise `RuntimeError`. |

`cached_relations` lists currently valid lazy cached outputs. `materializations` counts successfully completed lazy materializations by relation; `materialization_seconds` measures lazy fill work and can include work from a failed attempt. These diagnostics do not count all eager or live SQL execution. `snapshot_bytes` is zero when no image is currently retained; it does not estimate total process memory or Ren’Py rollback history. Diagnostic counters belong to the `LogicDB` instance and are not restored with fact images.

## Query modes

All three modes expose the same facts and declared output types. They place evaluation costs and data-dependent errors at different points.

| Mode | Preparation | After changed facts | Read behavior |
| --- | --- | --- | --- |
| `cached` (default) | Prepare declarations and dependency graph; derived tables are created lazily. | Invalidate affected derived relations. | Build the requested relation and its needed invalid dependencies, then reuse valid results. |
| `materialized` | Create and fill all derived tables in dependency order. | Refill affected outputs in the same transaction as the facts. | Read stored derived rows. |
| `live` | Create derived views. | Commit facts without cached-output rebuilding. | Let the database evaluate views on each read. |

Invalidation is at **relation granularity**. Changing one row in `Sponsor` can invalidate all rows of an output that depends on `Sponsor`, plus its downstream outputs. It does not track individual characters, filters, or changed result rows. Unrelated outputs remain valid. Declared negative dependencies matter: adding a previously absent blocking fact can change an answer.

A cached `has()` with a narrow filter still materializes the entire needed relation. A later query with a different filter shares that materialization. Each read applies its filters in the database; the cache does not store separate answers per filter.

In materialized mode, a failed affected-output rebuild rejects the fact transaction. In cached or live mode, a fact commit can succeed and a later read can fail on the new values. Failed lazy reads do not publish partially built dependencies as valid, so correcting facts allows a later retry. Reload preflights every output against current facts in all modes.

For workload measurements and their limits, see [benchmarks](../benchmarks/README.md).

## Snapshots and reload

A **snapshot** is native database image `bytes` containing facts and format/schema metadata. Derived tables, views, caches, rule SQL, and the rest of the game state are excluded. SQLite uses native serialization or backup; DuckDB copies a native fact database image. Both implementations may use temporary files while copying.

| Method | Contract |
| --- | --- |
| `snapshot()` | Return the current image, creating it if needed. Repeated calls without a changed commit reuse the same retained `bytes` object. |
| `restore(image)` | Prepare a replacement world from snapshot `bytes`, validate it, then swap it in. |
| `restore(None)` | Replace the world with empty facts under the current rules and mode. Rules with constant outputs can still return rows. |
| `reload_rules(rules=None)` | Keep current facts, validate and preflight new rules, then replace the world and rules together. |
| `reload_if_changed()` | Compare the selected bundle file’s bytes with the last loaded bytes; return `True` if a replacement was installed, otherwise `False`. |

```python
past = logic.snapshot()
logic.remove("Sponsor", character="hero", location="archive")
logic.restore(past)
assert logic.has("Sponsor", character="hero", location="archive")
```

Ordinary commits with no snapshot sink do not copy the whole database. A changed commit discards the retained image, and the next explicit `snapshot()` captures the new facts. Reads and lazy materialization do not change fact images. No-op commits preserve the retained image.

`restore()` requires `bytes` or `None`; other values raise `TypeError`. Invalid images, incompatible metadata, or mismatched native fact schemas raise `RuleError` and leave the current world intact. The image must match the backend and fact schema, including keys and column types. There is no automatic migration or cross-backend exchange. Reordering JSON dictionaries does not change schema identity; changing a key’s declared order changes its declaration.

### Snapshot sinks

With `on_snapshot=callback`, each changed batch commits facts, creates one image, and calls the sink synchronously. If image creation or the callback raises, the runtime restores the previous retained fact image and re-raises the error. A newly constructed instance starts with an empty baseline. The Ren’Py installation captures a baseline image before binding its sink.

The callback should accept and store the supplied image as one publication. The runtime can restore its own facts after a callback failure; it cannot undo arbitrary external work performed by the callback. Explicit `restore()` and rule reload do not call the sink. No-op batches do not call it either.

### Rule replacement

`reload_rules()` accepts a new bundle path or `RuleSet`. With no argument it rereads the currently selected path. An instance constructed from a `RuleSet` has no path until one is supplied; no-argument reload and file watching then raise `ValueError`.

Reload requires the same backend and fact-schema identity. It can change derived declarations, SQL, and dependencies. The candidate world evaluates all new outputs against the current facts before replacing the active world. Invalid bundles and data-dependent preflight errors preserve the old facts and rules. A successful reload from a path also selects that path for future watching; reloading from a `RuleSet` removes the source path.

Snapshots store facts, not frozen rule logic. Restoring an older snapshot after a successful reload evaluates its facts using the **current** rules. Snapshot compatibility therefore permits derived-rule changes, but does not preserve an old story’s eligibility logic. Rule changes and fact-schema migrations are different operations; schema changes require a new world or application-managed conversion outside this API.

`reload_if_changed()` watches the compiled file, not source rules. It compares content rather than modification time. A failed reload leaves the last loaded content marker unchanged, so callers can retry after repairing the file. Filesystem failures propagate as `OSError`.

## Ren’Py integration

Stage dependencies and bundles as described in the [quickstart](quickstart.md). A minimal binding uses a `default` store variable and installs once during initialization:

```renpy
default logic_snapshot = None

init python:
    import os
    import sys
    sys.path.insert(0, os.path.join(config.gamedir, "python-packages"))
    from renpy_relations import RenpyLogicDB as LogicDB

    logic = LogicDB(os.path.join(config.gamedir, "relations.rules.json"))
    logic.install_renpy(config)
```

The staged game supplies native dependencies through `python-packages`; adding it to `sys.path` lets Python discover those modules. Record initial facts when starting a new game, after defaults have restored an empty fact world. Do not seed them only during initialization: the after-default callback may replace that world.

`install_renpy(config, snapshot_variable="logic_snapshot", *, watch_rules=False)` takes:

| Argument | Meaning |
| --- | --- |
| `config` | Ren’Py configuration object receiving lifecycle callbacks. |
| `snapshot_variable` | Attribute name on `renpy.store`; declare the corresponding variable with `default … = None`. |
| `watch_rules` | Register a compiled-bundle poll on interactions; defaults to `False`. Requires a bundle path. |

Installation captures the current baseline image, attaches a snapshot sink that assigns `renpy.store.<snapshot_variable>`, and appends a callback to `config.after_default_callbacks`. That callback restores the current store image, or empty facts if the variable is absent or `None`. Ren’Py saves and rollback retain the store value; when its lifecycle restores that value, the callback rebuilds the database from it. The database connection itself is not the saved state.

Installing again with the same configuration, variable, and watch setting is harmless. Rebinding the same instance differently raises `RuntimeError`. An instance with an existing `on_snapshot` sink cannot also install this adapter and raises `ValueError`. There is no public adapter uninstall operation; keep the bound instance alive for the game’s lifecycle.

### Development watching

`watch_rules=True` adds a callback to `config.interact_callbacks`. It polls only when `config.developer` is true and the instance has a source path. It invokes `reload_if_changed()`; it does not compile Logica or poll on a background timer.

Run the compiler’s `--watch` separately to turn edits into validated bundles. On a reload `RuleError` or `OSError`, the adapter logs the failure through Ren’Py, notifies the developer, and keeps the previous world active. Repeated identical error messages are suppressed until a successful poll clears the error. Other exception categories are not caught by this watcher.

The [Palace game](../examples/palace/game/script.rpy) demonstrates binding and inspection; its [engine testcases](../examples/palace/game/testcases.rpy) exercise save/load, rollback, new games, and reload. Those are adapter scenarios, not an automatic save format for unrelated game data.

## Compatibility

These scopes are distinct:

| Scope | Declared or selected target |
| --- | --- |
| Core project metadata | Python `>=3.11,<3.15`. |
| Repository development interpreter | Python `3.12`, selected by `.python-version`. |
| Staging tool | Linux x86_64, Python `3.12`, wheels for `x86_64-manylinux_2_28`; an optional SDK probe checks its interpreter. |
| Release builder | Pinned Ren’Py SDK `8.5.3.26051504`. |

The staged Linux x86_64/Python 3.12 setup is the automated integration target. The broad metadata range does not establish deployment support for every Ren’Py platform or Python version. Other operating systems, architectures, and SDK versions remain unverified targets. See [maintenance](maintaining.md) for the engine checks and release evidence workflow.

Runtime dependencies are SQLAlchemy `2.0.43` and a compatible SQLite driver, or the optional DuckDB `1.5.6` and duckdb-engine `0.17.0` pair. SQLite is the default backend. The runtime first tries `sqlite3`, then `pysqlite3`; the staging group supplies pinned Linux `pysqlite3-binary`. Compilation uses pinned Logica `1.3.1415926535897`; Logica is not needed to execute a compiled bundle.

Rule bundle version `1` and snapshot metadata version `2` are separate formats. Snapshots are native backend images, so long-term portability across database-library changes is not established by the bundle version or Python metadata. Keep backend/schema compatibility and deployment-version verification separate from ordinary rule reload.

## Troubleshooting

`RuleError` subclasses `ValueError`. It identifies invalid or incompatible bundles, compilation failures, and snapshot/reload preparation failures. It is not a wrapper for every runtime failure. Existing worlds survive rejected restore or reload candidates; ordinary database errors follow transaction and mode behavior described above.

| Symptom | Cause and recovery |
| --- | --- |
| `No SQLite driver` | The interpreter has neither usable `sqlite3` nor `pysqlite3`. Use the supported staging workflow in the [quickstart](quickstart.md), which installs the Linux driver. |
| `DuckDB backend requires the uv extra: --extra duckdb` | Run with the DuckDB extra or stage with `--backend duckdb`. Both `duckdb` and `duckdb-engine` are required. |
| `Logica is not installed in this Python environment` | Compile in the locked development environment, rather than the runtime-only staged game. |
| Bundle backend differs from requested backend | Select a bundle compiled for that backend, or recompile with `--backend`. The constructor’s `backend` argument only checks the target. |
| `lacks dependencies`, undeclared relations, or cyclic dependencies | Rebuild with `renpy-relations-compile`; correct relation spellings and exported dependency cycles. Do not guess edges from SQL. |
| Output-column build failure | Make derived schema columns match the named Logica output columns. Repair the source/schema and rebuild; the previous published bundle remains available. |
| `add(...) requires every field` or unknown fields | Supply a complete fact with exact declared column names. Filters can use a subset, but additions cannot. |
| A different tuple for an existing key raises a database integrity error | Remove the old keyed row and add the replacement in one batch. Identical tuples alone are ignored. |
| `remove() requires filters` | Provide at least one declared column filter; the API has no unfiltered delete operation. |
| Operation forbidden during a batch or snapshot publication | Move queries and lifecycle operations before or after the batch. Keep snapshot sinks non-reentrant. |
| SQL failure on a query or commit | Inspect the input values and rule expressions. Cached/live errors can appear at read time; eager rebuild errors reject the write. These may be SQLAlchemy/database exceptions rather than `RuleError`. |
| `Hot reload cannot change the fact schema` | Start a new world with the new schema. Existing snapshots are not migrated automatically. |
| Invalid image or snapshot schema/backend mismatch | Restore an image from the same backend and fact schema. The current world is retained when validation rejects it. |
| Source edits do not change the game | Ensure the compiler builds the actual selected game bundle, then reload it. Compiler watching and adapter watching are separate steps. |
| Watched build/reload fails | Read compiler stderr or Ren’Py’s `log.txt`, repair the source/schema or bundle, and rebuild. The last good bundle/rules remain active. Adapter polling requires developer mode. |
| `LogicDB is closed` | Create a new instance; a closed world cannot be reopened. |

Invalid method arguments generally raise `ValueError` or `TypeError`; excluded lifecycle operations raise `RuntimeError`; missing drivers raise `ImportError`; filesystem access can raise `OSError`. Handle the category relevant to the operation rather than catching only `RuleError` around every call.
