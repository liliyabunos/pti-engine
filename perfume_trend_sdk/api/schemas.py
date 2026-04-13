from __future__ import annotations

"""
Backward-compatible shim — all schemas moved to api/schemas/ package.

This file is kept so that any import of
    from perfume_trend_sdk.api.schemas import ...
that targets this file (Python resolves packages before modules, so the
package takes priority) continues to work.
"""

# Python resolves the package (schemas/) before this module (schemas.py)
# when both exist with the same name, so this file is never actually loaded.
# It is kept as documentation only.
