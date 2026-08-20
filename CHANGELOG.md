# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org);
while the major version is 0, minor bumps may change tool outputs.

## Unreleased

### Added

- **MCP Apps views** — `search_finn` and `get_listing` now carry `ui://`
  resources, so in Claude Desktop, claude.ai and VS Code the results grid and
  the listing dossier render inside the conversation instead of coming back as
  JSON. Photos load from FINN's CDN, declared in the resource's CSP, so nothing
  is copied to disk; the view follows the host's theme and hands link clicks back
  to the host with `ui/open-link`. Clients without the extension get the same
  JSON as before.
- **`sporhund-widget`** and the **`listing-widget` skill** — listings as a
  widget inside the chat: a compact list of rows for several, a detailed card
  for one. The widget sandbox blocks remote image hosts, so thumbnails are
  inlined as base64 and pass through the agent's context; photos are therefore
  the entire cost, and the design follows the measurement (80w ~1.1k tokens,
  240w ~5.9k). Lists default to 80w, the command prints its own token estimate,
  and `--only` re-uses a search you already ran instead of fetching each listing.
  Photos are re-encoded with Pillow to an exact byte budget rather than picked
  off FINN's CDN width ladder, and every one is kept small on purpose: a base64
  blob has to be carried intact into the widget call, and a ~15 KB one arrives
  corrupted, so a detail card shows four small photos rather than one large one.
- **`sporhund-render`** — renders listings as a self-contained HTML page, meant
  to be published as an artifact. `search` gives a thumbnail grid with price,
  spec line, location and chips for anything that changes how a price reads
  (private seller vs dealer, auction, leasing, wanted-to-buy). `listing` gives a
  dossier: photo gallery, spec table, the seller's own description set in a
  serif to keep it distinct from measured data, optional registry findings
  (`--verify`) and an optional market-position bar (`--comparables`).
- **`listing-view` skill** and **`/sporhund:show`** — tell an agent when to
  render a page instead of reciting listings, and to keep the published artifact
  private, since it contains the sellers' photographs.

### Fixed

- FINN's image CDN serves a fixed ladder of widths (80, 240, 320, 400, 480, 640,
  960, 1280, 1600) and returns 404 for anything else, so `view_listing_images`
  silently lost every photo at, say, `width=800`. Requested widths now snap up
  to the next size the CDN actually has.

### Changed

- Photos are still fetched on demand and never mirrored, but rendering writes
  them into a local page, so they now touch disk. [NOTICE.md](NOTICE.md) says
  what that means and where the private-use line sits.

## 0.3.0 — 2026-08-20

### Fixed

- `find_comparables` now loosens the year and mileage bands step by step until
  it has at least five comparables, instead of reporting a percentile computed
  from two. The default ±1 year / ±40 000 km is right for a common modern car
  and far too narrow for a rare or old one — a 1986 Golf returned two
  comparables and a meaningless −70% position; it now returns seven. The result
  reports `search_used.widened` so the loosening is never silent, and a common
  car still resolves in a single search.
- `find_comparables` flags when the *subject* is an auction or leasing ad via
  `subject_price_note`. Comparables are used-car asking prices, so a current
  auction bid sitting far below them is not a discount, and the percentile
  should not be read as one.

### Added

- `find_comparables` takes `widen` (default true) to hold the bands exactly as
  given.

## 0.2.0 — 2026-08-20

First release published to PyPI. Earlier versions existed only as a git
checkout, so a `0.1.0` install is a working copy of unknown vintage — see
*Updating* in the README.

### Added

- **`check_setup`** — reports which tools are live, whether a Statens vegvesen
  API key is configured and which of the three locations it came from, and what
  to do when it isn't. With `verify_key=true`, asks Statens vegvesen whether the
  key is actually accepted. Reports locations and warnings only; the key's value
  never reaches a tool result or a log.
- **`vegvesen-key` skill** and **`/sporhund:setup`** — guided ordering,
  installing, verifying and troubleshooting of the registry key. The user pastes
  the key into a file themselves, never into a chat.
- **Claude Code plugin** — `.claude-plugin/` makes this repo its own
  marketplace, so the MCP server, skill and command install in one step.
- **`get_search_filters`** — discover every filter FINN supports for a vertical:
  parameter names, coded values with labels, live hit counts, and the
  location/category/model hierarchies.
- Car search results now carry `fuel`, `transmission`, `make`, `model`,
  `model_specification`, `warranty_duration`, `chassis_number`,
  `registration_number` and `sales_form`. Registration numbers on search results
  make it possible to screen a whole page of cars against the registry without
  fetching each listing.
- Job listings expose `no_of_positions`.
- `find_comparables` compares within the same fuel type when at least five
  same-fuel comparables exist, and reports `fuel_matched`.
- Unrecognized search filters come back as `ignored_filters` instead of silently
  broadening results.

### Fixed

- An unknown vehicle returns **204 No Content** from the registry, not 404, so
  `lookup_vehicle` reported `Registry returned HTTP 204` instead of "No vehicle
  found" — and would have failed to parse the empty body had it reached the 200
  branch.
- Car listings that carry both JSON-LD and a `data-props` payload lost all car
  detail; both sources are now merged.
- Car ad descriptions returned the ~160-character SEO stub instead of the
  seller's full text.
- Private car sellers were labeled as dealers: the `dealer_segment` codes run
  the opposite way in the car vertical than in torget.
- Leasing ads leaked monthly rates into price statistics; they are now excluded
  from `search_finn` price stats and from `find_comparables`, with a note saying
  how many were dropped.
- A bare car finnkode 404'd instead of resolving through FINN's per-vertical
  redirect.
- Listing prices arrived in several shapes and are now normalized to integers.
- `check_watch` said something misleading when a watch found nothing; it now
  says "Nothing new since your last check."
- The server advertised an empty version in `serverInfo`.

### Changed

- `vertical` is a proper enum (`torget`, `car`, `job`) rather than a free string.
- The registry "deregistered" finding is severity `info`, not a warning: roughly
  half of live listings are deregistered while for sale. The doors comparison was
  dropped for firing on clean listings.
- Documentation corrected: the vehicle registry publishes **no odometer
  readings**, so a claimed mileage can only be judged against comparable
  listings, never verified.
