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
import json
import sys
from typing import Any

from .finn import FinnClient

LIST_WIDTH = 80
HERO_WIDTH = 240
STRIP_WIDTH = 80
DEFAULT_LIMIT = 6
# base64 chars / 4 ~= tokens. The fragment has to survive one tool result in
# one piece: an oversized print is truncated to a file, and reading that file
# back is the second pass this whole design exists to avoid. So the budget is
# enforced by downgrading images, not by hoping.
DEFAULT_BUDGET = 5_000

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


def uri(payload: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


CSS = """<style>
.sh-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.sh-l{display:flex;flex-direction:column;gap:var(--gap-sm);font-family:var(--font-sans)}
.sh-r{display:grid;grid-template-columns:72px 1fr;gap:var(--pad-md);align-items:center;\
padding:var(--pad-md);background:var(--surface-1);border:1px solid var(--border);\
border-radius:var(--radius);text-decoration:none;color:inherit}
.sh-r:hover{border-color:var(--border-strong)}
.sh-t{width:72px;height:54px;object-fit:cover;border-radius:4px;display:block;background:var(--surface-0)}
.sh-b{display:flex;flex-direction:column;gap:3px;min-width:0;align-items:flex-start}
.sh-g{font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;\
color:var(--text-accent);background:var(--bg-accent);padding:1px 6px;border-radius:3px}
.sh-g.w{color:var(--text-warning);background:var(--bg-warning)}
.sh-h{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.sh-p{font-family:var(--font-mono);font-size:18px;font-weight:600;color:var(--text-primary);\
font-variant-numeric:tabular-nums}
.sh-d{font-family:var(--font-mono);font-size:11px;font-variant-numeric:tabular-nums;color:var(--text-secondary)}
.sh-d.u{color:var(--text-success)}
.sh-n{font-size:13px;font-weight:600;color:var(--text-primary)}
.sh-m{font-family:var(--font-mono);font-size:11.5px;color:var(--text-secondary)}
.sh-f{font-family:var(--font-mono);font-size:11px;color:var(--text-muted);padding-top:var(--gap-xs)}
.sh-hero{width:100%;max-height:230px;object-fit:cover;border-radius:var(--radius);display:block}\
.sh-hero.sm{width:96px;height:72px}
.sh-strip{display:flex;gap:6px;margin-top:6px}
.sh-strip img{width:56px;height:42px;object-fit:cover;border-radius:3px;display:block}
.sh-spec{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:var(--gap-xs);\
margin-top:var(--gap-sm)}
.sh-c{background:var(--surface-1);border:1px solid var(--border);border-radius:var(--radius);\
padding:var(--pad-sm)}
.sh-k{font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;\
color:var(--text-muted)}
.sh-v{font-family:var(--font-mono);font-size:13px;color:var(--text-primary);font-variant-numeric:tabular-nums}
.sh-q{font-family:var(--font-voice);font-size:13px;color:var(--text-secondary);line-height:1.55;\
margin-top:var(--gap-sm)}
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


def compact_widget(rows: list[dict[str, Any]], thumbs: dict[str, str], *, title: str,
                   market: list[int] | None = None) -> str:
    """A list of listings: thumbnail, price, what it is, how it sits vs the market.

    `market` is every price the search found, not just the rows shown — a median
    of three hand-picked listings says nothing, a median of the whole result set
    is the number worth comparing against."""
    mid = median(market if market else [r.get("price") for r in rows])
    items = []
    for row in rows:
        code = row.get("finnkode", "")
        thumb = thumbs.get(code)
        picture = (
            f'<img class="sh-t" src="{thumb}" alt="">' if thumb
            else '<div class="sh-t"></div>'
        )
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
                delta = (f'<span class="sh-d{cls}">{sign}{amount} vs median</span>')
        spec = " · ".join(p for p in (
            str(row["year"]) if isinstance(row.get("year"), int) else None,
            num(row.get("mileage"), "km"),
            row.get("fuel"),
            row.get("location"),
        ) if p)
        items.append(
            f'<a class="sh-r" href="{esc(row.get("url"))}">{picture}<div class="sh-b">'
            f'<div>{_tags(row)}</div>'
            f'<div class="sh-h"><span class="sh-p">{esc(kr(price))}</span>{delta}</div>'
            f'<div class="sh-n">{esc(row.get("heading"))}</div>'
            f'<div class="sh-m">{esc(spec)}</div></div></a>'
        )
    count = len(market) if market else len(rows)
    foot = f"Median of {count} matching · {kr(mid)}" if mid else f"{len(rows)} listings"
    return (
        f'<h2 class="sh-sr">{esc(title)}: {len(rows)} FINN listings with thumbnail, '
        f'price, year, mileage and distance from the median asking price.</h2>{CSS}'
        f'<div class="sh-l">{"".join(items)}</div>'
        f'<div class="sh-f">{esc(foot)}</div>'
    )


_SPEC = [("year", "Year", ""), ("mileage", "Mileage", "km"), ("fuel", "Fuel", ""),
         ("transmission", "Gearbox", ""), ("power_hp", "Power", "hp"),
         ("owners", "Owners", ""), ("eu_check_next", "EU check", ""),
         ("registration_number", "Reg.", ""), ("condition", "Condition", "")]


def detail_widget(listing: dict[str, Any], hero: str | None, strip: list[str],
                  *, hero_width: int = HERO_WIDTH) -> str:
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

    # A small source stretched full-width just looks broken; show it small.
    size = "" if hero_width > LIST_WIDTH else " sm"
    picture = f'<img class="sh-hero{size}" src="{hero}" alt="">' if hero else ""
    thumbs = "".join(f'<img src="{s}" alt="">' for s in strip)
    strip_html = f'<div class="sh-strip">{thumbs}</div>' if thumbs else ""
    blurb = (listing.get("description") or "").strip()
    if len(blurb) > 260:
        blurb = blurb[:260].rsplit(" ", 1)[0] + "…"

    return (
        f'<h2 class="sh-sr">{esc(listing.get("name"))}, {esc(kr(listing.get("price")))}, '
        f'with photo, key specification and an excerpt of the seller\'s description.</h2>{CSS}'
        f'<a class="sh-r" style="grid-template-columns:1fr;gap:var(--gap-sm)" '
        f'href="{esc(listing.get("url"))}">'
        f'{picture}{strip_html}'
        f'<div class="sh-b" style="width:100%">'
        f'<div class="sh-h"><span class="sh-p">{esc(kr(listing.get("price")))}</span>'
        f'{_tags(props)}</div>'
        f'<div class="sh-n">{esc(listing.get("name"))}</div>'
        f'<div class="sh-spec" style="width:100%">{"".join(cells)}</div>'
        + (f'<div class="sh-q">{esc(blurb)}</div>' if blurb else "")
        + "</div></a>"
    )


async def _thumbs(client: FinnClient, rows: list[dict[str, Any]], width: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        url, code = row.get("image_url"), row.get("finnkode")
        if not url or not code:
            continue
        try:
            payload, mime = await client.fetch_image(url, width=width)
        except Exception as exc:
            print(f"! thumbnail {code}: {exc}", file=sys.stderr)
            continue
        out[code] = uri(payload, mime)
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
        thumbs = {} if args.no_images else await _thumbs(client, rows, args.width)
        return compact_widget(rows, thumbs, title=args.query or args.vertical, market=market)

    listing = await client.get_listing(args.finnkode)
    urls = listing.get("images") or []
    hero, strip = None, []
    if not args.no_images and urls:
        payload, mime = await client.fetch_image(urls[0], width=args.hero)
        hero = uri(payload, mime)
        for url in urls[1 : 1 + args.strip]:
            try:
                data, mt = await client.fetch_image(url, width=STRIP_WIDTH)
            except Exception:
                continue
            strip.append(uri(data, mt))
    return detail_widget(listing, hero, strip, hero_width=args.hero)


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
    lst.add_argument("--width", type=int, default=LIST_WIDTH,
                     help=f"Thumbnail width (default {LIST_WIDTH}; 240 costs ~5x more).")
    lst.set_defaults(finnkode=None)

    one = sub.add_parser("one", parents=[images], help="A single listing, in detail.")
    one.add_argument("finnkode")
    one.add_argument("--strip", type=int, default=2,
                     help="Extra small photos (default 2; each adds ~1k tokens, 0 saves most).")
    one.add_argument("--hero", type=int, default=LIST_WIDTH,
                     help=f"Hero photo width (default {LIST_WIDTH}). {HERO_WIDTH} gives a\n                           real photo but costs ~5.9k tokens, so raise --budget with it.")

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

    steps = []
    if args.mode == "list" and getattr(args, "width", LIST_WIDTH) > LIST_WIDTH:
        steps.append(("width", LIST_WIDTH, f"thumbnails dropped to {LIST_WIDTH}w"))
    if args.mode == "one":
        steps.append(("strip", 0, "small photos dropped"))
        steps.append(("hero", LIST_WIDTH, f"hero dropped to {LIST_WIDTH}w"))
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
