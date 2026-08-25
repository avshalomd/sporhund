"""The server's side of the Facebook bridge.

Imports nothing from the optional extra: this module only knows how to find and
run the `sporhund-fb` executable, so the MCP server keeps working — and keeps
reporting honestly — on machines where the Facebook source was never installed.

The subprocess boundary is the point. A browser is a heavy, crash-prone thing to
host inside a long-lived stdio server, and the server's own environment is
rebuilt by uvx on every plugin update, so the browser could not live there even
if that were desirable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

EXECUTABLE = "sporhund-fb"

INSTALL_COMMAND = (
    "uv tool install 'sporhund[facebook]' && playwright install chromium"
)

# A cold start pays for a browser launch; a search then loads a page under a
# deliberate 4-second pacing floor. Generous, because the failure this guards
# against is a wedged subprocess, not a slow one.
_TIMEOUT_S = 120.0


class FacebookUnavailable(RuntimeError):
    """Raised when the optional Facebook source is not installed."""


def _own_bin() -> Path:
    """The script directory of the environment this server is running in."""
    return Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")


def _candidate_dirs() -> list[Path]:
    """Where a working `sporhund-fb` could live, best first.

    uv's tool directory comes before PATH because of a trap worth spelling out.
    `[project.scripts]` entries cannot be attached to an optional extra, so the
    plain `sporhund` distribution also installs a `sporhund-fb` — including into
    the uvx environment this server itself runs from. That copy can never work:
    its environment has no browser and never will. It is also the *first* thing
    a plain PATH lookup finds, because uvx puts its own bin at the front. So the
    server's own script directory is skipped outright, and the tool directory is
    consulted before the rest of PATH.
    """
    dirs: list[Path] = []
    for value in (os.environ.get("UV_TOOL_BIN_DIR"), os.environ.get("XDG_BIN_HOME")):
        if value:
            dirs.append(Path(value).expanduser())
    dirs.append(Path.home() / ".local" / "bin")
    dirs.extend(
        Path(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
    )

    own = _own_bin().resolve()
    seen: set[Path] = set()
    ordered: list[Path] = []
    for directory in dirs:
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved == own or resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(directory)
    return ordered


def executable_path() -> str | None:
    """Where a usable `sporhund-fb` lives, or None if the extra is not installed.

    Deliberately not `shutil.which`: see `_candidate_dirs` for why a plain PATH
    lookup finds a copy that cannot work.
    """
    override = os.environ.get("SPORHUND_FB")
    if override:
        candidate = Path(override).expanduser()
        return str(candidate) if candidate.exists() else None
    for directory in _candidate_dirs():
        candidate = directory / EXECUTABLE
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def installed() -> bool:
    return executable_path() is not None


async def run(*args: str) -> dict[str, Any]:
    """Run the sidecar and return its JSON, raising on anything else."""
    path = executable_path()
    if path is None:
        raise FacebookUnavailable(
            "The Facebook source is not installed. It is optional and off by "
            f"default; to switch it on, run: {INSTALL_COMMAND}"
        )

    process = await asyncio.create_subprocess_exec(
        path,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(
            f"The Facebook helper did not finish within {_TIMEOUT_S:.0f}s."
        ) from None

    text = stdout.decode("utf-8", "replace").strip()
    if not text:
        detail = stderr.decode("utf-8", "replace").strip() or "no output"
        raise RuntimeError(f"The Facebook helper returned nothing ({detail}).")

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(
            f"The Facebook helper returned output that was not JSON: {text[:200]}"
        ) from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload


async def describe() -> dict[str, Any]:
    """Capability report for `check_setup`.

    Never raises: an absent or broken Facebook source is a state to report, not
    an error that should take the rest of the setup report down with it.
    """
    path = executable_path()
    state: dict[str, Any] = {
        "tools": ["search_facebook", "get_facebook_listing"],
        "installed": path is not None,
        "helper": path,
        "opt_in": True,
        "reads_as": "anonymous visitor — never signed in",
    }
    if not state["installed"]:
        state["how_to_enable"] = {
            "step_1": f"Run: {INSTALL_COMMAND}",
            "step_2": "Run check_setup again to confirm it is switched on.",
            "note": (
                "Optional. Everything else works without it. This one downloads "
                "a browser (~150 MB) because Facebook does not serve Marketplace "
                "to plain HTTP clients."
            ),
        }
        return state

    try:
        state.update(await run("check"))
    except Exception as exc:  # noqa: BLE001 - a report, not a failure
        state["error"] = str(exc)
    return state
