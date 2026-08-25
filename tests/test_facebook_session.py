"""Tests for when the guest session checks itself.

The ordering here is the whole point and it is easy to get wrong: a logged-out
check that runs only after the page comes back does not prevent the signed-in
request, it just notices afterwards — and against a live page it does not even
manage that, because Facebook clears a session cookie it rejects, so the jar
comes back empty and the check passes. These use a stub browser, so no network.
"""

from __future__ import annotations

import json

import pytest

from sporhund.facebook.guard import NotLoggedOutError
from sporhund.facebook.session import GuestSession

GUEST = [{"name": "datr", "value": "abc"}]
SIGNED_IN = GUEST + [{"name": "c_user", "value": "100000000000000"}]


class StubPage:
    def __init__(self, log: list[str], html: str) -> None:
        self._log = log
        self._html = html

    async def goto(self, url, **kwargs):
        self._log.append(f"goto {url}")
        return None

    async def content(self) -> str:
        return self._html

    async def close(self) -> None:
        pass


class StubContext:
    """A browser that records what was asked of it, and in what order."""

    def __init__(self, jars: list[list[dict]], html: str = "<html></html>") -> None:
        self._jars = jars
        self._html = html
        self._reads = 0
        self.log: list[str] = []

    async def cookies(self) -> list[dict]:
        # Successive calls can report different jars, which is how the live
        # cookie-cleared-on-rejection behaviour is reproduced.
        self.log.append("cookies")
        jar = self._jars[min(self._reads, len(self._jars) - 1)]
        self._reads += 1
        return jar

    async def new_page(self) -> StubPage:
        return StubPage(self.log, self._html)


def _session(context: StubContext) -> GuestSession:
    session = GuestSession()
    session._context = context
    return session


@pytest.mark.anyio
async def test_no_request_is_made_while_signed_in():
    """The request must never go out, not merely be regretted afterwards."""
    context = StubContext([SIGNED_IN])
    with pytest.raises(NotLoggedOutError):
        await _session(context)._load("https://www.facebook.com/marketplace/oslo/")
    assert not any(entry.startswith("goto") for entry in context.log)


@pytest.mark.anyio
async def test_the_check_runs_before_the_navigation():
    context = StubContext([GUEST])
    await _session(context)._load("https://www.facebook.com/marketplace/oslo/")
    assert context.log[0] == "cookies"
    assert context.log[1].startswith("goto")


@pytest.mark.anyio
async def test_a_cleared_cookie_cannot_hide_a_signed_in_request():
    """Facebook empties a session cookie it rejects, so the jar comes back clean.

    Checking only on the way back would pass here — which is exactly what
    happened against a live page before the check was moved ahead of the load.
    """
    context = StubContext([SIGNED_IN, GUEST])
    with pytest.raises(NotLoggedOutError):
        await _session(context)._load("https://www.facebook.com/marketplace/oslo/")


@pytest.mark.anyio
async def test_a_session_acquired_during_the_load_is_still_caught():
    """The second check earns its keep when the jar was clean on the way out."""
    context = StubContext([GUEST, SIGNED_IN])
    with pytest.raises(NotLoggedOutError):
        await _session(context)._load("https://www.facebook.com/marketplace/oslo/")
    assert any(entry.startswith("goto") for entry in context.log)


@pytest.mark.anyio
async def test_a_search_with_no_matches_is_not_an_error():
    """Zero results is an answer.

    "kjøleskap" in Stavanger genuinely returns nothing on the first page, and
    raising there reported a working source as broken.
    """
    context = StubContext([GUEST], html="<html>no listings here</html>")
    assert await _session(context).search("kjoleskap", "stavanger") == []


@pytest.mark.anyio
async def test_a_search_with_matches_still_returns_them():
    listing = {
        "id": "1",
        "marketplace_listing_title": "Sofa",
        "listing_price": {"formatted_amount": "kr 900", "amount": "900.00"},
    }
    html = (
        '<script type="application/json">'
        + json.dumps({"feed": [listing]})
        + "</script>"
    )
    context = StubContext([GUEST], html=html)
    rows = await _session(context).search("sofa", "oslo")
    assert [r["heading"] for r in rows] == ["Sofa"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
