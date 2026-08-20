# Sporhund

<!-- mcp-name: io.github.avshalomd/sporhund -->

**A FINN.no connector for your AI agent.** Sporhund ("bloodhound" in Norwegian)
gives Claude — or any MCP client — the ability to search, inspect and track
listings on [FINN.no](https://www.finn.no), Norway's dominant marketplace, so you
can hunt for a car, a flat or a bargain by just describing what you want.

It is a *connector*, not an agent: it hands your agent clean data and sharp
tools, and your agent does the thinking.

> **Built for personal use.** This is a convenience layer over your own browsing,
> not a data service. It fetches public FINN pages on demand, paces requests
> politely, keeps everything on your machine, and never stores or redistributes
> FINN's content. Please read [NOTICE.md](NOTICE.md) — it explains the legal line
> this project is designed to stay on the safe side of, and why you should too.

## What it can do

The server exposes these tools to your agent:

| Tool | What it does |
|------|--------------|
| `search_finn` | Search **torget** (secondhand goods), **car** (used cars), or **job** (jobs) with free text, price/year/mileage filters, sorting, and paging. Returns structured listings plus quick price statistics (min / median / mean / max). Each listing reports `trade_type` and `seller_type`, so giveaways and wanted-to-buy ads are distinguishable from real sales. Unrecognized filter names are reported back as `ignored_filters` instead of silently broadening the results. Car results include fuel, make/model, registration number and sales form (leasing/auction ads are labeled, and leasing rates are excluded from price stats). |
| `get_search_filters` | Discover every filter FINN supports for a vertical — parameter names, coded values with labels, live hit counts, and the location/category/model hierarchies. Coded values differ per vertical; call this instead of guessing. |
| `get_listing` | Fetch one listing's **full** seller description (not the ~160-char SEO stub), price, condition, and attributes by finnkode or URL. For cars this includes year, mileage, owners, fuel, power, transmission, first registration, next EU-check date, known-damage/repair flags, and the full equipment list. |
| `view_listing_images` | Actually **look** at a listing's photos — condition, wear, rust, what's in the box. Fetches up to 6 images (default 3) at a chosen width into memory only; nothing is saved. Skip it when the text already answers the question: images cost far more context than text. |
| `verify_car` | **Check a car ad against Norway's official vehicle registry.** Surfaces what FINN never shows: an ex-rental/ex-taxi, an import, an EU-control date that contradicts the ad, or a deregistered car (routine while listed — flagged as info with practical advice, since ~half of fresh listings are). Needs your own Vegvesen key. |
| `lookup_vehicle` | Raw registry lookup by registration or chassis number. |
| `find_comparables` | Position a car against the listings a buyer would cross-shop: price percentile, distance from the median, cheapest alternatives. Compares within the same fuel type when possible, and excludes leasing ads. Asking prices, not sold prices — no API key needed. |
| `create_watch` | Save a search under a name (stored locally). |
| `check_watch` | Re-run a saved search and return **only listings you haven't seen before** — a smarter, agent-driven version of *lagrede søk*. |
| `list_watches` / `delete_watch` | Manage your saved watches. |
| `check_setup` | Report which tools are live right now, whether the vehicle-registry key is configured and where it came from, and — with `verify_key=true` — whether Statens vegvesen actually accepts it. Reports locations and warnings only; never reads or returns the key itself. |

Because your agent is Claude, the *intelligence* lives in the conversation: the
server gives Claude clean FINN data, and Claude does the reasoning — "is this car
a good deal versus the others?", "draft a message to this seller", "which of
these new apartments fit my commute?". The server stays a thin, honest data
layer.

### Example conversation

> **You:** Watch FINN for cargo bikes under 15 000 kr from private sellers, and
> tell me what's new since yesterday.
>
> **Claude:** *(calls `create_watch` once, then `check_watch` daily)* — 3 new
> listings since your last check. The cheapest, a Babboe Curve at 9 500 kr, is
> ~28% below the median of the 40 comparable listings I can see…

## Supported verticals

Wired up today (these pages embed clean structured data): **Torget**, **Bil**
(cars), **Jobb**.

**Not yet:** real estate (Eiendom). FINN has moved that vertical to a different
page technology (a React-Router streamed format) that needs a separate parser.
It's the natural next addition — see *Roadmap*.

## Requirements

- Python ≥ 3.10
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- *Optional:* a Statens vegvesen API key, for the vehicle-registry tools

### Optional: vehicle registry access

`verify_car` and `lookup_vehicle` read Norway's official vehicle registry. That
needs an API key, which is **personal to you** — order your own with BankID
(free, 50 000 lookups/day):

<https://www.vegvesen.no/kjoretoy/eie/kjoretoyopplysninger/bestill-api-nokkel/>

Copy `.env.example` to `.env` and paste the key in:

```bash
cp .env.example .env && chmod 600 .env   # then edit VEGVESEN_API_KEY=
```

`.env` is git-ignored. **Never commit, bundle or share a key** — you are
personally responsible for its use, and a shared key gets withdrawn. Everything
still works without one; only the registry tools switch off.

Rather than doing this by hand, run `/sporhund:setup` (or just ask your agent to
set up the vehicle registry). The bundled `vegvesen-key` skill walks through
ordering, installing and verifying the key, and diagnoses a rejected one. It
tells you where to paste the key — it never asks you to paste it into the chat.
At any point, `check_setup` tells you what is switched on.

Registry data is © Statens vegvesen (Kjøretøyregisteret), licensed
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/). It contains no owner
information.

