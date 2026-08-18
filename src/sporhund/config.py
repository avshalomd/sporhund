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
