import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from compile_rules import compile_rules
from renpy_relations import LogicDB


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks/run.py"
spec = importlib.util.spec_from_file_location("relation_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


@pytest.mark.parametrize("mode", ["cached", "live", "materialized"])
def test_benchmark_dataset_has_correct_complete_relations(mode, tmp_path):
    bundle = tmp_path / "rules.json"
    compile_rules(ROOT / "examples/palace/world.l", ROOT / "examples/palace/schema.json", bundle)
    db = LogicDB(bundle, mode=mode)
    size = 40
    try:
        benchmark.populate(db, size)
        expected = benchmark.cardinalities(size)
        for name, count in expected["facts_by_relation"].items():
            assert len(db.query(name)) == count
        assert {(r["character"], r["location"]) for r in db.query("CanEnter")} == set().union(
            *(benchmark.access_rows(i, size) for i in range(size)))
        assert {r["character"] for r in db.query("CanInvestigate")} == {
            benchmark.character(i) for i in range(size) if i % 3 == 0}
        assert {r["character"] for r in db.query("CanClaimReward")} == {
            benchmark.character(i) for i in range(size) if benchmark.eligible(i, size)}
        for name, count in expected["expected_derived_rows"].items():
            assert len(db.query(name)) == count
    finally:
        db.close()


def test_benchmark_cli_produces_raw_samples_and_report_for_every_mode(tmp_path):
    output = tmp_path / "results"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sizes", "40", "--repetitions", "1", "--queries", "6",
         "--batch-size", "3", "--out", str(output)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads((output / "results.json").read_text())
    assert len(document["runs"]) == 4
    assert all(run["status"] == "ok" for run in document["runs"])
    fixtures = {run["fixture_sha256"] for run in document["runs"]}
    assert len(fixtures) == 1
    for group in document["summary"]:
        assert group["successful"] == group["attempted"] == 1
        assert group["phases"]["warm_has"]["n"] == 6
        assert group["phases"]["warm_query"]["n"] == 6
    for run in document["runs"][1:]:
        assert run["batch_changes"] == 3
        assert "first_has_after_restore" in run["phases"]
    assert (output / "phases.csv").is_file()
    assert "不含 Ren’Py 界面" in (output / "REPORT.md").read_text()


def test_failed_runs_are_not_averaged_into_successful_measurements():
    records = [
        {"kind": "measure", "size": 40, "mode": "cached", "status": "ok",
         "snapshot_bytes": 100, "phases": {"first_has": {"seconds": 2}}},
        {"kind": "measure", "size": 40, "mode": "cached", "status": "timeout",
         "phases": {"first_has": {"seconds": 0.001}}},
    ]
    summary = benchmark.summarize(records)[0]
    assert summary["attempted"] == 2
    assert summary["successful"] == 1
    assert summary["phases"]["first_has"]["median_seconds"] == 2
    assert summary["phases"]["first_has"]["n"] == 1


def test_backend_workers_use_distinct_fixtures_and_summary_groups(tmp_path):
    pytest.importorskip("duckdb")
    output = tmp_path / "backends"
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--sizes", "40", "--backends", "sqlite", "duckdb",
        "--modes", "cached", "--repetitions", "1", "--queries", "6", "--batch-size", "3",
        "--out", str(output)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads((output / "results.json").read_text())
    assert len(document["runs"]) == 4
    assert {r["backend"] for r in document["summary"]} == {"sqlite", "duckdb"}
    for backend in ("sqlite", "duckdb"):
        records = [r for r in document["runs"] if r["backend"] == backend]
        assert len({r["fixture_sha256"] for r in records}) == 1
        assert all(r["status"] == "ok" and not r["history_bound"] for r in records)
        assert (output / ".work" / f"world-40-{backend}.snapshot").is_file()


def test_missing_worker_result_is_a_recorded_failure(tmp_path):
    output = tmp_path / "missing-worker"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sizes", "40", "--repetitions", "1",
         "--python", "/bin/true", "--out", str(output)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 1
    document = json.loads((output / "results.json").read_text())
    assert document["runs"][0]["status"] == "error"
    assert document["summary"] == []
    assert "Worker produced no result" in (output / "REPORT.md").read_text()


def test_worker_start_failure_is_recorded(tmp_path):
    output = tmp_path / "failed-start"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sizes", "40", "--python", str(tmp_path / "missing-python"),
         "--out", str(output)], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 1
    document = json.loads((output / "results.json").read_text())
    assert document["runs"][0]["status"] == "error"
    assert "Could not start worker" in (output / "REPORT.md").read_text()


def test_output_with_interrupted_work_is_rejected(tmp_path):
    output = tmp_path / "interrupted"
    work = output / ".work"
    work.mkdir(parents=True)
    (work / "seed-40-cached-0.json").write_text(json.dumps({"status": "ok"}))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sizes", "40", "--python", "/bin/true",
         "--out", str(output)], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "Output directory must be empty" in result.stderr
    assert not (output / "results.json").exists()
