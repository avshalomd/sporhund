"""The opt-in Facebook Marketplace source.

Read as an anonymous visitor only — see `guard.py` for why that is enforced
rather than assumed. Nothing here is imported by the MCP server process; the
browser lives in a separate sidecar (`cli.py`), reached over a subprocess.
"""

from __future__ import annotations

from .guard import (
    AUTH_COOKIE_NAMES,
    NotLoggedOutError,
    assert_logged_out,
    authenticated_cookie_names,
    page_looks_logged_out,
)

__all__ = [
    "AUTH_COOKIE_NAMES",
    "NotLoggedOutError",
    "assert_logged_out",
    "authenticated_cookie_names",
    "page_looks_logged_out",
]
