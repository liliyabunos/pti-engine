from __future__ import annotations

"""
Backward-compatible re-export of all API schemas.

New code should import from perfume_trend_sdk.api.schemas.entity or
perfume_trend_sdk.api.schemas.dashboard directly.
"""

from perfume_trend_sdk.api.schemas.dashboard import (  # noqa: F401
    DashboardResponse,
    ScreenerResponse,
    TopMoverRow,
)
from perfume_trend_sdk.api.schemas.entity import (  # noqa: F401
    EntityDetail,
    EntitySummary,
    MentionRow,
    SignalRow,
    SnapshotRow,
)
