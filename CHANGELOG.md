# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org);
while the major version is 0, minor bumps may change tool outputs.

## 0.5.2 — 2026-08-25

### Fixed

- **A Facebook search with no matches reported itself as a failure.** Anonymous
  visitors get roughly twenty results per search, so a narrow query in a smaller
  place legitimately comes back empty — "kjøleskap" in Stavanger does, while
  "sofa" in the same place does not. Raising there told the caller the source
  was broken while it was working exactly as intended. An empty search now
  returns `count: 0` with a note explaining what that does and does not mean.

## 0.5.1 — 2026-08-25

### Fixed

- **The Facebook tools could not find their helper when run from the plugin.**
  Entry points cannot be limited to an optional extra, so the plain `sporhund`
  distribution also installs a `sporhund-fb` — including into the uvx
  environment the plugin's server runs from. That copy has no browser and never
  can, and a plain PATH lookup found it first, because uvx puts its own bin at
  the front. The result was an installed source reporting itself as having no
  browser, and every call failing. The server now skips its own script directory
  outright and consults uv's tool directory ahead of the rest of PATH.
  `check_setup` reports which helper it resolved, and `SPORHUND_FB` overrides it.
- **A failing helper surfaced as an opaque tool error** rather than something an
  agent could act on. Rate limits and helper crashes now come back as
  `status: "failed"` with the reason, matching how a missing install already
  behaved.

## 0.5.0 — 2026-08-22

### Added

- **Facebook Marketplace as an optional second source.** `search_facebook` and
  `get_facebook_listing` read public Marketplace listings alongside FINN's,
  which matters most for second-hand goods: listing on FINN costs money and
  Facebook is free, so the cheap, local and bulky end of the market genuinely
  lives there. Weak for cars — Facebook ads carry no registration number, so the
  vehicle-registry cross-check cannot be applied to them.
- **Everything is read logged out, and that is enforced rather than assumed.**
  Meta's terms bind signed-in users (*Meta v. Bright Data*, N.D. Cal. 2024), so
  signing in would turn a lawful public read into a terms breach. The session
  checks for Facebook's `c_user` and `xs` session cookies before every request
  and refuses to continue if either is present, and it runs in a browser profile
  Sporhund owns rather than the user's own. A logged-out reader receives no
  seller identity at all, so no personal data is collected either.
- **Off by default, installed on request**, like the vehicle-registry key. It
  needs a browser, which is a heavier dependency than anything else here, so it
  ships as an extra with its own `sporhund-fb` helper:
  `uv tool install 'sporhund[facebook]' && playwright install chromium`. Without
  it the tools return `status: "not_installed"` and say how to switch it on, and
  a default install stays at two dependencies. `check_setup` reports the state,
  and the new `facebook-source` skill walks through setup and use.

### Notes

- The helper lives in its own tool environment on purpose: the plugin's server
  runs from a `uvx` environment that is rebuilt on every plugin update, so
  anything installed into it after the fact would be silently discarded.
- Anonymous browsing is rate-limited near 30–60 page loads an hour per IP, so
  the session paces itself and keeps a persistent guest profile rather than
  arriving as a new stranger on every run.

## 0.4.0 — 2026-08-20

### Added

- **MCP Apps views** — `search_finn` and `get_listing` now carry `ui://`
  resources, so in Claude Desktop, claude.ai and VS Code the results grid and
  the listing dossier render inside the conversation instead of coming back as
  JSON. Photos load from FINN's CDN, declared in the resource's CSP, so nothing
  is copied to disk; the view follows the host's theme and hands link clicks back
  to the host with `ui/open-link`. Clients without the extension get the same
  JSON as before.
### Fixed

- FINN's image CDN serves a fixed ladder of widths (80, 240, 320, 400, 480, 640,
  960, 1280, 1600) and returns 404 for anything else, so `view_listing_images`
  silently lost every photo at, say, `width=800`. Requested widths now snap up
  to the next size the CDN actually has.

### Changed

- The plugin builds its MCP server from its own checkout rather than from PyPI.
  The marketplace serves this repository at HEAD, so a plugin's skills are always
  as new as `main` while PyPI is only as new as the last tag — pairing the two
  had already shipped a skill invoking a command absent from the release.
- In-chat widgets and the page renderer were built and then shelved; see
  [TODO.md](TODO.md) for why, and what replaces them.

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
