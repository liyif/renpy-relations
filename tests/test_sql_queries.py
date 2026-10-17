import pytest
from sqlalchemy.exc import SQLAlchemyError

from renpy_relations import LogicDB, RuleSet
import renpy_relations.runtime as runtime
from test_backends import rules


@pytest.fixture(params=["sqlite", "duckdb"])
def backend(request):
    if request.param == "duckdb":
        pytest.importorskip("duckdb")
    return request.param


@pytest.fixture(params=["cached", "live", "materialized"])
def db(backend, request):
    logic = LogicDB(rules(backend), mode=request.param)
    with logic.batch():
        for who in ("alice", "bob", "carol"):
            logic.add("Permit", who=who)
        logic.add("Blocked", who="bob")
    try:
        yield logic
    finally:
        logic.close()


def test_join_cte_aggregation_order_and_bound_parameters(db):
    assert db.query_sql(
        """-- Comments and a trailing semicolon are valid.
        WITH candidates AS (
            SELECT a.who FROM Allowed a JOIN Permit p ON p.who=a.who
            WHERE a.who >= :minimum
        )
        SELECT who, COUNT(*) AS n FROM candidates
        GROUP BY who ORDER BY who DESC LIMIT :limit;
        """,
        {"minimum": "a", "limit": 1}, reads=("Allowed", "Permit"),
    ) == [{"who": "carol", "n": 1}]
    assert db.query_sql(
        "SELECT who FROM Allowed WHERE who=:who",
        {"who": "alice' OR 1=1 --"}, reads=("Allowed",),
    ) == []
    assert db.query_sql("SELECT COUNT(*) AS n FROM Allowed", reads=("Allowed",)) == [{"n": 2}]


def test_sql_queries_follow_changes_restore_and_rule_reload(db):
    query = "SELECT who FROM Allowed ORDER BY who"
    expected = [{"who": "alice"}, {"who": "carol"}]
    assert db.query_sql(query, reads=("Allowed",)) == expected
    snapshot = db.snapshot()
    db.add("Blocked", who="alice")
    assert db.query_sql(query, reads=("Allowed",)) == [{"who": "carol"}]
    db.restore(snapshot)
    assert db.query_sql(query, reads=("Allowed",)) == expected
    changed = rules(db.backend).document
    changed["derived"]["Visible"]["sql"] = "SELECT who FROM Permit WHERE who='alice'"
    db.reload_rules(RuleSet(changed))
    assert db.query_sql(query, reads=("Allowed",)) == [{"who": "alice"}]


def test_cached_query_prepares_only_needed_relations_once(backend, monkeypatch):
    db = LogicDB(rules(backend))
    fills = []
    fill = runtime._fill

    def record(conn, world, rules, name):
        fills.append(name)
        return fill(conn, world, rules, name)

    monkeypatch.setattr(runtime, "_fill", record)
    try:
        db.add("Permit", who="alice")
        sql = "SELECT a.who FROM Allowed a JOIN Visible v ON a.who=v.who"
        reads = ("Allowed", "Visible", "Allowed")
        assert db.query_sql(sql, reads=reads) == [{"who": "alice"}]
        assert fills == ["Visible", "Allowed"]
        assert db.stats()["materializations"] == {"Visible": 1, "Allowed": 1}
        db.query_sql(sql, reads=reads)
        assert fills == ["Visible", "Allowed"]
        db.add("Blocked", who="alice")
        assert db.query_sql(sql, reads=reads) == []
        assert fills == ["Visible", "Allowed", "Allowed"]
        # Results are not cached by SQL text or parameters.
        db.remove("Blocked", who="alice")
        assert db.query_sql(sql, reads=reads) == [{"who": "alice"}]
        assert "Counted" not in fills
    finally:
        db.close()


def test_query_failure_rolls_back_cache_preparation_and_remains_usable(backend):
    db = LogicDB(rules(backend))
    try:
        db.add("Permit", who="alice")
        with pytest.raises(db._world.backend.errors):
            db.query_sql("SELECT absent_column FROM Allowed", reads=("Allowed",))
        assert db.stats()["materializations"] == {}
        assert db.query_sql("SELECT * FROM Allowed", reads=("Allowed",)) == [{"who": "alice"}]
        assert db.stats()["materializations"] == {"Visible": 1, "Allowed": 1}
    finally:
        db.close()


