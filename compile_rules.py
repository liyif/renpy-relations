"""Compatibility CLI for the installed relation_rules compiler."""

from relation_rules.compiler import compile_rules, main

__all__ = ["compile_rules", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
