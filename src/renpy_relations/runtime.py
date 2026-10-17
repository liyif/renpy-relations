"""Relational facts and compiled rules for Python (Python 3.11+, SQLAlchemy 2.0).

    logic = LogicDB("relations.rules.json", mode="cached")
    logic.add("Sponsor", character="hero", location="archive")
    assert logic.has("CanEnter", character="hero", location="archive")

SQLite or DuckDB is selected by the compiled rule bundle. Native images save
only facts and format/schema metadata. Derived data lives in TEMP.
All writes go through batch/add/remove; queries are read-only and forbidden in
a batch. Rule SQL and dependency edges are trusted build-time output from
renpy-relations-compile; this runtime only executes them and derives the evaluation
order from the declared edges. Application values are bound.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import tempfile
from time import perf_counter

try:
    import sqlite3
except ImportError:
    try:
        import pysqlite3 as sqlite3
    except ImportError:
        sqlite3 = None

from sqlalchemy import (
    BigInteger, Boolean, Column, Double, Float, MetaData, String, Table,
    UniqueConstraint, create_engine, delete, event, literal_column, select, text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.postgresql import insert as conflict_insert


class RuleError(ValueError):
    """Invalid/incompatible rules or snapshot; an existing world is preserved."""


# BIGINT avoids SQLite's implicit INTEGER PRIMARY KEY / rowid alias. It also
# keeps explicit whole-tuple conflict targets valid when the key is numeric.
_TYPES = {"text": String, "integer": BigInteger, "real": Float, "boolean": Boolean}
_SQL_TYPES = {"text": "TEXT", "integer": "INTEGER", "real": "REAL", "boolean": "INTEGER"}
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


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
    """Validated, copy-isolated JSON rule definitions. Dependencies are compiled build-time output."""

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
        if set(doc) - {"format", "version", "backend", "facts", "derived", "source", "dependencies"}:
            raise RuleError("Unknown rule bundle fields")
        self.backend = doc.get("backend", "sqlite")
        if self.backend not in ("sqlite", "duckdb"):
            raise RuleError("backend must be sqlite or duckdb")
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
        self._table_definitions = None
        if doc["derived"] and "dependencies" not in doc:
            raise RuleError("Rule bundle lacks dependencies; compile with renpy-relations-compile")
        self.reads = {name: tuple(sorted(reads)) for name, reads in doc.get("dependencies", {}).items()}
        # Edges among derived relations drive invalidation and evaluation order.
        self.dependencies = {name: tuple(n for n in reads if n in doc["derived"])
                             for name, reads in self.reads.items()}

    @classmethod
    def load(cls, path):
        return _read_bundle(Path(path))[0]

    @property
    def document(self):
        """Return an independent copy suitable for writing a bundle."""
        return json.loads(json.dumps(self._document))

    def _tables(self):
        if self._table_definitions is not None:
            return self._table_definitions
        metadata = MetaData()
        tables = {}
        for kind in ("facts", "derived"):
            for name, spec in self._document[kind].items():
                key = spec.get("key", [])
                types = dict(_TYPES)
                if self.backend == "duckdb":
                    types.update(integer=BigInteger, real=Double)
                # Schema identity ignores dictionary order. Native database DDL
                # must therefore use a stable order too, including unique indexes.
                fields = sorted(spec["columns"]) if kind == "facts" else list(spec["columns"])
                columns = [Column(
                    column, types[spec["columns"][column]](), nullable=kind == "derived",
                    primary_key=column in key, autoincrement=False,
                ) for column in fields]
                constraints = [UniqueConstraint(*fields)] if kind == "facts" else []
                tables[name] = Table(
                    name, metadata, *columns, *constraints,
                    schema="main" if kind == "facts" else "temp",
                    prefixes=["TEMPORARY"] if self.backend == "duckdb" and kind == "derived" else [],
                )
        self._table_definitions = tables
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
    backend: object
    dependencies: dict = field(default_factory=dict)
    reads: dict = field(default_factory=dict)
    order: tuple = ()
    valid: set = field(default_factory=set)
    created: set = field(default_factory=set)
    pending_created: set = field(default_factory=set)

    def affected(self, conn, facts):
        """The database follows reverse edges; Python binds changed fact names."""
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


class _SQLiteBackend:
    name = "sqlite"
    sql_types = _SQL_TYPES
    graph_suffix = " WITHOUT ROWID"

    def __init__(self):
        if sqlite3 is None:
            raise ImportError("No SQLite driver; use Python with sqlite3 support or install pysqlite3-binary")
        self.errors = (SQLAlchemyError, sqlite3.Error)

    def engine(self):
        return _new_engine()

    @contextmanager
    def read_only(self, conn, statement):
        raw = conn.connection.dbapi_connection
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        denied = False

        def authorize(action, *_):
            nonlocal denied
            if action in allowed:
                return sqlite3.SQLITE_OK
            denied = True
            return sqlite3.SQLITE_DENY

        raw.set_authorizer(authorize)
        try:
            yield
        except SQLAlchemyError as exc:
            if denied:
                raise ValueError("query_sql() requires a read-only query") from exc
            raise
        finally:
            raw.set_authorizer(None)

    def insert(self, table, values):
        return sqlite_insert(table).values(values).on_conflict_do_nothing(
            index_elements=list(table.columns))

    def changed(self, conn, statement):
        result = conn.execute(statement)
        try:
            return result.rowcount > 0
        finally:
            result.close()

    def create_tables(self, conn, tables):
        for table in tables:
            table.create(conn)

    def load_rows(self, conn, table, rows):
        if rows:
            placeholders = ",".join("?" for _ in rows[0])
            conn.exec_driver_sql(f"INSERT INTO {table} VALUES ({placeholders})", rows)

    def schema(self, conn):
        return conn.exec_driver_sql(
            'SELECT type,name,tbl_name,sql FROM main.sqlite_schema ORDER BY type,name').all()

    def check(self, conn):
        if conn.exec_driver_sql('PRAGMA main.quick_check').all() != [("ok",)]:
            raise RuleError("Invalid SQLite snapshot")

    def snapshot(self, engine):
        with engine.connect() as conn:
            raw = conn.connection.dbapi_connection
            if hasattr(raw, "serialize"):
                return raw.serialize(name="main")
            # SDK pysqlite3 exposes backup but not serialize. SQLite copies pages;
            # no fact rows cross the Python boundary.
            with tempfile.TemporaryDirectory(prefix="relations-snapshot-") as directory:
                path = Path(directory) / "facts.sqlite"
                target = sqlite3.connect(str(path))
                try:
                    raw.backup(target, name="main")
                finally:
                    target.close()
                return path.read_bytes()

    def restore(self, engine, image, facts):
        if not image.startswith(b"SQLite format 3\0"):
            raise RuleError("Snapshot is not a SQLite image (backend/format mismatch)")
        with engine.connect() as conn:
            raw = conn.connection.dbapi_connection
            if hasattr(raw, "deserialize"):
                raw.deserialize(image, name="main")
                return
            with tempfile.TemporaryDirectory(prefix="relations-restore-") as directory:
                path = Path(directory) / "facts.sqlite"
                path.write_bytes(image)
                source = sqlite3.connect(str(path))
                try:
                    source.backup(raw, name="main")
                finally:
                    source.close()


class _DuckDBBackend:
    """Execute prepared rules and copy fact images; never analyze rule SQL."""

    name = "duckdb"
    sql_types = {**_SQL_TYPES, "integer": "BIGINT", "real": "DOUBLE"}
    graph_suffix = ""

    def __init__(self):
        try:
            import duckdb
            import duckdb_engine  # Registers the SQLAlchemy dialect.
        except ImportError as exc:
            raise ImportError("DuckDB backend requires the uv extra: --extra duckdb") from exc
        self.errors = (SQLAlchemyError, duckdb.Error)
        self._native_errors = (duckdb.Error,)
        self._select_type = duckdb.StatementType.SELECT

    def engine(self):
        return create_engine("duckdb:///:memory:", poolclass=StaticPool,
            connect_args={"config": {"threads": 1, "autoload_known_extensions": False,
                                     "autoinstall_known_extensions": False}})

    @contextmanager
    def read_only(self, conn, statement):
        # The native parser sees dialect placeholders, not SQLAlchemy's :names.
        raw = conn.connection.dbapi_connection
        statements = raw.extract_statements(str(statement.compile(dialect=conn.dialect)))
        if len(statements) != 1 or statements[0].type != self._select_type:
            raise ValueError("query_sql() requires a single read-only query")
        yield

    def create_tables(self, conn, tables):
        statements = [str(CreateTable(table).compile(dialect=conn.dialect)) for table in tables]
        if statements:
            conn.exec_driver_sql(";\n".join(statements))

    def load_rows(self, conn, table, rows):
        # Bind each graph column once, instead of executing one INSERT per edge.
        if rows:
            columns = tuple(map(list, zip(*rows)))
            conn.exec_driver_sql(f"INSERT INTO {table} SELECT " +
                                 ",".join("unnest(?)" for _ in columns), columns)

    def insert(self, table, values):
        # The PostgreSQL statement builder emits DuckDB's supported conflict
        # target syntax. Keeping the target preserves custom-key violations.
        return conflict_insert(table).values(values).on_conflict_do_nothing(
            index_elements=list(table.columns))

    def changed(self, conn, statement):
        # DuckDB rowcount is -1; only the existence of a changed row is needed.
        result = conn.execute(statement.returning(literal_column("1")))
        try:
            return result.first() is not None
        finally:
            result.close()

    def schema(self, conn):
        return conn.exec_driver_sql('''
            SELECT 'table',schema_name || '.' || table_name,sql FROM duckdb_tables()
              WHERE database_name=current_database()
            UNION ALL SELECT 'view',schema_name || '.' || view_name,sql FROM duckdb_views()
              WHERE database_name=current_database() AND NOT internal
            UNION ALL SELECT 'index',schema_name || '.' || index_name,sql FROM duckdb_indexes()
              WHERE database_name=current_database()
            UNION ALL SELECT 'sequence',schema_name || '.' || sequence_name,sql FROM duckdb_sequences()
              WHERE database_name=current_database()
            UNION ALL SELECT 'function',schema_name || '.' || function_name,coalesce(macro_definition,'') FROM duckdb_functions()
              WHERE database_name=current_database() AND NOT internal
            UNION ALL SELECT 'schema',schema_name,'' FROM duckdb_schemas()
              WHERE database_name=current_database() AND NOT internal
            UNION ALL SELECT 'type',schema_name || '.' || type_name,logical_type FROM duckdb_types()
              WHERE database_name=current_database() AND NOT internal
            ORDER BY 1,2,3
        ''').all()

    def check(self, conn):
        pass  # DuckDB validates its storage format while opening/copying the image.

    @contextmanager
    def _attached_image(self, engine, path, *, read_only):
        # COPY/ATTACH use one native connection with an explicit transaction;
        # SQLAlchemy must not start a competing implicit transaction here.
        connection = engine.raw_connection()
        raw = connection.dbapi_connection
        attached = False
        literal = "'" + str(path).replace("'", "''") + "'"
        options = "TYPE DUCKDB, READ_ONLY" if read_only else "TYPE DUCKDB"
        try:
            raw.execute(f"ATTACH {literal} AS __rr_image ({options})")
            attached = True
            yield raw
        except BaseException:
            if attached:
                try:
                    raw.execute("DETACH __rr_image")
                except self._native_errors:
                    pass  # Preserve the original copy/validation failure.
            raise
        else:
            raw.execute("DETACH __rr_image")
        finally:
            connection.close()

    def snapshot(self, engine):
        with tempfile.TemporaryDirectory(prefix="relations-snapshot-") as directory:
            path = Path(directory) / "facts.duckdb"
            with self._attached_image(engine, path, read_only=False) as raw:
                current = raw.execute("SELECT current_database()").fetchone()[0]
                quoted = engine.dialect.identifier_preparer.quote(current)
                raw.execute(f"COPY FROM DATABASE {quoted} TO __rr_image")
            # DETACH completes the standalone image before Python reads it.
            return path.read_bytes()

    def restore(self, engine, image, facts):
        if image[8:12] != b"DUCK":
            raise RuleError("Snapshot is not a DuckDB image (backend/format mismatch)")
        with tempfile.TemporaryDirectory(prefix="relations-restore-") as directory:
            path = Path(directory) / "facts.duckdb"
            path.write_bytes(image)
            with self._attached_image(engine, path, read_only=True) as raw:
                quote = engine.dialect.identifier_preparer.quote
                current = quote(raw.execute("SELECT current_database()").fetchone()[0])
                raw.execute("BEGIN")
                try:
                    for name in (*facts, "__rr_metadata"):
                        raw.execute(f"DROP TABLE main.{quote(name)}")
                    raw.execute(f"COPY FROM DATABASE __rr_image TO {current}")
                    raw.execute("COMMIT")
                except BaseException:
                    try:
                        raw.execute("ROLLBACK")
                    except self._native_errors:
                        pass
                    raise


def _install_graph(conn, world, rules):
    world.reads = rules.reads
    world.dependencies = rules.dependencies
    suffix = world.backend.graph_suffix
    conn.exec_driver_sql(f'CREATE TEMP TABLE __rr_edges (source TEXT, target TEXT, PRIMARY KEY(source,target)){suffix}')
    conn.exec_driver_sql('CREATE INDEX __rr_reverse ON __rr_edges(target,source)')
    conn.exec_driver_sql(f'CREATE TEMP TABLE __rr_nodes (name TEXT PRIMARY KEY, derived INTEGER, rank INTEGER){suffix}')
    conn.exec_driver_sql(f'CREATE TEMP TABLE __rr_changed (name TEXT PRIMARY KEY){suffix}')
    world.backend.load_rows(conn, 'temp.__rr_nodes', [(name, int(name in rules.dependencies), 0)
                                                  for name in world.tables])
    world.backend.load_rows(conn, 'temp.__rr_edges', [(source, target) for target, reads in rules.reads.items()
                                                  for source in reads])
    # The native query propagates depths from roots, deduplicating diamonds at
    # the same depth. A DAG has no path as long as its node count. Bounding the
    # recursion also terminates cycles reachable from a root; rootless cycles
    # leave nodes unranked. No SQL text or graph traversal is handled in Python.
    count = len(world.tables)
    conn.exec_driver_sql('''
        CREATE TEMP TABLE __rr_ranks AS
        WITH RECURSIVE levels(name, rank) AS (
            SELECT n.name, 0 FROM temp.__rr_nodes n
            WHERE NOT EXISTS (SELECT 1 FROM temp.__rr_edges e WHERE e.target=n.name)
            UNION
            SELECT e.target, l.rank+1 FROM levels l
            JOIN temp.__rr_edges e ON e.source=l.name WHERE l.rank<?
        )
        SELECT name, max(rank) AS rank FROM levels GROUP BY name
    ''', (count,))
    ranked, maximum = conn.exec_driver_sql('SELECT count(*), max(rank) FROM temp.__rr_ranks').one()
    if ranked != count or (maximum is not None and maximum >= count):
        raise RuleError("Cyclic derived relation dependency")
    conn.exec_driver_sql('''
        UPDATE temp.__rr_nodes SET rank=r.rank FROM temp.__rr_ranks r
        WHERE r.name=__rr_nodes.name
    ''')
    conn.exec_driver_sql('DROP TABLE temp.__rr_ranks')
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
        expressions.append(f"CAST({value} AS {world.backend.sql_types[type_name]}) AS {identifier}")
    sql = rules._document["derived"][name]["sql"]
    # Explicit casts give views and materialized tables the same field semantics.
    return f'SELECT {", ".join(expressions)} FROM ({sql}) AS __rr_source'


def _fill(conn, world, rules, name):
    table = world.tables[name]
    quote = world.engine.dialect.identifier_preparer.quote
    columns = ", ".join(quote(c.name) for c in table.columns)
    if name not in world.created and name not in world.pending_created:
        world.backend.create_tables(conn, [table])
        world.pending_created.add(name)
    else:
        conn.execute(delete(table))
    conn.exec_driver_sql(
        f'INSERT INTO temp.{quote(name)} ({columns}) '
        + _projection(world, rules, name)
    )


def _build_world(rules, mode, snapshot, *, preflight=False):
    backend = {"sqlite": _SQLiteBackend, "duckdb": _DuckDBBackend}[rules.backend]()
    world = _World(backend.engine(), rules._tables(), backend)
    metadata = ("renpy-relations-snapshot", 2, rules.backend, rules.fact_schema_id)
    try:
        with world.engine.begin() as conn:
            backend.create_tables(conn, [world.tables[name] for name in rules._document["facts"]])
            conn.exec_driver_sql('CREATE TABLE __rr_metadata (format TEXT NOT NULL, version INTEGER NOT NULL, backend TEXT NOT NULL, fact_schema_id TEXT NOT NULL)')
            conn.exec_driver_sql('INSERT INTO __rr_metadata VALUES (?,?,?,?)', metadata)
            expected_schema = backend.schema(conn)
        if snapshot is not None:
            backend.restore(world.engine, snapshot, rules._document["facts"])
            with world.engine.begin() as conn:
                backend.check(conn)
                if backend.schema(conn) != expected_schema:
                    raise RuleError("Snapshot fact schema differs; migration is not supported")
                if conn.exec_driver_sql('SELECT * FROM __rr_metadata').all() != [metadata]:
                    raise RuleError("Snapshot backend/version/fact schema differs")
        with world.engine.begin() as conn:
            _install_graph(conn, world, rules)
            if mode == "materialized" or preflight:
                backend.create_tables(conn, [world.tables[name] for name in world.order])
                world.created.update(world.order)
                for name in world.order:
                    _fill(conn, world, rules, name)
            if mode == "live":
                if preflight:
                    for name in reversed(world.order):
                        world.tables[name].drop(conn)
                quote = world.engine.dialect.identifier_preparer.quote
                for name in world.order:
                    conn.exec_driver_sql(f"CREATE TEMP VIEW {quote(name)} AS {_projection(world, rules, name)}")
            elif mode == "cached" and preflight:
                for name in reversed(world.order):
                    world.tables[name].drop(conn)
                world.created.clear()
        return world
    except Exception as exc:
        world.engine.dispose()
        if isinstance(exc, backend.errors):
            raise RuleError(f"Cannot prepare rules/snapshot: {exc}") from exc
        raise


def _snapshot_world(world, rules):
    return world.backend.snapshot(world.engine)


class LogicDB:
    """Facts, queries and lifecycle operations over one synchronous world."""

    def __init__(self, rules, *, backend=None, mode="cached", on_snapshot=None):
        if mode not in ("live", "materialized", "cached"):
            raise ValueError("mode must be live, materialized or cached")
        self.mode = mode
        self._path = None if isinstance(rules, RuleSet) else Path(rules).resolve()
        if self._path is None:
            self._rules, self._loaded_file = rules, None
        else:
            self._rules, self._loaded_file = _read_bundle(self._path)
        if backend is not None and backend != self._rules.backend:
            raise RuleError(f"Rule bundle backend is {self._rules.backend}, requested {backend}")
        self.backend = self._rules.backend
        self._world = _build_world(self._rules, mode, None)
        self._tx = None
        self._dirty = set()
        self._notifying = False
        self._on_snapshot = on_snapshot
        self._materializations = {}
        self._materialization_seconds = 0.0
        self._saved = None

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
        # With a sink, None denotes the empty world; subsequent accepted commits
        # retain their image. Binding a populated world captures its baseline once.
        before = self._saved
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
        self._saved = None
        if self._on_snapshot is None:
            return
        try:
            value = self.snapshot()
            self._notifying = True
            try:
                self._on_snapshot(value)
            finally:
                self._notifying = False
            self._saved = value
        except Exception:
            self.restore(before)
            raise

    def add(self, name, /, **values):
        """Assert a complete fact; identical tuples are ignored, key conflicts fail."""
        table = self._table(name, values, fact=True)
        if set(values) != set(table.c.keys()):
            raise ValueError(f"add({name}) requires every field: {list(table.c.keys())}")
        if self._tx is None:
            with self.batch():
                self.add(name, **values)
            return
        statement = self._world.backend.insert(table, values)
        if self._world.backend.changed(self._tx, statement):
            self._dirty.add(name)

    def remove(self, name, /, **filters):
        """Retract matching facts. An empty filter is forbidden."""
        table = self._table(name, filters, fact=True)
        if not filters:
            raise ValueError("remove() requires filters")
        if self._tx is None:
            with self.batch():
                self.remove(name, **filters)
            return
        statement = delete(table).where(
            *(table.c[k] == value for k, value in filters.items()),
        )
        if self._world.backend.changed(self._tx, statement):
            self._dirty.add(name)

    def _ensure_cached(self, conn, name, staged):
        world = self._world
        if name not in world.dependencies or name in world.valid or name in staged:
            return
        for dependency in world.needed(conn, name):
            if dependency not in world.valid and dependency not in staged:
                started = perf_counter()
                _fill(conn, world, self._rules, dependency)
                self._materialization_seconds += perf_counter() - started
                staged.add(dependency)

    @contextmanager
    def _read_connection(self, reads):
        staged = set()
        try:
            with self._world.engine.begin() as conn:
                if self.mode == "cached":
                    for name in reads:
                        self._ensure_cached(conn, name, staged)
                yield conn
            self._world.created.update(self._world.pending_created)
        finally:
            self._world.pending_created.clear()
        # Validity is published only when every materialization/read committed.
        self._world.valid.update(staged)
        for relation in staged:
            self._materializations[relation] = self._materializations.get(relation, 0) + 1

    def _read(self, name, filters, *, exists):
        self._idle()
        table = self._table(name, filters)
        statement = select(table).where(*(table.c[k] == v for k, v in filters.items()))
        if exists:
            statement = statement.limit(1)
        with self._read_connection((name,)) as conn:
            result = conn.execute(statement)
            try:
                value = result.first() is not None if exists else [dict(r) for r in result.mappings()]
            finally:
                result.close()
        return value

    def query(self, name, /, **filters):
        """Return independent dict rows. Row order is unspecified."""
        return self._read(name, filters, exists=False)

    def has(self, name, /, **filters):
        return self._read(name, filters, exists=True)

    def query_sql(self, sql, params=None, *, reads):
        """Query trusted SQL; reads declares every directly referenced relation."""
        self._idle()
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("query_sql() requires non-empty SQL")
        if params is not None and not isinstance(params, Mapping):
            raise TypeError("params must be a mapping of named parameters")
        if not isinstance(reads, (list, tuple)):
            raise TypeError("reads must be a list or tuple of relation names")
        for name in reads:
            self._table(name, {})
        statement = text(sql)
        with self._read_connection(reads) as conn:
            with self._world.backend.read_only(conn, statement):
                result = conn.execute(statement, dict(params) if params is not None else {})
                try:
                    if not result.returns_rows:
                        raise ValueError("query_sql() requires a read-only query returning rows")
                    if len(result.keys()) != len(set(result.keys())):
                        raise ValueError("query_sql() requires unique result column names; use AS aliases")
                    rows = [dict(row) for row in result.mappings()]
                finally:
                    result.close()
        return rows

    def snapshot(self):
        self._idle()
        if self._saved is None:
            self._saved = _snapshot_world(self._world, self._rules)
        return self._saved

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
        self._swap(candidate)
        self._saved = snapshot

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
        if bundle.backend != self.backend:
            raise RuleError("Hot reload cannot change backend; compile for the selected backend")
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
        return {"mode": self.mode, "backend": self.backend, "cached_relations": sorted(self._world.valid),
                "materializations": dict(self._materializations),
                "materialization_seconds": self._materialization_seconds,
                "snapshot_bytes": len(self._saved) if self._saved is not None else 0}

    def close(self):
        if self._world is not None:
            self._idle()
            self._world.engine.dispose()
            self._world = None
            self._saved = None
