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
import html as htmllib
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
# Images come from a CDN, and a browser opening one listing pulls all of them at
# once, so a lighter interval is appropriate there than for app pages.
_MIN_IMAGE_INTERVAL_S = 0.5

# finncdn serves arbitrary widths via the path segment after /dynamic/.
# 640px is plenty to judge an item's condition without wasting context.
DEFAULT_IMAGE_WIDTH = 640
MAX_IMAGES_PER_CALL = 6
_CDN_SIZE_RE = re.compile(r"(https://images\.finncdn\.no/dynamic/)([^/]+)(/)")

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

# Search docs carry sales_form as a code; item pages carry the label.
_SALES_FORM_LABELS = {
    "1": "Bruktbil til salgs",
    "2": "Nybil til salgs",
    "4": "Bud ønskes",
    "5": "Leasing",
    "7": "Auksjon",
}
_STATE_RE = re.compile(
    r'<script type="application/json" data-react-query-state>(.*?)</script>', re.S
)
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_OG_DESC_RE = re.compile(r'<meta property="og:description" content="([^"]*)"')
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')
# Car/mobility item pages carry the ad in a base64+urlencoded `data-props`
# attribute on the page-root div, rather than in JSON-LD.
_DATA_PROPS_RE = re.compile(r'data-props="([A-Za-z0-9+/=]+)"')
# The seller's full free text lives in the rendered page. JSON-LD only carries
# an SEO-truncated (~160 char) version, which is useless for judging an item.
_DESC_SECTION_RE = re.compile(
    r'<section[^>]*data-testid="description"[^>]*>(.*?)</section>', re.S
)
# Both Torget and car pages render the seller's free text in a div whose class
# list contains whitespace-pre-wrap (Torget wraps it in a data-testid section,
# car pages in an "expandable-section" under an <h2>Beskrivelse</h2>).
_PREWRAP_OPEN_RE = re.compile(r'<div[^>]*class="[^"]*whitespace-pre-wrap[^"]*"[^>]*>')
_DIV_TOKEN_RE = re.compile(r"<div\b|</div\s*>", re.I)
_STRIP_BLOCKS_RE = re.compile(r"<(script|style|button)\b.*?</\1>", re.S)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_BLOCK_END_RE = re.compile(r"</(?:p|div|li|h\d)\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


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
    # "Til salgs" / "Gis bort" / "Ønskes kjøpt" — lets a caller tell real
    # for-sale ads apart from giveaways and wanted-to-buy ads.
    trade_type: str | None = None
    # Just the primary thumbnail here — a full gallery per row would swamp a
    # 50-result page. get_listing returns every image for a single ad.
    image_url: str | None = None
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
            "trade_type": self.trade_type,
            "image_url": self.image_url,
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
    # Filter keys the caller sent that FINN did not recognize (it ignores them
    # silently, which turns a typo into a subtly wrong result set).
    ignored_filters: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "vertical": self.vertical,
            "query_url": self.query_url,
            "total_matches": self.total_matches,
            "page": self.page,
            "last_page": self.last_page,
            "count": len(self.listings),
            "listings": [l.to_dict() for l in self.listings],
        }
        if self.ignored_filters:
            out["ignored_filters"] = self.ignored_filters
            out["warning"] = (
                "FINN did not recognize these filter parameters and ignored "
                "them — the results are broader than requested. Use "
                "get_search_filters to see valid names and values: "
                + ", ".join(self.ignored_filters)
            )
        return out


