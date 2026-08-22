# TODO

Work that is decided but not built, and decisions worth not re-litigating.
Shipped items live in [CHANGELOG.md](CHANGELOG.md).

## Verticals and features

- [ ] Real estate (Eiendom), buy and rent — **parser solved, see below.**
- [ ] "Draft first message" / negotiation prep, as MCP prompts.
- [ ] Optional desktop notifications for `check_watch`.
- [x] Car ads cross-checked against Statens vegvesen's vehicle registry.
- [x] Deal scoring: `find_comparables` positions a car against its market.

Anything beyond personal use goes through the sanctioned route first (a FINN
partner API, or written consent from Vend). See [NOTICE.md](NOTICE.md).

## Next vertical: real estate (Eiendom)

Picked over Torget. Torget is already searchable and watchable; what it lacks is
a trustworthy value layer, and second-hand goods have no registry and no
canonical comparables to build one from. Eiendom is the report's #2 wedge, it is
the vertical with the widest information gap between the two sides, and the one
blocker — "needs a React-Router stream parser" — is no longer a blocker.

**The shell is decoded.** Eiendom pages ship their data as a single
`window.__reactRouterContext.streamController.enqueue("…")` string: one
JS-escaped line holding a flat array with index references. Rehydrating it is
about forty lines — walk the array, treat every int inside a container as an
index into it (negative values are undefined/null sentinels), and read `_N`
object keys as "the key is the string at index N". Verified live on
2026-08-21 against the lettings and homes searches and against both ad pages.

What that one decoder buys:

- **Search docs in the same shape the other verticals already use** — `id`,
  `heading`, `location`, `image`/`image_urls`, `timestamp`, `canonical_url` —
  so `_normalize` needs only a `realestate` branch for `price_suggestion` /
  `price_total` / `price_shared_cost`, `area_range`, `number_of_bedrooms`,
  `property_type_description`, `owner_type_description`, `furnished_state`,
  `organisation_name`, `viewing_times` and `coordinates`.
- **Filters in the exact shape `_parse_filters` already reads**, so
  `get_search_filters` works with no changes (17 groups on lettings, including
  `price`, `area`, `min_bedrooms`, `facilities`, `viewing`, `start_month`).
- **Paging and totals** from `metadata.paging` (`param: page`) and
  `metadata.result_size.match_count`.
- **Watches for free** — the store keys on a vertical string, so
  `create_watch`/`check_watch` work the moment the vertical is registered.
- **Both subverticals from one entry**: `/realestate/lettings/search.html` and
  `/realestate/homes/search.html` are the same shell.

