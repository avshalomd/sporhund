"""Chat widgets — listings rendered inline in the conversation.

A third delivery path, with a constraint the other two don't have: the widget
sandbox blocks remote image hosts, so thumbnails must be inlined as base64, and
that base64 passes through the agent's context. Photos therefore dominate the
token cost, and the whole design follows from measuring it:

    80w  ~1.1k tokens each      240w  ~5.9k      320w  ~10.5k

So a list uses 80w (six of them cost about as much as one 240w), and only the
single-listing view spends 240w on one hero image. Widths come from FINN's own
CDN ladder rather than a local resizer, so this needs no image library.

Everything prints to stdout as one fragment: the agent runs the command once and
pastes the result once. Writing a file and reading it back doubles the cost.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import io
import json
import sys
from typing import Any

from PIL import Image

from .finn import FinnClient

# FINN's CDN only serves a fixed ladder of widths, which leaves an awkward gap:
# 80w is too small to look at and 240w is too many bytes to emit in one piece.
# So fetch a good source and re-encode to an exact byte budget instead.
SOURCE_WIDTH = 640
# The rule that governs every number below: a photo must be *encoded at the size
# it is displayed at*. `fit_jpeg` meets a byte budget by dropping quality and
# then shrinking, so an over-tight budget silently returns a 97px image that the
# layout then stretches to 190px — which looks like corruption but is just an
# upscale. Pick the tile size first, then a budget generous enough to keep it.
THUMB_BYTES = 2_000     # a list row's thumbnail, shown at 104px
THUMB_SIDE = 120
PHOTO_BYTES = 1_200     # one tile in a detail card's contact sheet, shown at ~78px
PHOTO_SIDE = 80
MAX_PHOTOS = 12         # i.e. all of them; FINN listings rarely carry more
DEFAULT_LIMIT = 6
# base64 chars / 4 ~= tokens. The fragment has to survive one tool result in
# one piece: an oversized print is truncated to a file, and reading that file
# back is the second pass this whole design exists to avoid. So the budget is
# enforced by downgrading images, not by hoping.
# Measured, not guessed: a ~24 KB tool result survives whole, a ~31 KB one is
# truncated to a file. 5 600 tokens is ~22.4 KB, which leaves margin.
DEFAULT_BUDGET = 5_800

NB = " "


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def kr(value: Any) -> str:
    if not isinstance(value, int):
        return "Price n/a"
    return f"{value:,}".replace(",", NB) + NB + "kr"


def num(value: Any, unit: str) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return f"{int(value):,}".replace(",", NB) + NB + unit


def median(values: list[int]) -> int | None:
    xs = sorted(v for v in values if isinstance(v, int))
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


def uri(payload: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def fit_jpeg(payload: bytes, *, max_bytes: int, max_side: int, ratio: float | None = None) -> bytes:
    """Re-encode a photo to land under `max_bytes`, shrinking quality then size.

    Every byte here becomes four-thirds of a byte of base64 in the agent's
    context, so the budget is the design constraint and picture quality is what
    gets spent against it — not the other way round.
    """
    image = Image.open(io.BytesIO(payload))
    image = image.convert("RGB")
    if ratio:
        image = _centre_crop(image, ratio)
    image.thumbnail((max_side, max_side), Image.LANCZOS)

    best = None
    while True:
        for quality in (72, 60, 50, 42, 35, 28):
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
            best = buffer.getvalue()
            if len(best) <= max_bytes:
                return best
        if min(image.size) <= 64:  # already tiny; take what we have
            return best
        image = image.resize((int(image.width * 0.8), int(image.height * 0.8)), Image.LANCZOS)


def _centre_crop(image: Image.Image, ratio: float) -> Image.Image:
    """Crop to an aspect ratio around the middle, where the subject usually is."""
    width, height = image.size
    if width / height > ratio:
        new_width = int(height * ratio)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = int(width / ratio)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


_BASE_CSS = """<style>
.sh-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.sh-r{display:grid;gap:14px;align-items:center;padding:var(--pad-md);\
background:var(--surface-1);border:1px solid var(--border);border-radius:var(--radius);\
text-decoration:none;color:inherit}
.sh-r:hover{border-color:var(--border-strong)}
.sh-n{font-size:13.5px;font-weight:600;color:var(--text-primary);line-height:1.35}
.sh-m{font-family:var(--font-mono);font-size:11.5px;color:var(--text-secondary);\
font-variant-numeric:tabular-nums}
.sh-p{font-family:var(--font-mono);font-size:18px;font-weight:600;color:var(--text-primary);\
font-variant-numeric:tabular-nums;letter-spacing:-.02em;white-space:nowrap}
.sh-g{font-family:var(--font-mono);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;\
color:var(--text-secondary);border:1px solid var(--border-strong);padding:1px 6px;border-radius:3px}
.sh-g.w{color:var(--text-warning);border-color:var(--border-warning)}
</style>"""

_LIST_CSS = """<style>
.sh-l{display:flex;flex-direction:column;gap:var(--gap-sm);font-family:var(--font-sans)}
.sh-l .sh-r{grid-template-columns:104px minmax(0,1fr) auto}
.sh-t{width:104px;height:78px;object-fit:cover;border-radius:4px;display:block;\
background:var(--surface-0)}
.sh-b{display:flex;flex-direction:column;gap:4px;min-width:0}
.sh-tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:1px}
.sh-side{display:flex;flex-direction:column;align-items:flex-end;gap:3px;text-align:right}
.sh-d{font-family:var(--font-mono);font-size:11px;font-variant-numeric:tabular-nums;\
color:var(--text-secondary);white-space:nowrap}
.sh-d.u{color:var(--text-success)}
.sh-f{font-family:var(--font-mono);font-size:11px;color:var(--text-muted);\
padding-top:var(--gap-xs)}
</style>"""

_DETAIL_CSS = """<style>
.sh-one{font-family:var(--font-sans)}
.sh-one .sh-r{grid-template-columns:1fr;gap:var(--gap-sm)}
.sh-gal{display:grid;grid-template-columns:repeat(auto-fit,minmax(76px,1fr));gap:5px}
.sh-gal img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:4px;display:block;\
background:var(--surface-0)}
.sh-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sh-tags{display:flex;gap:5px;flex-wrap:wrap}
.sh-spec{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:var(--gap-xs)}
.sh-c{background:var(--surface-0);border:1px solid var(--border);border-radius:6px;\
padding:7px 9px}
.sh-k{font-family:var(--font-mono);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;\
color:var(--text-muted)}
.sh-v{font-family:var(--font-mono);font-size:13px;color:var(--text-primary);\
font-variant-numeric:tabular-nums}
.sh-q{font-family:var(--font-voice);font-size:13px;color:var(--text-secondary);line-height:1.55}
</style>"""


def _tags(row: dict[str, Any]) -> str:
    """Only what changes how a price should be read."""
    out = []
    trade = row.get("trade_type")
    if trade and trade.lower() != "til salgs":
        out.append((trade, True))
    form = row.get("sales_form")
    if form and not str(form).lower().startswith("bruktbil"):
        out.append((form, True))
    if row.get("seller_type"):
        out.append(("Private" if row["seller_type"] == "private" else "Dealer", False))
    return "".join(
        f'<span class="sh-g{" w" if warn else ""}">{esc(text)}</span>' for text, warn in out
    )


def car_name(row: dict[str, Any]) -> str:
    """"Tesla Model 3" plus its variant, without the dealer keyword dump.

    `model_specification` is sometimes a real trim ("Long Range AWD") and
    sometimes an advert ("SR / 415km / Skinn / Autopilot / EU27 / Norsk++++").
    The first segment is the useful half of both.
    """
    heading = (row.get("heading") or "").strip()
    spec = (row.get("model_specification") or "").strip()
    if spec:
        spec = spec.replace("|", "/").split("/")[0].strip(" -–,")
    if not spec or spec.lower() in heading.lower() or len(spec) > 44:
        return heading
    return f"{heading} · {spec}"


def compact_widget(rows: list[dict[str, Any]], thumbs: dict[str, str], *, title: str,
                   market: list[int] | None = None) -> str:
    """A list of listings, laid out like a classified ad: photo, what it is, price.

    `market` is every price the search found, not just the rows shown — a median
    of three hand-picked listings says nothing, a median of the whole result set
    is the number worth comparing against.
    """
    mid = median(market if market else [r.get("price") for r in rows])
    items = []
    for row in rows:
        thumb = thumbs.get(row.get("finnkode", ""))
        picture = (f'<img class="sh-t" src="{thumb}" alt="">' if thumb
                   else '<div class="sh-t"></div>')
        price = row.get("price")
        delta = ""
        if mid and isinstance(price, int):
            gap = price - mid
            if gap == 0:
                delta = '<span class="sh-d">at median</span>'
            else:
                amount = f"{abs(gap):,}".replace(",", NB)
                sign = "−" if gap < 0 else "+"
                cls = " u" if gap < 0 else ""
                delta = f'<span class="sh-d{cls}">{sign}{amount} vs median</span>'
        spec = " · ".join(p for p in (
            str(row["year"]) if isinstance(row.get("year"), int) else None,
            num(row.get("mileage"), "km"),
            row.get("fuel"),
            row.get("location"),
        ) if p)
        tags = _tags(row)
        items.append(
            f'<a class="sh-r" href="{esc(row.get("url"))}">{picture}'
            f'<div class="sh-b"><div class="sh-n">{esc(car_name(row))}</div>'
            f'<div class="sh-m">{esc(spec)}</div>'
            + (f'<div class="sh-tags">{tags}</div>' if tags else "")
            + f'</div><div class="sh-side"><span class="sh-p">{esc(kr(price))}</span>'
            f'{delta}</div></a>'
        )
    count = len(market) if market else len(rows)
    foot = f"Median of {count} matching · {kr(mid)}" if mid else f"{len(rows)} listings"
    return (
        f'<h2 class="sh-sr">{esc(title)}: {len(rows)} FINN listings with thumbnail, '
        f'price, year, mileage and distance from the median asking price.</h2>'
        f'{_BASE_CSS}{_LIST_CSS}'
        f'<div class="sh-l">{"".join(items)}</div>'
        f'<div class="sh-f">{esc(foot)}</div>'
    )


_SPEC = [("year", "Year", ""), ("mileage", "Mileage", "km"), ("fuel", "Fuel", ""),
         ("transmission", "Gearbox", ""), ("power_hp", "Power", "hp"),
         ("owners", "Owners", ""), ("eu_check_next", "EU check", ""),
         ("registration_number", "Reg.", ""), ("condition", "Condition", "")]


def detail_widget(listing: dict[str, Any], photos: list[str]) -> str:
    """One listing, in enough depth to decide whether to open the ad."""
    props = listing.get("properties") or {}
    cells = []
    for key, label, unit in _SPEC:
        value = props.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        elif isinstance(value, int) and unit:
            value = num(value, unit)
        cells.append(f'<div class="sh-c"><div class="sh-k">{esc(label)}</div>'
                     f'<div class="sh-v">{esc(value)}</div></div>')

    tiles = "".join(f'<img src="{p}" alt="">' for p in photos)
    gallery = f'<div class="sh-gal">{tiles}</div>' if tiles else ""
    blurb = (listing.get("description") or "").strip()
    if len(blurb) > 300:
        blurb = blurb[:300].rsplit(" ", 1)[0] + "…"
    tags = _tags({**props, "seller_type": listing.get("seller_type")})
    name = car_name({"heading": listing.get("name"),
                     "model_specification": props.get("model_specification")})

    return (
        f'<h2 class="sh-sr">{esc(name)}, {esc(kr(listing.get("price")))}, '
        f'with photos, key specification and an excerpt of the seller\'s description.</h2>'
        f'{_BASE_CSS}{_DETAIL_CSS}<div class="sh-one">'
        f'<a class="sh-r" href="{esc(listing.get("url"))}">'
        f'<div class="sh-head"><span class="sh-n">{esc(name)}</span>'
        f'<span class="sh-p">{esc(kr(listing.get("price")))}</span></div>'
        + (f'<div class="sh-tags">{tags}</div>' if tags else "")
        + gallery
        + f'<div class="sh-spec">{"".join(cells)}</div>'
        + (f'<div class="sh-q">{esc(blurb)}</div>' if blurb else "")
        + "</a></div>"
    )


async def _thumbs(client: FinnClient, rows: list[dict[str, Any]], budget: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        url, code = row.get("image_url"), row.get("finnkode")
        if not url or not code:
            continue
        try:
            payload, _ = await client.fetch_image(url, width=SOURCE_WIDTH)
            out[code] = uri(fit_jpeg(payload, max_bytes=budget, max_side=THUMB_SIDE, ratio=4 / 3))
        except Exception as exc:
            print(f"! thumbnail {code}: {exc}", file=sys.stderr)
    return out


async def build(args: argparse.Namespace) -> str:
    client = FinnClient()
    if args.mode == "list":
        if args.finnkode:
            # Already-chosen listings: one search is still cheaper than N page
            # fetches, so take the codes from a search the caller already ran.
            raise SystemExit("Pass a search, or use `one <finnkode>` for a single listing.")
        filters = json.loads(args.filters) if args.filters else {}
        result = await client.search(args.vertical, query=args.query, filters=filters)
        rows = [l.to_dict() for l in result.listings]
        market = [r.get("price") for r in rows if isinstance(r.get("price"), int)]
        if args.only:
            by_code = {r.get("finnkode"): r for r in rows}
            rows = [by_code[c] for c in args.only.split(",") if c in by_code]
        rows = rows[: args.limit]
        thumbs = {} if args.no_images else await _thumbs(client, rows, args.thumb_bytes)
        return compact_widget(rows, thumbs, title=args.query or args.vertical, market=market)

    listing = await client.get_listing(args.finnkode)
    urls = listing.get("images") or []
    photos: list[str] = []
    if not args.no_images:
        for url in urls[: args.photos]:
            try:
                data, _ = await client.fetch_image(url, width=SOURCE_WIDTH)
            except Exception as exc:
                print(f"! photo: {exc}", file=sys.stderr)
                continue
            photos.append(
                uri(fit_jpeg(data, max_bytes=args.photo_bytes,
                             max_side=PHOTO_SIDE, ratio=4 / 3)))
    return detail_widget(listing, photos)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sporhund-widget",
        description="Print a chat-widget fragment for FINN listings, to paste into show_widget.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    # On each subcommand rather than the parent, so it reads naturally after it.
    images = argparse.ArgumentParser(add_help=False)
    images.add_argument("--no-images", action="store_true",
                        help="Text only; costs almost nothing.")
    images.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                        help=f"Token ceiling (default {DEFAULT_BUDGET}); photos are "
                             "shed automatically to stay under it.")

    lst = sub.add_parser("list", parents=[images], help="Several listings, compact.")
    lst.add_argument("vertical", choices=("torget", "car", "job"))
    lst.add_argument("query", nargs="?", default="")
    lst.add_argument("--filters", default="", help="JSON object, as for search_finn.")
    lst.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    lst.add_argument("--only", default="", help="Comma-separated finnkoder to keep, in search order.")
    lst.add_argument("--thumb-bytes", type=int, default=THUMB_BYTES,
                     help=f"Bytes per thumbnail before base64 (default {THUMB_BYTES}).")
    lst.set_defaults(finnkode=None)

    one = sub.add_parser("one", parents=[images], help="A single listing, in detail.")
    one.add_argument("finnkode")
    one.add_argument("--photos", type=int, default=MAX_PHOTOS,
                     help=f"How many photos (default {MAX_PHOTOS}); each costs ~700 tokens.")
    one.add_argument("--photo-bytes", type=int, default=PHOTO_BYTES,
                     help=f"Bytes per photo before base64 (default {PHOTO_BYTES}). Large\n                           blobs do not survive being carried into a widget, so keep this small.")

    args = parser.parse_args()
    fragment, note = asyncio.run(_within_budget(args))
    print(f"# ~{len(fragment) // 4} tokens{note}", file=sys.stderr)
    print(fragment)


async def _within_budget(args: argparse.Namespace) -> tuple[str, str]:
    """Build the widget, shedding image quality until it fits the budget.

    Downgrading beats warning: a fragment over budget gets truncated out of the
    tool result, and recovering it costs more than the photos were worth.
    """
    fragment = await build(args)
    if args.no_images or len(fragment) // 4 <= args.budget:
        return fragment, ""

    # Shed picture quality before shedding pictures: a smaller photo still shows
    # the car, while no photo at all defeats the point of a widget.
    if args.mode == "list":
        steps = [("thumb_bytes", 1_100, "thumbnails compressed harder"),
                 ("thumb_bytes", 700, "thumbnails compressed hardest")]
    else:
        steps = [("photos", 11, "showing 11 photos"),
                 ("photos", 10, "showing 10 photos"),
                 ("photos", 8, "showing 8 photos"),
                 ("photos", 6, "showing 6 photos")]
    for attribute, value, said in steps:
        setattr(args, attribute, value)
        fragment = await build(args)
        if len(fragment) // 4 <= args.budget:
            return fragment, f" ({said} to fit the budget)"

    args.no_images = True
    fragment = await build(args)
    return fragment, " (photos dropped entirely; raise --budget to keep them)"


if __name__ == "__main__":
    main()
