import json
from pathlib import Path
import subprocess
import tarfile

import pytest

import prepare_game
import release
from benchmarks import baseline_sources


def release_fixture(tmp_path):
    artifact = tmp_path / "sample.tar.gz"
    artifact.write_bytes(b"release artifact")
    row = {"file": artifact.name, "bytes": artifact.stat().st_size, "sha256": release.digest(artifact)}
    manifest = tmp_path / "RELEASE.json"
    manifest.write_text(json.dumps({"version": "0.1.0", "artifacts": [row]}))
    (tmp_path / "SHA256SUMS").write_text("".join(
        f"{release.digest(p)}  {p.name}\n" for p in (artifact, manifest)))
    return artifact


def test_checksums_cover_manifest_and_payload(tmp_path):
    release_fixture(tmp_path)
    assert release.verify(tmp_path)["version"] == "0.1.0"


@pytest.mark.parametrize("change", ["tamper", "missing", "unlisted", "duplicate"])
def test_incomplete_or_changed_release_is_rejected(tmp_path, change):
    artifact = release_fixture(tmp_path)
    checksums = tmp_path / "SHA256SUMS"
    if change == "tamper":
        artifact.write_bytes(b"changed")
    elif change == "missing":
        artifact.unlink()
    elif change == "unlisted":
        checksums.write_text(checksums.read_text() + "0" * 64 + "  ../outside\n")
    else:
        checksums.write_text(checksums.read_text() * 2)
    with pytest.raises(ValueError):
        release.verify(tmp_path)


def test_source_export_uses_commit_and_omits_ignored_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
    git("init", "-q")
    (repo / "source.py").write_text("original")
    (repo / ".gitignore").write_text("secret.txt\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "source")
    (repo / "secret.txt").write_text("local only")
    monkeypatch.setattr(release, "ROOT", repo)
    output = tmp_path / "export"
    commit, hashes = release.clean_source(output)
    assert commit == git("rev-parse", "HEAD")
    assert (output / "source.py").read_text() == "original"
    assert not (output / "secret.txt").exists()
    assert hashes["source.py"] == release.digest(output / "source.py")
    (repo / "source.py").write_text("uncommitted")
    with pytest.raises(ValueError, match="Commit or stash"):
        release.clean_source(tmp_path / "dirty-export")


@pytest.mark.parametrize("existing", [True, False])
def test_staging_refuses_overwrites_and_source_recursion(tmp_path, existing):
    source = tmp_path / "project"
    (source / "game").mkdir(parents=True)
    output = source / "nested"
    if existing:
        output.mkdir()
        (output / "keep.txt").write_text("keep")
    with pytest.raises(ValueError):
        prepare_game.prepare(source, output)
    if existing:
        assert (output / "keep.txt").read_text() == "keep"
    else:
        assert not output.exists()


def test_dependency_inventory_requires_and_preserves_license_paths(tmp_path):
    info = tmp_path / "example-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: example\nVersion: 1.0\n")
    with pytest.raises(ValueError, match="Missing license"):
        prepare_game.inventory(tmp_path)
    (info / "LICENSE").write_text("Original license text")
    (info / "RECORD").write_text("example-1.0.dist-info/LICENSE,,\n")
    assert prepare_game.inventory(tmp_path) == [
        {"name": "example", "version": "1.0", "licenses": ["example-1.0.dist-info/LICENSE"]}]


def test_playable_archive_without_runtime_is_rejected(tmp_path):
    archive = tmp_path / "broken.tar.bz2"
    (tmp_path / "empty").mkdir()
    with tarfile.open(archive, "w:bz2") as stream:
        stream.add(tmp_path / "empty", arcname="tidelight")
    with pytest.raises(ValueError, match="Game archive is missing"):
        release.check_payload(archive)


@pytest.mark.parametrize("engine,text,expected", [
    (False, "15 passed in 1.0s", 15),
    (False, "15 passed, 2 skipped in 1.0s", None),
    (False, "0 passed in 1.0s", None),
    (True, "Test cases : 9 | 8 passed\nStatus: PASSED", None),
    (True, "Test cases : 0 | 0 passed\nStatus: PASSED", None),
    (True, "Test cases : 9 | 9 passed\nStatus: \x1b[32mPASSED\x1b[0m", 9),
])
def test_release_requires_complete_test_reports(tmp_path, engine, text, expected):
    log = tmp_path / "test.log"
    log.write_text(text)
    if expected is None:
        with pytest.raises(ValueError):
            release.read_test_evidence(log, engine=engine)
    else:
        assert release.read_test_evidence(log, engine=engine) == expected


def test_engine_report_must_match_the_expected_suite_size(tmp_path):
    log = tmp_path / "engine.log"
    log.write_text("Test cases : 8 | 8 passed\nStatus: PASSED")
    with pytest.raises(ValueError, match="Unexpected test count"):
        release.read_test_evidence(log, engine=True, expected=9)


def test_example_versions_match_the_release_metadata():
    version = prepare_game.project_version()
    for example in ("palace", "tidelight"):
        script = (prepare_game.ROOT / "examples" / example / "game/script.rpy").read_text()
        assert f'define config.version = "{version}"' in script


def test_archived_benchmarks_load_pinned_controls_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline_sources, "ROOT", tmp_path)
    manifest = json.loads((baseline_sources.BASELINES / "manifest.json").read_text())
    for short, entry in manifest.items():
        content = baseline_sources.historical_runtime(short)
        assert content == baseline_sources.historical_runtime(entry["commit"])
        assert len(content) > 20000


def test_modified_benchmark_control_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/renpy_relations.py").write_text("modified")
    (tmp_path / "manifest.json").write_text(json.dumps({"ref": {"commit": "original", "sha256": "0" * 64}}))
    monkeypatch.setattr(baseline_sources, "BASELINES", tmp_path)
    with pytest.raises(ValueError, match="checksum mismatch"):
        baseline_sources.historical_runtime("ref")
