import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks/graph.py"


def load_benchmark():
    spec = importlib.util.spec_from_file_location("graph_benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graph_uses_distinct_backends_and_preserves_partial_timeout(tmp_path, monkeypatch):
    benchmark = load_benchmark()
    output = tmp_path / "graph.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--lengths", "128", "--backends", "sqlite", "duckdb",
                                     "--timeout", "0.5", "--out", str(output)])
    calls = []

    def run(command, **kwargs):
        backend = command[command.index("--backend") + 1]
        destination = Path(command[command.index("--out") + 1])
        calls.append((backend, destination, kwargs["timeout"]))
        benchmark.atomic_json(destination, {"length": 128, "backend": backend,
                                            "status": "running", "current_phase": "load"})
        if backend == "duckdb":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        benchmark.atomic_json(destination, {"length": 128, "backend": backend, "status": "ok"})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    assert benchmark.main() == 1
    assert [backend for backend, _, _ in calls] == ["sqlite", "duckdb"]
    assert len({destination for _, destination, _ in calls}) == 2
    assert all(timeout == 0.5 for _, _, timeout in calls)
    records = json.loads(output.read_text())["runs"]
    assert records[0]["status"] == "ok"
    assert records[1]["status"] == "error"
    assert records[1]["current_phase"] == "load"
