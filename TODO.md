# TODO

Work that is decided but not built, and decisions worth not re-litigating.
Shipped items live in [CHANGELOG.md](CHANGELOG.md); the longer-range vertical
plans are in the README's *Roadmap*.

## Next: a shortlist report, on demand

Once a user has narrowed a search down to a few real candidates, they should be
able to ask for a **report** — one artifact covering the shortlist, generated on
request rather than automatically.

The pieces already exist; what is missing is the thing that turns them into
advice:

- `sporhund-render` produces the page,
- `find_comparables` gives each car's market position,
- `verify_car` gives the registry findings,
- and search results now carry registration numbers, so a whole shortlist can be
  registry-checked without fetching each listing.

**The value is in the skill, not the renderer.** A report that lists three cars
is worth little; one that says *which* to see first, what each is likely hiding,
what to ask each seller, and which price has room in it, is worth the trip. That
means writing an expert skill — a buyer's-agent brief — with the renderer as its
output format. Sketch of what a report should carry per car: the photos, the
asking price against the comparable median, the registry findings, the specific
questions this car raises, and a plain verdict on where it ranks.

**Why an artifact and not a widget:** `Artifact` takes a *file path*, so the tool
reads the images off disk and they never pass through the agent's context. Full-
size photos cost nothing, the ceiling is 16 MB, and there is no hand-copied
base64 to corrupt. See *Shelved* below.

**On sharing.** Artifacts are private until the user shares them from the page's
share menu, which is the right default here — but note the tension with
[NOTICE.md](NOTICE.md): a report with the sellers' photographs embedded is
exactly what must not be shared. If a shareable report is wanted, it needs a
distinct mode that **links** to FINN rather than embedding photos, so what
travels is the user's own analysis and not FINN's content. Worth building as
`--shareable` rather than leaving it to whoever clicks Share.

## Shelved: listings as in-chat widgets

Rendering listings as `show_widget` fragments is **shelved as too expensive**,
in tokens and in wall-clock time. The code is kept out of the repo under
`archive/` (git-ignored): `widget.py`, its tests, and the `listing-widget` skill.

Why it cannot be made cheap:

- The widget sandbox enforces a CSP allowlist of six CDNs. `images.finncdn.no`
  is not among them, so a plain `<img src>` silently fails.
- A widget has no filesystem access, so there is no cache or local file to point
  at either.
- That leaves inlining the pixels as `data:` URIs — and because the HTML is a
  *tool parameter*, every one of those base64 bytes crosses the agent's context.
  A single 960px photo is roughly 43k tokens.
- Carrying ~20 KB of base64 by hand between two tool calls is also simply
  unreliable; several attempts arrived with corrupted images.

The compact list form did work well and was cheap (~2.7k tokens for three rows,
80×60 thumbnails). If in-chat listings are ever revisited, that is the only
shape worth reviving — and only if the host gains either an image-host allowance
or a way to pass a file rather than a string.

**Kept from that work** (already merged, not archived): FINN's CDN serves a fixed
ladder of widths and 404s on anything else, so `resize_image_url` snaps upward —
`view_listing_images(width=800)` used to return no photos at all.
