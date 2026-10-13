"""Compile Logica source and relation declarations into a runtime JSON bundle."""

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sys
import tempfile
import time

from renpy_relations import LogicDB, RuleError, RuleSet


def compile_rules(source, schema, output):
    """Build and validate everything before atomically replacing the output."""
    source, schema, output = (Path(p).resolve() for p in (source, schema, output))
    inputs_before = _inputs(source, schema)
    try:
        declarations = json.loads(schema.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RuleError(f"Invalid schema file {schema}: {exc}") from exc
    if not isinstance(declarations, dict) or set(declarations) != {"facts", "derived"}:
        raise RuleError("Schema must contain exactly facts and derived dictionaries")
    if not isinstance(declarations["derived"], dict):
        raise RuleError("derived must be a relation dictionary")
    for name, spec in declarations["derived"].items():
        if not isinstance(spec, dict) or set(spec) != {"columns"}:
            raise RuleError(f"{name}: schema declares only columns; SQL comes from Logica")
    document = {
        "format": "renpy-relations", "version": 1,
        "facts": declarations["facts"],
        "derived": {name: {**spec, "sql": "SELECT 1"}
                    for name, spec in declarations["derived"].items()},
    }
    RuleSet(document)  # Validate declarations before invoking the compiler.
    try:
        compiler_version = version("logica")
    except PackageNotFoundError as exc:
        raise RuleError("Logica is not installed in this Python environment") from exc
    source_bytes = source.read_bytes()
    # Use the pinned compiler's parser and SQL generator. Exported predicates
    # become external relation reads in other exports, instead of being inlined
    # into every query and bypassing their cached/typed relation results.
    from logica.parser_py import parse
    from logica.compiler import universe

    try:
        parsed = parse.ParseFile(source_bytes.decode("utf-8"), import_root=str(source.parent))["rule"]
        heads = {rule["head"]["predicate_name"] for rule in parsed}
        exports = set(document["derived"])
        if exports - heads:
            raise RuleError(f"Exported predicates are not defined: {sorted(exports - heads)}")
        if heads & document["facts"].keys():
            raise RuleError("Facts are external tables and cannot also have rule definitions")
        for name, spec in document["derived"].items():
            definitions = [rule for rule in parsed
                           if rule["head"]["predicate_name"] not in exports - {name}]
            program = universe.LogicaProgram(definitions)
            if program.annotations.Engine() != "sqlite":
                raise RuleError('Rules must declare @Engine("sqlite")')
            spec["sql"] = program.FormattedPredicateSql(name)
    except RuleError:
        raise
    except Exception as exc:
        raise RuleError(f"Logica compilation failed: {exc}") from exc
    document["source"] = {
        "file": source.name,
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "compiler": f"logica {compiler_version}",
        "inputs": {str(Path(p).relative_to(source.parent)) if Path(p).is_relative_to(source.parent)
                   else str(Path(p)): digest for p, digest in inputs_before},
    }
    bundle = RuleSet(document)
    logic = LogicDB(bundle)
    try:
        for name in document["derived"]:
            logic.query(name)
    finally:
        logic.close()
    if _inputs(source, schema) != inputs_before:
        raise RuleError("Source/schema changed during compilation; rebuild to get a consistent bundle")
    content = json.dumps(bundle.document, ensure_ascii=False, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_text(encoding="utf-8") == content:
        return bundle
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return bundle


def _inputs(source, schema):
    """Watch local Logica imports too; external import roots are outside scope."""
    paths = set(source.parent.rglob("*.l")) | {source, schema}
    return tuple((str(p), hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in sorted(paths))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Logica source with @Engine(\"sqlite\")")
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--watch", action="store_true", help="Rebuild when local .l/schema files change")
    args = parser.parse_args(argv)
    source, schema = args.source.resolve(), args.schema.resolve()

    def build():
        try:
            bundle = compile_rules(source, schema, args.output)
            print(f"Built {args.output} ({len(bundle.document['derived'])} derived relations)", flush=True)
            return True
        except (RuleError, OSError) as exc:
            print(f"Build failed: {exc}", file=sys.stderr, flush=True)
            return False

    if not args.watch:
        return 0 if build() else 1
    previous = None
    try:
        while True:
            try:
                current = _inputs(source, schema)
            except OSError as exc:
                current = ("unavailable", str(exc))
            if current != previous:
                build()
                previous = current
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
