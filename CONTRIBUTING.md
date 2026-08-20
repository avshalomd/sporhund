# Working on Sporhund

The [README](README.md) covers installing and using the plugin. This is the
inside view.

## Layout

The repository is its own Claude Code marketplace as well as a Python package:

| Path | What it holds |
|---|---|
| [`src/sporhund/finn.py`](src/sporhund/finn.py) | The only module that touches finn.no: fetching, pacing, parsing, normalising |
| [`src/sporhund/server.py`](src/sporhund/server.py) | The MCP tools. No HTTP or parsing of its own |
| [`src/sporhund/vegvesen.py`](src/sporhund/vegvesen.py) | Statens vegvesen lookups and ad-vs-registry comparison |
| [`src/sporhund/render.py`](src/sporhund/render.py) | Renders listings as a self-contained page |
| [`.claude-plugin/`](.claude-plugin) | Plugin and marketplace manifests |
| [`skills/`](skills), [`commands/`](commands) | What an agent loads on demand |

## Running the tests

```bash
uv sync
```

```bash
python tests/refresh_fixtures.py   # save a few pages locally (git-ignored)
```

```bash
uv run pytest
```

Fixtures and the local watch database are git-ignored on purpose: **no FINN data
is ever committed.** Parser tests skip themselves when fixtures are absent, so a
clean checkout still passes.

Validate the plugin manifests with:

```bash
claude plugin validate .
```

## How the parsing works

- **Search pages** are server-rendered by FINN with the results embedded as a
  base64 JSON blob (`<script data-react-query-state>`). We decode that and
  normalise each listing — the same data the browser already received.
- **Listing pages** come in two shapes, merged when both are present: a JSON-LD
  `Product` block (torget) and a base64 `data-props` attribute (cars, much
  richer). The seller's full description is read from the rendered page, because
  JSON-LD carries only an SEO-truncated version.
- **Prices** are normalised to plain integers whatever shape they arrived in, so
  they are comparable across verticals.
- **Images**: search results carry the primary thumbnail URL and `get_listing`
  returns every photo URL — links only, nothing downloaded. Only
  `view_listing_images` and `sporhund-render` fetch bytes, capped and resized
  through FINN's own CDN. That CDN serves a fixed ladder of widths and 404s on
  anything else, so requested widths snap upward. Non-finncdn URLs are refused.
- **A bare finnkode** resolves through `finn.no/<code>`, which redirects to
  whichever vertical owns the ad.

## Behaviour that is deliberate

- Pacing: a process-wide minimum interval between requests (2 s), one request
  per tool call, no background loops.
- Storage: a local SQLite file recording only which listing ids a watch has
  already seen — never a copy of FINN's content.
- Read [NOTICE.md](NOTICE.md) before changing any of the above.

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `SPORHUND_DB` | Path to the local watch database | `~/.local/share/sporhund/watches.db` |
| `VEGVESEN_API_KEY` | Statens vegvesen key, for the registry tools | unset (tools disabled) |

## Releasing

Bump the version in `pyproject.toml`, `src/sporhund/__init__.py` and both
manifests under `.claude-plugin/`, update [CHANGELOG.md](CHANGELOG.md), then
publish a GitHub release. `publish.yml` runs the tests and uploads to PyPI via
trusted publishing — no tokens involved.
