"""FINN.no read client for personal use.

This module fetches public FINN.no listing pages on demand — exactly the pages a
person browsing the site would load — and pulls the structured listing data that
FINN itself embeds in each page (the React-Query hydration state for search
pages, and JSON-LD for individual listings).

Design constraints, on purpose (see NOTICE and README):
  * One request per user action. No background crawling loops, no bulk mirroring.
  * A conservative minimum interval between requests (polite pacing).
  * Nothing is redistributed; callers keep results on their own machine.

It is a convenience layer over your own browsing, not a data pipeline.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import unquote, urlencode, urlparse

import httpx

# A normal desktop-Chrome identity: we are loading the same pages a person would.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
}

# Polite pacing: never fire search requests faster than this, process-wide.
_MIN_REQUEST_INTERVAL_S = 2.0

# Vertical -> search URL. Only verticals whose pages embed the clean
# React-Query state are wired up here; real estate has moved to a different
# app shell (see README "Known limitations").
SEARCH_URLS: dict[str, str] = {
    "torget": "https://www.finn.no/recommerce/forsale/search",
    "car": "https://www.finn.no/mobility/search/car",
    "job": "https://www.finn.no/job/search",
}

# Human-friendly convenience params -> the raw FINN query keys they map to.
# Anything not listed here can still be passed through verbatim via `filters`.
_RANGE_ALIASES = {
    "price_from": "price_from",
    "price_to": "price_to",
    "year_from": "year_from",
    "year_to": "year_to",
    "mileage_from": "mileage_from",
    "mileage_to": "mileage_to",
}

_FINNKODE_RE = re.compile(r"(\d{6,})")
_STATE_RE = re.compile(
    r'<script type="application/json" data-react-query-state>(.*?)</script>', re.S
)
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_OG_DESC_RE = re.compile(r'<meta property="og:description" content="([^"]*)"')
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')
# Car/mobility item pages carry the ad in a base64+urlencoded `data-props`
# attribute on the page-root div, rather than in JSON-LD.
_DATA_PROPS_RE = re.compile(r'data-props="([A-Za-z0-9+/=]+)"')


class FinnError(RuntimeError):
    """Raised when a page could not be fetched or its data could not be read."""


@dataclass
class Listing:
    """A single normalized listing, trimmed to the fields worth reasoning about."""

    finnkode: str
    heading: str
    url: str
    price: int | None = None
    currency: str | None = None
    location: str | None = None
    published: int | None = None  # epoch ms, when available
    seller_type: str | None = None  # "private" / "dealer" when known
    extra: dict[str, Any] = field(default_factory=dict)  # vertical-specific fields

    def to_dict(self) -> dict[str, Any]:
        d = {
            "finnkode": self.finnkode,
            "heading": self.heading,
            "url": self.url,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "published": self.published,
            "seller_type": self.seller_type,
        }
        d.update(self.extra)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class SearchResult:
    vertical: str
    query_url: str
    total_matches: int | None
    page: int
    last_page: int | None
    listings: list[Listing]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical,
            "query_url": self.query_url,
            "total_matches": self.total_matches,
            "page": self.page,
            "last_page": self.last_page,
            "count": len(self.listings),
            "listings": [l.to_dict() for l in self.listings],
        }


class FinnClient:
    """Fetches and parses FINN pages, with process-wide polite pacing."""

    def __init__(self, min_interval_s: float = _MIN_REQUEST_INTERVAL_S) -> None:
        self._min_interval = min_interval_s
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def _get(self, url: str, params: dict[str, str] | None = None) -> str:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(
                    headers=_HEADERS, timeout=20.0, follow_redirects=True
                ) as client:
                    resp = await client.get(url, params=params)
            finally:
                self._last_request = time.monotonic()
        if resp.status_code != 200:
            raise FinnError(f"FINN returned HTTP {resp.status_code} for {resp.url}")
        return resp.text

    # -- search ----------------------------------------------------------------

    async def search(
        self,
        vertical: str,
        query: str | None = None,
        *,
        page: int = 1,
        sort: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> SearchResult:
        if vertical not in SEARCH_URLS:
            raise FinnError(
                f"Unknown vertical {vertical!r}. Known: {', '.join(SEARCH_URLS)}"
            )
        params: dict[str, str] = {}
        if query:
            params["q"] = query
        if page and page > 1:
            params["page"] = str(page)
        if sort:
            params["sort"] = sort
        for key, value in (filters or {}).items():
            if value is None or value == "":
                continue
            mapped = _RANGE_ALIASES.get(key, key)
            params[mapped] = str(value)

        base = SEARCH_URLS[vertical]
        html = await self._get(base, params=params)
        result = _parse_search(html, vertical)
        result.query_url = f"{base}?{urlencode(params)}" if params else base
        return result

    # -- single listing --------------------------------------------------------

    async def get_listing(self, finnkode_or_url: str) -> dict[str, Any]:
        url = _canonical_item_url(finnkode_or_url)
        html = await self._get(url)
        return _parse_listing(html, url)


# -- parsing helpers -----------------------------------------------------------


def _decode_state(html: str) -> dict[str, Any]:
    m = _STATE_RE.search(html)
    if not m:
        raise FinnError(
            "Could not find embedded search state on the page. FINN may have "
            "changed this vertical's page format."
        )
    raw = m.group(1).strip()
    try:
        return json.loads(base64.b64decode(raw))
    except Exception:
        try:
            return json.loads(raw)
        except Exception as exc:  # pragma: no cover - defensive
            raise FinnError(f"Could not decode embedded search state: {exc}") from exc


def _find_results(node: Any) -> dict[str, Any] | None:
    """Locate the {docs, filters, metadata} results object anywhere in the tree."""
    if isinstance(node, dict):
        if isinstance(node.get("docs"), list) and "metadata" in node:
            return node
        for value in node.values():
            found = _find_results(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_results(value)
            if found is not None:
                return found
    return None


def _parse_search(html: str, vertical: str) -> SearchResult:
    state = _decode_state(html)
    results = _find_results(state)
    if results is None:
        raise FinnError("Embedded search state contained no results block.")
    metadata = results.get("metadata", {})
    paging = metadata.get("paging", {}) or {}
    result_size = metadata.get("result_size", {}) or {}
    listings = [_normalize(doc, vertical) for doc in results["docs"]]
    return SearchResult(
        vertical=vertical,
        query_url="",
        total_matches=result_size.get("match_count"),
        page=paging.get("current", 1),
        last_page=paging.get("last"),
        listings=[l for l in listings if l is not None],
    )


def _seller_type(doc: dict[str, Any]) -> str | None:
    flags = doc.get("flags") or []
    if "private" in flags:
        return "private"
    seg = doc.get("dealer_segment")
    if seg:
        return "dealer"
    return None


def _normalize(doc: dict[str, Any], vertical: str) -> Listing | None:
    finnkode = str(doc.get("id") or "")
    if not finnkode:
        return None
    price = None
    currency = None
    price_obj = doc.get("price")
    if isinstance(price_obj, dict):
        price = price_obj.get("amount")
        currency = price_obj.get("currency_code")
    elif isinstance(price_obj, (int, float)):
        price = int(price_obj)

    extra: dict[str, Any] = {}
    if vertical == "car":
        for key in ("year", "mileage"):
            if doc.get(key) is not None:
                extra[key] = doc[key]
    elif vertical == "job":
        for src, dst in (
            ("company_name", "company"),
            ("deadline", "deadline"),
            ("job_title", "job_title"),
        ):
            if doc.get(src) is not None:
                extra[dst] = doc[src]

    return Listing(
        finnkode=finnkode,
        heading=doc.get("heading") or doc.get("job_title") or "(no title)",
        url=doc.get("canonical_url") or _canonical_item_url(finnkode),
        price=price,
        currency=currency,
        location=doc.get("location"),
        published=doc.get("timestamp"),
        seller_type=_seller_type(doc),
        extra=extra,
    )


def _canonical_item_url(finnkode_or_url: str) -> str:
    s = finnkode_or_url.strip()
    if s.startswith("http"):
        host = urlparse(s).netloc
        if not host.endswith("finn.no"):
            raise FinnError(f"Refusing to fetch a non-finn.no URL: {s}")
        return s
    m = _FINNKODE_RE.search(s)
    if not m:
        raise FinnError(f"Could not read a finnkode from {finnkode_or_url!r}")
    # Recommerce is the modern canonical path and redirects to the right
    # vertical for any finnkode, so it is a safe default entry point.
    return f"https://www.finn.no/recommerce/forsale/item/{m.group(1)}"


def _parse_listing(html: str, url: str) -> dict[str, Any]:
    out: dict[str, Any] = {"url": url}
    # Torget / recommerce items expose a JSON-LD Product block.
    _merge_product_ld(html, out)
    # Car / mobility items carry the ad in a base64 data-props attribute.
    if "name" not in out:
        _merge_data_props(html, out)
    # Fallbacks that work on any page.
    if not out.get("description"):
        m = _OG_DESC_RE.search(html)
        if m:
            out["description"] = m.group(1)
    if not out.get("name"):
        m = _OG_TITLE_RE.search(html)
        if m:
            out["name"] = m.group(1)
    if len(out) == 1:  # only the url — we found nothing useful
        raise FinnError(
            "Could not read listing data. The page format may have changed, "
            "or the listing may no longer exist."
        )
    return {k: v for k, v in out.items() if v is not None}


def _merge_product_ld(html: str, out: dict[str, Any]) -> None:
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            out["name"] = data.get("name")
            out["description"] = data.get("description")
            out["condition"] = data.get("itemCondition")
            offers = data.get("offers")
            if isinstance(offers, dict):
                out["price"] = offers.get("price")
                out["currency"] = offers.get("priceCurrency")
                out["availability"] = offers.get("availability")
            props = data.get("additionalProperty")
            if isinstance(props, list):
                out["properties"] = {
                    p.get("name"): p.get("value")
                    for p in props
                    if isinstance(p, dict) and p.get("name")
                }
            return


def _merge_data_props(html: str, out: dict[str, Any]) -> None:
    m = _DATA_PROPS_RE.search(html)
    if not m:
        return
    try:
        decoded = unquote(base64.b64decode(m.group(1)).decode("utf-8"))
        props = json.loads(decoded)
    except Exception:
        return
    ad = _find_key(props, "ad")
    if not isinstance(ad, dict):
        return
    out["name"] = ad.get("title") or ad.get("heading")
    price = ad.get("price")
    if isinstance(price, dict):
        out["price"] = price.get("total") or price.get("main")
        out["currency"] = "NOK"
    elif isinstance(price, (int, float)):
        out["price"] = int(price)
    details: dict[str, Any] = {}
    for key in ("year", "mileage", "mileage_unit", "no_of_seats", "no_of_doors",
                "body_type", "transmission", "wheel_drive", "owners",
                "model_and_make", "exterior_color", "sales_form"):
        if ad.get(key) is not None and not isinstance(ad[key], (dict, list)):
            details[key] = ad[key]
    engine = ad.get("engine")
    if isinstance(engine, dict):
        fuel = engine.get("fuel")
        if isinstance(fuel, dict):
            details["fuel"] = fuel.get("value")
        if engine.get("effect") is not None:
            details["power_hp"] = engine.get("effect")
    trans = ad.get("transmission")
    if isinstance(trans, dict):
        details["transmission"] = trans.get("value")
    if ad.get("eu_check"):
        details["eu_check"] = ad["eu_check"]
    if details:
        out["properties"] = details
    if not out.get("description") and ad.get("description"):
        out["description"] = ad["description"]


def _find_key(node: Any, target: str) -> Any:
    """Depth-first search for the first value stored under `target`."""
    if isinstance(node, dict):
        if target in node:
            return node[target]
        for value in node.values():
            found = _find_key(value, target)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_key(value, target)
            if found is not None:
                return found
    return None


def summarize(listings: Iterable[Listing]) -> dict[str, Any]:
    """Cheap price statistics over a set of listings, for deal context."""
    prices = sorted(l.price for l in listings if l.price)
    if not prices:
        return {"count": 0}
    n = len(prices)
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) // 2
    return {
        "count": n,
        "min": prices[0],
        "median": median,
        "max": prices[-1],
        "mean": sum(prices) // n,
    }
