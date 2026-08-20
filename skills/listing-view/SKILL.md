---
name: listing-view
description: Render FINN.no listings as a visual page instead of a wall of text — a thumbnail grid for search results, or a full dossier with photo gallery, spec table, registry check and market position for one listing. Use whenever showing the user search results from Sporhund, or when they ask about a specific listing, unless they only wanted a single fact.
---

# Showing listings visually

A FINN listing is mostly a photograph and a price. Reading twenty of them back
as bullet points throws away the part a buyer actually judges on. Sporhund ships
a renderer that turns tool output into a self-contained HTML page; publish that
as an artifact and the user gets something they can actually look at.

**Never hand-write this HTML.** The renderer already handles image fetching and
inlining, both colour themes, responsive layout, escaping and the footer. Your
job is to choose the view, run it, and publish it.

## First: has the client already drawn it?

Sporhund ships MCP Apps views. In a client that supports them — Claude Desktop,
claude.ai, VS Code — `search_finn` and `get_listing` render themselves in the
conversation automatically, with live photos from FINN's CDN. **Nothing for you
to do: don't render a second copy.** Just comment on what the user is looking at.

Reach for the renderer below when the client showed no view (you will see only
JSON come back), or when the user wants something the inline view does not do:
a page they can keep, a registry check and market position side by side, or a
grid put together from several searches.

## Which view

| Situation | View |
| --- | --- |
| You ran `search_finn`, or the user is browsing | Results grid |
| The user names one listing, asks "tell me about this one", or you are about to advise on a purchase | Listing dossier |
| The user asked one narrow factual question ("is it still listed?", "what's the mileage?") | No page — just answer |

Don't render a page for every turn. One good page beats three near-identical
ones; when the user refines a search, update the same artifact rather than
publishing a new one.

## Results grid

```bash
uvx --from sporhund sporhund-render --out results.html \
  search car "volkswagen golf" --filters '{"year_from":2019,"price_to":200000}' --limit 24
```

Cards carry a thumbnail, the price, the heading, a year/mileage/fuel line,
location, and chips for anything that changes how a price should be read —
private seller vs dealer, and non-standard ad types like *Ønskes kjøpt*,
*Auksjon* or *Leasing*.

Pass the **same** `--filters` JSON you passed to `search_finn`, so the page and
your commentary describe the same result set. `--limit` defaults to 24; keep it
there or lower, since every card carries an inlined photo.

## Listing dossier

```bash
uvx --from sporhund sporhund-render --out listing.html \
  listing 256110421 --comparables --verify
```

Gives the full gallery, the spec table, the seller's own description set in a
serif so it reads as *their* words rather than our data, plus:

- `--comparables` adds the market-position bar: where this asking price sits
  between the cheapest and dearest comparable, with the median marked. Use it
  whenever the user is weighing a purchase.
- `--verify` adds the vehicle-registry check. Cars only, and it needs the user's
  Statens vegvesen key — see the `vegvesen-key` skill. A clean check still shows
  as *clear*, because silence would read as "not checked".

Both flags degrade quietly: a missing key or a non-car listing loses that
section, never the page.

## Publishing

Publish the file with the Artifact tool. It is already artifact-shaped — a
`<title>`, inline CSS, inlined images, no external requests except Google Fonts.

- **Favicon** (required, and it is what the user sees as the artifact's
  thumbnail in their gallery): `🔎` for a results grid, `🚗` for a car dossier,
  `📦` for anything on torget, `🏠` for property, `💼` for a job. Keep it stable
  when you update a page.
- **Description**: one sentence naming the search or the item, e.g. "24 e-Golfs
  under 200 000 kr, cheapest first" — it becomes the gallery card's subtitle.
- Then say the useful thing in chat. The page shows *what* the listings are; you
  still owe the user the *so what* — which ones are worth a look and why.

## Speed and size

Photos dominate both the runtime and the file. Each image is a separate paced
request, so a 24-card grid takes around half a minute.

- `--no-images` renders in a second or two. Good for a quick scan, or when the
  user only wants the numbers.
- `--limit`, `--max-images` and `--image-width` all trade size for detail. The
  artifact ceiling is 16 MB; the defaults stay far under it.

## Before you publish someone else's photographs

The page **contains** the seller's photos, not links to them, and publishing
puts them on claude.ai. Artifacts start private, which is the right setting for
this and the one to leave it on.

- Never share or make public a page rendered from FINN listings, and don't
  offer to. It is for the user's own appraisal.
- If the user asks to share one, say plainly why that is a redistribution
  problem and offer the FINN links instead — every card and dossier already
  links back to the original ad.
- Delete rendered files from disk once published; they are working files, not
  a local archive of FINN's content.