def test_write_ddl_transaction_and_multiple_statements_are_rejected(db):
    native_errors = db._world.backend.errors
    rejected = (
        "DELETE FROM Permit RETURNING who",
        "UPDATE Permit SET who='changed' RETURNING who",
        "INSERT INTO Permit VALUES ('changed') RETURNING who",
        "CREATE TABLE Extra (who TEXT)",
        "CREATE TEMP TABLE Extra AS SELECT * FROM Permit",
        "DROP TABLE Permit",
        "ALTER TABLE Permit ADD COLUMN extra TEXT",
        "ATTACH ':memory:' AS extra",
        "PRAGMA threads=2",
        "EXPLAIN DELETE FROM Permit",
        "SELECT * INTO Extra FROM Permit",
        "SELECT * FROM query('DELETE FROM Permit RETURNING who')",
        "SELECT * FROM query('SELECT * FROM Permit; DELETE FROM Permit')",
        "BEGIN", "COMMIT", "ROLLBACK",
        "SELECT 1 AS n; DELETE FROM Permit",
        "DELETE FROM Permit; SELECT 1 AS n",
    )
    before = db.snapshot()
    for sql in rejected:
        with pytest.raises((ValueError, *native_errors)):
            db.query_sql(sql, reads=("Allowed",))
        assert db.query("Permit", who="alice") == [{"who": "alice"}]
        assert db.snapshot() is before
    db.add("Permit", who="dave")
    assert db.has("Allowed", who="dave")


def test_sql_requires_idle_world_and_independent_rows(db):
    with db.batch():
        with pytest.raises(RuntimeError, match="batch"):
            db.query_sql("SELECT who FROM Permit", reads=("Permit",))
    rows = db.query_sql("SELECT who FROM Permit WHERE who=:who", {"who": "alice"}, reads=["Permit"])
    rows[0]["who"] = "changed locally"
    assert db.has("Permit", who="alice")
    db.close()
    with pytest.raises(RuntimeError, match="closed"):
        db.query_sql("SELECT 1 AS n", reads=())


def test_sql_cannot_reenter_snapshot_publication(backend):
    attempts = []

    def sink(_):
        with pytest.raises(RuntimeError, match="publication"):
            db.query_sql("SELECT who FROM Permit", reads=("Permit",))
        attempts.append(True)

    db = LogicDB(rules(backend), on_snapshot=sink)
    try:
        db.add("Permit", who="alice")
        assert attempts == [True]
    finally:
        db.close()


def test_empty_queries_inputs_and_duplicate_output_names(db):
    assert db.query_sql("SELECT :value AS value", {"value": None}, reads=()) == [{"value": None}]
    assert db.query_sql("SELECT who FROM Permit WHERE who='absent'", reads=("Permit",)) == []
    for sql in (None, "", "   "):
        with pytest.raises(ValueError, match="non-empty"):
            db.query_sql(sql, reads=())
    with pytest.raises(TypeError, match="params"):
        db.query_sql("SELECT :value", [1], reads=())
    for reads in ("Permit", None, {"Permit"}):
        with pytest.raises(TypeError, match="reads"):
            db.query_sql("SELECT * FROM Permit", reads=reads)
    with pytest.raises(TypeError):
        db.query_sql("SELECT 1 AS n")
    with pytest.raises(ValueError, match="Unknown relation"):
        db.query_sql("SELECT 1 AS n", reads=("Missing",))
    with pytest.raises((ValueError, SQLAlchemyError)):
        db.query_sql("SELECT 1 AS n, 2 AS n", reads=())
    assert db.query_sql("SELECT 1 AS first, 2 AS second", reads=()) == [{"first": 1, "second": 2}]


def test_recursive_cte_and_missing_parameter_recovery(db):
    assert db.query_sql(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<:n) "
        "SELECT x FROM n ORDER BY x",
        {"n": 3}, reads=(),
    ) == [{"x": 1}, {"x": 2}, {"x": 3}]
    with pytest.raises(SQLAlchemyError):
        db.query_sql("SELECT who FROM Allowed WHERE who=:who", reads=("Allowed",))
    assert db.query_sql(
        "SELECT who FROM Allowed WHERE who=:who", {"who": "alice"}, reads=("Allowed",),
    ) == [{"who": "alice"}]


def test_sql_results_use_native_driver_types(backend):
    bundle = RuleSet({"format": "renpy-relations", "version": 1, "backend": backend,
        "facts": {"Flag": {"columns": {"active": "boolean"}}}, "derived": {}})
    db = LogicDB(bundle)
    try:
        db.add("Flag", active=True)
        value = db.query_sql("SELECT active FROM Flag", reads=("Flag",))[0]["active"]
        assert type(value) is (bool if backend == "duckdb" else int)
        assert db.query("Flag") == [{"active": True}]
    finally:
        db.close()


def test_sqlite_authorizer_with_renpy_driver(monkeypatch):
    driver = pytest.importorskip("pysqlite3")
    monkeypatch.setattr(runtime, "sqlite3", driver)
    db = LogicDB(rules("sqlite"))
    try:
        db.add("Permit", who="alice")
        assert db.query_sql("SELECT who FROM Allowed", reads=("Allowed",)) == [{"who": "alice"}]
        with pytest.raises(ValueError, match="read-only"):
            db.query_sql("DELETE FROM Permit", reads=())
        db.remove("Permit", who="alice")
        assert db.query_sql("SELECT who FROM Allowed", reads=("Allowed",)) == []
    finally:
        db.close()
