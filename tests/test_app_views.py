"""Tests for the MCP Apps views — the ones rendered inside the conversation.

The wire format is the fragile part: method names are strings agreed with the
host, and a typo fails silently as a blank frame. These pin them down, and pin
down the registration ordering bug that once dropped two tools from the list.
"""

from __future__ import annotations

import pytest

from sporhund import server
from sporhund.app_ui import (
    IMAGE_HOST,
    LISTING_URI,
    RESULTS_URI,
    listing_view,
    results_view,
)

VIEWS = pytest.mark.parametrize("view", [results_view, listing_view])


@VIEWS
def test_a_view_is_a_complete_standalone_document(view):
    """Unlike an artifact, an iframe view owns its own head and body."""
    html = view()
    assert html.startswith("<!doctype html>")
    for tag in ("<html", "<head>", "<body>", "<title>", 'id="root"'):
        assert tag in html


@VIEWS
def test_a_view_speaks_the_apps_handshake_in_order(view):
    """ui/initialize, then initialized, then the host may send data."""
    html = view()
    assert html.index("ui/initialize") < html.index("ui/notifications/initialized")
    for method in (
        "ui/notifications/tool-input",
        "ui/notifications/tool-result",
        "ui/notifications/size-changed",
        "ui/open-link",
    ):
        assert method in html


@VIEWS
def test_a_view_reaches_no_host_but_finn_and_google_fonts(view):
    """Anything else would need a CSP entry the resource does not declare."""
    import re

    hosts = set(re.findall(r"https://([a-z0-9.-]+)", view()))
    assert hosts <= {"images.finncdn.no", "fonts.googleapis.com", "fonts.gstatic.com",
                     "modelcontextprotocol.io"}


@VIEWS
def test_a_view_asks_the_cdn_for_a_width_it_actually_serves(view):
    from sporhund.finn import CDN_IMAGE_WIDTHS

    html = view()
    assert "snapWidth" in html
    assert str(list(CDN_IMAGE_WIDTHS)) in html or str(CDN_IMAGE_WIDTHS[0]) in html


def test_the_ui_resources_are_registered_and_declare_the_image_host():
    if server._apps is None:
        pytest.skip("this mcp package has no Apps extension")
    by_uri = {str(b.resource.uri): b.resource for b in server._apps.resources()}
    assert set(by_uri) == {RESULTS_URI, LISTING_URI}
    for resource in by_uri.values():
        assert resource.mime_type == "text/html;profile=mcp-app"
        assert IMAGE_HOST in resource.meta["ui"]["csp"]["resourceDomains"]


@pytest.mark.anyio
async def test_the_ui_bound_tools_are_still_listed_as_tools():
    """Registering a tool on the extension after construction silently dropped
    it from the tool list; these two must always be present."""
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert len(tools) >= 12
    assert tools["search_finn"].meta == {"ui": {"resourceUri": RESULTS_URI}}
    assert tools["get_listing"].meta == {"ui": {"resourceUri": LISTING_URI}}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_every_colour_token_is_defined_on_bare_root():
    """A token defined only under a media query renders unreadable in the
    default 'system' theme — the classic broken-view bug."""
    import re

    from sporhund.app_ui import stylesheet

    css = stylesheet()
    bare = css.split("@media", 1)[0]
    declared = set(re.findall(r"(--[a-z0-9-]+):", bare))
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))
    assert used <= declared, f"only defined in a theme block: {sorted(used - declared)}"
