"""Compatibility entry point for existing Ren’Py Relations games.

General Python applications should import LogicDB from relation_rules.
"""

from relation_rules import RuleError, RuleSet
from relation_rules.renpy import RenpyLogicDB as LogicDB
from relation_rules.runtime import sqlite3

__all__ = ["LogicDB", "RuleError", "RuleSet"]
