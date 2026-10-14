import pytest

from renpy_relations import LogicDB, RuleError, RuleSet


def branched_rules():
    return RuleSet({"format": "renpy-relations", "version": 1,
        "facts": {n: {"columns": {"value": "text"}} for n in ("Left", "Right", "Blocked", "Unused")},
        "derived": {
            "A": {"columns": {"value": "text"}, "sql": "SELECT value FROM Left"},
            "B": {"columns": {"value": "text"}, "sql": "SELECT value FROM Right"},
            "Diamond": {"columns": {"value": "text"}, "sql": "SELECT value FROM A UNION SELECT value FROM B"},
            "Allowed": {"columns": {"value": "text"}, "sql": "SELECT value FROM Diamond d WHERE NOT EXISTS (SELECT 1 FROM Blocked b WHERE b.value=d.value)"},
            "Constant": {"columns": {"value": "text"}, "sql": "SELECT 'constant' AS value"},
            "Counted": {"columns": {"value": "integer"}, "sql": "SELECT count(*) AS value FROM Unused"},
        },
        "dependencies": {"A": ["Left"], "B": ["Right"], "Diamond": ["A", "B"],
                         "Allowed": ["Diamond", "Blocked"], "Constant": [], "Counted": ["Unused"]}})


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


def test_dependencies_must_describe_every_derived_relation():
    document = branched_rules().document
    db = LogicDB(RuleSet(document))
    try:
        missing = branched_rules().document
        missing["dependencies"].pop("Allowed")
        with pytest.raises(RuleError, match="Dependencies must describe every derived relation"):
            RuleSet(missing)
        unknown = branched_rules().document
        unknown["dependencies"]["Allowed"] = ["Missing"]
        with pytest.raises(RuleError, match="Invalid dependencies"):
            RuleSet(unknown)
        assert db.has("Constant", value="constant")
    finally:
        db.close()


def test_native_graph_handles_chain_beyond_python_recursion_limit():
    count = 1050
    document = {"format": "renpy-relations", "version": 1,
                "facts": {"Seed": {"columns": {"value": "text"}}}, "derived": {}, "dependencies": {}}
    for i in range(count):
        source = "Seed" if i == 0 else f"Rule{i-1}"
        document["derived"][f"Rule{i}"] = {"columns": {"value": "text"}, "sql": f"SELECT value FROM {source}"}
        document["dependencies"][f"Rule{i}"] = [source]
    db = LogicDB(RuleSet(document))
    try:
        db.add("Seed", value="yes")
        assert db.has(f"Rule{count-1}", value="yes")
        db.remove("Seed", value="yes")
        assert not db.has(f"Rule{count-1}", value="yes")
    finally:
        db.close()


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
@pytest.mark.parametrize("cycle", ["rootless", "reachable", "self"])
def test_native_graph_rejects_cycles_including_reachable_cycles(backend, cycle):
    if backend == "duckdb":
        pytest.importorskip("duckdb")
    dependencies = {"A": ["B"], "B": ["A"]}
    if cycle == "reachable":
        dependencies["A"].append("Seed")
    elif cycle == "self":
        dependencies = {"A": ["Seed", "A"], "B": ["Seed"]}
    document = {"format": "renpy-relations", "version": 1, "backend": backend,
                "facts": {"Seed": {"columns": {"v": "text"}}},
                "derived": {name: {"columns": {"v": "text"}, "sql": "SELECT v FROM Seed"}
                            for name in dependencies}, "dependencies": dependencies}
    with pytest.raises(RuleError, match="Cyclic"):
        LogicDB(RuleSet(document))


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
@pytest.mark.parametrize("mode", ["cached", "materialized", "live"])
def test_native_order_handles_paths_of_different_lengths_and_constants(backend, mode):
    if backend == "duckdb":
        pytest.importorskip("duckdb")
    document = {"format": "renpy-relations", "version": 1, "backend": backend,
        "facts": {"Seed": {"columns": {"v": "text"}}},
        "derived": {
            "Joiner": {"columns": {"v": "text"}, "sql": "SELECT v FROM Seed UNION SELECT v FROM Middle"},
            "Middle": {"columns": {"v": "text"}, "sql": "SELECT v FROM Constant UNION SELECT v FROM Seed"},
            "Constant": {"columns": {"v": "text"}, "sql": "SELECT 'constant' AS v"}},
        "dependencies": {"Joiner": ["Seed", "Middle"], "Middle": ["Constant", "Seed"], "Constant": []}}
    db = LogicDB(RuleSet(document), mode=mode)
    try:
        assert db.query("Joiner") == [{"v": "constant"}]
        db.add("Seed", v="new")
        assert {r["v"] for r in db.query("Joiner")} == {"constant", "new"}
    finally:
        db.close()
