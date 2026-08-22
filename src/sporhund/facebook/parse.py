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
            # A page carries the same listing several times at different levels
            # of completeness — a search card, a feed unit, the full record — so
            # keep the fullest copy rather than whichever was reached first.
            previous = found.get(listing_id)
            if previous is None or len(node) > len(previous):
                found[listing_id] = node
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
    coordinates = _coordinates(raw)
    if coordinates:
        extra["coordinates"] = coordinates

    return {
        "source": "facebook",
        "id": listing_id,
        "heading": raw.get(_TITLE_KEY) or raw.get("custom_title") or "(no title)",
        "url": ITEM_URL.format(id=listing_id),
        "price": price,
        "currency": currency,
        "location": _location(raw),
        "published": _published(raw.get("creation_time")),
        "image_url": _photo(raw.get("primary_listing_photo")),
        "extra": extra,
    }


# An ISO code standing on its own ("NOK2,500", "USD 0"), not letters inside a
# word. Norwegian pages render the currency as a lowercase "kr" instead.
_ISO_CURRENCY_RE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")
_KRONER_RE = re.compile(r"(?<![A-Za-z])kr(?![A-Za-z])", re.I)


def _price(node: Any) -> tuple[int | None, str | None]:
    """Read the numeric amount, and treat the rendered one with suspicion.

    `amount` is reliable. `formatted_amount` is not, in two distinct ways that a
    live run turned up and a fixture captured in one locale would have hidden.
    Its shape depends on the page's locale — "kr 4 000" in Norwegian, "NOK2,500"
    in English — so the currency has to be read from either form. And a listing
    with no price at all renders in whatever currency Facebook falls back to,
    which is not the local one: free Oslo sofas come back as "$0" and "USD 0".
    Reporting dollars for a Norwegian giveaway would be worse than saying
    nothing, so a zero price is returned without a currency.
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

    # Item pages state the currency outright; search cards never do, and render
    # it into the formatted string instead — under either of two key names.
    currency = node.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        formatted = str(
            node.get("formatted_amount")
            or node.get("formatted_amount_zeros_stripped")
            or ""
        )
        iso = _ISO_CURRENCY_RE.search(formatted)
        currency = (
            iso.group(1) if iso else ("NOK" if _KRONER_RE.search(formatted) else None)
        )
    if price == 0:
        currency = None
    return price, currency


def _location(raw: dict[str, Any]) -> str | None:
    """The place name, from whichever shape this page uses.

    Search cards nest it under `location.reverse_geocode`. Item pages put bare
    coordinates in `location` and keep the human-readable place in a separate
    `location_text` — so reading `location` alone gives nothing at all there.
    """
    node = raw.get("location")
    if isinstance(node, dict):
        geocode = node.get("reverse_geocode")
        if isinstance(geocode, dict):
            page = geocode.get("city_page")
            if isinstance(page, dict) and page.get("display_name"):
                return str(page["display_name"])
            if geocode.get("city"):
                return str(geocode["city"])
    text = raw.get("location_text")
    if isinstance(text, dict) and text.get("text"):
        return str(text["text"])
    return None


def _coordinates(raw: dict[str, Any]) -> dict[str, float] | None:
    for key in ("item_location", "location"):
        node = raw.get(key)
        if isinstance(node, dict):
            lat, lon = node.get("latitude"), node.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return {"lat": float(lat), "lon": float(lon)}
    return None


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


_OG_IMAGE_RE = re.compile(r'<meta property="og:image" content="([^"]*)"')


def detail_from_html(html: str, item_id: str | None = None) -> dict[str, Any] | None:
    """The full record for a single item page.

    `item_id` matters more than it looks. An item page is not just the listing
    asked for — it also carries "Today's picks", a strip of unrelated ads, and
    any of those can be the object with the most fields on the page. Picking the
    richest one outright returns a house in Lunner when a sofa in Oslo was
    asked for, which is a far worse failure than returning nothing. So when the
    id is known the search is restricted to it, and a miss returns None rather
    than falling back to a neighbour.

    Photos are not on the listing object: they sit in a `listing_photos` array
    on a neighbouring node, with the hero also exposed as an og:image tag, so
    both are searched.
    """
    found: dict[str, dict[str, Any]] = {}
    blobs = list(iter_json_blobs(html))
    for blob in blobs:
        _walk(blob, found, 0)
    if not found:
        return None

    if item_id is not None:
        raw = found.get(str(item_id))
        if raw is None:
            return None
    else:
        raw = max(found.values(), key=len)
    row = normalize(raw)

    description = raw.get("redacted_description")
    if isinstance(description, dict) and description.get("text"):
        row["description"] = str(description["text"])

    attributes = {
        str(a.get("attribute_name")): str(a.get("label") or a.get("value"))
        for a in raw.get("attribute_data") or []
        if isinstance(a, dict) and a.get("attribute_name")
    }
    if attributes:
        row["attributes"] = attributes

    photos: list[str] = []
    for blob in blobs:
        _collect_photos(blob, photos, 0)
    hero = _OG_IMAGE_RE.search(html)
    if hero:
        photos.insert(0, hero.group(1))
    row["image_urls"] = list(dict.fromkeys(photos))
    return row


def _collect_photos(node: Any, out: list[str], depth: int) -> None:
    if depth > 40 or not isinstance(node, (dict, list)):
        return
    if isinstance(node, dict):
        for photo in node.get("listing_photos") or []:
            if isinstance(photo, dict):
                uri = _photo(photo)
                if uri:
                    out.append(uri)
        for value in node.values():
            _collect_photos(value, out, depth + 1)
        return
    for value in node:
        _collect_photos(value, out, depth + 1)
