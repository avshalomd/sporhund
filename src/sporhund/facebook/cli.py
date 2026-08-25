"""`sporhund-fb` — the sidecar the MCP server shells out to.

This exists so the browser never enters the server's own environment. The
plugin launches its server through `uvx --from ${CLAUDE_PLUGIN_ROOT}`, an
environment resolved at launch and rebuilt on every plugin update, so anything
installed into it after the fact would be silently discarded. Installing the
extra as its own tool environment (`uv tool install 'sporhund[facebook]'`) puts
this script on PATH instead, where it survives updates and stays absent for
everyone who never asks for it.

Everything it prints on stdout is one JSON document, so the caller never has to
parse prose. Diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sporhund-fb",
        description="Read public Facebook Marketplace listings as an anonymous visitor.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Report whether this sidecar can run.")
    check.set_defaults(func=_check)

    search = sub.add_parser("search", help="Search Marketplace.")
    search.add_argument("--query", required=True)
    search.add_argument("--place", default="oslo")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=_search)

    listing = sub.add_parser("listing", help="Read one listing in full.")
    listing.add_argument("--id", required=True, dest="item_id")
    listing.set_defaults(func=_listing)

    args = parser.parse_args(argv)
    try:
        payload = asyncio.run(args.func(args))
    except Exception as exc:  # noqa: BLE001 - the boundary reports, never raises
        json.dump({"error": str(exc), "kind": type(exc).__name__}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


async def _check(_args: argparse.Namespace) -> dict[str, Any]:
    """Say what is installed without launching anything expensive."""
    from .session import profile_dir

    result: dict[str, Any] = {
        "playwright_installed": False,
        "browser_installed": False,
        "profile_dir": str(profile_dir()),
    }
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError:
        result["how_to_fix"] = (
            "uv tool install 'sporhund[facebook]' && playwright install chromium"
        )
        return result

    result["playwright_installed"] = True
    async with async_playwright() as pw:
        # executable_path is a promise about where the browser *would* live;
        # checking the file is what tells us `playwright install` has been run.
        from pathlib import Path

        result["browser_installed"] = Path(pw.chromium.executable_path).exists()
    if not result["browser_installed"]:
        result["how_to_fix"] = "playwright install chromium"
    return result


async def _search(args: argparse.Namespace) -> dict[str, Any]:
    from .session import GuestSession

    async with GuestSession() as session:
        listings = await session.search(args.query, args.place, args.limit)
    result: dict[str, Any] = {
        "source": "facebook",
        "count": len(listings),
        "listings": listings,
    }
    if not listings:
        # Say what an empty result does and does not mean, so nobody reads it
        # as the source being broken — and so a genuine parsing failure is still
        # something the caller can suspect rather than being papered over.
        result["note"] = (
            "No matches on the first page. Facebook only serves about twenty "
            "results per search to anonymous visitors, so a narrow query in a "
            "smaller place can legitimately come back empty — try a broader "
            "term or a larger place. If everything comes back empty, the source "
            "may be rate-limited or Facebook's page shape may have changed."
        )
    return result


async def _listing(args: argparse.Namespace) -> dict[str, Any]:
    from .session import GuestSession

    async with GuestSession() as session:
        return await session.listing(args.item_id)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
