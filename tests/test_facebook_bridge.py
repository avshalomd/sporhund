"""Tests for the subprocess bridge and the tools that sit on it.

The Facebook source is absent on most machines, so the behaviour that matters
most is what happens when it is missing: the server must keep working and say
plainly how to switch it on, rather than raising. A stub executable stands in
for the real sidecar so none of this needs a browser.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from sporhund import facebook_source, server


@pytest.fixture
def no_sidecar(monkeypatch, tmp_path):
    """A PATH with no `sporhund-fb` on it."""
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def stub_sidecar(monkeypatch, tmp_path):
    """Install a fake `sporhund-fb` that echoes a canned payload."""

    def install(payload: str, exit_code: int = 0) -> None:
        script = tmp_path / facebook_source.EXECUTABLE
        script.write_text(
            "#!/bin/sh\n"
            f"cat <<'EOF'\n{payload}\nEOF\n"
            f"exit {exit_code}\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    return install


def test_reports_absent_when_not_installed(no_sidecar):
    assert facebook_source.executable_path() is None
    assert facebook_source.installed() is False


@pytest.mark.anyio
async def test_run_raises_a_named_error_when_absent(no_sidecar):
    with pytest.raises(facebook_source.FacebookUnavailable) as excinfo:
        await facebook_source.run("check")
    assert "uv tool install" in str(excinfo.value)


@pytest.mark.anyio
async def test_describe_explains_how_to_enable(no_sidecar):
    state = await facebook_source.describe()
    assert state["installed"] is False
    assert state["opt_in"] is True
    assert "how_to_enable" in state
    assert "150 MB" in state["how_to_enable"]["note"]


@pytest.mark.anyio
async def test_describe_never_raises_on_a_broken_sidecar(stub_sidecar):
    stub_sidecar("this is not json")
    state = await facebook_source.describe()
    assert state["installed"] is True
    assert "error" in state


@pytest.mark.anyio
async def test_run_returns_parsed_json(stub_sidecar):
    stub_sidecar(json.dumps({"count": 2, "listings": [{"id": "1"}, {"id": "2"}]}))
    payload = await facebook_source.run("search", "--query", "sofa")
    assert payload["count"] == 2


@pytest.mark.anyio
async def test_sidecar_errors_surface_as_exceptions(stub_sidecar):
    stub_sidecar(json.dumps({"error": "Refusing to read Facebook while signed in"}))
    with pytest.raises(RuntimeError, match="signed in"):
        await facebook_source.run("check")


@pytest.mark.anyio
async def test_search_tool_degrades_instead_of_failing(no_sidecar):
    result = await server.search_facebook("sofa")
    assert result["status"] == "not_installed"
    assert "uv tool install" in result["detail"]


@pytest.mark.anyio
async def test_listing_tool_accepts_an_id_or_a_url(stub_sidecar):
    stub_sidecar(json.dumps({"id": "123", "heading": "Sofa"}))
    from_id = await server.get_facebook_listing("123")
    from_url = await server.get_facebook_listing(
        "https://www.facebook.com/marketplace/item/123/"
    )
    assert from_id["heading"] == from_url["heading"] == "Sofa"


@pytest.mark.anyio
async def test_listing_tool_rejects_nonsense_without_spawning_anything(no_sidecar):
    result = await server.get_facebook_listing("not-a-listing")
    assert result["status"] == "bad_input"


@pytest.mark.anyio
async def test_check_setup_reports_facebook_as_a_capability(no_sidecar):
    report = await server.check_setup()
    facebook = report["facebook_marketplace"]
    assert facebook["installed"] is False
    assert facebook["reads_as"].startswith("anonymous visitor")
    assert set(facebook["tools"]) == {"search_facebook", "get_facebook_listing"}


@pytest.fixture
def anyio_backend():
    return "asyncio"
