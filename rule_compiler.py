"""Build-time SQL analysis and execution plans; never imported by game loading.

`compile_document()` turns trusted SQL declarations into a sealed plan:
dependency edges, a topological order, and a fingerprint binding both to the
rule content. `renpy_relations` only *executes* that plan at runtime, so game
loading never parses or introspects rule SQL.
"""

import json

from sqlalchemy.exc import SQLAlchemyError

from renpy_relations import (
    RuleError, RuleSet, _World, _SQLiteBackend, _DuckDBBackend, _digest, _fill, sqlite3,
)


# Functions whose value is not fixed by the fact rows. Kept beside the analysis
# that rejects them; the runtime never inspects function names.
_VOLATILE_FUNCTIONS = frozenset({
    "random", "randomblob", "changes", "total_changes", "last_insert_rowid",
    "load_extension", "current_date", "current_time", "current_timestamp",
    "date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff",
})


def _sqlite_reads(conn, world, rules):
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

    return dependencies


def _order(conn, world, rules, dependencies):
    derived = rules._document["derived"]
    # SQL resolution above reports edges, including negative/subquery reads.
    # Graph algorithms execute in SQLite, without Python DFS or SQL text parsing.
    suffix = world.backend.graph_suffix
    conn.exec_driver_sql(f'CREATE TEMP TABLE __rr_edges (source TEXT, target TEXT, PRIMARY KEY(source,target)){suffix}')
    conn.exec_driver_sql('CREATE INDEX __rr_reverse ON __rr_edges(target,source)')
    conn.exec_driver_sql(f'CREATE TEMP TABLE __rr_nodes (name TEXT PRIMARY KEY, derived INTEGER, rank INTEGER){suffix}')
    conn.exec_driver_sql(f'CREATE TEMP TABLE __rr_changed (name TEXT PRIMARY KEY){suffix}')
    if world.tables:
        world.backend.load_rows(conn, 'temp.__rr_nodes', [(name, int(name in derived), 0) for name in world.tables])
    edges = [(source, target) for target, sources in dependencies.items() for source in sources]
    if edges:
        world.backend.load_rows(conn, 'temp.__rr_edges', edges)
    # Distinct ancestor counts strictly increase along each edge in a DAG.
    # UNION deduplicates diamonds and terminates even when a cycle is present.
    ranks = conn.exec_driver_sql('''
        WITH RECURSIVE ancestors(node, ancestor) AS (
            SELECT target, source FROM temp.__rr_edges
            UNION
            SELECT a.node, e.source FROM ancestors a JOIN temp.__rr_edges e ON e.target=a.ancestor
        )
        SELECT node, count(*), max(CASE WHEN node=ancestor THEN 1 ELSE 0 END) FROM ancestors GROUP BY node
    ''').all()
    if any(row[2] for row in ranks):
        raise RuleError("Cyclic derived relation dependency")
    if ranks:
        conn.exec_driver_sql('CREATE TEMP TABLE __rr_ranks(rank INTEGER, name TEXT)')
        world.backend.load_rows(conn, 'temp.__rr_ranks', [(r[1], r[0]) for r in ranks])
        conn.exec_driver_sql('UPDATE temp.__rr_nodes SET rank=r.rank FROM temp.__rr_ranks r WHERE r.name=__rr_nodes.name')
    world.reads = dependencies
    world.dependencies = {name: tuple(n for n in names if n in derived)
                          for name, names in dependencies.items()}
    world.order = tuple(r[0] for r in conn.exec_driver_sql(
        'SELECT name FROM temp.__rr_nodes WHERE derived=1 ORDER BY rank,name'))


