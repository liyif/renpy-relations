import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import relation_rules.runtime as runtime
from relation_rules import LogicDB, RuleError, RuleSet
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event


@pytest.fixture(params=["sqlite", "duckdb"])
def backend(request):
    if request.param == "duckdb":
        pytest.importorskip("duckdb")
    return request.param


def rules(backend):
    return RuleSet({"format": "renpy-relations", "version": 1, "backend": backend,
        "facts": {"Permit": {"columns": {"who": "text"}},
                  "Blocked": {"columns": {"who": "text"}}},
        "derived": {
            "Visible": {"columns": {"who": "text"}, "sql": "SELECT who FROM Permit"},
            "Allowed": {"columns": {"who": "text"}, "sql": "SELECT who FROM Visible v WHERE NOT EXISTS (SELECT 1 FROM Blocked b WHERE b.who=v.who)"},
            "Counted": {"columns": {"n": "integer"}, "sql": "SELECT count(*) AS n FROM Blocked"},
        },
        "dependencies": {"Visible": ["Permit"], "Allowed": ["Visible", "Blocked"], "Counted": ["Blocked"]}})


@pytest.mark.parametrize("mode", ["cached", "live", "materialized"])
def test_column_names_do_not_collide_with_method_parameters(backend, mode):
    bundle = RuleSet({"format": "renpy-relations", "version": 1, "backend": backend,
        "facts": {"Person": {"columns": {"name": "text", "self": "text"}}},
        "derived": {"Visible": {"columns": {"name": "text", "self": "text"},
                                "sql": "SELECT name, self FROM Person"}},
        "dependencies": {"Visible": ["Person"]}})
    db = LogicDB(bundle, mode=mode)
    try:
        assert db.query("Visible", name="hero", self="origin") == []
        db.add("Person", name="hero", self="origin")
        assert db.query("Visible", name="hero") == [{"name": "hero", "self": "origin"}]
        assert db.has("Visible", name="hero", self="origin")
        image = db.snapshot()
        db.remove("Person", name="hero", self="origin")
        assert not db.has("Visible", name="hero")
        db.restore(image)
        assert db.has("Visible", name="hero", self="origin")
    finally:
        db.close()


@pytest.mark.parametrize("mode", ["cached", "live", "materialized"])
def test_native_snapshot_branching_reload_and_failed_batch(backend, mode):
    db = LogicDB(rules(backend), backend=backend, mode=mode)
    try:
        db.add("Permit", who="hero")
        db.add("Permit", who="hero")
        assert db.query("Allowed") == [{"who": "hero"}]
        snapshot = db.snapshot()
        assert db.snapshot() is snapshot
        db.add("Blocked", who="hero")
        assert not db.has("Allowed")
        db.restore(snapshot)
        db.add("Permit", who="other")
        assert {r["who"] for r in db.query("Allowed")} == {"hero", "other"}
        with pytest.raises(RuntimeError, match="abort"):
            with db.batch():
                db.remove("Permit", who="hero")
                raise RuntimeError("abort")
        assert db.has("Allowed", who="hero")
        changed = rules(backend).document
        changed["derived"]["Visible"]["sql"] = "SELECT who FROM Permit WHERE who='other'"
        db.reload_rules(RuleSet(changed))
        assert db.query("Allowed") == [{"who": "other"}]
        db.restore(snapshot)
        assert not db.has("Allowed")
        db.restore(None)
        assert not db.has("Permit")
    finally:
        db.close()


def test_plain_commits_do_not_generate_snapshots(backend, monkeypatch):
    def unexpected(*args):
        pytest.fail("Ordinary batch copied the entire database")
    monkeypatch.setattr(runtime, "_snapshot_world", unexpected)
    db = LogicDB(rules(backend), backend=backend)
    try:
        db.add("Permit", who="hero")
        assert db.has("Allowed")
        db.remove("Permit", who="hero")
        assert not db.has("Allowed")
        assert db.stats()["snapshot_bytes"] == 0
    finally:
        db.close()


def test_sqlite_snapshot_uses_native_image_and_excludes_temp_tables(monkeypatch):
    db = LogicDB(rules("sqlite"))
    try:
        db.add("Permit", who="hero")
        db.query("Allowed")
        # A native image must not SELECT fact rows through Python.
        raw = db._world.engine.raw_connection()
        raw.dbapi_connection.set_authorizer(lambda action, *args:
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and args[0] == "Permit" else sqlite3.SQLITE_OK)
        try:
            image = db.snapshot()
        finally:
            raw.dbapi_connection.set_authorizer(None)
            raw.close()
        assert image.startswith(b"SQLite format 3\0")
        with sqlite3.connect(":memory:") as inspection:
            inspection.deserialize(image)
            assert inspection.execute("SELECT * FROM Permit").fetchall() == [("hero",)]
            assert inspection.execute("SELECT name FROM sqlite_schema WHERE name='Allowed'").fetchall() == []
    finally:
        db.close()


