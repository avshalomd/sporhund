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
from .cars import brief, comparable_query, median_of, price_position
from .store import Store
from .vegvesen import (
    VegvesenClient,
    compare_claims,
    looks_like_plate,
    summarize_vehicle,
)

# Advertised to clients in serverInfo, so a connected agent can tell versions apart.
mcp = _Server("sporhund", version=__version__)

Vertical = Literal["torget", "car", "job"]
_client = FinnClient()
_store = Store()
_vegvesen = VegvesenClient()


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


@mcp.tool()
async def lookup_vehicle(plate_or_vin: str) -> dict[str, Any]:
    """Look up a vehicle in Norway's official vehicle registry.

    Returns what the state holds on the car — registration status, EU-control
    dates, first registration in Norway, official technical data — as opposed
    to what a seller typed into an ad. No owner information is available.

    Requires a personal Statens vegvesen API key; without one this raises a
    message explaining how to get your own. Prefer `verify_car` when you have a
    FINN listing, since it does the comparison for you.

    Args:
        plate_or_vin: A Norwegian registration number (e.g. "EV12138") or a
            chassis/VIN number.
    """
    value = plate_or_vin.strip()
    if looks_like_plate(value):
        raw = await _vegvesen.lookup(plate=value)
    else:
        raw = await _vegvesen.lookup(vin=value)
    return summarize_vehicle(raw)


@mcp.tool()
async def verify_car(finnkode_or_url: str) -> dict[str, Any]:
    """Check a FINN car ad against the official vehicle registry.

    This is the single most useful thing to run before contacting a seller: it
    compares the advertised claims with what Statens vegvesen actually records,
    and reports anything that disagrees or deserves a question. It surfaces
    things FINN never shows — a car that is currently deregistered, an EU-control
    date that differs from the ad, an import, or a former taxi.

    Note it cannot check mileage: the registry does not publish odometer
    readings, so a claimed kilometre count can only be judged against
    comparable listings, not verified.

    Requires a personal Statens vegvesen API key.

    Args:
        finnkode_or_url: A FINN listing code or full finn.no car listing URL.
    """
    listing = await _client.get_listing(finnkode_or_url)
    props = listing.get("properties") or {}
    plate = props.get("registration_number")
    vin = props.get("chassis_number")
    if not plate and not vin:
        raise ValueError(
            "This listing publishes no registration or chassis number, so it "
            "cannot be checked against the registry. It may not be a car ad."
        )

    official = summarize_vehicle(
        await _vegvesen.lookup(plate=plate) if plate else await _vegvesen.lookup(vin=vin)
    )

    findings = compare_claims(
        props, official, _today(), seller_type=listing.get("seller_type")
    )

    return {
        "listing": {
            "name": listing.get("name"),
            "url": listing.get("url"),
            "price": listing.get("price"),
            "claimed": {k: props.get(k) for k in
                        ("year", "mileage", "transmission", "fuel", "eu_check_next")
                        if props.get(k) is not None},
        },
        "official": official,
        "findings": findings,
        "verdict": (
            "Nothing in the registry contradicts the ad."
            if not findings
            else f"{len(findings)} thing(s) worth raising with the seller."
        ),
        "caveat": "Mileage cannot be verified — the registry publishes no odometer readings.",
    }


@mcp.tool()
async def find_comparables(
    finnkode_or_url: str,
    year_spread: int = 1,
    mileage_spread: int = 40000,
    query: str = "",
) -> dict[str, Any]:
    """Position a car against the listings a buyer would cross-shop.

    Fetches the ad, searches FINN for the same model within a year and mileage
    band, and reports where this price sits: percentile, distance from the
    median, and the cheapest alternatives. This is the negotiation groundwork —
    "the median comparable is 14 000 kr cheaper" is leverage; a price well
    below market is its own question.

    Honest limits, tell the user when they matter: these are asking prices,
    not sold prices; and free-text matching cannot see trim or equipment, so
    skim the comparables list before leaning on the numbers. No API key needed.

    Args:
        finnkode_or_url: The car listing to position.
        year_spread: Comparable years = subject year ± this (default 1).
        mileage_spread: Comparable mileage = subject km ± this (default 40 000).
        query: Override the auto-derived model search (use when the auto query
            comes back too broad or too narrow — check `search_used` in the result).
    """
    subject = await _client.get_listing(finnkode_or_url)
    props = subject.get("properties") or {}
    name = subject.get("name")

    q = query.strip() or comparable_query(name)
    if not q:
        raise ValueError("Could not derive a model query from this ad; pass `query`.")

    filters: dict[str, Any] = {}
    year, mileage = props.get("year"), props.get("mileage")
    if year:
        filters["year_from"], filters["year_to"] = year - year_spread, year + year_spread
    if isinstance(mileage, int):
        filters["mileage_from"] = max(0, mileage - mileage_spread)
        filters["mileage_to"] = mileage + mileage_spread

    result = await _client.search("car", query=q, filters=filters)
    subject_code = str(subject.get("url", "")).rstrip("/").rsplit("/", 1)[-1]
    comps = [l for l in result.listings if l.finnkode != subject_code]

    out: dict[str, Any] = {
        "subject": {
            "name": name, "price": subject.get("price"),
            "year": year, "mileage": mileage, "url": subject.get("url"),
        },
        "search_used": {"query": q, "filters": filters,
                        "total_matches": result.total_matches},
        "comparables_seen": len(comps),
    }
    price = subject.get("price")
    if isinstance(price, int) and comps:
        pos = price_position(price, [l.price for l in comps if l.price])
        out["position"] = pos
        out["comparables_median_year"] = median_of([l.extra.get("year") for l in comps])
        out["comparables_median_mileage"] = median_of([l.extra.get("mileage") for l in comps])
        out["cheapest_comparables"] = [
            brief(l) for l in sorted((l for l in comps if l.price), key=lambda x: x.price)[:8]
        ]
        if pos.get("n", 0) < 5:
            out["warning"] = (
                "Fewer than 5 comparables — widen year_spread/mileage_spread or "
                "adjust `query` before trusting the position."
            )
    out["caveats"] = (
        "Asking prices, not sold prices. Trim/equipment not matched — skim the "
        "comparables before quoting numbers."
    )
    return out


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
