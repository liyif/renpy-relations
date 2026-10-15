"""Create a self-contained Ren'Py project with locked Linux/Python 3.12 dependencies."""

import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
PLATFORM = "x86_64-manylinux_2_28"


def project_version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def inventory(packages):
    result = []
    for distribution in metadata.distributions(path=[str(packages)]):
        files = distribution.files or []
        licenses = sorted(str(p) for p in files if
                          p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")))
        if not licenses or not all((packages / p).is_file() for p in licenses):
            raise ValueError(f"Missing license files for {distribution.metadata['Name']}")
        result.append({"name": distribution.metadata["Name"], "version": distribution.version,
                       "licenses": licenses})
    if not result:
        raise ValueError("No installed runtime dependencies found")
    return sorted(result, key=lambda p: p["name"].lower())


def staged_readme(text, source_game):
    """Keep game-local links; name source-only files without broken links."""
    def replace(match):
        label, href = match.groups()
        url = urlsplit(href)
        if url.scheme or url.netloc or not url.path:
            return match.group(0)
        target = (source_game / unquote(url.path)).resolve()
        if target.is_relative_to(source_game) or not target.is_relative_to(ROOT):
            return match.group(0)
        source_path = target.relative_to(ROOT).as_posix()
        return f"{label} (`{source_path}` in the source archive)"
    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^\s)]+)\)", replace, text)


def prepare(game, output, *, backend="sqlite", sdk=None):
    game, output = Path(game).resolve(), Path(output).absolute()
    if not (game / "game").is_dir():
        raise ValueError("Source project must contain game/")
    if output.is_symlink() or output.exists():
        raise ValueError("Output must not already exist; choose a new directory")
    if output.resolve().is_relative_to(game) or game.is_relative_to(output.resolve()):
        raise ValueError("Source and output must not contain each other")
    if backend not in ("sqlite", "duckdb"):
        raise ValueError("Backend must be sqlite or duckdb")
    if sdk is not None:
        sdk = Path(sdk).resolve()
        interpreter = sdk / "lib/py3-linux-x86_64/python"
        info = subprocess.check_output([str(interpreter), "-c",
                                       "import sys; print('%d.%d' % sys.version_info[:2])"], text=True).strip()
        if info != "3.12":
            raise ValueError("This release installer targets a Linux x86_64 Python 3.12 SDK")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Work beside the destination and publish only after installation succeeds.
    with tempfile.TemporaryDirectory(prefix=".relations-stage-", dir=output.parent) as temporary:
        staging = Path(temporary) / "project"
        staging.mkdir()
        shutil.copytree(game / "game", staging / "game", ignore=shutil.ignore_patterns(
            "python-packages", "cache", "saves", "__pycache__", "*.rpyc", "*.pyc", "release.json"))
        for name in ("README.md", "world.l", "schema.json", "build_font.py"):
            if (game / name).is_file():
                shutil.copy2(game / name, staging / name)
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, staging / name)
        notices = staging / "THIRD_PARTY_NOTICES.md"
        font_reference = "game/fonts/README.md" if (staging / "game/fonts/README.md").is_file() else "https://github.com/notofonts/noto-cjk"
        notices.write_text(notices.read_text().replace("examples/tidelight/game/fonts/README.md", font_reference))
        readme = staging / "README.md"
        if readme.is_file():
            readme.write_text(staged_readme(readme.read_text(), game))
        packages = staging / "game/python-packages"
        requirements = staging / "runtime-requirements.txt"
        command = ["uv", "export", "--project", ROOT, "--locked", "--no-dev", "--group", "renpy-linux",
                   "--no-emit-project", "--format", "requirements-txt", "--output-file", requirements]
        if backend == "duckdb":
            command += ["--extra", "duckdb"]
        run(command, stdout=subprocess.DEVNULL)
        run(["uv", "pip", "install", "--python-version", "3.12", "--python-platform", PLATFORM,
             "--only-binary", ":all:", "--require-hashes", "--no-config", "--target", packages,
             "--requirements", requirements])
        shutil.copy2(ROOT / "renpy_relations.py", packages / "renpy_relations.py")
        shutil.copytree(ROOT / "relation_rules", packages / "relation_rules",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (packages / "renpy_relations.LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
        dependencies = inventory(packages)
        (staging / "DEPENDENCIES.json").write_text(json.dumps({
            "version": project_version(), "platform": PLATFORM, "python": "3.12", "backend": backend,
            "packages": dependencies}, ensure_ascii=False, indent=2) + "\n")
        if sdk is not None:
            # Import the installed module with the SDK interpreter, outside the source tree.
            probe = ("import sys; sys.path.insert(0, sys.argv[1]); "
                     "import renpy_relations; from renpy_relations import LogicDB; "
                     "db=LogicDB(sys.argv[2]); print(renpy_relations.__file__); db.close()")
            rules = "relations.duckdb.rules.json" if backend == "duckdb" else "relations.rules.json"
            run([interpreter, "-I", "-c", probe, packages, staging / "game" / rules], cwd=staging)
        # Recheck to avoid replacing a directory created while installation ran.
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared during installation; refusing to replace it")
        staging.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--backend", choices=("sqlite", "duckdb"), default="sqlite",
                        help="duckdb includes both DuckDB and SQLite drivers")
    parser.add_argument("--sdk", type=Path, help="Also verify imports with this Linux Python 3.12 SDK")
    args = parser.parse_args()
    try:
        output = prepare(args.game, args.out, backend=args.backend, sdk=args.sdk)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Staging failed: {exc}\n")
    print(f"Ready: {output}")


if __name__ == "__main__":
    main()
