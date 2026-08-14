"""MCP server exposing FINN.no search and watch tools for personal use.

Run over stdio (the usual MCP transport):

    uv run finn-agent

Then point an MCP client (e.g. Claude Desktop / Claude Code) at it. The tools
here fetch public FINN pages on demand, one request per call, and keep any state
locally. See NOTICE for the intended use.
"""

from __future__ import annotations

import json
from typing import Any

try:  # newer mcp package (>= 2026) renamed the high-level server
    from mcp.server.mcpserver import MCPServer as _Server
except ModuleNotFoundError:  # older packages ship it as FastMCP
    from mcp.server.fastmcp import FastMCP as _Server

from .finn import FinnClient, Listing, SearchResult, SEARCH_URLS, summarize
from .store import Store

mcp = _Server("finn-agent")
_client = FinnClient()
_store = Store()


def _filters_from(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"`filters` must be a JSON object string: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("`filters` must be a JSON object, e.g. '{\"price_to\": 5000}'")
    return parsed


@mcp.tool()
async def search_finn(
    vertical: str,
    query: str = "",
    page: int = 1,
    sort: str = "",
    filters: str = "",
) -> dict[str, Any]:
    """Search FINN.no and return structured listings.

    Args:
        vertical: One of "torget" (secondhand goods), "car" (used cars),
            or "job" (job ads).
        query: Free-text search, e.g. "elsykkel" or "volkswagen golf".
        page: 1-based results page (each page is ~50 listings).
        sort: Optional FINN sort key, e.g. "PUBLISHED_DESC" (newest first).
        filters: Optional JSON object string of extra FINN query parameters.
            Common ones: price_from, price_to (kr); for cars also year_from,
            year_to, mileage_from, mileage_to; plus any raw FINN filter such as
            {"dealer_segment": "1"} for private sellers only.

    Returns the total match count, paging info, and the listings on this page.
    """
    if vertical not in SEARCH_URLS:
        raise ValueError(
            f"Unknown vertical {vertical!r}. Choose one of: {', '.join(SEARCH_URLS)}."
        )
    result = await _client.search(
        vertical,
        query=query or None,
        page=page,
        sort=sort or None,
        filters=_filters_from(filters),
    )
    out = result.to_dict()
    out["price_stats"] = summarize(result.listings)
    return out


@mcp.tool()
async def get_listing(finnkode_or_url: str) -> dict[str, Any]:
    """Fetch the full detail of a single FINN listing.

    Args:
        finnkode_or_url: A FINN listing code (e.g. "235798748") or a full
            finn.no listing URL.

    Returns the title, full description, price, condition, and any structured
    attributes FINN publishes for the item.
    """
    return await _client.get_listing(finnkode_or_url)


@mcp.tool()
async def create_watch(
    name: str,
    vertical: str,
    query: str = "",
    sort: str = "",
    filters: str = "",
) -> dict[str, Any]:
    """Save a search as a named "watch" so you can later ask what's new.

    This stores only the search definition locally; it does not fetch anything.
    Use `check_watch` to see new matches since you last looked.

    Args:
        name: A unique short name, e.g. "cheap-cargo-bikes".
        vertical: "torget", "car", or "job".
        query: Free-text search.
        sort: Optional FINN sort key.
        filters: Optional JSON object string of FINN query parameters.
    """
    if vertical not in SEARCH_URLS:
        raise ValueError(
            f"Unknown vertical {vertical!r}. Choose one of: {', '.join(SEARCH_URLS)}."
        )
    if _store.get_watch(name) is not None:
        raise ValueError(
            f"A watch named {name!r} already exists. Pick another name or delete it."
        )
    parsed = _filters_from(filters)
    _store.create_watch(name, vertical, query or None, parsed, sort or None)
    return {"status": "created", "name": name, "vertical": vertical}


@mcp.tool()
async def list_watches() -> dict[str, Any]:
    """List all saved watches and how many listings each has seen so far."""
    return {"watches": _store.list_watches()}


@mcp.tool()
async def check_watch(name: str, pages: int = 1) -> dict[str, Any]:
    """Run a saved watch and return only listings not seen on a previous check.

    The first check of a fresh watch treats every current match as "new" and
    records them, so subsequent checks surface only genuinely new listings.

    Args:
        name: The watch name given to `create_watch`.
        pages: How many result pages to scan (1-3). Each page is one polite
            request; keep this small.
    """
    row = _store.get_watch(name)
    if row is None:
        raise ValueError(f"No watch named {name!r}. Use list_watches to see them.")
    pages = max(1, min(int(pages), 3))
    filters = json.loads(row["filters"] or "{}")

    collected: list[Listing] = []
    total_matches = None
    for page in range(1, pages + 1):
        result: SearchResult = await _client.search(
            row["vertical"],
            query=row["query"] or None,
            page=page,
            sort=row["sort"] or None,
            filters=filters,
        )
        total_matches = result.total_matches
        collected.extend(result.listings)
        if result.last_page and page >= result.last_page:
            break

    seen = _store.seen_finnkoder(row["id"])
    fresh = [l for l in collected if l.finnkode not in seen]
    is_first_check = row["last_checked_at"] is None
    _store.mark_seen(row["id"], [l.finnkode for l in collected])

    return {
        "watch": name,
        "vertical": row["vertical"],
        "total_matches": total_matches,
        "scanned": len(collected),
        "first_check": is_first_check,
        "new_count": len(fresh),
        "new_listings": [l.to_dict() for l in fresh],
        "note": (
            "First check: recorded current matches as the baseline. "
            "Run check_watch again later to see only new listings."
            if is_first_check
            else "These listings are new since your last check."
        ),
    }


@mcp.tool()
async def delete_watch(name: str) -> dict[str, Any]:
    """Delete a saved watch and its seen-history."""
    ok = _store.delete_watch(name)
    if not ok:
        raise ValueError(f"No watch named {name!r}.")
    return {"status": "deleted", "name": name}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
