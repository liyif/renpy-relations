import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
import suite


def test_smoke_runs_real_child_clis_with_empty_output_directories(tmp_path):
    pytest.importorskip("duckdb")
    pytest.importorskip("pysqlite3")
    output = tmp_path / "suite"
    completed = subprocess.run(
        [sys.executable, str(Path(suite.__file__)), "--smoke", "--out", str(output)],
        capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = json.loads((output / "results.json").read_text())
    assert len(document["runs"]) == 7
    assert all(record["status"] == "completed" for record in document["runs"])
    assert not list(output.glob("*.running.json"))


def test_controlled_plan_records_exact_scope_and_full_plan_expands_duckdb(tmp_path):
    tasks = suite.plan("controlled", sys.executable, tmp_path / "packages", tmp_path)
    by_name = {task["name"]: task for task in tasks}
    assert len(tasks) == 8
    assert by_name["conditions-sqlite"]["expected"] == {"runs": 108, "validations": 36}
    assert by_name["conditions-duckdb"]["expected"] == {"runs": 9, "validations": 3}
    assert by_name["facts-sqlite"]["expected"] == {"runs": 30}
    assert by_name["facts-duckdb"]["expected"] == {"runs": 10}
    assert by_name["snapshots"]["expected"] == {"runs": 18}
    assert by_name["graph"]["expected"] == {"runs": 6}
    assert all(by_name[name]["timeout"] == 120 for name in ("duckdb-load-3000", "duckdb-load-10000"))
    full = suite.plan("full", sys.executable, None, tmp_path)
    assert [task["name"] for task in full] == ["conditions", "facts", "snapshots", "graph"]
    assert full[0]["expected"] == {"runs": 216, "validations": 72}
    assert full[1]["expected"] == {"runs": 60}


def test_successful_partial_output_is_not_called_complete():
    document = {"runs": [{"status": "ok"}], "validations": []}
    assert suite.classify(document, {"expected": {"runs": 2}}) == "incomplete"
    assert suite.classify(document, {"expected": {"runs": 1}}) == "completed"
    assert suite.classify({"runs": [{"status": "error", "error": "worker timed out after 120 seconds"}]}) == "budget_limited"


def test_probe_budget_retains_partial_json_and_real_command(tmp_path, monkeypatch):
    task = suite.plan("controlled", sys.executable, None, tmp_path)[-1]

    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 120
        suite.atomic_json(task["result"], {"status": "running", "current_phase": "load"})
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(suite.subprocess, "run", timeout)
    monkeypatch.setattr(suite, "current_source_identity", lambda: {"sha256": {"renpy_relations.py": "known"}})
    record = suite.execute_task(task)
    assert record["status"] == "budget_limited"
    assert record["command"] == task["command"]
    assert suite.load_result(task)["current_phase"] == "load"
    assert json.loads((Path(task["directory"]) / "execution.json").read_text())["returncode"] is None


def test_suite_continues_after_failure_and_reports_unmeasured_scope(tmp_path, monkeypatch):
    output = tmp_path / "results"
    executed = []

    def execute(task):
        executed.append(task["name"])
        suite.atomic_json(task["result"], {
            key: [{"status": "ok"}] * count for key, count in task["expected"].items()})
        if task["probe"]:
            suite.atomic_json(task["result"], {"status": "ok", "runtime_sha256": "known"})
        return {**task, "status": "failed" if len(executed) == 1 else "completed", "returncode": 1 if len(executed) == 1 else 0}

    monkeypatch.setattr(suite, "execute_task", execute)
    assert suite.main(["--out", str(output), "--smoke"]) == 1
    document = json.loads((output / "results.json").read_text())
    assert len(executed) == 7
    assert document["runs"][0]["status"] == "failed"
    assert document["runs"][-1]["status"] == "completed"
    assert any("smoke" in item for item in document["unmeasured"])
    assert document["source"]["sha256"]["renpy_relations.py"]
    assert "## 执行命令" in (output / "REPORT.md").read_text()


def test_collection_rechecks_deleted_and_truncated_results(tmp_path):
    task = suite.plan("controlled", sys.executable, None, tmp_path)[0]
    record = {**task, "status": "completed", "returncode": 0}
    assert suite.revalidate_record(task, record)["status"] == "missing"
    suite.atomic_json(task["result"], {"runs": [{"status": "ok"}], "validations": []})
    assert suite.revalidate_record(task, record)["status"] == "incomplete"
    Path(task["result"]).write_text('{"runs":')
    assert suite.revalidate_record(task, record)["status"] == "failed"


def test_report_preserves_measured_hashes_after_workspace_changes(tmp_path, monkeypatch):
    task = suite.plan("controlled", sys.executable, None, tmp_path, smoke=True)[0]
    child = {key: [{"status": "ok"}] * count for key, count in task["expected"].items()}
    child.update(source_sha256={"native": "measured-runtime"}, file_sha256={"benchmarks/conditions.py": "measured-tool"})
    suite.atomic_json(task["result"], child)
    measured = suite.source_from_result(child)
    assert set(measured["sha256"]) == {"renpy_relations.py", "benchmarks/conditions.py"}
    record = {**task, "status": "completed", "returncode": 0, "measured_source": measured}
    monkeypatch.setattr(suite, "current_source_identity", lambda: {"sha256": {"renpy_relations.py": "later-runtime", "benchmarks/suite.py": "later-suite"}})
    document = suite.write_report(tmp_path, [record], smoke=True)
    assert document["measured_source"]["sha256"]["renpy_relations.py"] == "measured-runtime"
    assert "benchmarks/suite.py" not in document["measured_source"]["sha256"]
    assert document["report_generation_source"]["sha256"]["renpy_relations.py"] == "later-runtime"
    child["source_sha256"]["native"] = "tampered-runtime"
    suite.atomic_json(task["result"], child)
    assert suite.revalidate_record(task, record)["status"] == "failed"


@pytest.mark.parametrize("replacement", [None, '{"runs":', '{"runs": [], "validations": []}'])
def test_collect_never_trusts_completed_execution_when_result_is_lost(tmp_path, monkeypatch, replacement):
    task = suite.plan("controlled", sys.executable, None, tmp_path, smoke=True)[0]
    directory = Path(task["directory"])
    directory.mkdir()
    suite.atomic_json(directory / "execution.json", {
        **task, "status": "completed", "returncode": 0,
        "measured_source": {"origin": "captured_before_execution", "sha256": {"renpy_relations.py": "original"}}})
    if replacement is not None:
        Path(task["result"]).write_text(replacement)
    monkeypatch.setattr(suite, "plan", lambda *args: [task])
    monkeypatch.setattr(suite, "current_source_identity", lambda: {"sha256": {"renpy_relations.py": "later"}})
    assert suite.main(["--out", str(tmp_path), "--collect", "--smoke"]) == 1
    document = json.loads((tmp_path / "results.json").read_text())
    assert document["runs"][0]["status"] != "completed"
    assert document["measured_source"]["sha256"]["renpy_relations.py"] == "original"
    assert document["report_generation_source"]["sha256"]["renpy_relations.py"] == "later"