def _duckdb_reads(conn, world, rules):
    """Analyze the whole bundle once; catalog and AST inspection are set based."""
    specifications = rules._document['derived']
    world.backend.load_rows(conn, '__rr_sql', [(name, spec['sql']) for name, spec in specifications.items()])
    conn.exec_driver_sql('CREATE TEMP TABLE __rr_ast AS SELECT name,json_serialize_sql(sql) AS tree FROM __rr_sql')
    errors = conn.exec_driver_sql("""
        SELECT name,json_extract_string(tree,'$.error_message') FROM __rr_ast
        WHERE json_extract(tree,'$.error')::BOOLEAN IS TRUE
           OR json_array_length(tree,'$.statements')<>1
    """).all()
    if errors:
        raise RuleError(f'Invalid single SELECT: {errors[0]}')
    conn.exec_driver_sql("""
        CREATE TEMP TABLE __rr_functions AS
        SELECT lower(function_name) AS name,
               bool_and(stability IS NOT DISTINCT FROM 'CONSISTENT') AS stable
        FROM duckdb_functions() GROUP BY 1
    """)
    canonical = {name.casefold(): name for name in world.tables}
    rejected = conn.exec_driver_sql("""
        WITH nodes AS (
            SELECT a.name,j.key,j.value FROM __rr_ast a,
                 LATERAL json_tree(a.tree) j
        )
        SELECT DISTINCT n.name,'unsupported/non-deterministic function: ' || json_extract_string(n.value,'$')
        FROM nodes n LEFT JOIN __rr_functions f ON f.name=lower(json_extract_string(n.value,'$'))
        WHERE n.key='function_name' AND NOT coalesce(f.stable,FALSE)
          AND lower(json_extract_string(n.value,'$')) NOT IN ('unnest','range','generate_series','json_each','json_tree')
        UNION ALL
        SELECT name,'clock expression' FROM nodes
        WHERE key='column_names' AND json_array_length(value)=1
          AND lower(json_extract_string(value,'$[0]')) IN
              ('current_date','current_time','current_timestamp','localtime','localtimestamp')
        UNION ALL
        SELECT name,'external schema/catalog' FROM nodes
        WHERE (key='schema_name' AND lower(json_extract_string(value,'$')) NOT IN ('','main','temp'))
           OR (key='catalog_name' AND lower(json_extract_string(value,'$')) NOT IN ('','temp',lower(current_database())))
        UNION ALL
        SELECT DISTINCT n.name,'catalog view: ' || json_extract_string(n.value,'$')
        FROM nodes n JOIN duckdb_views() v
          ON lower(v.view_name)=lower(json_extract_string(n.value,'$'))
        WHERE n.key='table_name' AND v.internal
          AND NOT list_contains(?, lower(v.view_name))
    """, (list(canonical),)).all()
    if rejected:
        raise RuleError(f'{rejected[0][0]}: {rejected[0][1]}')
    raw = conn.connection.dbapi_connection
    dependencies = {}
    for name, spec in specifications.items():
        try:
            reads = raw.get_table_names(spec['sql'])
            if any(read.casefold() not in canonical for read in reads):
                raise RuleError('undeclared relation in rule SQL')
            result = conn.exec_driver_sql(f'SELECT * FROM ({spec["sql"]}) AS __rr_source LIMIT 0')
            try:
                columns = list(result.keys())
            finally:
                result.close()
            if len(columns) != len(spec['columns']) or set(columns) != set(spec['columns']):
                raise RuleError(f'expected columns {list(spec["columns"])}, got {columns}')
            dependencies[name] = tuple(sorted(canonical[read.casefold()] for read in reads))
        except (RuleError, *world.backend.errors) as exc:
            raise RuleError(f'{name}: invalid compiled SELECT: {exc}') from exc
    return dependencies


def compile_document(document):
    """Return a copy of a rule document with dependencies and a sealed plan.

    The input is never mutated. Old ``dependencies``/``plan`` fields are
    discarded and recomputed, so recompilation is always authoritative.
    """
    document = document.document if isinstance(document, RuleSet) else json.loads(json.dumps(document))
    document.pop('plan', None)
    document.pop('dependencies', None)
    rules = RuleSet(document)
    backend = {'sqlite': _SQLiteBackend, 'duckdb': _DuckDBBackend}[rules.backend]()
    world = _World(backend.engine(), rules._tables(), backend)
    try:
        with world.engine.begin() as conn:
            backend.create_tables(conn, list(world.tables.values()))
            world.created.update(document['derived'])
            if rules.backend == 'duckdb':
                conn.exec_driver_sql('CREATE TEMP TABLE __rr_sql(name TEXT,sql TEXT)')
                dependencies = _duckdb_reads(conn, world, rules)
            else:
                dependencies = _sqlite_reads(conn, world, rules)
            _order(conn, world, rules, dependencies)
            for name in world.order:
                _fill(conn, world, rules, name)
        document['dependencies'] = {name: list(reads) for name, reads in dependencies.items()}
        order = list(world.order)
        document['plan'] = {'version': 1, 'order': order,
                            'fingerprint': _digest({'rules': rules.content_id,
                                                    'dependencies': document['dependencies'],
                                                    'order': order})}
        return document
    except backend.errors as exc:
        raise RuleError(f'Cannot compile SQL rules: {exc}') from exc
    finally:
        world.engine.dispose()


def prepare_rules(document):
    """Compile declarations and return a sealed runtime RuleSet."""
    return RuleSet(compile_document(document))
