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
