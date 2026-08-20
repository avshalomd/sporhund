"""Local configuration and secret loading.

Secrets stay on the user's machine and are read at call time. Nothing here is
ever logged, echoed back through a tool result, or written anywhere.

Lookup order for any setting:
  1. the process environment (so a client's MCP `env` block or your shell wins)
  2. `.env` beside the project
  3. `~/.config/sporhund/.env`
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_PROJECT_ENV = Path(__file__).resolve().parents[2] / ".env"
_USER_ENV = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "sporhund" / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal KEY=value file. Blank lines and # comments ignored."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    except OSError:
        return {}
    return values


def get_secret(name: str) -> str | None:
    """Return a configured secret, or None when it isn't set anywhere."""
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for path in (_PROJECT_ENV, _USER_ENV):
        found = _read_env_file(path).get(name)
        if found:
            return found
    return None


def secret_locations() -> list[str]:
    """Where a user could put a secret — for error messages, never values."""
    return [str(_PROJECT_ENV), str(_USER_ENV)]


def describe_secret(name: str) -> dict[str, Any]:
    """Report *where* a secret is configured and nothing about its value.

    Setup help has to be able to say "your key is in ~/.config/..." without
    ever handling the key itself, so this returns locations and warnings only.
    """
    checked: list[dict[str, Any]] = []
    holders: list[str] = []

    from_env = os.environ.get(name)
    has_env = bool(from_env and from_env.strip())
    checked.append({"source": "environment variable", "has_key": has_env})
    if has_env:
        holders.append("environment variable")

    warnings: list[str] = []
    for path in (_PROJECT_ENV, _USER_ENV):
        exists = path.is_file()
        has_key = bool(_read_env_file(path).get(name))
        checked.append({"source": str(path), "exists": exists, "has_key": has_key})
        if has_key:
            holders.append(str(path))
        if exists and _is_group_or_world_readable(path):
            warnings.append(
                f"{path} is readable by other accounts on this machine. "
                f"Tighten it with: chmod 600 {path}"
            )

    if len(holders) > 1:
        warnings.append(
            f"{name} is set in more than one place ({', '.join(holders)}). "
            f"The first one wins, so editing the others has no effect."
        )

    return {
        "configured": bool(holders),
        "active_source": holders[0] if holders else None,
        "checked": checked,
        "warnings": warnings,
    }


def _is_group_or_world_readable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o077)
    except OSError:
        return False
