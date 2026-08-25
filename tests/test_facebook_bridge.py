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
    """Nowhere the helper could be found.

    Every location the resolver consults has to be neutralised, not just PATH —
    a real `sporhund-fb` under the developer's own ~/.local/bin would otherwise
    make these tests pass or fail depending on whose machine they run on.
    """
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "SPORHUND_FB"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def stub_sidecar(no_sidecar, monkeypatch, tmp_path):
    """Install a fake `sporhund-fb` that echoes a canned payload."""

    def install(payload: str, exit_code: int = 0) -> None:
        bin_dir = tmp_path / "stub-bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        script = bin_dir / facebook_source.EXECUTABLE
        # `echo` rather than `cat`: PATH is emptied by the no_sidecar fixture,
        # so only shell builtins are reachable from inside the stub.
        script.write_text(
            "#!/bin/sh\n"
            f"echo '{payload}'\n"
            f"exit {exit_code}\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    return install


def test_reports_absent_when_not_installed(no_sidecar):
    assert facebook_source.executable_path() is None
    assert facebook_source.installed() is False


def _make_executable(directory, name=facebook_source.EXECUTABLE):
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / name
    script.write_text("#!/bin/sh\necho '{}'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_the_servers_own_copy_of_the_helper_is_never_chosen(monkeypatch, tmp_path):
    """`[project.scripts]` cannot be limited to an extra.

    So the plain distribution installs a `sporhund-fb` into the very uvx
    environment this server runs from — a copy with no browser, which can never
    work, and which a plain PATH lookup finds first because uvx puts its own bin
    at the front. Live, this made an installed source report itself as having no
    browser and every call fail.
    """
    own_prefix = tmp_path / "uvx-env"
    _make_executable(own_prefix / "bin")
    monkeypatch.setattr(facebook_source.sys, "prefix", str(own_prefix))
    monkeypatch.setenv("PATH", str(own_prefix / "bin"))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    monkeypatch.delenv("UV_TOOL_BIN_DIR", raising=False)
    monkeypatch.delenv("XDG_BIN_HOME", raising=False)
    monkeypatch.delenv("SPORHUND_FB", raising=False)

    assert facebook_source.executable_path() is None


def test_the_uv_tool_copy_wins_over_the_servers_own(monkeypatch, tmp_path):
    own_prefix = tmp_path / "uvx-env"
    _make_executable(own_prefix / "bin")
    real = _make_executable(tmp_path / "tools" / "bin")
    monkeypatch.setattr(facebook_source.sys, "prefix", str(own_prefix))
    # The server's own bin first on PATH, exactly as uvx arranges it.
    monkeypatch.setenv("PATH", str(own_prefix / "bin"))
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "tools" / "bin"))
    monkeypatch.delenv("SPORHUND_FB", raising=False)

    assert facebook_source.executable_path() == str(real)


def test_an_explicit_override_wins(monkeypatch, tmp_path):
    chosen = _make_executable(tmp_path / "elsewhere", name="fb-helper")
    monkeypatch.setenv("SPORHUND_FB", str(chosen))
    assert facebook_source.executable_path() == str(chosen)


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
async def test_a_failing_helper_is_reported_not_raised(stub_sidecar):
    """A rate-limit or a dead helper must not surface as an opaque tool error.

    Live, a helper that could not start turned into "Error executing tool
    search_facebook" with nothing an agent could act on.
    """
    stub_sidecar(json.dumps({"error": "Facebook returned HTTP 400; rate-limited."}))
    result = await server.search_facebook("sofa")
    assert result["status"] == "failed"
    assert "rate-limited" in result["detail"]

    listing = await server.get_facebook_listing("123")
    assert listing["status"] == "failed"


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
