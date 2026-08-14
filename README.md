# finn-agent

A small **MCP server** that lets an AI agent (Claude, or any MCP client) search
and *watch* [FINN.no](https://www.finn.no) listings on your behalf — turning
FINN's browse-and-refresh experience into something you can drive with natural
language.

> **Personal use only.** This is a convenience layer over your own browsing, not
> a data service. It fetches public FINN pages on demand, paces requests
> politely, keeps everything on your machine, and never stores or redistributes
> FINN's content. Please read [NOTICE.md](NOTICE.md) — it explains the legal line
> this project deliberately stays on the safe side of.

This is **Phase 0** of the FINN-agent project: a private prototype to learn the
data model and validate the value before deciding whether to pursue a sanctioned
partnership or a user-side product. See [REPORT.md](REPORT.md) for the strategy.

## What it can do

The server exposes these tools to your agent:

| Tool | What it does |
|------|--------------|
| `search_finn` | Search **torget** (secondhand goods), **car** (used cars), or **job** (jobs) with free text, price/year/mileage filters, sorting, and paging. Returns structured listings plus quick price statistics (min / median / mean / max). Each listing reports `trade_type` and `seller_type`, so giveaways ("Gis bort") and wanted-to-buy ads ("Ønskes kjøpt") are distinguishable from real sales. |
| `get_listing` | Fetch one listing's **full** seller description (not the ~160-char SEO stub), price, condition, and attributes by finnkode or URL. For cars this includes year, mileage, owners, fuel, power, transmission, first registration, next EU-check date, known-damage/repair flags, and the full equipment list. |
| `create_watch` | Save a search under a name (stored locally). |
| `check_watch` | Re-run a saved search and return **only listings you haven't seen before** — a smarter, agent-driven version of *lagrede søk*. |
| `list_watches` / `delete_watch` | Manage your saved watches. |

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

## Install & run

```bash
uv sync
uv run finn-agent
```

That starts the MCP server on stdio. Point your MCP client at it.

### Claude Code

A project-scoped [`.mcp.json`](.mcp.json) is committed, so opening this
directory in Claude Code offers the server automatically — approve `finn` once
when prompted and the six tools appear. (It uses an absolute path; adjust it if
you move the repo.)

### Claude Desktop / other MCP clients

```json
{
  "mcpServers": {
    "finn": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/avshalom/projects/finn-agent", "finn-agent"]
    }
  }
}
```

Then ask Claude to search or watch FINN in plain language.

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
- Pacing: a process-wide minimum interval between requests (default 2 s); one
  request per tool call; no background loops.
- Storage: a local SQLite file under your user data dir
  (`~/.local/share/finn-agent/watches.db`, overridable with `FINN_AGENT_DB`).
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

## Configuration

| Env var | Purpose | Default |
|---------|---------|---------|
| `FINN_AGENT_DB` | Path to the local watch database | `~/.local/share/finn-agent/watches.db` |

## Roadmap

- [ ] Real estate (Eiendom) buy + rent — add a React-Router stream parser.
- [ ] Richer car-deal context (pull public Statens vegvesen vehicle data).
- [ ] "Draft first message" / negotiation-prep prompts as MCP prompts.
- [ ] Optional desktop notifications for `check_watch`.

Anything beyond personal use goes through the sanctioned route first (FINN
partner API / written consent from Vend). See [NOTICE.md](NOTICE.md).

## License

Personal, non-commercial use only — see [LICENSE](LICENSE).
