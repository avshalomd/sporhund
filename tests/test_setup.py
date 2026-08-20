"""Tests for setup reporting: where a key lives, and what the registry says.

The point of `describe_secret` is that it can explain a key's location without
ever handling its value, so these assert on that boundary as much as on the
reported facts. Everything here runs offline.
"""

from __future__ import annotations

import httpx
import pytest

from sporhund import config
from sporhund.vegvesen import VegvesenClient

SECRET = "super-secret-key-value"


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    """Point both .env locations at a temp dir and clear the environment."""
    project = tmp_path / "project.env"
    user = tmp_path / "user.env"
    monkeypatch.setattr(config, "_PROJECT_ENV", project)
    monkeypatch.setattr(config, "_USER_ENV", user)
    monkeypatch.delenv("VEGVESEN_API_KEY", raising=False)
    return project, user


def test_reports_no_key_and_where_it_looked(env_files):
    state = config.describe_secret("VEGVESEN_API_KEY")
    assert state["configured"] is False
    assert state["active_source"] is None
    assert [c["source"] for c in state["checked"]][0] == "environment variable"
    assert len(state["checked"]) == 3


def test_environment_wins_over_files(env_files, monkeypatch):
    project, _ = env_files
    project.write_text("VEGVESEN_API_KEY=from-file\n")
    monkeypatch.setenv("VEGVESEN_API_KEY", SECRET)

    state = config.describe_secret("VEGVESEN_API_KEY")
    assert state["active_source"] == "environment variable"
    assert any("more than one place" in w for w in state["warnings"])


def test_never_reveals_the_value(env_files, monkeypatch):
    monkeypatch.setenv("VEGVESEN_API_KEY", SECRET)
    assert SECRET not in repr(config.describe_secret("VEGVESEN_API_KEY"))


def test_warns_when_the_file_is_readable_by_others(env_files):
    project, _ = env_files
    project.write_text("VEGVESEN_API_KEY=x\n")
    project.chmod(0o644)

    warnings = config.describe_secret("VEGVESEN_API_KEY")["warnings"]
    assert any("chmod 600" in w for w in warnings)

    project.chmod(0o600)
    assert config.describe_secret("VEGVESEN_API_KEY")["warnings"] == []


@pytest.mark.parametrize(
    "status,ok,reason",
    [
        # An unknown plate answers 204 No Content — proof the key was accepted.
        (204, True, None),
        (200, True, None),
        (401, False, "rejected"),
        (403, False, "rejected"),
        (429, True, None),
        (500, False, "unexpected"),
    ],
)
def test_key_verification_reads_status_codes(monkeypatch, status, ok, reason):
    monkeypatch.setenv("VEGVESEN_API_KEY", SECRET)

    async def fake_get(self, params, key):
        return httpx.Response(status, request=httpx.Request("GET", "https://x"))

    monkeypatch.setattr(VegvesenClient, "_get", fake_get)
    verdict = _run(VegvesenClient().verify_key())
    assert verdict["ok"] is ok
    assert verdict.get("reason") == reason


def test_key_verification_says_when_no_key_is_configured(env_files):
    verdict = _run(VegvesenClient().verify_key())
    assert verdict == {"ok": False, "reason": "no_key", "detail": verdict["detail"]}
    assert "bestill-api-nokkel" in verdict["detail"]


def _run(coro):
    import asyncio

    return asyncio.run(coro)
