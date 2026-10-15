"""Embedded relational facts and compiled rules, independent of any game engine."""

from .runtime import LogicDB, RuleError, RuleSet

__all__ = ["LogicDB", "RuleError", "RuleSet"]
