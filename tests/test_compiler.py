import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from compile_rules import compile_rules
from renpy_relations import LogicDB, RuleError


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "palace"
COMPILER = Path(__file__).resolve().parents[1] / "compile_rules.py"


@pytest.fixture(params=["sqlite", "duckdb"])
def inputs(tmp_path, request):
    source, schema, output = (tmp_path / p for p in ("world.l", "schema.json", "rules.json"))
    shutil.copyfile(EXAMPLE / "world.l", source)
    shutil.copyfile(EXAMPLE / "schema.json", schema)
    if request.param == "duckdb":
        pytest.importorskip("duckdb")
        source.write_text(source.read_text().replace('@Engine("sqlite")', '@Engine("duckdb")'))
    return source, schema, output


def test_explicit_compilation_target_does_not_edit_source(tmp_path):
    pytest.importorskip("duckdb")
    source = EXAMPLE / "world.l"
    before = source.read_bytes()
    output = tmp_path / "duckdb.json"
    bundle = compile_rules(source, EXAMPLE / "schema.json", output, backend="duckdb")
    assert source.read_bytes() == before
    assert bundle.backend == "duckdb"
    db = LogicDB(bundle, backend="duckdb")
    try:
        assert db.describe("CanClaimReward")["reads"] == ["CanInvestigate", "RewardClaimed"]
    finally:
        db.close()


@pytest.mark.parametrize("mode", ["live", "materialized", "cached"])
def test_real_logica_rules_load_and_drive_permissions_and_one_time_rewards(inputs, mode):
    source, schema, output = inputs
    compile_rules(source, schema, output)
    db = LogicDB(output, mode=mode)
    try:
        assert not db.has("CanEnter")
        db.add("Sponsor", character="hero", location="archive")
        assert db.has("CanEnter", character="hero", location="archive")
        assert not db.has("CanClaimReward")
        db.add("Knows", character="hero", secret="forged_letter")
        assert db.query("CanClaimReward") == [{"character": "hero", "reward": "investigation"}]
        db.add("RewardClaimed", character="hero", reward="investigation")
        assert not db.has("CanClaimReward")
        db.remove("Sponsor", character="hero")
        assert not db.has("CanInvestigate")
        with db.batch():
            db.add("Member", character="hero", faction="scholars")
            db.add("FactionAccess", faction="scholars", location="archive")
        assert db.has("CanInvestigate", character="hero")
        assert not db.has("CanClaimReward")
    finally:
        db.close()


def test_failed_compilation_preserves_previous_bundle_and_success_reloads(inputs):
    source, schema, output = inputs
    compile_rules(source, schema, output)
    previous = output.read_bytes()
    original_source = source.read_text()
    db = LogicDB(output)
    try:
        db.add("Sponsor", character="hero", location="archive")
        source.write_text("This is not valid Logica !!!")
        with pytest.raises(RuleError):
            compile_rules(source, schema, output)
        assert output.read_bytes() == previous
        assert not db.reload_if_changed()
        assert db.has("CanEnter", character="hero", location="archive")
        source.write_text(original_source.replace('location: l);', 'location: l), l != "archive";'))
        compile_rules(source, schema, output)
        assert db.reload_if_changed()
        assert not db.has("CanEnter", character="hero", location="archive")
        assert db.has("Sponsor", character="hero")
    finally:
        db.close()


def test_output_shape_mismatch_is_rejected_before_publication(inputs):
    source, schema, output = inputs
    declarations = json.loads(schema.read_text())
    declarations["derived"]["CanEnter"]["columns"]["missing"] = "text"
    schema.write_text(json.dumps(declarations))
    with pytest.raises(RuleError, match="expected columns"):
        compile_rules(source, schema, output)
    assert not output.exists()


def test_rule_input_changes_during_build_do_not_publish_mixed_outputs(inputs, monkeypatch):
    source, schema, output = inputs
    from logica.compiler import universe
    original = universe.LogicaProgram.FormattedPredicateSql
    calls = 0

    def compiler_with_edit(self, *args, **kwargs):
        nonlocal calls
        result = original(self, *args, **kwargs)
        calls += 1
        if calls == 1:
            source.write_text(source.read_text() + "\n# edited during compilation\n")
        return result

    monkeypatch.setattr(universe.LogicaProgram, "FormattedPredicateSql", compiler_with_edit)
    with pytest.raises(RuleError, match="changed during compilation"):
        compile_rules(source, schema, output)
    assert not output.exists()


def test_exported_relations_remain_dependencies_and_share_cached_results(inputs):
    source, schema, output = inputs
    compile_rules(source, schema, output)
    db = LogicDB(output)
    try:
        metadata = json.loads(output.read_text())["dependencies"]
        assert metadata["CanEnter"] == ["FactionAccess", "Member", "Sponsor"]
        assert metadata["CanClaimReward"] == ["CanInvestigate", "RewardClaimed"]
        db.add("Sponsor", character="hero", location="archive")
        db.add("Knows", character="hero", secret="forged_letter")
        assert db.describe("CanInvestigate")["dependencies"] == ["CanEnter"]
        assert db.describe("CanClaimReward")["dependencies"] == ["CanInvestigate"]
        assert db.has("CanClaimReward", character="hero")
        assert db.has("CanEnter", character="hero", location="archive")
        assert db.stats()["materializations"] == {
            "CanEnter": 1, "CanInvestigate": 1, "CanClaimReward": 1,
        }
    finally:
        db.close()


def test_watch_builds_changed_rules_and_keeps_last_good_output_on_error(inputs, tmp_path):
    source, schema, output = inputs
    with (tmp_path / "watch.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(COMPILER), str(source), "--schema", str(schema),
             "--output", str(output), "--watch"], stdout=log, stderr=log,
        )

        def wait_for(predicate):
            deadline = time.monotonic() + 10
            while not predicate():
                assert process.poll() is None
                assert time.monotonic() < deadline, (tmp_path / "watch.log").read_text()
                time.sleep(0.05)

        try:
            wait_for(output.exists)
            previous = output.read_bytes()
            source.write_text(source.read_text() + "\n# changed\n")
            wait_for(lambda: output.read_bytes() != previous)
            good = output.read_bytes()
            source.write_text("invalid !!!")
            wait_for(lambda: "Build failed" in (tmp_path / "watch.log").read_text())
            assert output.read_bytes() == good
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_uncompiled_bundle_is_rejected():
    from renpy_relations import RuleSet
    document = {"format": "renpy-relations", "version": 1, "facts": {}, "derived": {}}
    with pytest.raises(RuleError, match="Uncompiled rule bundle"):
        LogicDB(RuleSet(document))
