import pytest

from renpy_relations import LogicDB, RuleError, RuleSet
from _helpers import compiled


def branched_rules():
    return compiled({"format": "renpy-relations", "version": 1,
        "facts": {n: {"columns": {"value": "text"}} for n in ("Left", "Right", "Blocked", "Unused")},
        "derived": {
            "A": {"columns": {"value": "text"}, "sql": "SELECT value FROM Left"},
            "B": {"columns": {"value": "text"}, "sql": "SELECT value FROM Right"},
            "Diamond": {"columns": {"value": "text"}, "sql": "SELECT value FROM A UNION SELECT value FROM B"},
            "Allowed": {"columns": {"value": "text"}, "sql": "SELECT value FROM Diamond d WHERE NOT EXISTS (SELECT 1 FROM Blocked b WHERE b.value=d.value)"},
            "Constant": {"columns": {"value": "text"}, "sql": "SELECT 'constant' AS value"},
            "Counted": {"columns": {"value": "integer"}, "sql": "SELECT count(*) AS value FROM Unused"},
        }})


@pytest.mark.parametrize("mode", ["cached", "materialized", "live"])
def test_selective_changes_preserve_unrelated_outputs_and_handle_negation(mode, monkeypatch):
    import renpy_relations
    db = LogicDB(branched_rules(), mode=mode)
    filled = []
    original = renpy_relations._fill

    def track(conn, world, rules, name):
        filled.append(name)
        return original(conn, world, rules, name)

    try:
        with db.batch():
            db.add("Left", value="left")
            db.add("Right", value="right")
        for name in branched_rules().document["derived"]:
            db.query(name)
        monkeypatch.setattr(renpy_relations, "_fill", track)
        db.add("Left", value="new")
        if mode == "cached":
            assert db.stats()["cached_relations"] == ["B", "Constant", "Counted"]
        assert {r["value"] for r in db.query("Allowed")} == {"left", "right", "new"}
        if mode != "live":
            assert set(filled) == {"A", "Diamond", "Allowed"}
        filled.clear()
        db.add("Blocked", value="new")
        assert not db.has("Allowed", value="new")
        if mode != "live":
            assert filled == ["Allowed"]
        filled.clear()
        db.add("Unused", value="x")
        assert db.query("Counted") == [{"value": 1}]
        if mode != "live":
            assert filled == ["Counted"]
    finally:
        db.close()


def test_compiled_dependency_metadata_must_match_sql():
    document = branched_rules().document
    db = LogicDB(compiled(document))
    try:
        # Tampering the recorded edges breaks the plan fingerprint binding the
        # order and dependencies to the rule content.
        tampered = branched_rules().document
        tampered["dependencies"]["Allowed"].remove("Blocked")
        with pytest.raises(RuleError, match="Compiled plan/dependencies differ"):
            RuleSet(tampered)
        assert db.has("Constant", value="constant")
    finally:
        db.close()


def test_native_graph_handles_chain_beyond_python_recursion_limit():
    count = 1050
    document = {"format": "renpy-relations", "version": 1,
                "facts": {"Seed": {"columns": {"value": "text"}}}, "derived": {}}
    for i in range(count):
        source = "Seed" if i == 0 else f"Rule{i-1}"
        document["derived"][f"Rule{i}"] = {"columns": {"value": "text"}, "sql": f"SELECT value FROM {source}"}
    db = LogicDB(compiled(document))
    try:
        db.add("Seed", value="yes")
        assert db.has(f"Rule{count-1}", value="yes")
        db.remove("Seed", value="yes")
        assert not db.has(f"Rule{count-1}", value="yes")
    finally:
        db.close()