class FinnClient:
    """Fetches and parses FINN pages, with process-wide polite pacing."""

    def __init__(self, min_interval_s: float = _MIN_REQUEST_INTERVAL_S) -> None:
        self._min_interval = min_interval_s
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def _get(
        self, url: str, params: dict[str, str] | None = None
    ) -> tuple[str, str]:
        """Fetch a page. Returns (html, final_url_after_redirects)."""
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
        return resp.text, str(resp.url)

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
        html, _ = await self._get(base, params=params)
        result = _parse_search(html, vertical)
        result.query_url = f"{base}?{urlencode(params)}" if params else base
        sent = {_RANGE_ALIASES.get(k, k) for k in (filters or {})}
        applied = _applied_filter_params(html)
        if sent and applied is not None:
            result.ignored_filters = sorted(sent - applied)
        return result

    async def get_filters(
        self,
        vertical: str,
        query: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch one search page and return FINN's own filter metadata for it."""
        if vertical not in SEARCH_URLS:
            raise FinnError(
                f"Unknown vertical {vertical!r}. Known: {', '.join(SEARCH_URLS)}"
            )
        params: dict[str, str] = {}
        if query:
            params["q"] = query
        for key, value in (filters or {}).items():
            if value not in (None, ""):
                params[_RANGE_ALIASES.get(key, key)] = str(value)
        html, _ = await self._get(SEARCH_URLS[vertical], params=params)
        state = _decode_state(html)
        results = _find_results(state)
        if results is None:
            raise FinnError("No filter metadata found on the search page.")
        return {
            "vertical": vertical,
            "total_matches": (results.get("metadata", {}).get("result_size") or {}).get("match_count"),
            "filters": _parse_filters(results.get("filters") or []),
        }

    # -- single listing --------------------------------------------------------

    async def get_listing(self, finnkode_or_url: str) -> dict[str, Any]:
        url = _canonical_item_url(finnkode_or_url)
        html, final_url = await self._get(url)
        return _parse_listing(html, final_url)

    # -- images ----------------------------------------------------------------

    async def fetch_image(
        self, url: str, width: int = DEFAULT_IMAGE_WIDTH
    ) -> tuple[bytes, str]:
        """Fetch one listing photo into memory. Never written to disk.

        Returns (bytes, mime_type). Only finncdn URLs are accepted, so a
        malformed listing can't be used to make this fetch somewhere else.
        """
        if not url.startswith("https://images.finncdn.no/"):
            raise FinnError(f"Refusing to fetch a non-finncdn image URL: {url}")
        sized = resize_image_url(url, width)
        async with self._lock:
            wait = _MIN_IMAGE_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(
                    headers=_HEADERS, timeout=20.0, follow_redirects=True
                ) as client:
                    resp = await client.get(sized)
            finally:
                self._last_request = time.monotonic()
        if resp.status_code != 200:
            raise FinnError(f"Image fetch returned HTTP {resp.status_code} for {sized}")
        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        return resp.content, mime


# -- parsing helpers -----------------------------------------------------------


def _applied_filter_params(html: str) -> set[str] | None:
    """Parameter names FINN actually APPLIED as filters on this search.

    metadata.params is just an echo of what was received (it includes
    unrecognized names), but metadata.selected_filters lists only the filters
    that took effect — the reliable signal for detecting silently-ignored
    parameters. Returns None when the page can't be read (fail open).
    """
    try:
        results = _find_results(_decode_state(html))
        selected = (results or {}).get("metadata", {}).get("selected_filters") or []
        return {
            p.get("parameter_name")
            for fl in selected
            for p in (fl.get("parameters") or [])
            if p.get("parameter_name")
        }
    except Exception:
        return None


def _parse_filters(raw_filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize FINN's filter metadata into something an agent can use."""
    out: list[dict[str, Any]] = []
    for f in raw_filters:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        entry: dict[str, Any] = {
            "name": f["name"],
            "display_name": f.get("display_name"),
        }
        if f.get("type") == "RANGE_FILTER":
            entry["type"] = "range"
            entry["params"] = [f.get("name_from"), f.get("name_to")]
            if f.get("unit"):
                entry["unit"] = f["unit"]
        items = f.get("filter_items") or []
        values = []
        for it in items[:100]:
            if not isinstance(it, dict):
                continue
            v: dict[str, Any] = {
                "label": it.get("display_name"),
                "value": it.get("value"),
                "hits": it.get("hits"),
            }
            children = it.get("filter_items") or []
            if children:
                v["children"] = [
                    {"label": c.get("display_name"), "value": c.get("value"),
                     "hits": c.get("hits")}
                    for c in children[:60]
                    if isinstance(c, dict)
                ]
            values.append(v)
        if values:
            entry["values"] = values
        out.append(entry)
    return out


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


def _coerce_price(value: Any) -> int | None:
    """Normalize the several shapes FINN reports prices in to a plain int.

    Search results give {"amount": 13500}, JSON-LD gives the string "13500",
    and car pages give {"total": 119000}. Callers comparing across verticals
    should never have to care which.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in ("total", "amount", "main", "value"):
            if value.get(key) is not None:
                return _coerce_price(value[key])
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def _seller_type(doc: dict[str, Any]) -> str | None:
    flags = doc.get("flags") or []
    if "private" in flags:
        return "private"
    seg = doc.get("dealer_segment")
    if isinstance(seg, str):
        # Car docs label the segment: "Privat", "Merkeforhandler", "Forhandler".
        return "private" if seg.lower().startswith("privat") else "dealer"
    if seg:
        return "dealer"
    return None


def _normalize(doc: dict[str, Any], vertical: str) -> Listing | None:
    finnkode = str(doc.get("id") or "")
    if not finnkode:
        return None
    price_obj = doc.get("price")
    price = _coerce_price(price_obj)
    currency = (
        price_obj.get("currency_code") if isinstance(price_obj, dict) else None
    )

    extra: dict[str, Any] = {}
    if vertical == "car":
        for key in ("year", "mileage", "fuel", "transmission", "make", "model",
                    "model_specification", "warranty_duration", "chassis_number"):
            if doc.get(key) is not None:
                extra[key] = doc[key]
        if doc.get("regno"):
            extra["registration_number"] = doc["regno"]
        sales_form = doc.get("sales_form")
        if sales_form is not None:
            extra["sales_form"] = _SALES_FORM_LABELS.get(
                str(sales_form), str(sales_form)
            )
    elif vertical == "job":
        for src, dst in (
            ("company_name", "company"),
            ("deadline", "deadline"),
            ("job_title", "job_title"),
            ("no_of_positions", "no_of_positions"),
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
        trade_type=doc.get("trade_type"),
        image_url=_primary_image(doc),
        extra=extra,
    )


def _primary_image(doc: dict[str, Any]) -> str | None:
    image = doc.get("image")
    if isinstance(image, dict) and image.get("url"):
        return image["url"]
    urls = doc.get("image_urls")
    if isinstance(urls, list) and urls:
        return urls[0]
    return None


def resize_image_url(url: str, width: int = DEFAULT_IMAGE_WIDTH) -> str:
    """Ask the CDN for a given width instead of the full-size original."""
    return _CDN_SIZE_RE.sub(rf"\g<1>{int(width)}w\g<3>", url, count=1)


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
    # A bare finnkode at the site root redirects to whichever vertical owns the
    # ad. Guessing a vertical-specific path instead 404s for anything that is
    # not a Torget item.
    return f"https://www.finn.no/{m.group(1)}"


def _clean_fragment(frag: str) -> str | None:
    frag = _STRIP_BLOCKS_RE.sub("", frag)
    frag = _BR_RE.sub("\n", frag)
    frag = _BLOCK_END_RE.sub("\n", frag)
    text = htmllib.unescape(_TAG_RE.sub("", frag))
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if line:
            lines.append(line)
        elif lines and lines[-1]:  # collapse runs of blank lines
            lines.append("")
    return "\n".join(lines).strip() or None


def _balanced_div_inner(html: str, content_start: int) -> str:
    """Inner HTML of a div whose opening tag ends at content_start."""
    depth = 1
    for m in _DIV_TOKEN_RE.finditer(html, content_start):
        depth += 1 if m.group(0).lower().startswith("<div") else -1
        if depth == 0:
            return html[content_start : m.start()]
    return html[content_start : content_start + 20000]  # unbalanced page: cap


def _extract_full_description(html: str) -> str | None:
    """Pull the seller's complete free text out of the rendered page.

    Candidates: the Torget description section, plus every whitespace-pre-wrap
    div (car pages). Longest cleaned candidate wins — ads may render several
    small pre-wrap blocks for other content.
    """
    candidates: list[str] = []
    m = _DESC_SECTION_RE.search(html)
    if m:
        cleaned = _clean_fragment(m.group(1))
        if cleaned:
            candidates.append(cleaned)
    for open_tag in _PREWRAP_OPEN_RE.finditer(html):
        cleaned = _clean_fragment(_balanced_div_inner(html, open_tag.end()))
        if cleaned:
            candidates.append(cleaned)
    return max(candidates, key=len, default=None)


def _parse_listing(html: str, url: str) -> dict[str, Any]:
    out: dict[str, Any] = {"url": url}
    # Torget / recommerce items expose a JSON-LD Product block.
    _merge_product_ld(html, out)
    # Car / mobility items carry the ad in a base64 data-props attribute. Some
    # pages have both, and the data-props payload is by far the richer of the
    # two, so always merge it in rather than treating the sources as exclusive.
    _merge_data_props(html, out)
    # Prefer the full on-page description over JSON-LD's ~160-char SEO stub.
    full = _extract_full_description(html)
    if full and len(full) > len(out.get("description") or ""):
        out["description"] = full
    # Fallbacks that work on any page.
    if not out.get("description"):
        m = _OG_DESC_RE.search(html)
        if m:
            out["description"] = htmllib.unescape(m.group(1))
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
            image = data.get("image")
            if isinstance(image, list):
                out["images"] = [u for u in image if isinstance(u, str)]
            elif isinstance(image, str):
                out["images"] = [image]
            out["name"] = data.get("name")
            out["description"] = data.get("description")
            out["condition"] = data.get("itemCondition")
            offers = data.get("offers")
            if isinstance(offers, dict):
                out["price"] = _coerce_price(offers.get("price"))
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
    ad = props.get("adData", {}).get("ad") if isinstance(props, dict) else None
    if not isinstance(ad, dict):  # layout differs by vertical; fall back to a scan
        ad = _find_key(props, "ad")
    if not isinstance(ad, dict):
        return
    # Only fill what JSON-LD did not already provide.
    if not out.get("name"):
        out["name"] = ad.get("title") or ad.get("heading")
    price = _coerce_price(ad.get("price"))
    if price is not None and out.get("price") is None:
        out["price"] = price
        out.setdefault("currency", "NOK")

    details: dict[str, Any] = {}
    for key in ("year", "mileage", "mileage_unit", "no_of_seats", "no_of_doors",
                "owners", "model_and_make", "exterior_color",
                "first_registration", "registration_number", "service_history",
                "right_to_exchange"):
        if ad.get(key) is not None and not isinstance(ad[key], (dict, list)):
            details[key] = ad[key]
    # Several fields are {"id": n, "value": "..."} wrappers; keep the label.
    for key in ("body_type", "transmission", "wheel_drive", "sales_form",
                "registration_class", "car_location"):
        value = ad.get(key)
        if isinstance(value, dict) and value.get("value") is not None:
            details[key] = value["value"]
        elif isinstance(value, str):
            details[key] = value

    engine = ad.get("engine")
    if isinstance(engine, dict):
        fuel = engine.get("fuel")
        if isinstance(fuel, dict):
            details["fuel"] = fuel.get("value")
        if engine.get("effect") is not None:
            details["power_hp"] = engine.get("effect")

    # Condition signals a buyer actually cares about.
    eu_check = ad.get("eu_check")
    if isinstance(eu_check, dict) and eu_check.get("next"):
        details["eu_check_next"] = eu_check["next"]
    damages = ad.get("damages")
    if isinstance(damages, dict) and damages.get("has_known_damages") is not None:
        details["has_known_damages"] = damages["has_known_damages"]
    repairs = ad.get("repairs")
    if isinstance(repairs, dict) and repairs.get("has_undergone_repairs") is not None:
        details["has_undergone_repairs"] = repairs["has_undergone_repairs"]

    if details:
        # JSON-LD's additionalProperty is thin; the ad payload wins on conflict.
        merged = {**(out.get("properties") or {}), **details}
        out["properties"] = merged

    images = ad.get("images")
    if isinstance(images, list):
        urls = [
            img.get("uri") or img.get("url")
            for img in images
            if isinstance(img, dict) and (img.get("uri") or img.get("url"))
        ]
        if len(urls) > len(out.get("images") or []):
            out["images"] = urls

    equipment = ad.get("equipment")
    if isinstance(equipment, list):
        labels = [e.get("value") for e in equipment if isinstance(e, dict) and e.get("value")]
        if labels:
            out["equipment"] = labels

    # The payload often carries the seller's complete text as raw HTML — the
    # sturdiest source there is (some dealer ads render no pre-wrap block).
    for key in ("description_unsafe", "description"):
        raw = ad.get(key)
        if isinstance(raw, str) and raw.strip():
            cleaned = _clean_fragment(raw)
            if cleaned and len(cleaned) > len(out.get("description") or ""):
                out["description"] = cleaned


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
