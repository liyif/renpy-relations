"""Build and verify the experimental Linux release from a clean Git commit."""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from prepare_game import ROOT, project_version


SDK_VERSION = "8.5.3.26051504"


def read_test_evidence(log, *, engine=False, expected=None):
    text = re.sub(r"\x1b\[[0-9;]*m", "", Path(log).read_text())
    if engine:
        match = re.search(r"Test cases\s*:\s*(\d+)\s*\|\s*(\d+) passed", text)
        if not match or match[1] != match[2] or "Status: PASSED" not in text:
            raise ValueError(f"Engine did not pass every selected testcase: {log}")
    else:
        match = re.search(r"(\d+) passed", text)
        if not match or re.search(r"\d+ (?:skipped|xfailed|xpassed)", text):
            raise ValueError(f"Source test coverage is incomplete: {log}")
    count = int(match[1])
    if count <= 0 or (expected is not None and count != expected):
        raise ValueError(f"Unexpected test count ({count}, expected {expected}): {log}")
    return count


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked(command, *, cwd=None, log=None, environment=None):
    print("+ " + " ".join(map(str, command)), flush=True)
    if log is None:
        return subprocess.run(list(map(str, command)), cwd=cwd, env=environment, check=True)
    with Path(log).open("w") as stream:
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}")


def clean_source(destination):
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if status:
        raise ValueError("Commit or stash all source changes before building a release")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    payload = subprocess.check_output(["git", "archive", "--format=tar",
                                       f"--prefix={destination.name}/", commit], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        if any(not (member.isfile() or member.isdir()) for member in archive.getmembers()):
            raise ValueError("Release sources must contain only regular files and directories")
        archive.extractall(destination.parent, filter="data")
    hashes = {str(path.relative_to(destination)): digest(path)
              for path in sorted(destination.rglob("*")) if path.is_file()}
    return commit, hashes


def archive_directory(directory, target):
    with tarfile.open(target, "w:gz") as archive:
        archive.add(directory, arcname=directory.name)


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "RELEASE.json").read_text())
    expected = {row["file"]: row for row in manifest["artifacts"]}
    expected["RELEASE.json"] = None
    checksums = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        if Path(name).name != name or name in checksums:
            raise ValueError(f"Invalid checksum entry: {name}")
        checksums[name] = checksum
    if set(checksums) != set(expected):
        raise ValueError("Checksums do not cover exactly the release manifest and artifacts")
    for name, checksum in checksums.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or digest(path) != checksum:
            raise ValueError(f"Checksum mismatch or missing artifact: {name}")
        row = expected[name]
        if row and (row["sha256"] != checksum or row["bytes"] != path.stat().st_size):
            raise ValueError(f"Manifest mismatch: {name}")
    return manifest


def check_payload(archive):
    with tarfile.open(archive) as bundle:
        names = {str(Path(member.name).relative_to(Path(member.name).parts[0]))
                 for member in bundle.getmembers()}
        required = {"tidelight.sh", "LICENSE", "LICENSE.txt", "THIRD_PARTY_NOTICES.md",
                    "DEPENDENCIES.json", "game/script.rpy", "game/story.rpy", "game/content.json",
                    "game/relations.rules.json", "game/relations.duckdb.rules.json",
                    "game/release.json", "game/fonts/tidelight.otf", "game/fonts/OFL.txt",
                    "game/python-packages/renpy_relations.py", "lib/py3-linux-x86_64/python"}
        if not required <= names:
            raise ValueError(f"Game archive is missing: {sorted(required - names)}")
        forbidden = [name for name in names if name.startswith(("game/saves/", "game/cache/"))
                     or Path(name).name.startswith("testcases") or name.endswith(".rpa")]
        if forbidden:
            raise ValueError(f"Development files or archives in playable release: {forbidden}")
        if not any(name.startswith("game/python-packages/_duckdb") and name.endswith(".so") for name in names):
            raise ValueError("DuckDB native extension missing from game archive")
        if not any(name.startswith("game/python-packages/pysqlite3/") and name.endswith(".so") for name in names):
            raise ValueError("SQLite native extension missing from game archive")


