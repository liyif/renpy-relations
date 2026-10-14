import json
from types import SimpleNamespace
import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from renpy_relations import LogicDB, RuleError, RuleSet


@pytest.fixture
def rules():
    return RuleSet({
        "format": "renpy-relations", "version": 1,
        "facts": {"Permit": {"columns": {"character": "text", "location": "text"}}},
        # Deliberately use reverse dependency order and different SELECT column order.
        "derived": {
            "Eligible": {"columns": {"character": "text"},
                         "sql": "SELECT character FROM Access WHERE location = 'archive'"},
            "Unrelated": {"columns": {"character": "text"}, "sql": "SELECT 'nobody' AS character"},
            "Access": {"columns": {"character": "text", "location": "text"},
                       "sql": "SELECT location, character FROM Permit"},
        },
        "dependencies": {"Eligible": ["Access"], "Unrelated": [], "Access": ["Permit"]},
    })


@pytest.fixture(params=["live", "materialized", "cached"])
def mode(request):
    return request.param


def test_fact_changes_and_snapshot_restore_have_same_meaning_in_all_modes(rules, mode):
    db = LogicDB(rules, mode=mode)
    try:
        with db.batch():
            db.add("Permit", character="hero", location="archive")
            db.add("Permit", character="hero", location="archive")
        assert db.query("Eligible") == [{"character": "hero"}]
        assert len(db.query("Permit")) == 1
        snapshot = db.snapshot()
        db.remove("Permit", character="hero")
        assert not db.has("Eligible", character="hero")
        db.restore(snapshot)
        assert db.has("Eligible", character="hero")
        db.restore(None)
        assert not db.has("Permit")
        assert not db.has("Eligible")
    finally:
        db.close()


def test_cached_relations_are_shared_across_queries_and_only_needed_dependencies_are_built(rules):
    db = LogicDB(rules)
    try:
        db.add("Permit", character="hero", location="archive")
        assert db.stats()["cached_relations"] == []
        assert db.has("Eligible", character="hero")
        row = db.query("Access", character="hero")[0]
        row["location"] = "changed by caller"
        assert db.query("Access")[0]["location"] == "archive"
        for i in range(50):
            assert not db.has("Eligible", character=f"other{i}")
        assert db.stats()["cached_relations"] == ["Access", "Eligible"]
        assert db.stats()["materializations"] == {"Access": 1, "Eligible": 1}
        # A duplicate assertion and unmatched removal do not invalidate caches.
        db.add("Permit", character="hero", location="archive")
        db.remove("Permit", character="missing")
        assert db.stats()["cached_relations"] == ["Access", "Eligible"]
        db.remove("Permit", character="hero")
        assert db.stats()["cached_relations"] == []
        assert not db.has("Eligible")
        assert db.stats()["materializations"] == {"Access": 2, "Eligible": 2}
    finally:
        db.close()


def test_filter_comparisons_use_sql_semantics_not_python_cache_key_equality(mode):
    rules = RuleSet({
        "format": "renpy-relations", "version": 1,
        "facts": {"Token": {"columns": {"value": "text"}}},
        "derived": {"Visible": {"columns": {"value": "text"}, "sql": "SELECT value FROM Token"}},
        "dependencies": {"Visible": ["Token"]},
    })
    db = LogicDB(rules, mode=mode)
    try:
        db.add("Token", value="1.0")
        assert not db.has("Visible", value=1)
        assert db.has("Visible", value=1.0)
    finally:
        db.close()


def test_declared_output_types_and_nulls_are_consistent_across_modes(mode):
    rules = RuleSet({
        "format": "renpy-relations", "version": 1, "facts": {},
        "derived": {"Typed": {
            "columns": {"text_value": "text", "number": "integer", "truth": "boolean", "missing": "real"},
            "sql": "SELECT 7 AS text_value, '9' AS number, 2 AS truth, NULL AS missing",
        }},
        "dependencies": {"Typed": []},
    })
    db = LogicDB(rules, mode=mode)
    try:
        assert db.query("Typed", text_value="7", number=9, truth=True, missing=None) == [
            {"text_value": "7", "number": 9, "truth": True, "missing": None}]
    finally:
        db.close()


def test_failed_batch_preserves_facts_outputs_and_cache(rules, mode):
    db = LogicDB(rules, mode=mode)
    try:
        db.add("Permit", character="hero", location="archive")
        assert db.has("Eligible")
        stats = db.stats()
        with pytest.raises(RuntimeError, match="abort"):
            with db.batch():
                db.remove("Permit", character="hero")
                db.add("Permit", character="other", location="archive")
                raise RuntimeError("abort")
        assert db.query("Eligible") == [{"character": "hero"}]
        assert db.stats()["materializations"] == stats["materializations"]
    finally:
        db.close()


def test_transactions_cannot_observe_or_replace_intermediate_world(rules):
    db = LogicDB(rules)
    try:
        with db.batch():
            db.add("Permit", character="hero", location="archive")
            for operation in (lambda: db.query("Eligible"), lambda: db.has("Permit"),
                              db.snapshot, lambda: db.restore(None), lambda: db.reload_rules(rules)):
                with pytest.raises(RuntimeError):
                    operation()
            with pytest.raises(RuntimeError):
                with db.batch():
                    pass
        assert db.has("Eligible")
    finally:
        db.close()


