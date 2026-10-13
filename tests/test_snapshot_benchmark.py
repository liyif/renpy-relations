import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks/snapshots.py"


def test_snapshot_benchmark_checks_real_state_and_keeps_raw_samples(tmp_path):
    pytest.importorskip("duckdb")
    pytest.importorskip("pysqlite3")
    output = tmp_path / "results"
    result = subprocess.run([sys.executable, str(SCRIPT), "--sizes", "40", "--repetitions", "1",
                             "--out", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    records = json.loads((output / "results.json").read_text())["runs"]
    assert len(records) == 3
    assert all(r["status"] == "ok" for r in records)
    assert {r["driver"] for r in records} == {"sqlite3", "pysqlite3", "duckdb"}
    assert len({r["runtime_sha256"] for r in records}) == 1
    for record in records:
        assert record["samples"][0]["snapshot_bytes"] > 0
        assert set(record["samples"][0]) == {
            "plain_commit", "history_commit", "snapshot", "snapshot_reused", "restore", "snapshot_bytes"}
    assert "不代表剧情条件查询速度" in (output / "REPORT.md").read_text()


@pytest.mark.parametrize("failure", [OSError("could not start"), subprocess.TimeoutExpired("worker", 180)])
def test_worker_failure_is_recorded_and_never_reported_as_measurement(tmp_path, monkeypatch, failure):
    spec = importlib.util.spec_from_file_location("snapshot_benchmark", SCRIPT)
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    output = tmp_path / "failed"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--sizes", "40", "--out", str(output)])
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(benchmark.subprocess, "run", fail)
    assert benchmark.main() == 1
    records = json.loads((output / "results.json").read_text())["runs"]
    assert len(records) == 3
    assert all(r["status"] == "error" and "samples" not in r for r in records)
    assert "FAILED" in (output / "REPORT.md").read_text()