def build(sdk, output):
    sdk, output = Path(sdk).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Output must not exist; previous release artifacts are never overwritten")
    if not (sdk / "renpy.sh").is_file():
        raise ValueError("Expected a Linux Ren'Py SDK containing renpy.sh")
    sdk_report = subprocess.check_output([str(sdk / "renpy.sh"), "--version"], text=True).strip()
    if SDK_VERSION not in sdk_report:
        raise ValueError(f"Release is pinned to Ren'Py {SDK_VERSION}; got {sdk_report}")
    output.mkdir(parents=True)
    logs = output / "logs"
    logs.mkdir()
    version = project_version()
    environment = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_VIDEODRIVER="x11",
                       LIBGL_ALWAYS_SOFTWARE="1")
    uv = ["uv", "run", "--locked", "--extra", "duckdb", "--group", "renpy-linux", "--group", "assets"]
    with tempfile.TemporaryDirectory(prefix="relations-release-") as work:
        work = Path(work)
        source = work / f"renpy-relations-{version}"
        commit, source_hashes = clean_source(source)
        source_archive = output / f"renpy-relations-{version}-source.tar.gz"
        archive_directory(source, source_archive)
        # Test the extracted archive, rather than the working copy used to create it.
        extracted = work / "source-check"
        extracted.mkdir()
        with tarfile.open(source_archive) as archive:
            archive.extractall(extracted, filter="data")
        source = extracted / source.name
        checked(uv + ["pytest", "-q"], cwd=source, log=logs / "source-tests.log")
        source_tests = read_test_evidence(logs / "source-tests.log")
        engine_runs = []
        for name in ("palace", "tidelight"):
            staged = work / name
            expected_cases = len(re.findall(r"^    testcase ",
                (source / "examples" / name / "game/testcases.rpy").read_text(), re.MULTILINE))
            checked(uv + ["python", "prepare_game.py", "--game", source / "examples" / name,
                          "--out", staged, "--backend", "duckdb", "--sdk", sdk],
                    cwd=source, log=logs / f"{name}-install.log")
            checked([sdk / "renpy.sh", staged, "lint"], log=logs / f"{name}-lint.log", environment=environment)
            for backend in ("sqlite", "duckdb"):
                for mode in ("cached", "live", "materialized"):
                    checked(uv + ["python", "check_renpy.py", "--sdk", sdk, "--game", staged,
                                  "--headless", "--backend", backend, "--mode", mode, "--timeout", "180"],
                            cwd=source, log=logs / f"{name}-{backend}-{mode}.log")
                    engine_runs.append({"game": name, "backend": backend, "mode": mode,
                                        "cases": read_test_evidence(logs / f"{name}-{backend}-{mode}.log", engine=True,
                                                                    expected=expected_cases)})
        staged = work / "tidelight"
        runtime_archive = output / f"renpy-relations-{version}-linux-x86_64-runtime.zip"
        with zipfile.ZipFile(runtime_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            prefix = f"renpy-relations-{version}-runtime"
            for path in sorted((staged / "game/python-packages").rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, f"{prefix}/{path.relative_to(staged)}")
            for name in ("LICENSE", "DEPENDENCIES.json", "runtime-requirements.txt"):
                archive.write(staged / name, f"{prefix}/{name}")
            archive.writestr(f"{prefix}/INSTALL.md", "# Ren’Py Relations runtime\n\n"
                            "Copy the contents of game/python-packages into your game's matching directory.\n"
                            "This bundle targets Linux x86_64 / CPython 3.12 and includes both database drivers.\n"
                            "Compile your rules with compile_rules.py from the source archive; place the JSON in game/.\n"
                            "See QUICKSTART.md in the source archive for a complete integration example.\n"
                            "Keep LICENSE and the dependency license files listed in DEPENDENCIES.json.\n")
        (staged / "game/release.json").write_text(json.dumps({"version": version, "commit": commit}) + "\n")
        (staged / "game/build.rpy").write_text(f'''init python:
    build.name = "tidelight"
    build.directory_name = "tidelight-{version}"
    build.executable_name = "tidelight"
    build.include_i686 = False
    build.classify("game/testcases*", None)
    build.classify("game/cache/**", None)
    build.classify("game/saves/**", None)
    build.classify("**/__pycache__/**", None)
    build.classify("game/python-packages/**", "linux")
    build.classify("game/**", "all")
''')
        (staged / "PLAY.md").write_text("# 潮汐替我们保管\n\n运行 `./tidelight.sh` 开始游戏。\n"
                                          "默认 SQLite；运行 `RELATIONS_BACKEND=duckdb ./tidelight.sh` 切换后端。\n"
                                          "存档目录按后端隔离；首次切换后请开始新游戏。\n"
                                          "这是文字演出版，包含三位成年女主角与五个结局。\n")
        checked(["xvfb-run", "-a", sdk / "renpy.sh", "launcher", "distribute", staged,
                 "--package", "linux", "--no-update", "--destination", output],
                log=logs / "build-game.log", environment=environment)
        game_archive = output / f"tidelight-{version}-linux.tar.bz2"
        check_payload(game_archive)
        installed = work / "installed-game"
        installed.mkdir()
        with tarfile.open(game_archive) as archive:
            archive.extractall(installed, filter="data")
        playable = installed / f"tidelight-{version}-linux"
        if not playable.is_dir():
            candidates = [p for p in installed.iterdir() if p.is_dir()]
            if len(candidates) != 1:
                raise ValueError("Unexpected playable archive layout")
            playable = candidates[0]
        # Inject tests only into this disposable extracted copy, after checking
        # that the downloadable archive excludes them. Use its own bundled engine.
        testcases = (source / "examples/tidelight/game/testcases.rpy").read_text()
        packaged_cases = len(re.findall(r"^    testcase ", testcases, re.MULTILINE))
        testcases = testcases.replace("    before testcase:\n", "    before testcase:\n"
            "        assert eval not config.developer\n"
            "        assert eval os.path.realpath(sys.modules['renpy_relations'].__file__) == "
            "os.path.realpath(os.path.join(config.gamedir, 'python-packages', 'renpy_relations.py'))\n", 1)
        (playable / "game/testcases.rpy").write_text(testcases)
        for backend in ("sqlite", "duckdb"):
            checked(uv + ["python", "check_renpy.py", "--launcher", playable / "tidelight.sh",
                          "--game", playable, "--headless", "--backend", backend, "--timeout", "180"],
                    cwd=source, log=logs / f"packaged-{backend}.log")
            engine_runs.append({"game": "packaged-tidelight", "backend": backend, "mode": "cached",
                                "cases": read_test_evidence(logs / f"packaged-{backend}.log", engine=True,
                                                            expected=packaged_cases)})
        artifacts = [source_archive, runtime_archive, game_archive]
        manifest = {"version": version, "commit": commit, "built_at": datetime.now(timezone.utc).isoformat(),
                    "sdk": sdk_report, "uv": subprocess.check_output(["uv", "--version"], text=True).strip(),
                    "platform": "linux-x86_64", "python": "3.12",
                    "source_files": source_hashes,
                    "checks": {"source_pytest_passed": source_tests, "engine_runs": engine_runs,
                               "packaged_engine": "own bundled engine, developer=False"},
                    "artifacts": [{"file": p.name, "bytes": p.stat().st_size, "sha256": digest(p)} for p in artifacts]}
        manifest_path = output / "RELEASE.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        (output / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in artifacts + [manifest_path]))
    verify(output)
    print(f"Release verified: {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--sdk", type=Path, required=True)
    builder.add_argument("--out", type=Path, required=True)
    verifier = commands.add_parser("verify")
    verifier.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args.sdk, args.out)
        else:
            manifest = verify(args.directory)
            print(f"Verified {manifest['version']}: {len(manifest['artifacts'])} artifacts")
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Release failed: {exc}\n")


if __name__ == "__main__":
    main()
