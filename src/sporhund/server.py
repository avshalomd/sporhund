"""MCP server exposing FINN.no search and watch tools for personal use.

Run over stdio (the usual MCP transport):

    uv run sporhund

Then point an MCP client (e.g. Claude Desktop / Claude Code) at it. The tools
here fetch public FINN pages on demand, one request per call, and keep any state
locally. See NOTICE for the intended use.
"""

from __future__ import annotations

import json
from typing import Any, Literal

try:  # newer mcp package (>= 2026) renamed the high-level server
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ModuleNotFoundError:  # older packages ship it as FastMCP
    from mcp.server.fastmcp import FastMCP as _Server, Image

from . import __version__
from .finn import (
    DEFAULT_IMAGE_WIDTH,
    MAX_IMAGES_PER_CALL,
    FinnClient,
    Listing,
    SearchResult,
    SEARCH_URLS,
    summarize,
)
from .store import Store

# Advertised to clients in serverInfo, so a connected agent can tell versions apart.
mcp = _Server("sporhund", version=__version__)

Vertical = Literal["torget", "car", "job"]
_client = FinnClient()
_store = Store()


def _require_vertical(vertical: str) -> None:
    """Guard for clients that ignore the schema enum and send anything."""
    if vertical not in SEARCH_URLS:
        raise ValueError(
            f"Unknown vertical {vertical!r}. Choose one of: {', '.join(SEARCH_URLS)}."
        )


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
    vertical: Vertical,
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
            year_to, mileage_from, mileage_to. Useful raw FINN filters:
            {"dealer_segment": "1"} private sellers only ("3" = dealers);
            {"trade_type": "1"} genuine for-sale ads only ("2" = giveaways,
            "3" = wanted-to-buy) — worth setting on Torget, where giveaway and
            wanted ads otherwise appear alongside real listings.

    Each listing reports `trade_type` and `seller_type` so giveaways and
    wanted-to-buy ads can be told apart from real for-sale listings.
    Returns the total match count, paging info, and the listings on this page.
    """
    _require_vertical(vertical)
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

    Returns the title, the seller's full description, price, condition, any
    structured attributes FINN publishes, and `images` — the photo URLs, as
    links only, nothing downloaded. To actually look at the photos, use
    `view_listing_images`.
    """
    return await _client.get_listing(finnkode_or_url)


# Image content can't be described by an output schema, so this tool returns
# unstructured content blocks.
@mcp.tool(structured_output=False)
async def view_listing_images(
    finnkode_or_url: str,
    max_images: int = 3,
    width: int = DEFAULT_IMAGE_WIDTH,
) -> list[Image]:
    """Look at a listing's photos — use when the pictures answer the question.

    Worth calling for things text can't settle: actual condition and wear,
    whether the described damage looks serious, what is included in the box,
    tyre tread, rust, or whether a room matches the description. Skip it when
    the text already answers the question — images cost far more context than
    text, and each one is a separate request.

    Photos are fetched into memory only and are never saved. `get_listing`
    returns the image URLs without downloading anything, which is enough if
    you only need to hand the user a link.

    Args:
        finnkode_or_url: A FINN listing code or full finn.no listing URL.
        max_images: How many photos to fetch, newest-first (1-6, default 3).
        width: Pixel width to request from FINN's image CDN (default 640).
            Larger costs more context; 640 is plenty to judge condition.
    """
    max_images = max(1, min(int(max_images), MAX_IMAGES_PER_CALL))
    width = max(120, min(int(width), 1280))

    listing = await _client.get_listing(finnkode_or_url)
    urls = listing.get("images") or []
    if not urls:
        raise ValueError(
            f"No photos found for {finnkode_or_url!r}. The ad may have none, "
            "or it may no longer exist."
        )

    images: list[Image] = []
    for url in urls[:max_images]:
        data, mime = await _client.fetch_image(url, width=width)
        images.append(Image(data=data, format=mime.removeprefix("image/")))
    return images


@mcp.tool()
async def create_watch(
    name: str,
    vertical: Vertical,
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
    _require_vertical(vertical)
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
        "note": _watch_note(is_first_check, len(fresh)),
    }


def _watch_note(is_first_check: bool, new_count: int) -> str:
    if is_first_check:
        return (
            "First check: recorded the current matches as the baseline. "
            "Run check_watch again later to see only new listings."
        )
    if new_count == 0:
        return "Nothing new since your last check."
    return "These listings are new since your last check."


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