**Ad pages use the same shell too**, and carry far more than the search doc:
`price` (with `salesCostSum`, `municipalFees`, `taxValue` — the 2.5%
dokumentavgift is real money a buyer's agent should surface), `energyLabel`,
`constructionYear`, `plot`, `ownershipType`, `size` (BRA-i/BRA-e), `facilities`,
`viewings` with ISO dates, `propertyInfo`, `floorplans`, and `prospectusView` —
a link to the broker's full salgsoppgave. `get_listing` currently limps on
og:-tags for these pages and returns no price at all.

**`cadastres` is the vegvesen moment.** Every homes ad carries
`{municipalityNumber, landNumber, titleNumber}` — the matrikkel key. That is the
hook for legally clean public enrichment (Kartverket, Enova's energy register),
exactly the pattern that already works for cars: FINN supplies the ad, an open
public register supplies the check.

**Gotcha worth writing down:** Eiendom does *not* share the location code space
with mobility/torget. Rogaland is `20012` here and `22047` there, counties are
`0.<county>` and municipalities `1.<county>.<municipality>`. Codes must come
from that vertical's own `get_search_filters`, never carried across. An invalid
code returns HTTP 500, not an empty result.

Suggested first slice: rentals. It is where a watch actually earns its keep —
minutes matter in a scarcity market, and `check_watch` already exists.

## Second source: Facebook Marketplace

Researched 2026-08-22, including live checks. **Verdict: real, but not next.**

**Logged out works better than the write-ups claim.** In a clean browser with no
Facebook account, Norwegian Marketplace search renders 24 listings a page with
price, title and location, and item pages render in full — price, location,
listed-date, condition and the *complete* seller description. A Tesla ad pulled
this way carried "Km stand: 256175" and "EU-godkjent til 08/28" in its free
text. The blogs saying logged-out search redirects to login, or that
descriptions are truncated to a snippet, are wrong for Norway.

**But plain HTTP does not work, and that is the blocker.** Sporhund is httpx and
regex — no browser, two dependencies. Fetching Marketplace that way got three
200s and then a hard HTTP 400 "Sorry, something went wrong" that persisted for
the IP. The pages need JS execution and a bootstrapped guest cookie; reported
limits are ~30–60 requests/hour/IP. Adding this source means adding Playwright,
which is a different class of dependency from everything here now.

**Agreed shape: an opt-in capability, onboarded like the vegvesen key.** The
browser never enters the server's own environment — the plugin launches through
`uvx --from ${CLAUDE_PLUGIN_ROOT}`, an environment resolved at launch and
rebuilt on every update, so nothing can be installed into it after the fact.
Instead ship a `facebook` extra and a second console script (`sporhund-fb`).
Onboarding runs `uv tool install 'sporhund[facebook]'` and
`playwright install chromium`, which builds a persistent tool environment and
puts the script on PATH; the server shells out to it when present and otherwise
returns a "not installed" result pointing at the setup skill. One package, one
release train, and a core that stays at two dependencies for everyone who never
asks for this.

**Efficiency notes for whoever builds it:** intercept the GraphQL JSON the page
fetches rather than scraping the DOM — the first page is server-rendered and
later pages arrive as JSON, and both can be captured, which is far more durable
than CSS selectors. Block images, CSS and fonts at the route level. Persist the
guest browser profile so the `datr` cookie survives between runs, keep one
long-lived browser rather than one per query, and reuse the pacing discipline
already in `FinnClient` against the ~30–60/hour ceiling.

**The hard rule the skill must carry**, mirroring "never ask the user to paste
the key into the chat": **never log in, and never accept Facebook credentials or
session cookies.** This is not only the usual credential-handling rule — the
*Bright Data* holding that makes this defensible at all applies **only while
logged out**. A logged-in session would convert a lawful public read into a
terms breach, so guest-only is a correctness requirement, not a preference.

**The legal posture inverts, which is worth understanding.** In *Meta v. Bright
Data* (N.D. Cal., Jan 2024) Judge Chen held Meta's terms bind only users who are
logged in — scraping public data while logged out is not a terms breach — and
Meta then dropped the case and waived appeal. So for Meta, **logged out is the
defensible shape**, the exact opposite of FINN, where the defensible shape is a
user-side agent acting inside the user's own session. Unchanged either way:
Meta's robots.txt is `User-agent: * / Disallow: /` with a notice requiring
express written permission, the EEA database right still applies, and GDPR still
covers seller data — logged-out access exposing less of it helps here.

**Where the value actually is — and isn't.** FINN dominates Norway (87% vs 42%
for Facebook groups in the last comparable survey; Marketplace launched here in
2017 with little measurable effect on incumbents). For **cars it adds little**:
Facebook ads rarely carry a registration number, so `verify_car` and the whole
vegvesen enrichment — Sporhund's sharpest tool — mostly cannot fire. For
**Torget-style goods it adds real supply**: listing on FINN costs money and
Facebook is free, so the cheap/local/bulky end genuinely lives elsewhere. That
is the cross-marketplace "same sofa, 40% less" value in REPORT.md §5(D), and it
is the only slice worth building.

Cleaner alternatives for a second Norwegian source, if the Playwright dependency
is unwelcome: Tise (secondhand fashion, >1M Norwegian users), and Blocket / DBA
/ Tori for a Nordic story.

## Next: a shortlist report, on demand

Once a user has narrowed a search down to a few real candidates, they should be
able to ask for a **report** — one artifact covering the shortlist, generated on
request rather than automatically.

The data already exists; what is missing is both the page and the thing that
turns facts into advice:

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

An earlier renderer (`sporhund-render`) is in `archive/render.py` — it built a
self-contained page with an inlined gallery, a spec table and a price-position
bar. Worth reading before rewriting, but it was a page generator, not the
buyer's brief described above, and it shipped a skill referencing a command that
did not exist in the published release. Whatever replaces it must be reachable
from whatever the plugin actually installs.

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