def test_rejected_snapshot_recovers_last_accepted_facts(rules, mode):
    accepted = []

    def sink(value):
        if accepted:
            raise RuntimeError("snapshot rejected")
        accepted.append(value)

    db = LogicDB(rules, mode=mode, on_snapshot=sink)
    try:
        db.add("Permit", character="hero", location="archive")
        with pytest.raises(RuntimeError, match="snapshot rejected"):
            db.remove("Permit", character="hero")
        assert db.query("Eligible") == [{"character": "hero"}]
    finally:
        db.close()


def test_primary_key_conflicts_fail_instead_of_silently_ignoring_changes():
    rules = RuleSet({"format": "renpy-relations", "version": 1,
                     "facts": {"Member": {"columns": {"character": "text", "faction": "text"},
                                          "key": ["character"]}}, "derived": {}})
    db = LogicDB(rules)
    try:
        db.add("Member", character="hero", faction="scholars")
        db.add("Member", character="hero", faction="scholars")
        with pytest.raises(IntegrityError):
            db.add("Member", character="hero", faction="guards")
        with db.batch():
            db.remove("Member", character="hero")
            db.add("Member", character="hero", faction="guards")
        assert db.query("Member") == [{"character": "hero", "faction": "guards"}]
    finally:
        db.close()


def test_reload_keeps_facts_and_old_snapshots_use_new_rules(rules, mode):
    db = LogicDB(rules, mode=mode)
    try:
        db.add("Permit", character="hero", location="archive")
        snapshot = db.snapshot()
        assert db.has("Eligible")
        changed = rules.document
        changed["derived"]["Eligible"]["sql"] = "SELECT character FROM Access WHERE location = 'palace'"
        changed["derived"].pop("Unrelated")
        changed["derived"]["NewOutput"] = {"columns": {"character": "text"},
                                            "sql": "SELECT character FROM Permit"}
        changed["dependencies"] = {"Eligible": ["Access"], "Access": ["Permit"], "NewOutput": ["Permit"]}
        db.reload_rules(RuleSet(changed))
        assert db.query("Permit") == [{"character": "hero", "location": "archive"}]
        assert not db.has("Eligible")
        assert db.has("NewOutput", character="hero")
        with pytest.raises(ValueError, match="Unknown relation"):
            db.query("Unrelated")
        db.restore(snapshot)
        assert not db.has("Eligible")
        assert db.has("NewOutput", character="hero")
    finally:
        db.close()


def test_invalid_reload_bundle_preserves_the_current_world(rules, mode):
    db = LogicDB(rules, mode=mode)
    try:
        db.add("Permit", character="hero", location="archive")
        assert db.has("Eligible")
        changed = rules.document
        changed["dependencies"]["Eligible"] = ["Missing"]
        with pytest.raises(RuleError):
            db.reload_rules(RuleSet(changed))
        assert db.query("Eligible") == [{"character": "hero"}]
    finally:
        db.close()


def test_schema_mismatch_and_corrupt_snapshot_do_not_destroy_the_world(rules):
    db = LogicDB(rules)
    changed = rules.document
    changed["facts"]["Permit"]["columns"]["extra"] = "integer"
    other = LogicDB(RuleSet(changed))
    try:
        db.add("Permit", character="hero", location="archive")
        for invalid in (b"not sqlite", other.snapshot()):
            with pytest.raises(RuleError):
                db.restore(invalid)
            assert db.has("Eligible", character="hero")
        with pytest.raises(RuleError, match="fact schema"):
            db.reload_rules(RuleSet(changed))
        assert db.has("Eligible", character="hero")
    finally:
        db.close()
        other.close()


@pytest.mark.parametrize("damage", ["metadata", "schema"])
def test_snapshot_validation_failure_keeps_original_world_and_cache(damage, mode):
    rules = RuleSet({"format": "renpy-relations", "version": 1,
                     "facts": {"Resource": {"columns": {"amount": "real"}}},
                     "derived": {"Available": {"columns": {"amount": "real"},
                                                "sql": "SELECT amount FROM Resource"}},
                     "dependencies": {"Available": ["Resource"]}})
    db = LogicDB(rules, mode=mode)
    try:
        db.add("Resource", amount=1.0)
        assert db.query("Available") == [{"amount": 1.0}]
        stats = db.stats()
        with sqlite3.connect(":memory:") as inspection:
            inspection.deserialize(db.snapshot())
            if damage == "metadata":
                inspection.execute("UPDATE __rr_metadata SET version=999")
            else:
                inspection.execute("CREATE TABLE extra(value TEXT)")
            inspection.commit()
            corrupt = inspection.serialize()
        with pytest.raises(RuleError):
            db.restore(corrupt)
        assert db.query("Resource") == [{"amount": 1.0}]
        assert db.query("Available") == [{"amount": 1.0}]
        assert db.stats()["materializations"] == stats["materializations"]
    finally:
        db.close()