**What it cannot do:** the registry publishes no odometer readings, so a claimed
mileage can only be judged against comparable listings, never verified.

## Install & run

Once published to PyPI, no clone or setup is needed — any MCP client can run it
directly:

```bash
uvx sporhund
```

From a checkout of this repo instead:

```bash
uv sync
uv run sporhund
```

Either starts the MCP server on stdio. Point your MCP client at it.

### Codex CLI

```bash
codex mcp add sporhund -- uvx sporhund
```

### Claude Code

Install it as a plugin, which brings the MCP server, the `/sporhund:setup`
command and the `vegvesen-key` skill in one step:

```bash
claude plugin marketplace add avshalomd/sporhund
```

Then `claude plugin install sporhund@sporhund`.

Alternatively, a project-scoped [`.mcp.json`](.mcp.json) is committed, so opening
this directory in Claude Code offers the bare server automatically — approve
`sporhund` once when prompted and the tools appear.

### Claude Desktop / other MCP clients

Once on PyPI (no checkout needed):

```json
{
  "mcpServers": {
    "sporhund": {
      "command": "uvx",
      "args": ["sporhund"]
    }
  }
}
```

From a local checkout, use `"args": ["run", "--directory", "/path/to/sporhund", "sporhund"]`
with `"command": "uv"` instead.

Then ask Claude to search or watch FINN in plain language.

## Updating

Ask your agent to run `check_setup` — it reports the running version, which is
the reliable way to tell what you actually have. Then, depending on how you
installed it:

| Installed as | Update with |
|---|---|
| `uvx sporhund` (PyPI) | `uvx --refresh sporhund` — or clear the cache with `uv cache clean sporhund` |
| Claude Code plugin | `claude plugin update sporhund@sporhund` |
| Git checkout | `git pull && uv sync` |

**Restart the MCP client afterwards.** The server is a long-lived stdio process,
so a running client keeps the old code until it re-launches it.

Version numbers before 0.2.0 were never published: a `0.1.0` install is a git
checkout of unknown vintage, so pull and re-sync rather than trusting the
number. Your saved watches and their seen-listing history are untouched by an
update — they live in a separate SQLite file — and your API key is read from
`.env` at call time, so it survives upgrades too. See [CHANGELOG.md](CHANGELOG.md)
for what changed.

## How it works

- Search pages: FINN server-renders results and embeds them as a base64 JSON
  blob (`<script data-react-query-state>`). The server decodes that and
  normalizes each listing — the same data your browser already received.
- Listing pages come in two shapes, and both are merged when present: a JSON-LD
  `Product` block (Torget) and a base64 `data-props` attribute (cars, which is
  much richer). The seller's full description is read from the rendered
  `description` section, because JSON-LD only carries an SEO-truncated version.
- Prices are normalized to plain integers regardless of which shape they came
  from, so values are comparable across verticals.
- Images: search results carry the primary thumbnail URL and `get_listing`
  returns every photo URL — **links only, nothing downloaded**. Only
  `view_listing_images` fetches actual bytes, on request, capped, resized via
  FINN's own CDN (`/dynamic/<width>w/`), held in memory and never written to
  disk. Non-finncdn URLs are refused outright.
- A bare finnkode is resolved through `finn.no/<code>`, which redirects to
  whichever vertical owns the ad, so codes work for cars and jobs too.
- Pacing: a process-wide minimum interval between requests (default 2 s); one
  request per tool call; no background loops.
- Storage: a local SQLite file under your user data dir
  (`~/.local/share/sporhund/watches.db`, overridable with `SPORHUND_DB`).
  It records only which listing ids a watch has already seen — never a copy of
  FINN's content.

## Development

```bash
uv sync
python tests/refresh_fixtures.py   # save a few pages locally (git-ignored)
uv run pytest                      # parser tests run against those pages
```

Fixtures and the local database are git-ignored on purpose: **no FINN data is
ever committed.**

The repository doubles as its own Claude Code marketplace:
[`.claude-plugin/`](.claude-plugin) holds the plugin and marketplace manifests,
[`skills/`](skills) the skills an agent loads on demand, and
[`commands/`](commands) the slash commands. Check them with:

```bash
claude plugin validate .
```

## Configuration

| Env var | Purpose | Default |
|---------|---------|---------|
| `SPORHUND_DB` | Path to the local watch database | `~/.local/share/sporhund/watches.db` |
| `VEGVESEN_API_KEY` | Statens vegvesen key, for the registry tools | unset (tools disabled) |

## Roadmap

- [ ] Real estate (Eiendom) buy + rent — add a React-Router stream parser.
- [x] Car ads cross-checked against Statens vegvesen's vehicle registry.
- [x] Deal scoring: `find_comparables` positions a car against its market.
- [ ] "Draft first message" / negotiation-prep prompts as MCP prompts.
- [ ] Optional desktop notifications for `check_watch`.

Anything beyond personal use goes through the sanctioned route first (FINN
partner API / written consent from Vend). See [NOTICE.md](NOTICE.md).

## License & disclaimer

MIT — see [LICENSE](LICENSE). The code is free to use; **how you use it against
FINN.no is governed by FINN's own terms** — see [NOTICE.md](NOTICE.md) for the
responsible-use guidance this project is designed around.

Sporhund is an independent project, **not affiliated with or endorsed by
FINN.no or Vend Marketplaces**.
