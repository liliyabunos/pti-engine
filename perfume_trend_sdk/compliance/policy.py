from __future__ import annotations

"""
FragranceIndex.ai Public Export Policy loader and enforcement utilities.

Reads config/public_export_policy.yaml and provides:
- Field allow/deny lookups
- Compliance check for schema field sets
- Runtime violation detection
"""

from pathlib import Path
from typing import Optional

import yaml

# Resolve config path relative to the repo root (two levels above this file:
# perfume_trend_sdk/compliance/ → perfume_trend_sdk/ → repo root)
_REPO_ROOT = Path(__file__).parent.parent.parent
POLICY_PATH = _REPO_ROOT / "config" / "public_export_policy.yaml"


class ComplianceViolation(Exception):
    """Raised when a denied field is found in a public export context."""

    def __init__(self, violations: list[str], context: str = "") -> None:
        self.violations = violations
        self.context = context
        detail = ", ".join(violations)
        msg = f"Compliance violation — denied fields in public export"
        if context:
            msg += f" ({context})"
        msg += f": {detail}"
        super().__init__(msg)


def load_policy() -> dict:
    """Load and return the public export policy as a dict."""
    if not POLICY_PATH.exists():
        raise FileNotFoundError(
            f"Public export policy not found at {POLICY_PATH}. "
            "Ensure config/public_export_policy.yaml is present."
        )
    with open(POLICY_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get_allowed_fields() -> frozenset[str]:
    """Return the set of fields allowed in public exports."""
    policy = load_policy()
    return frozenset(policy["public_export"]["allowed_fields"])


def get_denied_fields() -> frozenset[str]:
    """Return the set of fields denied from public exports."""
    policy = load_policy()
    return frozenset(policy["public_export"]["denied_fields"])


def check_fields_compliant(
    field_names: list[str] | set[str],
    context: str = "",
    raise_on_violation: bool = False,
) -> tuple[bool, list[str]]:
    """
    Check whether all field_names are absent from the denied list.

    Returns:
        (is_compliant: bool, violations: list[str])

    If raise_on_violation is True, raises ComplianceViolation instead of
    returning False.
    """
    denied = get_denied_fields()
    violations = sorted(f for f in field_names if f in denied)
    is_compliant = len(violations) == 0
    if not is_compliant and raise_on_violation:
        raise ComplianceViolation(violations, context=context)
    return is_compliant, violations


def assert_schema_compliant(
    schema_fields: list[str] | set[str],
    schema_name: str = "",
) -> None:
    """
    Assert that none of schema_fields appear in the denied list.
    Raises ComplianceViolation if any denied field is found.

    Usage in tests:
        from perfume_trend_sdk.compliance import assert_schema_compliant
        assert_schema_compliant(MySchema.model_fields.keys(), "MySchema")
    """
    check_fields_compliant(schema_fields, context=schema_name, raise_on_violation=True)


# Public re-export for convenience
assert_schema_compliant = assert_schema_compliant  # noqa: PLW0127 (explicit re-export)
