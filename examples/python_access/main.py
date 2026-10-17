"""Run precompiled access rules in an ordinary synchronous Python program."""

import argparse
from pathlib import Path

from renpy_relations import LogicDB


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sqlite", "duckdb"), default="sqlite")
    args = parser.parse_args()
    rules = Path(__file__).with_name(f"access.{args.backend}.rules.json")
    logic = LogicDB(rules)
    try:
        with logic.batch():
            logic.add("Member", user="alice", role="editor")
            logic.add("RoleAccess", role="editor", resource="drafts")
            logic.add("Sponsored", user="bob", resource="drafts")
        print("Eligible:", sorted(logic.query("CanAccess"), key=lambda row: row["user"]))
        print("Access by resource:", logic.query_sql(
            "SELECT resource, COUNT(*) AS users FROM CanAccess GROUP BY resource ORDER BY resource",
            reads=("CanAccess",),
        ))
        saved = logic.snapshot()
        logic.add("Revoked", user="alice", resource="drafts")
        print("Alice after revocation:", logic.has("CanAccess", user="alice", resource="drafts"))
        logic.restore(saved)
        print("Alice after restore:", logic.has("CanAccess", user="alice", resource="drafts"))
    finally:
        logic.close()


if __name__ == "__main__":
    main()
