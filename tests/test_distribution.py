"""Exercise the delivered Python package outside its source checkout."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(*command, cwd, **kwargs):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def delivery(tmp_path_factory):
    work = tmp_path_factory.mktemp("python-delivery")
    built = work / "built"
    run("uv", "build", "--out-dir", str(built), cwd=ROOT)
    sdist, = built.glob("*.tar.gz")
    # Rebuild from the sdist: files beside the checkout cannot mask omissions.
    rebuilt = work / "rebuilt"
    run("uv", "build", str(sdist), "--wheel", "--out-dir", str(rebuilt), cwd=work)
    wheel, = rebuilt.glob("*.whl")
    example = work / "example"
    shutil.copytree(ROOT / "examples/python_access", example)
    return work, sdist, wheel, example


def test_distributions_include_core_compatibility_and_licenses(delivery):
    work, sdist, wheel, example = delivery
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert {"relation_rules/__init__.py", "relation_rules/runtime.py",
                "relation_rules/compiler.py", "relation_rules/renpy.py",
                "renpy_relations.py", "compile_rules.py"} <= set(names)
        assert any(name.endswith("/licenses/LICENSE") for name in names)
        assert any(name.endswith("/licenses/THIRD_PARTY_NOTICES.md") for name in names)
        metadata = archive.read(next(name for name in names if name.endswith("/METADATA"))).decode()
        assert 'Requires-Dist: SQLAlchemy==2.0.43' in metadata
        assert 'Provides-Extra: compiler' in metadata
        assert not any(name.startswith(("examples/", "tests/", "benchmarks/")) for name in names)
    with tarfile.open(sdist) as archive:
        assert not any('/.work/' in name or '/python-packages/' in name for name in archive.getnames())
        assert not any(Path(name).name in ('log.txt', 'traceback.txt', 'errors.txt', 'profile.txt')
                       or '/test-results/' in name for name in archive.getnames())
        assert any(name.endswith('/examples/python_access/access.sqlite.rules.json')
                   for name in archive.getnames())


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_installed_runtime_without_engine_or_compiler(delivery, backend):
    work, sdist, wheel, example = delivery
    env = work / backend
    run("uv", "venv", str(env), "--python", sys.executable, cwd=work)
    python = env / "bin/python"
    requirement = str(wheel) + ("[duckdb]" if backend == "duckdb" else "")
    run("uv", "pip", "install", "--python", str(python), requirement, cwd=work)
    probe = '''
import importlib.abc
import importlib.util
import sys
from pathlib import Path
class BlockEngine(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('renpy', 'logica'):
            raise RuntimeError('Unexpected dependency: ' + fullname)
sys.meta_path.insert(0, BlockEngine())
from relation_rules import LogicDB, RuleSet
from renpy_relations import LogicDB as CompatibleDB
assert issubclass(CompatibleDB, LogicDB)
assert not hasattr(LogicDB, 'install_renpy')
assert not hasattr(LogicDB, '_renpy_binding')
assert Path(sys.prefix) in Path(sys.modules['relation_rules'].__file__).parents
for mode in ('cached', 'live', 'materialized'):
    db = LogicDB(sys.argv[1], mode=mode)
    try:
        with db.batch():
            db.add('Member', user='alice', role='editor')
            db.add('RoleAccess', role='editor', resource='drafts')
        assert db.has('CanAccess', user='alice', resource='drafts')
        image = db.snapshot()
        db.add('Revoked', user='alice', resource='drafts')
        assert not db.has('CanAccess', user='alice', resource='drafts')
        db.restore(image)
        assert db.has('CanAccess', user='alice', resource='drafts')
    finally:
        db.close()
print('all modes passed')
'''
    assert run(str(python), "-I", "-c", probe,
               str(example / f"access.{backend}.rules.json"), cwd=work).strip() == "all modes passed"
    # Neither optional compiler nor engine is installed, rather than merely unused.
    run(str(python), "-I", "-c",
        "import importlib.util; assert importlib.util.find_spec('logica') is None; "
        "assert importlib.util.find_spec('renpy') is None", cwd=work)
    if backend == "sqlite":
        run(str(python), "-I", "-c",
            "import importlib.util; assert importlib.util.find_spec('duckdb') is None", cwd=work)
    output = run(str(python), str(example / "main.py"), "--backend", backend, cwd=work)
    assert "Alice after revocation: False" in output
    assert "Alice after restore: True" in output


def test_installed_compiler_command_and_module(delivery):
    work, sdist, wheel, example = delivery
    env = work / "compiler"
    run("uv", "venv", str(env), "--python", sys.executable, cwd=work)
    python = env / "bin/python"
    run("uv", "pip", "install", "--python", str(python), str(wheel) + "[compiler,duckdb]", cwd=work)
    for backend in ("sqlite", "duckdb"):
        output = work / f"compiled-{backend}.json"
        command = ([str(env / "bin/renpy-relations-compile")] if backend == "sqlite" else
                   [str(python), "-I", "-m", "relation_rules.compiler"])
        run(*command, str(example / "world.l"), "--schema", str(example / "schema.json"),
            "--backend", backend, "--output", str(output), cwd=work)
        assert json.loads(output.read_text()) == json.loads(
            (example / f"access.{backend}.rules.json").read_text())
