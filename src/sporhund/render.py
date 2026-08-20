"""Render listings as a self-contained HTML page.

The MCP tools return facts; this turns them into something a person can look
at — a results grid with thumbnails, or a full dossier for one listing.

Photos are inlined as data URIs rather than linked, because the page is meant
to be published as an artifact and artifact pages cannot load remote images.
That means the rendered file *contains* the seller's photographs: keep it
private, and see NOTICE.md before sharing one.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
import sys
from typing import Any, Iterable

from .finn import FinnClient, Listing

THUMB_WIDTH = 480
GALLERY_WIDTH = 960
MAX_GALLERY_IMAGES = 12

_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;500;600&"
    "family=IBM+Plex+Sans:wght@400;500;600;700&"
    "family=IBM+Plex+Serif:ital,wght@0,400;1,400&display=swap"
)


def esc(value: Any) -> str:
    """HTML-escape anything, including None and numbers."""
    return html.escape("" if value is None else str(value), quote=True)


def data_uri(payload: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


# Norwegian groups thousands with a space; a non-breaking one, so a price or a
# mileage never wraps down the middle of the number on a narrow card.
NB_SPACE = "\u00a0"


def kroner(value: Any) -> str:
    """Norwegian thousands grouping: 249000 -> '249 000 kr'."""
    if not isinstance(value, int):
        return "Price not stated"
    return f"{value:,}".replace(",", NB_SPACE) + NB_SPACE + "kr"


def number(value: Any, unit: str = "") -> str | None:
    if not isinstance(value, (int, float)):
        return None
    text = f"{int(value):,}".replace(",", NB_SPACE)
    return f"{text}{NB_SPACE}{unit}".strip() if unit else text


def spec_line(d: dict[str, Any]) -> str:
    """The one-line summary under a card heading: year, mileage, fuel."""
    parts = [
        str(d["year"]) if isinstance(d.get("year"), int) else None,
        number(d.get("mileage"), "km"),
        d.get("fuel"),
        d.get("transmission"),
    ]
    return " · ".join(p for p in parts if p)


def position_bar(pos: dict[str, Any], subject_price: int) -> str:
    """Where a price sits between the cheapest and dearest comparable.

    A percentile is a number; this is the same fact as a picture, which is the
    point of rendering at all.
    """
    lo, hi = pos.get("min"), pos.get("max")
    median = pos.get("median")
    if not all(isinstance(v, int) for v in (lo, hi, median)) or hi <= lo:
        return ""

    def at(value: int) -> float:
        return max(0.0, min(100.0, 100 * (value - lo) / (hi - lo)))

    subject_pct = at(subject_price)
    delta = pos.get("delta_vs_median_pct")
    verdict = "under median" if isinstance(delta, int) and delta < 0 else "over median"
    return f"""
      <figure class="bar">
        <div class="bar-track" role="img" aria-label="This ad at {kroner(subject_price)},
             against {pos.get('n')} comparables from {kroner(lo)} to {kroner(hi)},
             median {kroner(median)}.">
          <span class="bar-median" style="left:{at(median):.1f}%"></span>
          <span class="bar-subject" style="left:{subject_pct:.1f}%"></span>
        </div>
        <div class="bar-ends">
          <span>{esc(kroner(lo))}</span>
          <span class="bar-caption">median {esc(kroner(median))}</span>
          <span>{esc(kroner(hi))}</span>
        </div>
        <figcaption>This ad sits at the {esc(pos.get('percentile'))}th percentile of
          {esc(pos.get('n'))} comparable asking prices — {esc(abs(delta) if isinstance(delta, int) else '')}%
          {esc(verdict)}.</figcaption>
      </figure>"""


def stylesheet() -> str:
    """Tokens first, components second — so both themes resolve as a set.

    Every colour is defined on bare :root and only *redefined* in the theme
    blocks; a colour whose only definition sits behind a media query never
    applies in the un-stamped "system" state.
    """
    return """
    :root {
      --paper:#f2f5f4; --card:#fdfefe; --ink:#141a19; --ink-2:#5c6866;
      --rule:#d5dcda; --accent:#1d5c58; --accent-soft:#e3edeb;
      --flag:#93361f; --flag-soft:#f6e6e1; --ok:#2b6647;
      --shadow:0 1px 2px rgba(20,26,25,.06), 0 8px 24px -16px rgba(20,26,25,.28);
      --sans:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
      --mono:"IBM Plex Mono",ui-monospace,"SF Mono",monospace;
      --serif:"IBM Plex Serif",Georgia,serif;
    }
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) {
        --paper:#0f1413; --card:#161d1c; --ink:#e7ecea; --ink-2:#95a3a0;
        --rule:#28312f; --accent:#74c0b7; --accent-soft:#172a28;
        --flag:#e2907a; --flag-soft:#2b1c18; --ok:#6cbf97;
        --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
      }
    }
    :root[data-theme="dark"] {
      --paper:#0f1413; --card:#161d1c; --ink:#e7ecea; --ink-2:#95a3a0;
      --rule:#28312f; --accent:#74c0b7; --accent-soft:#172a28;
      --flag:#e2907a; --flag-soft:#2b1c18; --ok:#6cbf97;
      --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
    }

    body { background:var(--paper); color:var(--ink); font-family:var(--sans);
           line-height:1.5; margin:0; padding:clamp(16px,3vw,40px); }
    .wrap { max-width:1180px; margin:0 auto; display:flex; flex-direction:column; gap:28px; }
    a { color:var(--accent); }
    img { max-width:100%; display:block; }
    figure { margin:0; }

    /* Masthead ------------------------------------------------------------ */
    .head { display:flex; flex-direction:column; gap:6px;
            border-bottom:1px solid var(--rule); padding-bottom:18px; }
    .eyebrow { font-family:var(--mono); font-size:.72rem; letter-spacing:.14em;
               text-transform:uppercase; color:var(--accent); }
    .head h1 { font-size:clamp(1.5rem,3.2vw,2.1rem); font-weight:600; margin:0;
               text-wrap:balance; letter-spacing:-.015em; }
    .head .sub { color:var(--ink-2); font-size:.9rem; font-family:var(--mono); }

    /* Results grid -------------------------------------------------------- */
    .grid { display:grid; gap:20px;
            grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); }
    .card { background:var(--card); border:1px solid var(--rule); border-radius:4px;
            overflow:hidden; display:flex; flex-direction:column;
            box-shadow:var(--shadow); transition:transform .12s ease; }
    .card:hover, .card:focus-within { transform:translateY(-2px); }
    .thumb { aspect-ratio:4/3; background:var(--accent-soft); overflow:hidden; }
    .thumb img { width:100%; height:100%; object-fit:cover; }
    .thumb.empty { display:grid; place-items:center; color:var(--ink-2);
                   font-family:var(--mono); font-size:.72rem; letter-spacing:.1em; }
    .card-body { padding:14px 15px 16px; display:flex; flex-direction:column; gap:7px; flex:1; }
    .price { font-family:var(--mono); font-size:1.22rem; font-weight:600;
             font-variant-numeric:tabular-nums; letter-spacing:-.02em; }
    .card h2 { font-size:.94rem; font-weight:600; margin:0; line-height:1.32;
               text-wrap:balance; }
    .card h2 a { color:inherit; text-decoration:none; }
    .card h2 a:hover { text-decoration:underline; }
    .card h2 a:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
    .meta { font-family:var(--mono); font-size:.75rem; color:var(--ink-2);
            font-variant-numeric:tabular-nums; }
    .chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:auto; padding-top:4px; }
    .chip { font-family:var(--mono); font-size:.66rem; letter-spacing:.06em;
            text-transform:uppercase; padding:2px 7px; border-radius:2px;
            background:var(--accent-soft); color:var(--accent); }
    .chip.warn { background:var(--flag-soft); color:var(--flag); }

    /* Detail view --------------------------------------------------------- */
    .dossier { display:grid; gap:28px; grid-template-columns:minmax(0,1.45fr) minmax(270px,1fr); }
    @media (max-width:880px) { .dossier { grid-template-columns:1fr; } }
    .stage { background:var(--card); border:1px solid var(--rule); border-radius:4px;
             overflow:hidden; box-shadow:var(--shadow); }
    .stage img { width:100%; aspect-ratio:4/3; object-fit:contain; background:var(--accent-soft); }
    .strip { display:flex; gap:8px; overflow-x:auto; padding:10px; }
    .strip button { flex:0 0 76px; padding:0; border:1px solid var(--rule);
                    border-radius:3px; overflow:hidden; background:none; cursor:pointer; }
    .strip button[aria-current="true"] { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); }
    .strip button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    .strip img { width:100%; aspect-ratio:4/3; object-fit:cover; }

    .facts { display:flex; flex-direction:column; gap:16px; }
    .headline-price { font-family:var(--mono); font-size:1.85rem; font-weight:600;
                      font-variant-numeric:tabular-nums; letter-spacing:-.03em; }
    dl.spec { display:grid; grid-template-columns:auto 1fr; gap:0; margin:0;
              border-top:1px solid var(--rule); }
    dl.spec dt, dl.spec dd { padding:7px 0; border-bottom:1px solid var(--rule); margin:0; }
    dl.spec dt { font-family:var(--mono); font-size:.72rem; letter-spacing:.08em;
                 text-transform:uppercase; color:var(--ink-2); padding-right:18px; }
    dl.spec dd { font-family:var(--mono); font-size:.85rem; text-align:right;
                 font-variant-numeric:tabular-nums; }

    section.block { display:flex; flex-direction:column; gap:12px; }
    section.block > h2 { font-size:.78rem; font-family:var(--mono); letter-spacing:.14em;
                         text-transform:uppercase; color:var(--accent); margin:0;
                         padding-bottom:8px; border-bottom:1px solid var(--rule); }
    /* The seller's own words, set apart from our data by the serif. */
    .prose { font-family:var(--serif); font-size:.96rem; line-height:1.62;
             max-width:66ch; white-space:pre-wrap; }
    .equipment { display:flex; flex-wrap:wrap; gap:6px; padding:0; margin:0; list-style:none; }
    .equipment li { font-size:.78rem; padding:3px 9px; border:1px solid var(--rule);
                    border-radius:2px; color:var(--ink-2); }

    .findings { display:flex; flex-direction:column; gap:8px; padding:0; margin:0; list-style:none; }
    .finding { display:flex; gap:11px; align-items:flex-start; padding:11px 13px;
               background:var(--card); border:1px solid var(--rule);
               border-left:3px solid var(--ink-2); border-radius:3px; font-size:.88rem; }
    .finding.warn { border-left-color:var(--flag); }
    .finding.ok { border-left-color:var(--ok); }
    .finding .tag { font-family:var(--mono); font-size:.66rem; letter-spacing:.08em;
                    text-transform:uppercase; color:var(--ink-2); flex:0 0 62px; padding-top:2px; }

    /* Price-position bar -------------------------------------------------- */
    .bar { display:flex; flex-direction:column; gap:9px; }
    .bar-track { position:relative; height:8px; border-radius:4px;
                 background:linear-gradient(90deg,var(--accent-soft),var(--rule)); }
    .bar-median, .bar-subject { position:absolute; top:50%; }
    .bar-median { width:2px; height:16px; background:var(--ink-2); transform:translate(-1px,-50%); }
    .bar-subject { width:13px; height:13px; border-radius:50%; background:var(--accent);
                   border:2px solid var(--card); transform:translate(-50%,-50%); }
    .bar-ends { display:flex; justify-content:space-between; font-family:var(--mono);
                font-size:.72rem; color:var(--ink-2); font-variant-numeric:tabular-nums; }
    .bar-caption { color:var(--ink); }
    .bar figcaption { font-size:.85rem; color:var(--ink-2); max-width:60ch; }

    .foot { border-top:1px solid var(--rule); padding-top:16px; font-size:.78rem;
            color:var(--ink-2); font-family:var(--mono); line-height:1.7; }
    .scroll-x { overflow-x:auto; }
    @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
    """


def page_shell(title: str, body: str) -> str:
    """Artifact-style page content: no doctype/head/body, which the host adds."""
    return (
        f'<title>{esc(title)}</title>\n'
        f'<link rel="stylesheet" href="{_FONTS}">\n'
        f"<style>{stylesheet()}</style>\n"
        f'<div class="wrap">{body}</div>\n'
    )


def _chips(d: dict[str, Any]) -> str:
    """Only chips that change a decision: who is selling, and what kind of ad."""
    chips: list[tuple[str, bool]] = []
    seller = d.get("seller_type")
    if seller:
        chips.append(("Private seller" if seller == "private" else "Dealer", False))
    trade = d.get("trade_type")
    if trade and trade.lower() not in ("til salgs",):
        chips.append((trade, True))
    sales_form = d.get("sales_form")
    if sales_form and not str(sales_form).lower().startswith("bruktbil"):
        chips.append((sales_form, True))
    return "".join(
        f'<span class="chip{" warn" if warn else ""}">{esc(text)}</span>'
        for text, warn in chips
    )


def card(d: dict[str, Any], thumb: str | None) -> str:
    picture = (
        f'<div class="thumb"><img src="{thumb}" alt="" loading="lazy"></div>'
        if thumb
        else '<div class="thumb empty">No photo</div>'
    )
    line = spec_line(d)
    place = " · ".join(p for p in (d.get("location"),) if p)
    return f"""
      <article class="card">
        {picture}
        <div class="card-body">
          <div class="price">{esc(kroner(d.get("price")))}</div>
          <h2><a href="{esc(d.get("url"))}" target="_blank" rel="noopener noreferrer">{esc(d.get("heading"))}</a></h2>
          {f'<div class="meta">{esc(line)}</div>' if line else ""}
          {f'<div class="meta">{esc(place)}</div>' if place else ""}
          <div class="chips">{_chips(d)}</div>
        </div>
      </article>"""


def results_page(
    rows: list[dict[str, Any]],
    thumbs: dict[str, str],
    *,
    title: str,
    subtitle: str,
) -> str:
    cards = "".join(card(d, thumbs.get(d.get("finnkode", ""))) for d in rows)
    body = f"""
      <header class="head">
        <div class="eyebrow">Sporhund · FINN.no</div>
        <h1>{esc(title)}</h1>
        <div class="sub">{esc(subtitle)}</div>
      </header>
      <div class="grid">{cards}</div>
      <footer class="foot">
        Listings and photographs belong to their sellers and to FINN.no; this page
        is a private view of a live search, not a copy of FINN. Prices are asking
        prices. Follow a heading to the original ad.
      </footer>"""
    return page_shell(title, body)


_SPEC_LABELS = [
    ("year", "Year", ""),
    ("mileage", "Mileage", "km"),
    ("fuel", "Fuel", ""),
    ("transmission", "Transmission", ""),
    ("power_hp", "Power", "hp"),
    ("owners", "Owners", ""),
    ("first_registration", "First registered", ""),
    ("eu_check_next", "Next EU check", ""),
    ("body_type", "Body", ""),
    ("wheel_drive", "Drive", ""),
    ("no_of_seats", "Seats", ""),
    ("registration_number", "Registration", ""),
    ("sales_form", "Sales form", ""),
    ("condition", "Condition", ""),
    ("location", "Location", ""),
]


def spec_rows(props: dict[str, Any]) -> str:
    rows = []
    for key, label, unit in _SPEC_LABELS:
        value = props.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        elif isinstance(value, int) and unit:
            value = number(value, unit)
        rows.append(f"<dt>{esc(label)}</dt><dd>{esc(value)}</dd>")
    return f'<dl class="spec">{"".join(rows)}</dl>' if rows else ""


def gallery(images: list[str]) -> str:
    """Main stage plus a thumbnail strip. Buttons, so it works from a keyboard."""
    if not images:
        return '<div class="stage"><div class="thumb empty">No photos</div></div>'
    strip = "".join(
        f'<button type="button" data-index="{i}" aria-current="{"true" if i == 0 else "false"}"'
        f' aria-label="Show photo {i + 1} of {len(images)}"><img src="{src}" alt=""></button>'
        for i, src in enumerate(images)
    )
    return f"""
      <div class="stage">
        <img id="stage-image" src="{images[0]}" alt="Listing photo 1 of {len(images)}">
        {f'<div class="strip scroll-x">{strip}</div>' if len(images) > 1 else ""}
      </div>"""


_GALLERY_JS = """
<script>
(function () {
  var stage = document.getElementById('stage-image');
  var buttons = Array.prototype.slice.call(document.querySelectorAll('.strip button'));
  if (!stage || !buttons.length) return;
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      var image = button.querySelector('img');
      if (!image) return;
      stage.src = image.src;
      stage.alt = button.getAttribute('aria-label') || '';
      buttons.forEach(function (other) {
        other.setAttribute('aria-current', String(other === button));
      });
    });
  });
})();
</script>"""


def findings_list(findings: Iterable[dict[str, Any]]) -> str:
    items = []
    for f in findings:
        severity = str(f.get("severity", "info")).lower()
        css = "warn" if severity in ("warning", "alert", "critical") else (
            "ok" if severity == "ok" else "")
        items.append(
            f'<li class="finding {css}"><span class="tag">{esc(severity)}</span>'
            f"<span><strong>{esc(f.get('issue') or '')}</strong> "
            f"{esc(f.get('detail') or '')}</span></li>"
        )
    return f'<ul class="findings">{"".join(items)}</ul>' if items else ""


def listing_page(
    listing: dict[str, Any],
    images: list[str],
    *,
    registry: dict[str, Any] | None = None,
    comparables: dict[str, Any] | None = None,
) -> str:
    props = dict(listing.get("properties") or {})
    props.setdefault("location", listing.get("location"))
    name = listing.get("name") or "Listing"
    description = listing.get("description") or ""
    equipment = listing.get("equipment") or []

    blocks = []
    if description.strip():
        blocks.append(
            "<section class=\"block\"><h2>Seller's own description</h2>"
            f'<div class="prose">{esc(description.strip())}</div></section>'
        )
    if equipment:
        items = "".join(f"<li>{esc(e)}</li>" for e in equipment)
        blocks.append(
            '<section class="block"><h2>Equipment</h2>'
            f'<ul class="equipment">{items}</ul></section>'
        )
    if registry is not None:
        findings = registry.get("findings") or []
        # A clean check is a finding too — silence would read as "not checked".
        body_html = findings_list(findings) if findings else (
            '<ul class="findings"><li class="finding ok"><span class="tag">clear</span>'
            f"<span>{esc(registry.get('verdict') or 'Nothing in the registry contradicts this ad.')}"
            "</span></li></ul>"
        )
        blocks.append(
            '<section class="block"><h2>Vehicle registry vs. the ad</h2>'
            f"{body_html}</section>"
        )
    if comparables and comparables.get("position"):
        price = listing.get("price")
        bar = position_bar(comparables["position"], price) if isinstance(price, int) else ""
        note = comparables.get("subject_price_note") or comparables.get("warning") or ""
        blocks.append(
            '<section class="block"><h2>Market position</h2>'
            f"{bar}"
            + (f'<div class="finding warn"><span class="tag">note</span>'
               f"<span>{esc(note)}</span></div>" if note else "")
            + "</section>"
        )

    body = f"""
      <header class="head">
        <div class="eyebrow">Sporhund · FINN.no</div>
        <h1>{esc(name)}</h1>
        <div class="sub">{esc(listing.get("url") or "")}</div>
      </header>
      <div class="dossier">
        {gallery(images)}
        <div class="facts">
          <div class="headline-price">{esc(kroner(listing.get("price")))}</div>
          {spec_rows(props)}
          <a href="{esc(listing.get("url"))}" target="_blank" rel="noopener noreferrer">Open the ad on FINN →</a>
        </div>
      </div>
      {"".join(blocks)}
      <footer class="foot">
        Photographs and ad text belong to the seller and to FINN.no, and are shown
        here for private appraisal only — do not republish this page. Prices are
        asking prices, not sold prices.
      </footer>{_GALLERY_JS}"""
    return page_shell(name, body)


# -- fetching ------------------------------------------------------------------


async def _thumbnails(
    client: FinnClient, rows: list[dict[str, Any]], width: int
) -> dict[str, str]:
    """One thumbnail per row, inlined. Failures drop the image, not the page."""
    thumbs: dict[str, str] = {}
    for row in rows:
        url, code = row.get("image_url"), row.get("finnkode")
        if not url or not code:
            continue
        try:
            payload, mime = await client.fetch_image(url, width=width)
        except Exception as exc:  # a missing photo must not lose the listing
            print(f"  ! thumbnail failed for {code}: {exc}", file=sys.stderr)
            continue
        thumbs[code] = data_uri(payload, mime)
    return thumbs


async def _gallery_images(
    client: FinnClient, urls: list[str], width: int, limit: int
) -> list[str]:
    out: list[str] = []
    for url in urls[:limit]:
        try:
            payload, mime = await client.fetch_image(url, width=width)
        except Exception as exc:
            print(f"  ! image failed: {exc}", file=sys.stderr)
            continue
        out.append(data_uri(payload, mime))
    return out


async def build_results(args: argparse.Namespace) -> str:
    client = FinnClient()
    filters = json.loads(args.filters) if args.filters else {}
    result = await client.search(
        args.vertical, query=args.query, filters=filters, page=args.page
    )
    rows = [l.to_dict() for l in result.listings][: args.limit]
    thumbs = {} if args.no_images else await _thumbnails(client, rows, args.thumb_width)
    total = result.total_matches
    subtitle = " · ".join(
        p for p in (
            f'"{args.query}"' if args.query else None,
            f"{total} matches" if total is not None else None,
            f"showing {len(rows)}",
            ", ".join(f"{k}={v}" for k, v in filters.items()) or None,
        ) if p
    )
    title = (args.title or (args.query.strip() if args.query else "") or
             f"{args.vertical.title()} on FINN")
    return results_page(rows, thumbs, title=title, subtitle=subtitle)


async def build_listing(args: argparse.Namespace) -> str:
    client = FinnClient()
    listing = await client.get_listing(args.finnkode)
    urls = listing.get("images") or []
    images = [] if args.no_images else await _gallery_images(
        client, urls, args.image_width, args.max_images
    )

    registry = None
    if args.verify:
        # Best effort: no key, no network, or not a car must not lose the page.
        try:
            from .server import verify_car
            registry = await verify_car(args.finnkode)
        except Exception as exc:
            print(f"  ! registry check skipped: {exc}", file=sys.stderr)

    comparables = None
    if args.comparables:
        try:
            from .server import find_comparables
            comparables = await find_comparables(args.finnkode)
        except Exception as exc:
            print(f"  ! comparables skipped: {exc}", file=sys.stderr)

    return listing_page(listing, images, registry=registry, comparables=comparables)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sporhund-render",
        description="Render FINN listings as a self-contained HTML page.",
    )
    parser.add_argument("--out", required=True, help="File to write the page to.")
    parser.add_argument("--no-images", action="store_true",
                        help="Skip photos — much faster, much smaller.")
    sub = parser.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("search", help="A grid of results, one card per listing.")
    s.add_argument("vertical", choices=("torget", "car", "job"))
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--filters", default="", help="JSON object, as for search_finn.")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--limit", type=int, default=24, help="Cards to render (default 24).")
    s.add_argument("--thumb-width", type=int, default=THUMB_WIDTH)
    s.add_argument("--title", default="", help="Page title; defaults to the query.")

    d = sub.add_parser("listing", help="One listing in full, with its gallery.")
    d.add_argument("finnkode")
    d.add_argument("--max-images", type=int, default=MAX_GALLERY_IMAGES)
    d.add_argument("--image-width", type=int, default=GALLERY_WIDTH)
    d.add_argument("--verify", action="store_true",
                   help="Include the vehicle-registry check (needs a key).")
    d.add_argument("--comparables", action="store_true",
                   help="Include the market-position bar.")

    args = parser.parse_args()
    build = build_results if args.mode == "search" else build_listing
    page = asyncio.run(build(args))
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(page)
    print(f"{args.out} · {len(page) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
