from __future__ import annotations

"""
Market Reality Verifier — D4 implementation.

Validates market outputs after ingestion + aggregation + signal detection.
Runs database invariant checks, API contract checks, pagination consistency
checks, and signal noise-suppression enforcement.

Returns a structured VerificationResult with passed_checks, failed_checks,
and warnings — suitable for CI gates or post-run reports.

Usage (programmatic):
    from perfume_trend_sdk.verification.market_verifier import MarketVerifier
    result = MarketVerifier(db=session).verify("2026-04-10")

Usage (with API checks):
    from fastapi.testclient import TestClient
    from perfume_trend_sdk.api.main import app
    result = MarketVerifier(db=session, test_client=TestClient(app)).verify("2026-04-10")
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from perfume_trend_sdk.analysis.market_signals.detector import DEFAULT_THRESHOLDS
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.signal import Signal

logger = logging.getLogger(__name__)

_VALID_SIGNAL_TYPES = frozenset({"new_entry", "breakout", "acceleration_spike", "reversal"})

# Required keys in API response shapes
_REQUIRED_DASHBOARD_KEYS = frozenset({
    "generated_at", "total_entities", "top_movers", "recent_signals", "breakouts",
})
_REQUIRED_TOP_MOVER_KEYS = frozenset({
    "rank", "ticker", "canonical_name", "composite_market_score", "momentum",
})
_REQUIRED_SIGNAL_KEYS = frozenset({
    "entity_id", "signal_type", "detected_at", "strength",
})

# Page size used for pagination consistency checks
_PAGINATION_PAGE_SIZE = 5


@dataclass
class VerificationResult:
    """Structured result from a MarketVerifier.verify() run."""

    date: str
    passed_checks: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Structured metrics populated by individual checks (e.g. demo_stats)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return len(self.failed_checks) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "passed": self.passed,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "summary": (
                f"PASS ({len(self.passed_checks)} checks)"
                if self.passed
                else (
                    f"FAIL ({len(self.failed_checks)} failure(s), "
                    f"{len(self.passed_checks)} passed)"
                )
            ),
        }


class MarketVerifier:
    """
    Validates market state for a target date.

    DB checks run directly via the SQLAlchemy session.
    API checks require a starlette TestClient (optional).

    Thresholds default to DEFAULT_THRESHOLDS from detector.py so
    suppression rules stay in sync with the detector.
    """

    def __init__(
        self,
        db: Session,
        thresholds: Optional[Dict[str, float]] = None,
        test_client: Optional[Any] = None,
        allow_demo: bool = False,
    ) -> None:
        self.db = db
        self.t = thresholds if thresholds is not None else dict(DEFAULT_THRESHOLDS)
        self.client = test_client
        self.allow_demo = allow_demo

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def verify(self, target_date: str) -> VerificationResult:
        """Run all checks for target_date and return a VerificationResult."""
        result = VerificationResult(date=target_date)

        # DB-only checks
        self._check_aggregated_rows_exist(result, target_date)
        self._check_metrics_non_negative(result, target_date)
        self._check_no_duplicate_signals(result, target_date)
        self._check_reversal_suppression(result, target_date)
        self._check_breakout_suppression(result, target_date)
        self._check_demo_data_presence(result, target_date)

        # API checks (skipped when no TestClient is provided)
        if self.client is not None:
            self._check_dashboard_schema(result)
            self._check_signals_schema(result)
            self._check_pagination_no_duplicates(result)
            self._check_pagination_stable_ordering(result)
        else:
            result.warnings.append(
                "api_checks_skipped: no test_client provided — "
                "pass test_client=TestClient(app) to enable API checks"
            )

        return result

    # ------------------------------------------------------------------
    # DB checks
    # ------------------------------------------------------------------

    def _check_aggregated_rows_exist(
        self, result: VerificationResult, target_date: str
    ) -> None:
        """entity_timeseries_daily must have at least one row for target_date."""
        try:
            target_date_obj = date.fromisoformat(target_date)
            count = (
                self.db.query(EntityTimeSeriesDaily)
                .filter(EntityTimeSeriesDaily.date == target_date_obj)
                .count()
            )
            if count > 0:
                result.passed_checks.append(
                    f"aggregated_rows_exist: {count} row(s) for {target_date}"
                )
            else:
                result.failed_checks.append(
                    f"aggregated_rows_exist: 0 rows in entity_timeseries_daily "
                    f"for {target_date} — run aggregation job first"
                )
        except Exception as exc:
            result.failed_checks.append(f"aggregated_rows_exist: unexpected error — {exc}")

    def _check_metrics_non_negative(
        self, result: VerificationResult, target_date: str
    ) -> None:
        """mention_count, engagement_sum, composite_market_score must be >= 0."""
        try:
            target_date_obj = date.fromisoformat(target_date)
            rows = (
                self.db.query(EntityTimeSeriesDaily)
                .filter(EntityTimeSeriesDaily.date == target_date_obj)
                .all()
            )
            violations: List[str] = []
            for row in rows:
                if (row.mention_count or 0.0) < 0:
                    violations.append(
                        f"entity_id={row.entity_id} mention_count={row.mention_count}"
                    )
                if (row.engagement_sum or 0.0) < 0:
                    violations.append(
                        f"entity_id={row.entity_id} engagement_sum={row.engagement_sum}"
                    )
                if (row.composite_market_score or 0.0) < 0:
                    violations.append(
                        f"entity_id={row.entity_id} "
                        f"composite_market_score={row.composite_market_score}"
                    )

            if violations:
                result.failed_checks.append(
                    f"metrics_non_negative: {len(violations)} violation(s) — "
                    f"{violations[:3]}"
                )
            else:
                result.passed_checks.append(
                    f"metrics_non_negative: all {len(rows)} row(s) have "
                    f"non-negative core metrics"
                )
        except Exception as exc:
            result.failed_checks.append(
                f"metrics_non_negative: unexpected error — {exc}"
            )

    def _check_no_duplicate_signals(
        self, result: VerificationResult, target_date: str
    ) -> None:
        """No (entity_id, signal_type, detected_at) duplicates for target_date.

        The ORM UniqueConstraint enforces this at write-time, but schema drift
        or direct inserts could create duplicates. Verify explicitly.
        """
        try:
            dupes = (
                self.db.query(
                    Signal.entity_id,
                    Signal.signal_type,
                    Signal.detected_at,
                    func.count().label("cnt"),
                )
                .filter(func.date(Signal.detected_at) == target_date)
                .group_by(Signal.entity_id, Signal.signal_type, Signal.detected_at)
                .having(func.count() > 1)
                .all()
            )
            if dupes:
                result.failed_checks.append(
                    f"no_duplicate_signals: {len(dupes)} duplicate "
                    f"(entity_id, signal_type, detected_at) group(s) for {target_date}"
                )
            else:
                result.passed_checks.append(
                    f"no_duplicate_signals: no duplicate signal rows for {target_date}"
                )
        except Exception as exc:
            result.failed_checks.append(
                f"no_duplicate_signals: unexpected error — {exc}"
            )

    def _check_reversal_suppression(
        self, result: VerificationResult, target_date: str
    ) -> None:
        """Every reversal signal must have mention_count >= reversal_min_mentions."""
        min_mentions = self.t.get("reversal_min_mentions", 2.0)
        try:
            rows = (
                self.db.query(Signal, EntityTimeSeriesDaily)
                .join(
                    EntityTimeSeriesDaily,
                    (Signal.entity_id == EntityTimeSeriesDaily.entity_id)
                    & (func.date(Signal.detected_at) == EntityTimeSeriesDaily.date),
                )
                .filter(
                    Signal.signal_type == "reversal",
                    func.date(Signal.detected_at) == target_date,
                )
                .all()
            )

            violations: List[str] = []
            for sig, snap in rows:
                if (snap.mention_count or 0.0) < min_mentions:
                    violations.append(
                        f"entity_id={sig.entity_id} "
                        f"mention_count={snap.mention_count:.2f} < {min_mentions}"
                    )

            if violations:
                result.failed_checks.append(
                    f"reversal_suppression: {len(violations)} reversal signal(s) fired "
                    f"with mention_count < reversal_min_mentions={min_mentions}: "
                    f"{violations[:3]}"
                )
            elif rows:
                result.passed_checks.append(
                    f"reversal_suppression: all {len(rows)} reversal signal(s) meet "
                    f"mention_count >= {min_mentions}"
                )
            else:
                result.passed_checks.append(
                    f"reversal_suppression: no reversal signals on {target_date}"
                )
        except Exception as exc:
            result.failed_checks.append(
                f"reversal_suppression: unexpected error — {exc}"
            )

    def _check_breakout_suppression(
        self, result: VerificationResult, target_date: str
    ) -> None:
        """Every breakout signal must have mention_count >= breakout_min_mentions."""
        min_mentions = self.t.get("breakout_min_mentions", 2.0)
        try:
            rows = (
                self.db.query(Signal, EntityTimeSeriesDaily)
                .join(
                    EntityTimeSeriesDaily,
                    (Signal.entity_id == EntityTimeSeriesDaily.entity_id)
                    & (func.date(Signal.detected_at) == EntityTimeSeriesDaily.date),
                )
                .filter(
                    Signal.signal_type == "breakout",
                    func.date(Signal.detected_at) == target_date,
                )
                .all()
            )

            violations: List[str] = []
            for sig, snap in rows:
                if (snap.mention_count or 0.0) < min_mentions:
                    violations.append(
                        f"entity_id={sig.entity_id} "
                        f"mention_count={snap.mention_count:.2f} < {min_mentions}"
                    )

            if violations:
                result.failed_checks.append(
                    f"breakout_suppression: {len(violations)} breakout signal(s) fired "
                    f"with mention_count < breakout_min_mentions={min_mentions}: "
                    f"{violations[:3]}"
                )
            elif rows:
                result.passed_checks.append(
                    f"breakout_suppression: all {len(rows)} breakout signal(s) meet "
                    f"mention_count >= {min_mentions}"
                )
            else:
                result.passed_checks.append(
                    f"breakout_suppression: no breakout signals on {target_date}"
                )
        except Exception as exc:
            result.failed_checks.append(
                f"breakout_suppression: unexpected error — {exc}"
            )

    def _check_demo_data_presence(
        self, result: VerificationResult, target_date: str
    ) -> None:
        """
        Detect synthetic/demo content items for target_date.

        Classification (platform-based):
          REAL      — source_platform in ('youtube', 'reddit')
                      Both are live-ingested real sources in V1.
                      YouTube: Data API v3. Reddit: public JSON endpoints.
                      Missing channel metadata on youtube is a quality issue, NOT a synthetic marker.
          SYNTHETIC — source_platform in ('tiktok', 'other') or unknown
                      TikTok: deferred — no production API credentials yet.
                      'other': catch-all for truly uncategorized / legacy synthetic data.

        Sub-warning: youtube items missing channel_id or channel_title are counted
        separately as a data-quality metric (not counted as synthetic).

        Behaviour controlled by self.allow_demo:
          False (default) — FAIL if demo_percentage > 0
          True            — WARN only

        Stores structured demo stats in result.metrics["demo_stats"].
        """
        try:
            rows = self.db.execute(
                text(
                    "SELECT source_platform, media_metadata_json "
                    "FROM canonical_content_items "
                    "WHERE substr(published_at, 1, 10) = :dt"
                ),
                {"dt": target_date},
            ).fetchall()
        except Exception as exc:
            result.warnings.append(
                f"demo_data_presence: cannot query canonical_content_items — {exc}"
            )
            return

        if not rows:
            result.warnings.append(
                f"demo_data_presence: no canonical_content_items found for "
                f"{target_date} — run ingestion first"
            )
            return

        total = len(rows)
        # Counters: real (youtube) and demo (other platforms)
        real_count = 0
        real_channels: set = set()
        demo_by_platform: Dict[str, int] = {}
        # Quality sub-counter: youtube items missing channel metadata
        yt_missing_channel_meta = 0

        for platform, meta_raw in rows:
            meta: Dict[str, Any] = {}
            if meta_raw:
                try:
                    meta = json.loads(meta_raw)
                except (ValueError, TypeError):
                    pass

            # Platform-based classification: youtube + reddit = real (V1 live sources)
            is_real = platform in ("youtube", "reddit")

            if is_real:
                real_count += 1
                channel_title = meta.get("channel_title")
                if channel_title:
                    real_channels.add(channel_title)
                if not meta.get("channel_id") or not channel_title:
                    yt_missing_channel_meta += 1
            else:
                label = platform if platform else "unknown"
                demo_by_platform[label] = demo_by_platform.get(label, 0) + 1

        demo_count = total - real_count
        demo_pct = round(demo_count / total * 100, 1) if total else 0.0
        real_pct = round(real_count / total * 100, 1) if total else 0.0

        breakdown_str = ", ".join(
            f"{k}={v}" for k, v in sorted(demo_by_platform.items())
        )

        # Store structured data in metrics
        result.metrics["demo_stats"] = {
            "total_items": total,
            "real_items": real_count,
            "demo_items": demo_count,
            "demo_percentage": demo_pct,
            "real_percentage": real_pct,
            "real_channels_count": len(real_channels),
            "demo_by_platform": dict(sorted(demo_by_platform.items())),
            "yt_missing_channel_meta": yt_missing_channel_meta,
        }

        msg = (
            f"demo_data_presence: {demo_pct}% demo ({demo_count}/{total} items) | "
            f"real={real_count} ({real_pct}%, {len(real_channels)} channels) | "
            f"demo breakdown: [{breakdown_str}]"
        )

        if demo_count == 0:
            result.passed_checks.append(
                f"demo_data_presence: 100% real data ({real_count} items, "
                f"{len(real_channels)} channels) — no synthetic content"
            )
        elif self.allow_demo:
            result.warnings.append(msg)
        else:
            result.failed_checks.append(msg)

        # Sub-warning: youtube items missing channel metadata (quality, not synthetic)
        if yt_missing_channel_meta > 0:
            result.warnings.append(
                f"demo_data_presence: {yt_missing_channel_meta} youtube item(s) missing "
                f"channel_id or channel_title — quality gap, not synthetic"
            )

    # ------------------------------------------------------------------
    # API checks
    # ------------------------------------------------------------------

    def _check_dashboard_schema(self, result: VerificationResult) -> None:
        """GET /api/v1/dashboard must return 200 with required keys and non-empty top_movers."""
        try:
            r = self.client.get("/api/v1/dashboard")
            if r.status_code != 200:
                result.failed_checks.append(
                    f"dashboard_schema: HTTP {r.status_code} (expected 200)"
                )
                return

            data = r.json()
            missing = _REQUIRED_DASHBOARD_KEYS - set(data.keys())
            if missing:
                result.failed_checks.append(
                    f"dashboard_schema: missing top-level keys: {sorted(missing)}"
                )
                return

            if not data.get("top_movers"):
                result.failed_checks.append(
                    "dashboard_schema: top_movers is empty — "
                    "no aggregated data available for the latest date"
                )
                return

            mover = data["top_movers"][0]
            missing_mover = _REQUIRED_TOP_MOVER_KEYS - set(mover.keys())
            if missing_mover:
                result.failed_checks.append(
                    f"dashboard_schema: top_movers[0] missing keys: "
                    f"{sorted(missing_mover)}"
                )
                return

            result.passed_checks.append(
                f"dashboard_schema: valid — {len(data['top_movers'])} top_movers, "
                f"{len(data['recent_signals'])} recent_signals"
            )
        except Exception as exc:
            result.failed_checks.append(f"dashboard_schema: unexpected error — {exc}")

    def _check_signals_schema(self, result: VerificationResult) -> None:
        """GET /api/v1/signals must return 200 with a list of valid signal rows."""
        try:
            r = self.client.get("/api/v1/signals")
            if r.status_code != 200:
                result.failed_checks.append(
                    f"signals_schema: HTTP {r.status_code} (expected 200)"
                )
                return

            data = r.json()
            if not isinstance(data, list):
                result.failed_checks.append(
                    f"signals_schema: expected list, got {type(data).__name__}"
                )
                return

            if data:
                # Check required keys on first row
                missing = _REQUIRED_SIGNAL_KEYS - set(data[0].keys())
                if missing:
                    result.failed_checks.append(
                        f"signals_schema: signal row missing keys: {sorted(missing)}"
                    )
                    return

                # All signal_type values must be in the known set
                invalid_types = {
                    s["signal_type"]
                    for s in data
                    if s.get("signal_type") not in _VALID_SIGNAL_TYPES
                }
                if invalid_types:
                    result.failed_checks.append(
                        f"signals_schema: unknown signal_type value(s): {invalid_types}"
                    )
                    return

            result.passed_checks.append(
                f"signals_schema: valid — {len(data)} signal(s) in response"
            )
        except Exception as exc:
            result.failed_checks.append(f"signals_schema: unexpected error — {exc}")

    def _check_pagination_no_duplicates(self, result: VerificationResult) -> None:
        """Two consecutive screener pages must not share any entity_id."""
        try:
            n = _PAGINATION_PAGE_SIZE
            r1 = self.client.get(f"/api/v1/screener?limit={n}&offset=0")
            r2 = self.client.get(f"/api/v1/screener?limit={n}&offset={n}")

            if r1.status_code != 200 or r2.status_code != 200:
                result.failed_checks.append(
                    f"pagination_no_duplicates: screener returned HTTP "
                    f"{r1.status_code}/{r2.status_code}"
                )
                return

            rows1 = r1.json().get("rows", [])
            rows2 = r2.json().get("rows", [])
            ids1 = {row["entity_id"] for row in rows1}
            ids2 = {row["entity_id"] for row in rows2}

            if not ids1:
                result.warnings.append(
                    "pagination_no_duplicates: first page returned 0 rows — "
                    "insufficient data to test pagination"
                )
                return

            if not ids2:
                result.warnings.append(
                    f"pagination_no_duplicates: second page (offset={n}) returned "
                    f"0 rows — fewer than {n * 2} total entities"
                )
                result.passed_checks.append(
                    f"pagination_no_duplicates: no overlap (second page empty, "
                    f"{len(ids1)} entities in first page)"
                )
                return

            overlap = ids1 & ids2
            if overlap:
                result.failed_checks.append(
                    f"pagination_no_duplicates: {len(overlap)} entity_id(s) appear "
                    f"in both page 1 and page 2: {sorted(overlap)[:5]}"
                )
            else:
                result.passed_checks.append(
                    f"pagination_no_duplicates: no overlap between page 1 "
                    f"({len(ids1)} rows) and page 2 ({len(ids2)} rows)"
                )
        except Exception as exc:
            result.failed_checks.append(
                f"pagination_no_duplicates: unexpected error — {exc}"
            )

    def _check_pagination_stable_ordering(self, result: VerificationResult) -> None:
        """The same screener request must return the same entity order on repeat calls."""
        try:
            r1 = self.client.get(f"/api/v1/screener?limit={_PAGINATION_PAGE_SIZE}&offset=0")
            r2 = self.client.get(f"/api/v1/screener?limit={_PAGINATION_PAGE_SIZE}&offset=0")

            if r1.status_code != 200 or r2.status_code != 200:
                result.warnings.append(
                    f"pagination_stable_ordering: screener returned HTTP "
                    f"{r1.status_code}/{r2.status_code}"
                )
                return

            ids1 = [row["entity_id"] for row in r1.json().get("rows", [])]
            ids2 = [row["entity_id"] for row in r2.json().get("rows", [])]

            if not ids1:
                result.warnings.append(
                    "pagination_stable_ordering: screener returned 0 rows — "
                    "cannot verify ordering stability"
                )
                return

            if ids1 != ids2:
                result.failed_checks.append(
                    "pagination_stable_ordering: order differs between two identical "
                    "requests — non-deterministic sort"
                )
            else:
                result.passed_checks.append(
                    f"pagination_stable_ordering: consistent ordering across two "
                    f"identical requests ({len(ids1)} rows)"
                )
        except Exception as exc:
            result.failed_checks.append(
                f"pagination_stable_ordering: unexpected error — {exc}"
            )