def test_duckdb_snapshot_excludes_temp_derived_tables():
    duckdb = pytest.importorskip("duckdb")
    db = LogicDB(rules("duckdb"))
    try:
        db.add("Permit", who="hero")
        db.query("Allowed")
        image = db.snapshot()
        assert image[8:12] == b"DUCK"
        with tempfile.TemporaryDirectory(prefix="relations-image-") as directory:
            path = Path(directory) / "facts.duckdb"
            path.write_bytes(image)
            connection = duckdb.connect(str(path))
            try:
                names = {row[0] for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables").fetchall()}
            finally:
                connection.close()
        assert "Permit" in names
        assert not ({"Visible", "Allowed", "Counted"} & names)
    finally:
        db.close()


def test_sqlite_backup_fallback_round_trip(monkeypatch):
    driver = pytest.importorskip("pysqlite3")
    monkeypatch.setattr(runtime, "sqlite3", driver)
    db = LogicDB(rules("sqlite"))
    try:
        db.add("Permit", who="hero")
        image = db.snapshot()
        assert image.startswith(b"SQLite format 3\0")
        db.remove("Permit", who="hero")
        db.restore(image)
        assert db.has("Allowed", who="hero")
    finally:
        db.close()


def test_wrong_backend_and_damaged_images_preserve_world(backend):
    db = LogicDB(rules(backend), backend=backend)
    try:
        db.add("Permit", who="hero")
        image = db.snapshot()
        for invalid in (b"invalid", image[:100]):
            with pytest.raises(RuleError):
                db.restore(invalid)
            assert db.has("Allowed", who="hero")
        other_backend = "duckdb" if backend == "sqlite" else "sqlite"
        changed = rules(backend).document
        changed["backend"] = other_backend
        with pytest.raises(RuleError, match="backend"):
            db.reload_rules(RuleSet(changed))
    finally:
        db.close()


@pytest.mark.parametrize("mode", ["cached", "live", "materialized"])
def test_snapshot_rejection_and_failure_restore_previous_facts(backend, mode, monkeypatch):
    received = []
    def sink(image):
        if received:
            raise RuntimeError("rejected")
        received.append(image)
    db = LogicDB(rules(backend), backend=backend, mode=mode, on_snapshot=sink)
    try:
        db.add("Permit", who="hero")
        with pytest.raises(RuntimeError, match="rejected"):
            db.remove("Permit", who="hero")
        assert db.has("Allowed", who="hero")
        def failure(*args):
            raise RuntimeError("backup failed")
        monkeypatch.setattr(runtime, "_snapshot_world", failure)
        with pytest.raises(RuntimeError, match="backup failed"):
            db.add("Blocked", who="hero")
        assert not db.has("Blocked")
        assert db.has("Allowed", who="hero")
    finally:
        db.close()


def test_noop_batch_with_sink_does_not_copy_database(backend, monkeypatch):
    db = LogicDB(rules(backend), on_snapshot=lambda image: None)
    try:
        def unexpected(*args):
            pytest.fail("No-op batch generated an image")
        monkeypatch.setattr(runtime, "_snapshot_world", unexpected)
        with db.batch():
            pass
        db.remove("Permit", who="missing")
    finally:
        db.close()


def test_keys_numbers_and_output_types(backend):
    bundle = RuleSet({"format": "renpy-relations", "version": 1, "backend": backend,
        "facts": {"Item": {"columns": {"id": "integer", "amount": "real", "active": "boolean"}, "key": ["id"]}},
        "derived": {"Visible": {"columns": {"id": "integer", "amount": "real", "active": "boolean"},
                                 "sql": "SELECT * FROM Item"}},
        "dependencies": {"Visible": ["Item"]}})
    db = LogicDB(bundle)
    try:
        values = {"id": 2**40, "amount": 1.23456789012345, "active": True}
        db.add("Item", **values)
        db.add("Item", **values)
        with pytest.raises(IntegrityError):
            db.add("Item", **{**values, "amount": 2.0})
        assert db.query("Visible") == [values]
        with db.batch():
            db.remove("Item", id=values["id"])
            db.add("Item", **{**values, "amount": 2.0})
        image = db.snapshot()
        db.restore(None)
        db.restore(image)
        assert db.query("Visible") == [{**values, "amount": 2.0}]
    finally:
        db.close()


def test_cached_invalidation_preserves_unrelated_relations(backend):
    db = LogicDB(rules(backend))
    try:
        for name in ("Visible", "Allowed", "Counted"):
            db.query(name)
        db.add("Permit", who="hero")
        assert db.stats()["cached_relations"] == ["Counted"]
        assert db.has("Allowed", who="hero")
        assert db.describe("Allowed")["reads"] == ["Blocked", "Visible"]
        db.add("Blocked", who="hero")
        assert db.stats()["cached_relations"] == ["Visible"]
        assert not db.has("Allowed")
        assert db.query("Counted") == [{"n": 1}]
    finally:
        db.close()


def test_renpy_adapter_uses_backend_images_and_restores_branches(backend, monkeypatch):
    from renpy_relations import LogicDB
    store = SimpleNamespace(logic_snapshot=None)
    monkeypatch.setitem(__import__("sys").modules, "renpy", SimpleNamespace(store=store))
    config = SimpleNamespace(after_default_callbacks=[], interact_callbacks=[], developer=True)
    db = LogicDB(rules(backend))
    try:
        db.install_renpy(config)
        config.after_default_callbacks[0]()
        db.add("Permit", who="hero")
        past = store.logic_snapshot
        db.add("Blocked", who="hero")
        store.logic_snapshot = past
        config.after_default_callbacks[0]()
        db.add("Permit", who="branch")
        assert {r["who"] for r in db.query("Allowed")} == {"hero", "branch"}
    finally:
        db.close()


def test_reordered_fact_declarations_keep_schema_and_snapshots_compatible(backend):
    original = rules(backend).document
    original["facts"]["Permit"]["columns"]["sequence"] = "integer"
    reordered = rules(backend).document
    reordered["facts"] = dict(reversed(original["facts"].items()))
    reordered["facts"]["Permit"] = {"columns": {"sequence": "integer", "who": "text"}}
    first, second = RuleSet(original), RuleSet(reordered)
    assert first.fact_schema_id == second.fact_schema_id
    db = LogicDB(first)
    other = LogicDB(second)
    try:
        db.add("Permit", who="hero", sequence=7)
        image = db.snapshot()
        db.reload_rules(second)
        assert db.has("Allowed", who="hero")
        other.restore(image)
        assert other.query("Permit") == [{"who": "hero", "sequence": 7}]
    finally:
        db.close()
        other.close()


@pytest.mark.parametrize("mode", ["cached", "materialized", "live"])
def test_data_dependent_reload_failure_preserves_world(backend, mode):
    db = LogicDB(rules(backend), mode=mode)
    try:
        db.add("Permit", who="not_a_number")
        assert db.has("Allowed", who="not_a_number")
        cached = db.stats()["cached_relations"]
        changed = rules(backend).document
        expression = "json(who)" if backend == "sqlite" else "CAST(who AS BIGINT)"
        changed["derived"]["Visible"]["sql"] = f"SELECT {expression} AS who FROM Permit"
        with pytest.raises(RuleError):
            db.reload_rules(RuleSet(changed))
        assert db.stats()["cached_relations"] == cached
        assert db.has("Allowed", who="not_a_number")
    finally:
        db.close()


def test_failed_lazy_table_creation_rolls_back_and_can_retry(backend):
    document = rules(backend).document
    expression = "json(who)" if backend == "sqlite" else "CAST(who AS BIGINT)"
    document["derived"]["Allowed"]["sql"] = f"SELECT {expression} AS who FROM Visible"
    document["dependencies"]["Allowed"] = ["Visible"]
    db = LogicDB(RuleSet(document))
    try:
        db.add("Permit", who="invalid")
        with pytest.raises(db._world.backend.errors):
            db.query("Allowed")
        assert db.stats()["cached_relations"] == []
        db.remove("Permit", who="invalid")
        db.add("Permit", who="1")
        assert db.query("Allowed") == [{"who": "1"}]
        assert db.stats()["materializations"] == {"Visible": 1, "Allowed": 1}
    finally:
        db.close()


def test_sqlite_bulk_removal_does_not_return_deleted_rows():
    db = LogicDB(rules("sqlite"))
    statements = []
    try:
        db.add("Permit", who="hero")
        assert db.has("Allowed")
        @event.listens_for(db._world.engine, "before_cursor_execute")
        def capture(conn, cursor, sql, parameters, context, executemany):
            statements.append(sql)
        db.remove("Permit", who="hero")
        deletes = [s for s in statements if s.startswith('DELETE FROM main.')]
        assert len(deletes) == 1
        assert "RETURNING" not in deletes[0]
        assert not db.has("Allowed")
    finally:
        db.close()
