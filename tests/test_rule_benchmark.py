import json
from pathlib import Path
import subprocess
import sys

import pytest

from renpy_relations import LogicDB, RuleSet


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from rules import dataset, populate


@pytest.mark.parametrize("shape", ["partitioned", "shared_table"])
@pytest.mark.parametrize("ratio", [1, 10])
def test_generated_workload_cardinality_and_condition_meaning(shape, ratio):
    document = dataset(128, ratio, shape)
    assert len(document["derived"]) == 128 * ratio
    db = LogicDB(RuleSet(document))
    try:
        populate(db, 128, shape)
        assert sum(len(db.query(n)) for n in document["facts"]) == 128
        assert all(db.has(n, flag="v0") for n in document["derived"])
        db.add("Blocked", flag="v0")
        assert db.has("D0Rule1", flag="v0")
        assert not db.has("D0Rule2", flag="v0")
    finally:
        db.close()


def test_cli_compares_real_baseline_and_native_and_records_rebuilds(tmp_path):
    output = tmp_path / "results"
    result = subprocess.run([
        sys.executable, str(ROOT / "benchmarks/rules.py"), "--facts", "128", "--ratios", "1",
        "--shapes", "partitioned", "shared_table", "--modes", "cached", "--repetitions", "1",
        "--out", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads((output / "results.json").read_text())
    assert len(document["runs"]) == 4
    by_key = {(r["shape"], r["variant"]): r for r in document["runs"]}
    native = by_key["partitioned", "native"]
    baseline = by_key["partitioned", "baseline"]
    assert native["local_rebuilt"] == 4
    assert baseline["local_rebuilt"] == 48
    assert native["unrelated_rebuilt"] == 0
    assert baseline["unrelated_rebuilt"] == 48
    assert by_key["shared_table", "native"]["local_rebuilt"] == 48
    assert all(r["status"] == "ok" for r in document["runs"])
    assert (output / "REPORT.md").is_file()


@pytest.mark.parametrize("count", [1000, 3000, 10000])
def test_generated_conditions_are_exactly_sized_distinct_and_cover_all_domains(count):
    document = dataset((count+64+9)//10, 10, "partitioned", conditions=count)
    leaves = {n: s["sql"] for n, s in document["derived"].items() if "GlobalState" in s["sql"]}
    assert len(leaves) == count
    assert len(document["derived"]) == count+64
    assert len(set(leaves.values())) == count
    assert {n.split("Rule")[0] for n in leaves} == {f"D{i}" for i in range(32)}


@pytest.mark.parametrize("shape", ["partitioned", "shared_table"])
def test_generated_condition_full_rows_and_negative_results(shape):
    count, facts = 1000, 107
    document = dataset(facts, 10, shape, conditions=count)
    db = LogicDB(RuleSet(document))
    try:
        populate(db, facts, shape)

        def verify(local=False, global_off=False, blocked=False):
            for domain in range(32):
                flags = range(domain, facts-2, 32)
                for ordinal in range(count//32 + int(domain < count%32)):
                    expected = {f"v{i//32}" for i in flags if not global_off
                                and not (local and domain == 0 and i//32 == 0)
                                and not (blocked and i//32 == 0)
                                and (i//32)%(ordinal+2) != ordinal%2}
                    rows = db.query(f"D{domain}Rule{ordinal+2}")
                    assert len(rows) == len(expected)
                    assert {r["flag"] for r in rows} == expected

        verify()
        name = "State" if shape == "shared_table" else "State0"
        fields = {"flag": "v0", **({"domain": 0} if shape == "shared_table" else {})}
        with db.batch():
            db.remove(name, **fields)
            db.add(name, **fields, enabled=0)
        verify(local=True)
        with db.batch():
            db.remove("GlobalState", enabled=1)
            db.add("GlobalState", enabled=0)
        verify(local=True, global_off=True)
        with db.batch():
            db.remove("Note", text="initial")
            db.add("Note", text="changed")
        verify(local=True, global_off=True)
        with db.batch():
            db.remove("GlobalState", enabled=0)
            db.add("GlobalState", enabled=1)
        db.add("Blocked", flag="v0")
        verify(local=True, blocked=True)
    finally:
        db.close()


def test_generated_predicates_have_distinct_meanings():
    db = LogicDB(RuleSet(dataset(384, 1, "partitioned", conditions=320)))
    try:
        populate(db, 384, "partitioned")
        witnesses = {frozenset(r["flag"] for r in db.query(f"D0Rule{i+2}")) for i in range(10)}
        assert len(witnesses) == 10
    finally:
        db.close()


def test_large_condition_cli_reads_every_condition_and_preserves_legacy_workload(tmp_path):
    output = tmp_path / "conditions"
    result = subprocess.run([
        sys.executable, str(ROOT / "benchmarks/conditions.py"), "--conditions", "320", "--ratios", "10",
        "--shapes", "partitioned", "--modes", "cached", "--repetitions", "1",
        "--backends", "sqlite", "--variants", "baseline", "native", "--out", str(output)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads((output / "results.json").read_text())
    assert len(document["runs"]) == 2
    assert len(document["validations"]) == 2
    assert all(r["status"] == "ok" and r["validated_full_relations"] == 1600 for r in document["validations"])
    for run in document["runs"]:
        assert run["status"] == "ok"
        assert run["conditions"] == 320 and run["rules"] == 384 and run["facts"] == 39
        assert "history_all" not in run["phases"]
        for phase in ("cold_panel", "warm_panel", "local_panel", "global_panel", "unrelated_panel"):
            item = run["phases"][phase]
            assert item["request_count"] == 320
            assert item["request_min_seconds"] <= item["request_median_seconds"] <= item["request_p95_seconds"] <= item["request_max_seconds"]
    native, = [r for r in document["runs"] if r["variant"] == "native"]
    baseline, = [r for r in document["runs"] if r["variant"] == "baseline"]
    assert native["local_rebuilt"] == 12
    assert baseline["local_rebuilt"] == 384
    assert "320" in (output / "REPORT.md").read_text()


def test_condition_cli_current_backends_do_not_read_unselected_baseline(tmp_path):
    pytest.importorskip("duckdb")
    output = tmp_path / "conditions-current"
    result = subprocess.run([
        sys.executable, str(ROOT / "benchmarks/conditions.py"), "--conditions", "320", "--ratios", "10",
        "--shapes", "partitioned", "--modes", "cached", "--repetitions", "1",
        "--baseline-ref", "deliberately-missing", "--out", str(output)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads((output / "results.json").read_text())
    assert set(document["source_sha256"]) == {"native"}
    assert {r["backend"] for r in document["runs"]} == {"sqlite", "duckdb"}
    assert len(document["runs"]) == len(document["validations"]) == 2
    assert all(r["status"] == "ok" and not r["history_bound"] for r in document["runs"])
    assert all(r["validated_full_relations"] == 1600 for r in document["validations"])
