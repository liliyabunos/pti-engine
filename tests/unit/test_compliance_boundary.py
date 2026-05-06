from __future__ import annotations

"""
Compliance Boundary v1 — Public Export Policy Tests
FragranceIndex.ai / FTI Market Terminal

These tests verify that:
1. The policy file exists and is structurally valid.
2. Required allowed and denied fields are present in the policy.
3. Public API schema models do NOT expose denied fields.
4. The compliance check utilities work correctly.
5. Public-safe view SQL definitions do not reference denied columns.
6. No raw content body, personal identifiers, or subscriber lists appear
   in public-facing schema field names.

Tests run with no database required — pure static analysis of schemas
and the policy YAML.
"""

import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
POLICY_PATH = REPO_ROOT / "config" / "public_export_policy.yaml"
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "032_add_public_safe_views.py"


def _policy() -> dict:
    with open(POLICY_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _denied_fields() -> frozenset[str]:
    return frozenset(_policy()["public_export"]["denied_fields"])


def _allowed_fields() -> frozenset[str]:
    return frozenset(_policy()["public_export"]["allowed_fields"])


# ---------------------------------------------------------------------------
# 1. Policy file structure
# ---------------------------------------------------------------------------


class TestPolicyFileStructure:
    def test_policy_file_exists(self):
        assert POLICY_PATH.exists(), (
            f"Public export policy not found at {POLICY_PATH}. "
            "Run: create config/public_export_policy.yaml"
        )

    def test_policy_loads_as_yaml(self):
        data = _policy()
        assert isinstance(data, dict)

    def test_policy_has_version(self):
        data = _policy()
        assert "version" in data
        assert data["version"] == "1"

    def test_policy_has_public_export_section(self):
        data = _policy()
        assert "public_export" in data
        assert "allowed_fields" in data["public_export"]
        assert "denied_fields" in data["public_export"]

    def test_allowed_fields_is_nonempty_list(self):
        allowed = _allowed_fields()
        assert len(allowed) > 10, "Expected at least 10 allowed fields"

    def test_denied_fields_is_nonempty_list(self):
        denied = _denied_fields()
        assert len(denied) > 5, "Expected at least 6 denied fields"

    def test_no_field_is_both_allowed_and_denied(self):
        overlap = _allowed_fields() & _denied_fields()
        assert overlap == set(), (
            f"Fields appear in both allowed and denied lists: {overlap}"
        )

    def test_policy_has_retention_section(self):
        data = _policy()
        assert "retention" in data

    def test_policy_has_product_boundary_section(self):
        data = _policy()
        assert "product_boundary" in data


# ---------------------------------------------------------------------------
# 2. Required field coverage
# ---------------------------------------------------------------------------


class TestRequiredPolicyCoverage:
    """Verify that the specific fields called out in the compliance spec
    are present in the appropriate allow/deny list."""

    REQUIRED_ALLOWED = {
        "entity_type",
        "entity_id",
        "canonical_name",
        "brand_name",
        "signal_type",
        "signal_date",
        "mention_count",
        "source_url",
        "title",
    }

    REQUIRED_DENIED = {
        "raw_comment_text",
        "full_post_body",
        "username_as_product",
        "follower_list",
        "subscriber_list",
        "email",
        "phone",
        "private_message",
        "precise_location",
        "sensitive_inference",
        "contact_enrichment",
        "people_scoring",
        "raw_platform_dataset_export",
        # Internal ingestion fields
        "text_content",
        "raw_payload_ref",
        "mentions_raw_json",
        "source_account_id",
        "author_id",
    }

    def test_required_allowed_fields_present(self):
        allowed = _allowed_fields()
        missing = self.REQUIRED_ALLOWED - allowed
        assert not missing, (
            f"Required allowed fields missing from policy: {missing}"
        )

    def test_required_denied_fields_present(self):
        denied = _denied_fields()
        missing = self.REQUIRED_DENIED - denied
        assert not missing, (
            f"Required denied fields missing from policy: {missing}"
        )


# ---------------------------------------------------------------------------
# 3. Public API schema compliance
# ---------------------------------------------------------------------------


class TestPublicSchemaCompliance:
    """Verify that public-facing Pydantic schema models do not expose
    denied fields. These schemas drive the Dashboard, Screener, and
    Entity pages — the primary customer-facing surfaces.

    Checks field NAMES only — no DB or HTTP required.
    """

    def _get_model_fields(self, model_class) -> set[str]:
        return set(model_class.model_fields.keys())

    def test_entity_summary_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.entity import EntitySummary
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(EntitySummary)
        ok, violations = check_fields_compliant(fields, context="EntitySummary")
        assert ok, (
            f"EntitySummary exposes denied fields: {violations}. "
            "Remove or rename these fields to comply with the public export policy."
        )

    def test_snapshot_row_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.entity import SnapshotRow
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(SnapshotRow)
        ok, violations = check_fields_compliant(fields, context="SnapshotRow")
        assert ok, f"SnapshotRow exposes denied fields: {violations}"

    def test_signal_row_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.entity import SignalRow
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(SignalRow)
        ok, violations = check_fields_compliant(fields, context="SignalRow")
        assert ok, f"SignalRow exposes denied fields: {violations}"

    def test_driver_row_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.entity import DriverRow
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(DriverRow)
        ok, violations = check_fields_compliant(fields, context="DriverRow")
        assert ok, f"DriverRow exposes denied fields: {violations}"

    def test_dashboard_kpis_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.dashboard import DashboardKPIs
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(DashboardKPIs)
        ok, violations = check_fields_compliant(fields, context="DashboardKPIs")
        assert ok, f"DashboardKPIs exposes denied fields: {violations}"

    def test_top_mover_row_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.dashboard import TopMoverRow
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(TopMoverRow)
        ok, violations = check_fields_compliant(fields, context="TopMoverRow")
        assert ok, f"TopMoverRow exposes denied fields: {violations}"

    def test_creator_row_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.creators import CreatorRow
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(CreatorRow)
        ok, violations = check_fields_compliant(fields, context="CreatorRow")
        assert ok, f"CreatorRow exposes denied fields: {violations}"

    def test_top_creator_row_schema_compliant(self):
        from perfume_trend_sdk.api.schemas.creators import TopCreatorRow
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(TopCreatorRow)
        ok, violations = check_fields_compliant(fields, context="TopCreatorRow")
        assert ok, f"TopCreatorRow exposes denied fields: {violations}"

    def test_creator_profile_response_compliant(self):
        """CreatorProfileResponse exposes creator_handle (allowed as attribution).
        It must NOT expose raw subscriber lists, emails, phones, or raw content."""
        from perfume_trend_sdk.api.schemas.creators import CreatorProfileResponse
        from perfume_trend_sdk.compliance import check_fields_compliant

        fields = self._get_model_fields(CreatorProfileResponse)
        ok, violations = check_fields_compliant(fields, context="CreatorProfileResponse")
        assert ok, f"CreatorProfileResponse exposes denied fields: {violations}"

    def test_recent_mention_row_does_not_expose_author_id(self):
        """RecentMentionRow may include author_name for content attribution
        but must not expose author_id (internal platform UID)."""
        from perfume_trend_sdk.api.schemas.entity import RecentMentionRow

        fields = set(RecentMentionRow.model_fields.keys())
        assert "author_id" not in fields, (
            "RecentMentionRow must not expose author_id (internal platform UID). "
            "Remove this field from the schema."
        )

    def test_no_public_schema_exposes_raw_text_content(self):
        """No public schema may have a field named text_content, caption,
        raw_text, full_post_body, or raw_comment_text."""
        from perfume_trend_sdk.api.schemas import entity, dashboard, creators

        raw_text_fields = {
            "text_content", "caption", "raw_text",
            "full_post_body", "raw_comment_text", "body_text",
        }

        schema_classes = [
            entity.EntitySummary,
            entity.SnapshotRow,
            entity.SignalRow,
            entity.RecentMentionRow,
            entity.DriverRow,
            dashboard.DashboardKPIs,
            dashboard.TopMoverRow,
            creators.CreatorRow,
            creators.CreatorProfileResponse,
            creators.TopCreatorRow,
        ]

        for cls in schema_classes:
            fields = set(cls.model_fields.keys())
            exposed = fields & raw_text_fields
            assert not exposed, (
                f"{cls.__name__} exposes raw text fields: {exposed}. "
                "Raw content body must never appear in public schemas."
            )

    def test_no_public_schema_exposes_contact_data(self):
        """No public schema may expose email, phone, or private_message."""
        from perfume_trend_sdk.api.schemas import entity, dashboard, creators

        contact_fields = {"email", "phone", "private_message", "direct_message"}

        schema_classes = [
            entity.EntitySummary,
            entity.SnapshotRow,
            entity.SignalRow,
            entity.RecentMentionRow,
            entity.DriverRow,
            dashboard.DashboardKPIs,
            dashboard.TopMoverRow,
            creators.CreatorRow,
            creators.CreatorProfileResponse,
            creators.TopCreatorRow,
        ]

        for cls in schema_classes:
            fields = set(cls.model_fields.keys())
            exposed = fields & contact_fields
            assert not exposed, (
                f"{cls.__name__} exposes contact data fields: {exposed}. "
                "Contact data must never appear in public schemas."
            )


# ---------------------------------------------------------------------------
# 4. Compliance utility correctness
# ---------------------------------------------------------------------------


class TestComplianceUtilities:
    def test_check_fields_compliant_passes_clean_fields(self):
        from perfume_trend_sdk.compliance import check_fields_compliant

        clean = ["entity_id", "canonical_name", "trend_score", "signal_type"]
        ok, violations = check_fields_compliant(clean)
        assert ok
        assert violations == []

    def test_check_fields_compliant_catches_denied_field(self):
        from perfume_trend_sdk.compliance import check_fields_compliant

        dirty = ["entity_id", "canonical_name", "email", "text_content"]
        ok, violations = check_fields_compliant(dirty)
        assert not ok
        assert "email" in violations
        assert "text_content" in violations

    def test_check_fields_compliant_raise_on_violation(self):
        from perfume_trend_sdk.compliance import check_fields_compliant, ComplianceViolation

        with pytest.raises(ComplianceViolation) as exc_info:
            check_fields_compliant(
                ["entity_id", "raw_comment_text"],
                context="TestEndpoint",
                raise_on_violation=True,
            )
        assert "raw_comment_text" in str(exc_info.value)
        assert "TestEndpoint" in str(exc_info.value)

    def test_compliance_violation_carries_field_list(self):
        from perfume_trend_sdk.compliance import ComplianceViolation

        exc = ComplianceViolation(["email", "phone"], context="SomeAPI")
        assert exc.violations == ["email", "phone"]
        assert exc.context == "SomeAPI"

    def test_get_denied_fields_returns_frozenset(self):
        from perfume_trend_sdk.compliance import get_denied_fields

        denied = get_denied_fields()
        assert isinstance(denied, frozenset)
        assert len(denied) > 0

    def test_get_allowed_fields_returns_frozenset(self):
        from perfume_trend_sdk.compliance import get_allowed_fields

        allowed = get_allowed_fields()
        assert isinstance(allowed, frozenset)
        assert len(allowed) > 0


# ---------------------------------------------------------------------------
# 5. Public-safe view SQL analysis
# ---------------------------------------------------------------------------


class TestPublicSafeViewSQL:
    """Verify the view definitions in the migration file do not reference
    denied columns. Static analysis — no DB required."""

    DENIED_COLUMN_PATTERNS = [
        r"\btext_content\b",
        r"\bcaption\b",
        r"\braw_text\b",
        r"\braw_payload_ref\b",
        r"\bmentions_raw_json\b",
        r"\bhashtags_json\b",
        r"\bmedia_metadata_json\b",
        r"\bsource_account_id\b",
        r"\bsource_account_handle\b",
        r"\bauthor_id\b",
        r"\bauthor_name\b",
        r"\bemail\b",
        r"\bphone\b",
    ]

    def _get_migration_sql(self) -> str:
        assert MIGRATION_PATH.exists(), (
            f"Migration 032 not found at {MIGRATION_PATH}"
        )
        return MIGRATION_PATH.read_text(encoding="utf-8")

    def _extract_view_sql(self, migration_text: str) -> str:
        """Extract the SQL from the _PUBLIC_SAFE_* variable string literals."""
        # Match the string bodies of the _PUBLIC_SAFE_* variables only
        pattern = re.compile(
            r'_PUBLIC_SAFE_\w+\s*=\s*"""(.*?)"""',
            re.DOTALL,
        )
        matches = pattern.findall(migration_text)
        return "\n".join(matches)

    def test_migration_file_exists(self):
        assert MIGRATION_PATH.exists(), f"Migration 032 not found at {MIGRATION_PATH}"

    def test_public_safe_entity_snapshots_view_defined(self):
        sql = self._get_migration_sql()
        assert "public_safe_entity_snapshots" in sql

    def test_public_safe_signals_view_defined(self):
        sql = self._get_migration_sql()
        assert "public_safe_signals" in sql

    def test_public_safe_content_items_view_defined(self):
        sql = self._get_migration_sql()
        assert "public_safe_content_items" in sql

    def test_view_sql_does_not_select_text_content(self):
        """text_content must not appear in SELECT lists of public-safe views.
        It may appear in EXPLICITLY EXCLUDED comments, which we verify separately."""
        migration = self._get_migration_sql()
        view_sql = self._extract_view_sql(migration)

        # Remove comment lines before checking SELECT
        select_lines = [
            line for line in view_sql.splitlines()
            if not line.strip().startswith("--")
        ]
        active_sql = "\n".join(select_lines)

        assert not re.search(r"\bcci\.text_content\b", active_sql), (
            "public_safe_content_items must NOT select text_content. "
            "Raw body text is for extraction only, not public export."
        )

    def test_view_sql_does_not_select_source_account_handle(self):
        migration = self._get_migration_sql()
        view_sql = self._extract_view_sql(migration)
        active_lines = [
            l for l in view_sql.splitlines()
            if not l.strip().startswith("--")
        ]
        active_sql = "\n".join(active_lines)

        assert not re.search(r"\bcci\.source_account_handle\b", active_sql), (
            "public_safe_content_items must NOT select source_account_handle. "
            "Raw ingestion handles are not for public export."
        )

    def test_view_sql_does_not_select_author_id(self):
        """Verify that no SELECT expression references author_id in the view SQL.
        author_id may appear in docstrings/comments listing excluded fields,
        but must not appear in active (non-comment) SELECT lines."""
        migration = self._get_migration_sql()
        view_sql = self._extract_view_sql(migration)
        active_lines = [
            line for line in view_sql.splitlines()
            if not line.strip().startswith("--")
        ]
        active_sql = "\n".join(active_lines)

        # author_id must not appear in any active SELECT clause
        assert not re.search(r"\bauthor_id\b", active_sql), (
            "public-safe views must not SELECT author_id. "
            "It is an internal platform UID excluded from public exports."
        )

    def test_excluded_fields_are_documented_in_view_comments(self):
        """Verify that the excluded fields are called out in SQL comments
        so future developers understand the compliance boundary."""
        migration = self._get_migration_sql()
        required_exclusion_comments = [
            "text_content",
            "source_account_id",
            "source_account_handle",
            "raw_payload_ref",
            "mentions_raw_json",
        ]
        for field in required_exclusion_comments:
            assert field in migration, (
                f"Field '{field}' should be documented as EXPLICITLY EXCLUDED "
                f"in the public_safe_content_items view SQL comment."
            )


# ---------------------------------------------------------------------------
# 6. Retention policy completeness
# ---------------------------------------------------------------------------


class TestRetentionPolicy:
    def test_retention_section_covers_raw_content(self):
        data = _policy()
        retention = data["retention"]
        assert "raw_content" in retention
        raw = retention["raw_content"]
        assert "purpose" in raw
        assert "recommended_retention_days" in raw
        assert int(raw["recommended_retention_days"]) > 0

    def test_retention_raw_content_purpose_mentions_extraction(self):
        data = _policy()
        purpose = data["retention"]["raw_content"]["purpose"].lower()
        assert "extract" in purpose or "resolution" in purpose, (
            "Raw content retention purpose should mention extraction or resolution"
        )

    def test_aggregate_signals_marked_as_product(self):
        data = _policy()
        agg = data["retention"]["aggregate_signals"]
        assert "product" in agg.get("retention", "").lower() or \
               "indefinite" in agg.get("retention", "").lower(), (
            "Aggregate signals should be retained indefinitely as the product"
        )
