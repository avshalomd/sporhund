# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org);
while the major version is 0, minor bumps may change tool outputs.

## Unreleased

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
