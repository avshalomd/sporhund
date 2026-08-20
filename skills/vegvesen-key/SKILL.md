---
name: vegvesen-key
description: Set up, check or repair the user's personal Statens vegvesen API key, which unlocks Sporhund's vehicle-registry tools (`lookup_vehicle`, `verify_car`). Use when those tools report no key or a rejected key, when the user asks how to enable registry checks or "why can't you verify this car", or when they are installing Sporhund for the first time.
---

# Vehicle-registry key setup

Sporhund's FINN tools work with no credentials. Two tools — `lookup_vehicle` and
`verify_car` — additionally read Norway's official vehicle registry, and that
needs an API key from Statens vegvesen. The key is **personal to the user**:
Sporhund never bundles, proxies or ships one, and the user's key must never be
shared with anyone else.

## Rules that do not bend

- **Never ask the user to paste the key into the chat**, and never repeat, echo,
  summarise or store a key that appears there anyway. If one does appear, say so
  plainly, tell them to treat it as compromised and order a replacement.
- **You do not put the key in the file — the user does.** Show them the path and
  the exact line; let them edit it themselves.
- The key must never be committed, screenshotted, or pasted into a shared
  document. A shared key gets withdrawn, and the user is personally responsible
  for every lookup made with it.

## Diagnose first

Always start with `check_setup`. It reports whether a key is configured, which
of the three locations it came from, and any warnings — without ever reading the
key's value.

- **`configured: true`** — run `check_setup(verify_key=true)`. That asks Statens
  vegvesen to accept the key, using a plate no vehicle uses, so no real vehicle
  is looked up. Report the verdict and stop; there is nothing to set up.
- **`configured: false`** — walk the user through *Ordering* and *Installing*
  below.
- **Warnings present** — act on them even when the key works. See
  *Troubleshooting*.

## Ordering a key

Tell the user, in their own terms:

- It is free, needs BankID, and allows 50 000 lookups a day — far more than
  personal car shopping uses.
- Order it here:
  <https://www.vegvesen.no/kjoretoy/eie/kjoretoyopplysninger/bestill-api-nokkel/>
- The key appears on *Din side* at vegvesen.no once approved.
- Set expectations honestly about what it buys: registration status, EU-control
  history, first registration in Norway, import status, whether the car has been
  a taxi or rental, and the official technical data to compare against the ad.
  It contains **no owner information** and **no odometer readings** — a claimed
  mileage can never be verified this way, only judged against comparable ads.

## Installing the key

`check_setup` returns the exact paths under `files`. There are three places, in
priority order:

1. The MCP client's own `env` block for the server (or the shell environment) —
   best when the client stores it in an OS keychain.
2. `.env` beside the project checkout.
3. `~/.config/sporhund/.env` — best when Sporhund runs from PyPI with no
   checkout, since it survives upgrades.

Give the user a copyable line and let them do the edit:

```
VEGVESEN_API_KEY=<the key from Din side>
```

Then tell them to tighten the file so other accounts on the machine cannot read
it, e.g. `chmod 600 ~/.config/sporhund/.env`, and to **restart the MCP client**
so the server is re-launched. Finally, re-run `check_setup(verify_key=true)` and
confirm it comes back `ok: true`.

## Troubleshooting

| Symptom | What it means | What to do |
| --- | --- | --- |
| `reason: "no_key"` | Nothing found in any location | Order and install as above |
| `reason: "rejected"` (401/403) | Key not active, or mangled on copy | Check it is active on Din side; re-copy whole, with no stray spaces or surrounding quotes |
| `reason: "network"` | Cannot reach vegvesen.no | Transient or offline — retry later; FINN tools still work meanwhile |
| Warning: set in more than one place | An earlier location wins | Point out which one is active, so they stop editing a file that has no effect |
| Warning: readable by other accounts | File permissions are loose | `chmod 600 <path>` |
| Verified ok, but quota used up (429) | 50 000 lookups spent today | Wait for the daily reset; nothing is wrong with the key |

## After it works

Say what changed, concretely: `verify_car <finnkode>` now cross-checks an ad
against the registry, and because car search results carry registration numbers,
a whole page of results can be screened at once. Mention that registry data is
© Statens vegvesen (Kjøretøyregisteret) under CC-BY 4.0, so attribution belongs
in anything the user publishes from it.
