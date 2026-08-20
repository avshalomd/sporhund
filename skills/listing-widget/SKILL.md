---
name: listing-widget
description: Show FINN listings as a widget inside the chat — a compact list when there are several, a detailed card when there is one. Use whenever presenting Sporhund search results or a specific listing to the user, instead of reciting them as text. Includes the token budget, which photos dominate.
---

# Listings as chat widgets

Reciting listings as bullet points throws away the photograph, which is most of
what a buyer judges on. `sporhund-widget` prints a ready-to-paste fragment for
`show_widget`.

## The one rule that matters for cost

**Run the command once, paste its output once.** The widget sandbox blocks
remote image hosts, so thumbnails are inlined as base64 and that base64 passes
through your context. Anything that makes it pass twice doubles the price:

- ✅ Run the command, take the fragment straight from the output, paste it.
- ❌ Redirect to a file, read the file, then retype it. That is two passes.
- ❌ Fetch photos with `view_listing_images` and try to rebuild the markup by
  hand. Those images cannot be embedded anyway — you cannot re-emit them.

## Two forms

**Several listings — compact.** One row each: thumbnail, price, distance from
the median, year/mileage/fuel/place, and a chip for anything that changes how the
price reads (private vs dealer, auction, leasing, wanted-to-buy).

```bash
uvx --from sporhund sporhund-widget list car "tesla model 3" \
  --filters '{"location":"0.20012","price_to":250000}' --limit 6
```

If you have already run `search_finn` and picked favourites, don't search again
from scratch — pass the same query and filters plus `--only`, which keeps just
those listings **in the order you list them**:

```bash
uvx --from sporhund sporhund-widget list car "tesla model 3" \
  --filters '{"location":"0.20012"}' --only 472255338,473103426,473532799
```

The median it reports is over the whole result set, not just the rows shown —
a median of three hand-picked listings would be meaningless.

**One listing — detailed.** Four photos, specification grid, and an excerpt of
the seller's description, for about 3.4k tokens.

```bash
uvx --from sporhund sporhund-widget one 256110421
```

Four small photos rather than one big one is deliberate, and the constraint is
worth knowing: a photo is a base64 string that has to be carried intact into the
`show_widget` call, and long blobs do not survive that — a ~15 KB one arrives
corrupted and renders as a broken image. Roughly 3 KB is the size that works, so
**never raise `--photo-bytes` looking for a better picture.** More photos, yes;
bigger ones, no.

When the photographs themselves are the question — paint condition, damage,
what's included — the widget is the wrong tool. Render a page instead and
publish it as an artifact (see the `listing-view` skill): it reads the images
from disk, so they cost no tokens at all and can be full size.

## Token budget

Photos are essentially the entire cost. Measured against FINN's CDN:

Each photo is re-encoded to about 2 KB, which is ~700 tokens once base64'd.
A six-row list costs roughly 7k tokens and a detail card about 3.4k.

So a six-listing widget costs roughly **7k tokens**, and a detailed listing
about **4.5k** (or 8k with `--hero 240`).

The command enforces this rather than trusting you: it prints its own estimate,
and if a widget would exceed `--budget` (default 5000) it sheds photos — strip
first, then hero size, then photos entirely — and says which it dropped. That
matters because an oversized fragment gets truncated out of the tool result, and
recovering it costs more than the photos were worth.

Bring it down further when you need to:

- `--limit 4` — fewer rows.
- `--photos 2` — fewer photos on a detail card.
- `--no-images` — near-free; right when the user is comparing numbers, not
  looking at cars.

## When not to render one

- The user asked one narrow question ("is it still listed?") — just answer.
- More than about 8 listings — narrow the search first; a wall of rows is no
  more readable than a wall of text, and costs far more.
- The client already drew the listings itself. In Claude Desktop, claude.ai and
  VS Code, `search_finn` and `get_listing` render their own MCP Apps views —
  see the `listing-view` skill. Don't render a second copy.

## After the widget

The widget shows *what* the listings are; you still owe the user the *so what* —
which are worth their attention and why. Put that in your reply, not in the
widget. Never repeat the listing details as text; they are already on screen.

Photographs belong to the sellers. The widget shows them for the user's own
appraisal, and every row links back to the original ad.
