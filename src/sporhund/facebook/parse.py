"""Turning Facebook's page payloads into listings.

Marketplace ships its first batch of results inside the page as Relay bootstrap
JSON, and later batches arrive as GraphQL responses while you scroll. Both carry
the *same* listing objects, so one walker reads both: rather than following a
path through Facebook's query structure — which is opaque, versioned, and
renamed often — this looks for objects that are recognisably listings and takes
them wherever they sit. That is why a Facebook redesign should cost a fixture
refresh here rather than a rewrite.

Nothing in this module needs a browser; it is pure data-shaping, and the tests
run it against a payload captured from a real logged-out page.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterator

ITEM_URL = "https://www.facebook.com/marketplace/item/{id}/"

# Facebook renders the whole bootstrap payload into <script type="application/json">
# tags. There are dozens per page and only one or two hold listings, so the
# walker is cheap enough to point at all of them.
_JSON_SCRIPT_RE = re.compile(
    r'<script type="application/json"[^>]*>(.*?)</script>', re.S
)

# The one field every Marketplace listing carries and nothing else does.
_TITLE_KEY = "marketplace_listing_title"


def iter_json_blobs(html: str) -> Iterator[Any]:
    """Yield each parsed <script type="application/json"> payload in the page."""
    for match in _JSON_SCRIPT_RE.finditer(html):
        try:
            yield json.loads(match.group(1))
        except (ValueError, TypeError):
            # Facebook mixes in blobs that are not JSON documents on their own.
            continue


def find_listings(node: Any, _depth: int = 0) -> list[dict[str, Any]]:
    """Collect every listing object anywhere inside a decoded payload.

    Deduplicated by id: the same listing is reachable by several paths in a
    Relay store, and a search that reported the same sofa four times would be
    worse than useless.
    """
    found: dict[str, dict[str, Any]] = {}
    _walk(node, found, 0)
    return list(found.values())


def _walk(node: Any, found: dict[str, dict[str, Any]], depth: int) -> None:
    if depth > 40 or not isinstance(node, (dict, list)):
        return
    if isinstance(node, dict):
        listing_id = node.get("id")
        if node.get(_TITLE_KEY) and isinstance(listing_id, str):
            found.setdefault(listing_id, node)
        for value in node.values():
            _walk(value, found, depth + 1)
        return
    for value in node:
        _walk(value, found, depth + 1)


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape one listing into the record the MCP tools hand back.

    Deliberately close to the FINN listing shape so an agent can put the two
    side by side, but the `source` field is always present and always
    "facebook": these ads have no registry number, no verified seller and no
    structured specification, and a caller that forgets which is which would
    give them credit they have not earned.
    """
    listing_id = str(raw.get("id") or "")
    price, currency = _price(raw.get("listing_price"))
    extra: dict[str, Any] = {}
    for key in ("is_sold", "is_pending"):
        if raw.get(key):
            extra[key] = True
    if raw.get("delivery_types"):
        extra["delivery_types"] = raw["delivery_types"]
    subtitles = [
        s.get("subtitle")
        for s in raw.get("custom_sub_titles_with_rendering_flags") or []
        if isinstance(s, dict) and s.get("subtitle")
    ]
    if subtitles:
        extra["subtitles"] = subtitles

    return {
        "source": "facebook",
        "id": listing_id,
        "heading": raw.get(_TITLE_KEY) or raw.get("custom_title") or "(no title)",
        "url": ITEM_URL.format(id=listing_id),
        "price": price,
        "currency": currency,
        "location": _location(raw.get("location")),
        "published": _published(raw.get("creation_time")),
        "image_url": _photo(raw.get("primary_listing_photo")),
        "extra": extra,
    }


def _price(node: Any) -> tuple[int | None, str | None]:
    """Read the numeric amount, never the rendered one.

    `formatted_amount` cannot be trusted for currency: a free item in Oslo comes
    back as "$0" because a logged-out visitor has no locale context. The numeric
    `amount` is correct regardless, and the currency is only reported when the
    rendered string actually names one.
    """
    if not isinstance(node, dict):
        return None, None
    amount = node.get("amount")
    price: int | None = None
    if amount is not None:
        try:
            price = int(round(float(amount)))
        except (TypeError, ValueError):
            price = None
    formatted = str(node.get("formatted_amount") or "")
    match = re.match(r"^([A-Z]{3})", formatted)
    currency = match.group(1) if match else None
    return price, currency


def _location(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    geocode = node.get("reverse_geocode")
    if not isinstance(geocode, dict):
        return None
    page = geocode.get("city_page")
    if isinstance(page, dict) and page.get("display_name"):
        return str(page["display_name"])
    city = geocode.get("city")
    return str(city) if city else None


def _published(value: Any) -> str | None:
    """Facebook stamps listings in whole seconds; FINN uses milliseconds."""
    if not isinstance(value, (int, float)):
        return None
    try:
        return (
            datetime.fromtimestamp(float(value), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def _photo(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    image = node.get("image")
    if isinstance(image, dict) and image.get("uri"):
        return str(image["uri"])
    return None


def listings_from_html(html: str) -> list[dict[str, Any]]:
    """Every listing in a rendered Marketplace page, normalized."""
    found: dict[str, dict[str, Any]] = {}
    for blob in iter_json_blobs(html):
        _walk(blob, found, 0)
    return [normalize(raw) for raw in found.values()]