def test_file_reload_can_recover_after_invalid_json(rules, tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules.document))
    db = LogicDB(path)
    try:
        db.add("Permit", character="hero", location="archive")
        assert not db.reload_if_changed()
        path.write_text("{")
        with pytest.raises(RuleError):
            db.reload_if_changed()
        assert db.has("Eligible")
        changed = rules.document
        changed["derived"]["Eligible"]["sql"] = "SELECT character FROM Access WHERE 0"
        path.write_text(json.dumps(changed))
        assert db.reload_if_changed()
        assert not db.has("Eligible")
        assert not db.reload_if_changed()
    finally:
        db.close()


def test_failed_lazy_materialization_does_not_mark_dependencies_valid(rules):
    changed = rules.document
    changed["derived"]["Eligible"]["sql"] = "SELECT json(location) AS character FROM Access"
    db = LogicDB(RuleSet(changed))
    try:
        db.add("Permit", character="hero", location="not_json")
        with pytest.raises(OperationalError):
            db.query("Eligible")
        assert db.stats()["cached_relations"] == []
        assert db.stats()["materializations"] == {}
        db.remove("Permit", character="hero")
        db.add("Permit", character="hero", location='"valid"')
        assert db.query("Eligible") == [{"character": '"valid"'}]
    finally:
        db.close()


def test_eager_rebuild_failure_rolls_back_fact_changes(rules):
    changed = rules.document
    changed["derived"]["Eligible"]["sql"] = "SELECT json(location) AS character FROM Access"
    db = LogicDB(RuleSet(changed), mode="materialized")
    try:
        with pytest.raises(OperationalError):
            db.add("Permit", character="hero", location="not_json")
        assert not db.has("Permit")
        assert not db.has("Access")
    finally:
        db.close()


def test_cycles_are_rejected_but_recursive_ctes_are_supported(rules):
    changed = rules.document
    changed["derived"]["Access"]["sql"] = "SELECT character, 'archive' AS location FROM Eligible"
    changed["dependencies"]["Access"] = ["Eligible"]
    with pytest.raises(RuleError, match="Cyclic"):
        LogicDB(RuleSet(changed))
    changed = rules.document
    changed["derived"]["Eligible"]["sql"] = (
        "WITH RECURSIVE n(v) AS (SELECT 1 UNION ALL SELECT v+1 FROM n WHERE v<3) "
        "SELECT CAST(v AS TEXT) AS character FROM n"
    )
    changed["dependencies"]["Eligible"] = []
    db = LogicDB(RuleSet(changed))
    try:
        assert sorted(r["character"] for r in db.query("Eligible")) == ["1", "2", "3"]
    finally:
        db.close()


def test_renpy_binding_restores_store_snapshot_and_is_idempotent(rules, monkeypatch):
    # Adapter contract only. Real engine lifecycle tests live in the demo.
    store = SimpleNamespace(logic_snapshot=None)
    notifications = []
    renpy = SimpleNamespace(store=store, log=notifications.append, notify=notifications.append)
    monkeypatch.setitem(__import__("sys").modules, "renpy", renpy)
    config = SimpleNamespace(after_default_callbacks=[], interact_callbacks=[], developer=True)
    db = LogicDB(rules)
    try:
        db.install_renpy(config)
        db.install_renpy(config)
        assert len(config.after_default_callbacks) == 1
        config.after_default_callbacks[0]()
        db.add("Permit", character="hero", location="archive")
        saved = store.logic_snapshot
        db.remove("Permit", character="hero")
        store.logic_snapshot = saved
        config.after_default_callbacks[0]()
        assert db.has("Eligible", character="hero")
        store.logic_snapshot = None
        config.after_default_callbacks[0]()
        assert not db.has("Permit")
    finally:
        db.close()


def test_renpy_watch_preserves_world_on_error_reports_once_and_honors_developer_mode(rules, tmp_path, monkeypatch):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules.document))
    logs, notifications = [], []
    renpy = SimpleNamespace(
        store=SimpleNamespace(logic_snapshot=None),
        exports=SimpleNamespace(log=logs.append, notify=notifications.append),
    )
    monkeypatch.setitem(__import__("sys").modules, "renpy", renpy)
    config = SimpleNamespace(after_default_callbacks=[], interact_callbacks=[], developer=True)
    db = LogicDB(path)
    try:
        db.install_renpy(config, watch_rules=True)
        db.install_renpy(config, watch_rules=True)
        assert len(config.interact_callbacks) == 1
        config.after_default_callbacks[0]()
        db.add("Permit", character="hero", location="archive")
        path.write_text("{")
        config.interact_callbacks[0]()
        config.interact_callbacks[0]()
        assert db.has("Eligible", character="hero")
        assert len(logs) == len(notifications) == 1
        changed = rules.document
        changed["derived"]["Eligible"]["sql"] = "SELECT character FROM Access WHERE 0"
        path.write_text(json.dumps(changed))
        config.interact_callbacks[0]()
        assert not db.has("Eligible")
        config.developer = False
        path.write_text("invalid")
        config.interact_callbacks[0]()
        assert len(logs) == len(notifications) == 1
    finally:
        db.close()
