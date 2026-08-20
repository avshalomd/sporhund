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

**One listing — detailed.** Hero photo, small strip, specification grid, and an
excerpt of the seller's description.

```bash
uvx --from sporhund sporhund-widget one 256110421
```

## Token budget

Photos are essentially the entire cost. Measured against FINN's CDN:

| Thumbnail width | Per photo | Note |
| --- | --- | --- |
| 80 (list default) | ~1.1k tokens | six of these ≈ one 240 |
| 240 (hero default) | ~5.9k tokens | only worth it for a single hero |
| 320 | ~10.5k tokens | don't |

So a six-listing widget costs roughly **7k tokens**, and a detailed single
listing roughly **8–11k**. The command prints its own estimate to stderr and
warns past ~25k.

Bring it down when you need to:

- `--limit 4` — fewer rows.
- `--no-images` — near-free; right when the user is comparing numbers, not
  looking at cars.
- `--strip 0` on `one` — drops the small photos, keeps the hero.
- Never raise `--width` above 80 for a list.

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
