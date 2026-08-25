"""The guest browser.

Facebook will not serve Marketplace to a plain HTTP client for long — a handful
of requests without a cookie jar and it starts answering "Sorry, something went
wrong" — so this source needs a real browser engine, which is why it lives out
here in an optional extra rather than in the server's own environment.

Two things about this session matter more than the scraping:

* It runs in a profile directory Sporhund owns, never the user's own browser.
  Their Facebook session is structurally out of reach, not merely unused.
* It asserts it is logged out before reading anything (see `guard.py`).

Playwright is imported lazily, inside the functions that need it, so that the
rest of the package — including the guard and the parser — stays importable
without the extra installed.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from .guard import assert_logged_out, page_looks_logged_out
from .parse import detail_from_html, listings_from_html

SEARCH_URL = "https://www.facebook.com/marketplace/{place}/search"
ITEM_URL = "https://www.facebook.com/marketplace/item/{id}/"

# Facebook rate-limits anonymous browsing hard — reports put it near 30–60 page
# loads an hour per IP, and a plain client of ours was cut off after three. This
# is the same discipline FinnClient uses, set slower because the ceiling is
# lower and the cost of being cut off is a dead source rather than one slow call.
MIN_REQUEST_INTERVAL_S = 4.0

# Most of a Marketplace page's weight is imagery and fonts we never look at.
# Blocking them at the network layer is the single biggest speed win available,
# and it also means far fewer requests per page load.
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


class FacebookError(RuntimeError):
    """Raised when a page could not be fetched or read."""


def profile_dir() -> Path:
    """Sporhund's own browser profile — deliberately not the user's.

    Persisted between runs on purpose: Facebook hands an anonymous visitor a
    `datr` cookie identifying the browser, and throwing that away on every run
    makes each one look like a brand-new stranger, which is exactly the traffic
    its abuse systems act on.
    """
    override = os.environ.get("SPORHUND_FB_PROFILE")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "sporhund" / "browser" / "facebook"


class GuestSession:
    """A logged-out Marketplace session. One browser, reused across queries."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Any = None
        self._context: Any = None
        self._last_request_at = 0.0

    async def __aenter__(self) -> "GuestSession":
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover - needs the extra
            raise FacebookError(
                "The Facebook source needs its optional extra. Install it with: "
                "uv tool install 'sporhund[facebook]' && playwright install chromium"
            ) from exc

        directory = profile_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(directory),
                headless=self._headless,
                user_agent=_DEFAULT_USER_AGENT,
                locale="nb-NO",
                viewport={"width": 1280, "height": 900},
            )
        except Exception as exc:  # pragma: no cover - needs a browser
            await self._shutdown()
            raise FacebookError(
                "Could not start Chromium. If this is a fresh install, run: "
                "playwright install chromium"
            ) from exc

        await self._context.route("**/*", _block_heavy_assets)
        # Check before the first navigation as well as after every one: a
        # persistent profile could in principle arrive already carrying a
        # session, and that must fail before any page is requested.
        await self._assert_guest()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._shutdown()

    async def _shutdown(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _assert_guest(self) -> None:
        assert_logged_out(await self._context.cookies())

    async def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            await asyncio.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()

    async def _load(self, url: str, params: dict[str, str] | None = None) -> str:
        # Before the request, not after. A logged-out check that runs only once
        # the page is back does not prevent anything — the request already went
        # out carrying whatever session cookies the jar held. Worse, it cannot
        # even detect it reliably: Facebook clears a session cookie it rejects,
        # so a jar that held `c_user` on the way out can come back empty. This
        # was verified against a live page, where the after-only check passed
        # while the request had gone out signed in.
        await self._assert_guest()
        await self._pace()
        page = await self._context.new_page()
        try:
            if params:
                from urllib.parse import urlencode

                url = f"{url}?{urlencode(params)}"
            response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if response is not None and response.status >= 400:
                raise FacebookError(
                    f"Facebook returned HTTP {response.status} for {url}. Anonymous "
                    "browsing is rate-limited; wait a while before retrying."
                )
            html = await page.content()
        finally:
            await page.close()

        # Check again on the way back, to catch a session picked up during the
        # load itself. Secondary: the check above is the one that protects.
        await self._assert_guest()
        if page_looks_logged_out(html) is False:
            raise FacebookError(
                "Facebook served a signed-in view. Refusing to read it."
            )
        return html

    async def search(
        self, query: str, place: str = "oslo", limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search Marketplace as an anonymous visitor.

        Only the first server-rendered batch is read — roughly twenty listings.
        Scrolling for more costs extra GraphQL round trips against a tight rate
        limit, and twenty ranked results is what the caller can actually use.
        """
        html = await self._load(
            SEARCH_URL.format(place=place), {"query": query}
        )
        # No matches is an answer, not a failure. Narrow queries in smaller
        # places legitimately come back empty — "kjøleskap" in Stavanger does —
        # and raising there told the caller the source was broken when it was
        # working exactly as it should.
        return listings_from_html(html)[:limit]

    async def listing(self, item_id: str) -> dict[str, Any]:
        """One listing in full, including the seller's description."""
        html = await self._load(ITEM_URL.format(id=item_id))
        # Pass the id through: an item page also carries a strip of unrelated
        # recommendations, and any of those can be the richest object on it.
        detail = detail_from_html(html, item_id)
        if detail is None:
            raise FacebookError(
                f"Could not read listing {item_id}. It may have been removed, or "
                "Facebook may have served a page without it."
            )
        return detail


async def _block_heavy_assets(route: Any, request: Any) -> None:
    if request.resource_type in _BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()
