"""Shared test helpers: compile rule documents into sealed runtime RuleSets.

Runtime ``RuleSet`` accepts only bundles that already carry a build-time plan.
Tests that build declarations inline go through :func:`compiled`; tests that
exercise plan tampering keep using the raw ``RuleSet``.
"""

from rule_compiler import compile_document, prepare_rules


def compiled(document):
    """Return a sealed RuleSet with build-time SQL analysis applied."""
    return prepare_rules(document)


def compiled_document(document):
    """Return a rule document carrying dependencies and a sealed plan."""
    return compile_document(document)
