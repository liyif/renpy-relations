"""Relation facts and compiled rules for Ren'Py (Python 3.11+, SQLAlchemy 2.0).

    logic = LogicDB("relations.rules.json", mode="cached")
    logic.add("Sponsor", character="hero", location="archive")
    assert logic.has("CanEnter", character="hero", location="archive")

Only facts and their schema identifier are saved. Derived data lives in TEMP.
All writes go through batch/add/remove; queries are read-only and forbidden in
a batch. Rule SQL is trusted build-time output, gameplay values are bound.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter
import zlib

try:
    import sqlite3
except ImportError:
    try:
        import pysqlite3 as sqlite3
    except ImportError as exc:
        raise ImportError(
            "This Python runtime has no SQLite driver. See README.md for Ren'Py runtime installation."
        ) from exc

from sqlalchemy import (
    Boolean, Column, Float, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, delete, event, select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool


class RuleError(ValueError):
    """Invalid/incompatible rules or snapshot; an existing world is preserved."""


_TYPES = {"text": String, "integer": Integer, "real": Float, "boolean": Boolean}
_SQL_TYPES = {"text": "TEXT", "integer": "INTEGER", "real": "REAL", "boolean": "INTEGER"}
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_VOLATILE_FUNCTIONS = frozenset({
    "random", "randomblob", "changes", "total_changes", "last_insert_rowid",
    "load_extension", "current_date", "current_time", "current_timestamp",
    "date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff",
})


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _name(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RuleError(f"Invalid relation/field name: {value!r}")
    if value.casefold().startswith("sqlite_"):
        raise RuleError(f"Reserved SQLite name: {value}")


class RuleSet:
    """Validated, copy-isolated JSON rule definitions. SQL is checked on loading."""

    def __init__(self, document):
        try:
            self._document = json.loads(json.dumps(document))
        except (TypeError, ValueError) as exc:
            raise RuleError("Rules must be a JSON document") from exc
        doc = self._document
        if not isinstance(doc, dict) or doc.get("format") != "renpy-relations":
            raise RuleError("Expected a renpy-relations rule bundle")
        if type(doc.get("version")) is not int or doc["version"] != 1:
            raise RuleError("Unsupported rule bundle version")
        if set(doc) - {"format", "version", "facts", "derived", "source", "dependencies"}:
            raise RuleError("Unknown rule bundle fields")
        names = set()
        for kind in ("facts", "derived"):
            relations = doc.get(kind)
            if not isinstance(relations, dict):
                raise RuleError(f"{kind} must be a relation dictionary")
            for name, spec in relations.items():
                _name(name)
                if name.casefold() in names:
                    raise RuleError(f"Duplicate relation name: {name}")
                names.add(name.casefold())
                allowed = {"columns", "key"} if kind == "facts" else {"columns", "sql"}
                if not isinstance(spec, dict) or set(spec) - allowed:
                    raise RuleError(f"Invalid declaration for {name}")
                columns = spec.get("columns")
                if not isinstance(columns, dict) or not columns:
                    raise RuleError(f"{name} needs named columns")
                column_names = set()
                for column, type_name in columns.items():
                    _name(column)
                    if column.casefold() in column_names:
                        raise RuleError(f"Duplicate column on {name}: {column}")
                    column_names.add(column.casefold())
                    if not isinstance(type_name, str) or type_name not in _TYPES:
                        raise RuleError(f"Unknown type on {name}.{column}: {type_name!r}")
                if kind == "facts" and "key" in spec:
                    key = spec["key"]
                    if (not isinstance(key, list) or not key
                            or any(not isinstance(c, str) or c not in columns for c in key)
                            or len(set(key)) != len(key)):
                        raise RuleError(f"Invalid primary key for {name}")
                if kind == "derived":
                    sql = spec.get("sql")
                    if not isinstance(sql, str) or not sql.strip():
                        raise RuleError(f"{name} needs compiled SELECT SQL")
                    spec["sql"] = sql.strip().rstrip(";").strip()
        if "dependencies" in doc:
            dependencies = doc["dependencies"]
            if not isinstance(dependencies, dict) or set(dependencies) != set(doc["derived"]):
                raise RuleError("Dependencies must describe every derived relation")
            known = doc["facts"].keys() | doc["derived"].keys()
            for name, reads in dependencies.items():
                if (not isinstance(reads, list) or any(not isinstance(n, str) or n not in known for n in reads)
                        or len(set(reads)) != len(reads)):
                    raise RuleError(f"Invalid dependencies for {name}")
        self.fact_schema_id = _digest(doc["facts"])
        self.content_id = _digest({k: doc[k] for k in ("facts", "derived")})

    @classmethod
    def load(cls, path):
        return _read_bundle(Path(path))[0]

    @property
    def document(self):
        """Return an independent copy suitable for writing a bundle."""
        return json.loads(json.dumps(self._document))

    def _tables(self):
        metadata = MetaData()
        tables = {}
        for kind in ("facts", "derived"):
            for name, spec in self._document[kind].items():
                key = spec.get("key", [])
                columns = [Column(
                    column, _TYPES[type_name](), nullable=kind == "derived",
                    primary_key=column in key,
                ) for column, type_name in spec["columns"].items()]
                constraints = [UniqueConstraint(*spec["columns"])] if kind == "facts" else []
                tables[name] = Table(
                    name, metadata, *columns, *constraints,
                    schema="main" if kind == "facts" else "temp",
                )
        return tables


def _read_bundle(path):
    content = path.read_bytes()
    try:
        return RuleSet(json.loads(content.decode("utf-8"))), content
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RuleError(f"Invalid rule file {path}: {exc}") from exc


@dataclass
class _World:
    engine: object
    tables: dict
    dependencies: dict = field(default_factory=dict)
    reads: dict = field(default_factory=dict)
    order: tuple = ()
    valid: set = field(default_factory=set)

    def affected(self, conn, facts):
        """SQLite follows reverse edges; Python only binds changed fact names."""
        conn.exec_driver_sql('DELETE FROM temp.__rr_changed')
        conn.exec_driver_sql('INSERT INTO temp.__rr_changed VALUES (?)', [(n,) for n in facts])
        return [r[0] for r in conn.exec_driver_sql('''
            WITH RECURSIVE affected(name) AS (
                SELECT name FROM temp.__rr_changed
                UNION
                SELECT e.target FROM temp.__rr_edges e JOIN affected a ON e.source=a.name
            )
            SELECT n.name FROM temp.__rr_nodes n JOIN affected a USING(name)
            WHERE n.derived=1 ORDER BY n.rank
        ''')]

    def needed(self, conn, name):
        return [r[0] for r in conn.exec_driver_sql('''
            WITH RECURSIVE needed(name) AS (
                VALUES (?)
                UNION
                SELECT e.source FROM temp.__rr_edges e JOIN needed n ON e.target=n.name
            )
            SELECT n.name FROM temp.__rr_nodes n JOIN needed a USING(name)
            WHERE n.derived=1 ORDER BY n.rank
        ''', (name,))]


def _new_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
        module=sqlite3,
        connect_args={"check_same_thread": True, "cached_statements": 0},
    )

    @event.listens_for(engine, "connect")
    def connect(dbapi_connection, _):
        # Explicit BEGIN makes DDL and TEMP writes transactional on Python 3.11+.
        dbapi_connection.isolation_level = None
        # Logica uses this pure helper for correlated negation/aggregation.
        dbapi_connection.create_function("MagicalEntangle", 2, lambda x, y: x, deterministic=True)

    @event.listens_for(engine, "begin")
    def begin(conn):
        conn.exec_driver_sql("BEGIN")

    return engine


def _validate_sql(conn, world, rules):
    """Let SQLite resolve names/columns and report actual relation dependencies."""
    raw = conn.connection.dbapi_connection
    canonical = {name.casefold(): name for name in world.tables}
    derived = rules._document["derived"]
    dependencies = {}
    for name, spec in derived.items():
        reads = set()
        rejected = []

        def authorize(action, arg1, arg2, database, source):
            if action == sqlite3.SQLITE_READ:
                relation = canonical.get(arg1.casefold())
                if relation is None:
                    if arg1.casefold() in ("json_each", "json_tree"):
                        return sqlite3.SQLITE_OK
                    rejected.append(f"undeclared relation {arg1}")
                    return sqlite3.SQLITE_DENY
                reads.add(relation)
            elif action == sqlite3.SQLITE_FUNCTION:
                if (arg2 or arg1 or "").casefold() in _VOLATILE_FUNCTIONS:
                    rejected.append(f"non-deterministic function {arg2 or arg1}")
                    return sqlite3.SQLITE_DENY
            elif action not in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
                rejected.append("only a SELECT is supported")
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        raw.set_authorizer(authorize)
        try:
            result = conn.exec_driver_sql(
                f'SELECT * FROM ({spec["sql"]}) AS __rr_source LIMIT 0'
            )
            columns = list(result.keys())
            result.close()
            expected = spec["columns"]
            if len(columns) != len(expected) or set(columns) != set(expected):
                raise RuleError(f"{name}: expected columns {list(expected)}, got {columns}")
        except SQLAlchemyError as exc:
            detail = "; ".join(rejected) or str(exc.orig)
            raise RuleError(f"{name}: unsupported or invalid rule SQL: {detail}") from exc
        finally:
            raw.set_authorizer(None)
        dependencies[name] = tuple(sorted(reads))

    # SQL resolution above reports edges, including negative/subquery reads.
    # Graph algorithms execute in SQLite, without Python DFS or SQL text parsing.
    conn.exec_driver_sql('CREATE TEMP TABLE __rr_edges (source TEXT, target TEXT, PRIMARY KEY(source,target)) WITHOUT ROWID')
    conn.exec_driver_sql('CREATE INDEX temp.__rr_reverse ON __rr_edges(target,source)')
    conn.exec_driver_sql('CREATE TEMP TABLE __rr_nodes (name TEXT PRIMARY KEY, derived INTEGER, rank INTEGER) WITHOUT ROWID')
    conn.exec_driver_sql('CREATE TEMP TABLE __rr_changed (name TEXT PRIMARY KEY) WITHOUT ROWID')
    if world.tables:
        conn.exec_driver_sql('INSERT INTO temp.__rr_nodes VALUES (?,?,0)',
                             [(name, int(name in derived)) for name in world.tables])
    edges = [(source, target) for target, sources in dependencies.items() for source in sources]
    if edges:
        conn.exec_driver_sql('INSERT INTO temp.__rr_edges VALUES (?,?)', edges)
    # Distinct ancestor counts strictly increase along each edge in a DAG.
    # UNION deduplicates diamonds and terminates even when a cycle is present.
    ranks = conn.exec_driver_sql('''
        WITH RECURSIVE ancestors(node, ancestor) AS (
            SELECT target, source FROM temp.__rr_edges
            UNION
            SELECT a.node, e.source FROM ancestors a JOIN temp.__rr_edges e ON e.target=a.ancestor
        )
        SELECT node, count(*), max(node=ancestor) FROM ancestors GROUP BY node
    ''').all()
    if any(row[2] for row in ranks):
        raise RuleError("Cyclic derived relation dependency")
    if ranks:
        conn.exec_driver_sql('UPDATE temp.__rr_nodes SET rank=? WHERE name=?', [(r[1], r[0]) for r in ranks])
    declared = rules._document.get("dependencies")
    if declared is not None and any(set(declared[n]) != set(reads) for n, reads in dependencies.items()):
        raise RuleError("Compiled dependencies differ from actual SQL reads; rebuild rules")
    world.reads = dependencies
    world.dependencies = {name: tuple(n for n in names if n in derived)
                          for name, names in dependencies.items()}
    world.order = tuple(r[0] for r in conn.exec_driver_sql(
        'SELECT name FROM temp.__rr_nodes WHERE derived=1 ORDER BY rank,name'))


def _projection(world, rules, name):
    quote = world.engine.dialect.identifier_preparer.quote
    columns = rules._document["derived"][name]["columns"]
    expressions = []
    for column, type_name in columns.items():
        identifier = quote(column)
        value = identifier
        if type_name == "boolean":
            value = f"CASE WHEN {identifier} IS NULL THEN NULL WHEN {identifier} THEN 1 ELSE 0 END"
        expressions.append(f"CAST({value} AS {_SQL_TYPES[type_name]}) AS {identifier}")
    sql = rules._document["derived"][name]["sql"]
    # Explicit casts give views and materialized tables the same field semantics.
    return f'SELECT {", ".join(expressions)} FROM ({sql}) AS __rr_source'


def _fill(conn, world, rules, name):
    table = world.tables[name]
    quote = world.engine.dialect.identifier_preparer.quote
    columns = ", ".join(quote(c.name) for c in table.columns)
    conn.execute(delete(table))
    conn.exec_driver_sql(
        f'INSERT INTO temp.{quote(name)} ({columns}) '
        + _projection(world, rules, name)
    )


def _build_world(rules, mode, snapshot, *, preflight=False):
    saved_facts = None
    if snapshot is not None:
        try:
            saved = json.loads(zlib.decompress(snapshot).decode("utf-8"))
            if (not isinstance(saved, dict) or saved.get("format") != "renpy-relations-snapshot"
                    or type(saved.get("version")) is not int or saved["version"] != 1):
                raise RuleError("Unsupported snapshot format")
            if saved.get("fact_schema_id") != rules.fact_schema_id:
                raise RuleError("Snapshot fact schema differs; migration is not supported")
            saved_facts = saved.get("facts")
            if not isinstance(saved_facts, dict) or set(saved_facts) != set(rules._document["facts"]):
                raise RuleError("Snapshot must contain exactly the declared fact relations")
            for name, rows in saved_facts.items():
                if (not isinstance(rows, list) or any(
                        not isinstance(row, dict) or set(row) != set(rules._document["facts"][name]["columns"])
                        for row in rows)):
                    raise RuleError(f"Invalid snapshot rows for {name}")
        except (zlib.error, json.JSONDecodeError, UnicodeError) as exc:
            raise RuleError(f"Invalid fact snapshot: {exc}") from exc
    world = _World(_new_engine(), rules._tables())
    try:
        with world.engine.begin() as conn:
            for name in rules._document["facts"]:
                table = world.tables[name]
                table.create(conn)
                if saved_facts is not None and saved_facts[name]:
                    conn.execute(table.insert(), saved_facts[name])
            # Placeholder tables let SQLite resolve even forward references.
            for name in rules._document["derived"]:
                world.tables[name].create(conn)
            _validate_sql(conn, world, rules)
            if mode == "materialized" or preflight:
                for name in world.order:
                    _fill(conn, world, rules, name)
            if mode == "live":
                for name in reversed(world.order):
                    world.tables[name].drop(conn)
                quote = world.engine.dialect.identifier_preparer.quote
                for name in world.order:
                    sql = _projection(world, rules, name)
                    conn.exec_driver_sql(f"CREATE TEMP VIEW {quote(name)} AS {sql}")
            elif mode == "cached" and preflight:
                for name in world.order:
                    conn.execute(delete(world.tables[name]))
        return world
    except Exception as exc:
        world.engine.dispose()
        if isinstance(exc, (SQLAlchemyError, sqlite3.Error)):
            raise RuleError(f"Cannot prepare rules/snapshot: {exc}") from exc
        raise


def _snapshot_world(world, rules):
    with world.engine.begin() as conn:
        facts = {name: [dict(row) for row in conn.execute(
            select(world.tables[name])).mappings()]
            for name in rules._document["facts"]}
    payload = {"format": "renpy-relations-snapshot", "version": 1,
               "fact_schema_id": rules.fact_schema_id, "facts": facts}
    # Logical facts are portable across DB-API drivers, including pysqlite3,
    # which does not expose serialize/deserialize.
    return zlib.compress(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":"), allow_nan=False).encode("utf-8"))


class LogicDB:
    """Facts, queries and lifecycle operations over one synchronous world."""

    def __init__(self, rules, *, mode="cached", on_snapshot=None):
        if mode not in ("live", "materialized", "cached"):
            raise ValueError("mode must be live, materialized or cached")
        self.mode = mode
        self._path = None if isinstance(rules, RuleSet) else Path(rules).resolve()
        if self._path is None:
            self._rules, self._loaded_file = rules, None
        else:
            self._rules, self._loaded_file = _read_bundle(self._path)
        self._world = _build_world(self._rules, mode, None)
        self._tx = None
        self._dirty = set()
        self._notifying = False
        self._on_snapshot = on_snapshot
        self._renpy_binding = None
        self._materializations = {}
        self._materialization_seconds = 0.0
        self._saved = self.snapshot()

    def _idle(self):
        if self._world is None:
            raise RuntimeError("LogicDB is closed")
        if self._tx is not None or self._notifying:
            raise RuntimeError("Operation is not allowed during a Facts batch or snapshot publication")

    def _table(self, name, fields, *, fact=False):
        if self._world is None:
            raise RuntimeError("LogicDB is closed")
        if not isinstance(name, str) or name not in self._world.tables:
            raise ValueError(f"Unknown relation: {name!r}")
        if fact and name not in self._rules._document["facts"]:
            raise ValueError(f"Only declared Facts may be modified: {name}")
        table = self._world.tables[name]
        unknown = fields.keys() - table.c.keys()
        if unknown:
            raise ValueError(f"Unknown fields on {name}: {sorted(unknown)}")
        return table

    @contextmanager
    def batch(self):
        """Commit facts and eager outputs together, then publish one snapshot."""
        self._idle()
        self._dirty = set()
        with self._world.engine.begin() as conn:
            self._tx = conn
            try:
                yield self
                affected = self._world.affected(conn, self._dirty) if self._dirty and self.mode != "live" else []
                if self.mode == "materialized":
                    for name in affected:
                        _fill(conn, self._world, self._rules, name)
            finally:
                self._tx = None
        if not self._dirty:
            return
        self._world.valid.difference_update(affected)
        try:
            value = self.snapshot()
            self._notifying = True
            try:
                if self._on_snapshot is not None:
                    self._on_snapshot(value)
            finally:
                self._notifying = False
            self._saved = value
        except Exception:
            self.restore(self._saved)
            raise

    def add(self, name, **values):
        """Assert a complete fact; identical tuples are ignored, key conflicts fail."""
        table = self._table(name, values, fact=True)
        if set(values) != set(table.c.keys()):
            raise ValueError(f"add({name}) requires every field: {list(table.c.keys())}")
        if self._tx is None:
            with self.batch():
                self.add(name, **values)
            return
        statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=list(table.columns),
        )
        if self._tx.execute(statement).rowcount > 0:
            self._dirty.add(name)

    def remove(self, name, **filters):
        """Retract matching facts. An empty filter is forbidden."""
        table = self._table(name, filters, fact=True)
        if not filters:
            raise ValueError("remove() requires filters")
        if self._tx is None:
            with self.batch():
                self.remove(name, **filters)
            return
        if self._tx.execute(delete(table).where(
            *(table.c[k] == value for k, value in filters.items()),
        )).rowcount > 0:
            self._dirty.add(name)

    def _ensure_cached(self, conn, name, staged):
        world = self._world
        if name not in world.dependencies or name in world.valid:
            return
        for dependency in world.needed(conn, name):
            if dependency not in world.valid:
                started = perf_counter()
                _fill(conn, world, self._rules, dependency)
                self._materialization_seconds += perf_counter() - started
                staged.add(dependency)

    def _read(self, name, filters, *, exists):
        self._idle()
        table = self._table(name, filters)
        statement = select(table).where(*(table.c[k] == v for k, v in filters.items()))
        if exists:
            statement = statement.limit(1)
        staged = set()
        with self._world.engine.begin() as conn:
            if self.mode == "cached":
                self._ensure_cached(conn, name, staged)
            result = conn.execute(statement)
            value = result.first() is not None if exists else [dict(r) for r in result.mappings()]
            result.close()
        # Validity is published only when every materialization/read committed.
        self._world.valid.update(staged)
        for relation in staged:
            self._materializations[relation] = self._materializations.get(relation, 0) + 1
        return value

    def query(self, name, **filters):
        """Return independent dict rows. Row order is unspecified."""
        return self._read(name, filters, exists=False)

    def has(self, name, **filters):
        return self._read(name, filters, exists=True)

    def snapshot(self):
        self._idle()
        return _snapshot_world(self._world, self._rules)

    def _swap(self, candidate):
        previous = self._world
        self._world = candidate
        previous.engine.dispose()

    def restore(self, snapshot):
        """Prepare before swapping; an invalid snapshot leaves the world intact."""
        self._idle()
        if snapshot is not None and not isinstance(snapshot, bytes):
            raise TypeError("snapshot must be bytes or None")
        candidate = _build_world(self._rules, self.mode, snapshot)
        try:
            value = _snapshot_world(candidate, self._rules)
        except Exception as exc:
            candidate.engine.dispose()
            raise RuleError(f"Invalid fact snapshot: {exc}") from exc
        self._swap(candidate)
        self._saved = value

    def reload_rules(self, rules=None):
        """Keep facts, preflight new outputs, then atomically replace all rules."""
        self._idle()
        path = self._path if rules is None else None if isinstance(rules, RuleSet) else Path(rules).resolve()
        if rules is None and path is None:
            raise ValueError("Pass a rule bundle or path; this LogicDB has no source path")
        if isinstance(rules, RuleSet):
            bundle, content = rules, None
        else:
            bundle, content = _read_bundle(path)
        if bundle.fact_schema_id != self._rules.fact_schema_id:
            raise RuleError("Hot reload cannot change the fact schema; start a new world")
        candidate = _build_world(bundle, self.mode, self.snapshot(), preflight=True)
        self._swap(candidate)
        self._rules = bundle
        self._path = path
        self._loaded_file = content

    def reload_if_changed(self):
        """Poll a compiled bundle; return whether a replacement was installed."""
        self._idle()
        if self._path is None:
            raise ValueError("Rule watching requires a source path")
        if self._path.read_bytes() == self._loaded_file:
            return False
        self.reload_rules()
        return True

    def describe(self, name):
        """Inspect a relation without evaluating its rules."""
        self._table(name, {})
        kind = "facts" if name in self._rules._document["facts"] else "derived"
        return {"name": name, "kind": kind,
                **json.loads(json.dumps(self._rules._document[kind][name])),
                "dependencies": list(self._world.dependencies.get(name, ())),
                "reads": list(self._world.reads.get(name, ())) }

    def stats(self):
        """Small, non-evaluating diagnostics for the cache experiment."""
        self._idle()
        return {"mode": self.mode, "cached_relations": sorted(self._world.valid),
                "materializations": dict(self._materializations),
                "materialization_seconds": self._materialization_seconds,
                "snapshot_bytes": len(self._saved)}

    def close(self):
        if self._world is not None:
            self._idle()
            self._world.engine.dispose()
            self._world = None

    def install_renpy(self, config, snapshot_variable="logic_snapshot", *, watch_rules=False):
        """Bind once in init python; declare the snapshot with `default` in .rpy."""
        self._idle()
        binding = (config, snapshot_variable, watch_rules)
        if self._renpy_binding is not None:
            if self._renpy_binding == binding:
                return
            raise RuntimeError("LogicDB is already bound to a different Ren'Py configuration")
        if watch_rules and self._path is None:
            raise ValueError("Rule watching requires a source path")
        if self._on_snapshot is not None:
            raise ValueError("A snapshot sink is already configured")
        import renpy

        def write_snapshot(value):
            setattr(renpy.store, snapshot_variable, value)

        def after_defaults():
            self.restore(getattr(renpy.store, snapshot_variable, None))

        last_error = None

        def watch():
            nonlocal last_error
            if not config.developer or self._path is None:
                return
            try:
                self.reload_if_changed()
                last_error = None
            except (RuleError, OSError) as exc:
                if str(exc) != last_error:
                    renpy.exports.log(f"Ren'Py Relations: reload failed: {exc}")
                    renpy.exports.notify("Rule reload failed; previous rules remain active. See log.txt.")
                    last_error = str(exc)

        self._on_snapshot = write_snapshot
        config.after_default_callbacks.append(after_defaults)
        if watch_rules:
            config.interact_callbacks.append(watch)
        self._renpy_binding = binding
