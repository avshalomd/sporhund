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

In Claude Code:

```bash
claude plugin marketplace add avshalomd/sporhund
```

```bash
claude plugin install sporhund@sporhund
```

Restart, and that's it — no clone, no Python setup. You'll need
[`uv`](https://docs.astral.sh/uv/) installed; the plugin fetches the rest.

Ask your agent to run `/sporhund:setup` at any point to see what's switched on.

### Optional: Norwegian vehicle registry

Two extras — checking a car ad against the state's own records, and looking up a
registration number — need a free API key from Statens vegvesen. It is personal
to you, so Sporhund can't ship one.

Just say **"set up the vehicle registry"** and your agent will walk you through
ordering and installing it. Everything else works without it.

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
- *"Make me a page for these three"* — renders a shortlist as a private page you
  can keep.

Covers **torget** (secondhand goods), **cars** and **jobs**. Property is not
supported yet — see [TODO.md](TODO.md).

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
