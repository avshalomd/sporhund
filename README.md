# Sporhund

<!-- mcp-name: io.github.avshalomd/sporhund -->

**A FINN.no connector for your AI agent.** Sporhund ("bloodhound" in Norwegian)
lets Claude search, inspect and track listings on
[FINN.no](https://www.finn.no) — so you can hunt for a car, a flat or a bargain
by describing what you want instead of clicking through filters.

It is a *connector*, not an agent: it hands your agent clean data and sharp
tools, and your agent does the thinking.

> **Built for personal use.** This is a convenience layer over your own
> browsing, not a data service. Please read [NOTICE.md](NOTICE.md) before using
> it — it explains the line this project stays on the safe side of.

## Setup

One command in Claude Code:

```bash
claude plugin marketplace add avshalomd/sporhund && claude plugin install sporhund@sporhund
```

Restart afterwards and that's it — no clone, no Python setup.

**One prerequisite:** [`uv`](https://docs.astral.sh/uv/) must be on your PATH.
The plugin fetches everything else, but without `uv` it installs cleanly and
then has no tools, which looks like nothing happening. If you don't have it:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

Ask your agent to run `/sporhund:setup` at any point to see what's switched on.

<details>
<summary>Other MCP clients (Claude Desktop, Codex, …)</summary>

The plugin is Claude Code only. Elsewhere, point your client at the package —
you get the tools, but not the skills or slash commands:

```bash
uvx sporhund
```

For Codex: `codex mcp add sporhund -- uvx sporhund`. For Claude Desktop, add
`{"command": "uvx", "args": ["sporhund"]}` under `mcpServers`.

</details>

### Optional: Norwegian vehicle registry

Two extras — checking a car ad against the state's own records, and looking up a
registration number — need a free API key from Statens vegvesen. It is personal
to you, so Sporhund can't ship one.

Just say **"set up the vehicle registry"** and your agent will walk you through
ordering and installing it. Everything else works without it.

### Optional: Facebook Marketplace as a second source

Facebook adds real supply at the cheap, local and bulky end that FINN charges to
list — furniture, appliances, garden things. It is off by default because,
unlike FINN, Facebook won't serve Marketplace to anything but a real browser, so
switching it on downloads one (~150 MB).

Say **"set up the Facebook source"** and your agent will walk you through it, or
run it yourself:

```bash
uv tool install 'sporhund[facebook]' && playwright install chromium
```

Everything is read **logged out, always** — Sporhund refuses to read Facebook
while signed in, and never touches your own browser profile. That is what keeps
it on solid ground legally, and it means results carry no seller details at all.
Worth knowing: Facebook ads have no registration number, so the registry checks
above can't be applied to cars found there.

## Using it

Talk normally. Some things worth asking for:

- *"Find me a Tesla Model 3 under 250 000 kr near Stavanger, less than 100 000 km."*
- *"Is this one priced fairly?"* — positions it against what comparable cars are
  actually asking, and flags auction and leasing ads whose "price" isn't a price.
- *"Check this car against the registry"* — surfaces what the ad won't say: an
  ex-rental or ex-taxi, an import, an EU-control date that contradicts the
  listing.
- *"Show me the photos"* — your agent looks at them and tells you what it sees.
- *"Watch this search and tell me what's new"* — saved searches that report only
  listings you haven't seen before.

Covers **torget** (secondhand goods), **cars** and **jobs** on FINN, plus
**Facebook Marketplace** if you switch it on. Property is not supported yet —
see [TODO.md](TODO.md).

## Updating

```bash
claude plugin update sporhund@sporhund
```

Restart afterwards: the connector is a long-running process, so a running client
keeps the old version until it re-launches. Your saved searches and your API key
both survive an update.

## License & disclaimer

MIT — see [LICENSE](LICENSE). The code is free to use; **how you use it against
FINN.no is governed by FINN's own terms** — see [NOTICE.md](NOTICE.md).

Sporhund is an independent project, **not affiliated with or endorsed by
FINN.no or Vend Marketplaces**.

---

Working on it? See [CONTRIBUTING.md](CONTRIBUTING.md). What's planned:
[TODO.md](TODO.md).
