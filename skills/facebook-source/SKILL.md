---
name: facebook-source
description: Switch on, check or repair Sporhund's optional Facebook Marketplace source, which adds `search_facebook` and `get_facebook_listing` as a second source alongside FINN. Use when those tools report they are not installed, when the user asks to search Facebook Marketplace or wants listings from more than one site, or when they ask why Facebook results are missing.
---

# Facebook Marketplace source

Sporhund reads FINN with two dependencies and no browser. Facebook will not
serve Marketplace to a plain HTTP client — a handful of requests without a
cookie jar and it starts answering "Sorry, something went wrong" — so this
source needs a real browser engine. That is a heavy thing to install on
somebody's machine for a feature they may never use, so it is **optional, off by
default, and installed only when the user asks for it**.

## Rules that do not bend

- **Never sign in, and never ask the user for Facebook credentials, cookies or
  a session.** If they offer them, decline and explain why.
- **Never point this at the user's own browser profile.** Sporhund uses a
  profile directory it owns. Do not "fix" a problem by reusing their Chrome
  profile or importing cookies from it.
- If a tool reports it refused to read because the session looked signed in,
  **that is the guard working**. Do not try to bypass it. Tell the user, and
  have them delete the Sporhund browser profile reported by `check_setup`.

These are not fussiness about credentials, though that applies too. The legal
footing for reading Marketplace at all is that a logged-out visitor is not bound
by Meta's terms of service — the holding in *Meta v. Bright Data* (N.D. Cal.,
January 2024), which Meta declined to appeal. **Signing in would convert a
lawful public read into a terms breach.** Logged-out is the whole basis, not a
default that can be changed for convenience.

## Diagnose first

Run `check_setup`. Its `facebook_marketplace` section reports whether the extra
is installed, whether the browser has been downloaded, and where the profile
directory lives. The tools also degrade honestly on their own: called without
the extra, they return `status: "not_installed"` rather than failing.

## Switching it on

One command, which the user runs themselves in a terminal:

```
uv tool install 'sporhund[facebook]' && playwright install chromium
```

Tell them what it costs before they run it: this downloads a Chromium build of
roughly 150 MB. It installs into its own tool environment, so it survives
`claude plugin update` and does not touch the connector's own environment.

Then run `check_setup` again to confirm. No restart is needed — the server finds
the helper on PATH at call time.

## Using it well

**Facebook is a supplement to FINN, not a peer.** Say which source a listing
came from; never merge the two into one list as though they were equivalent.

- **Good for second-hand goods.** Listing on FINN costs money and Facebook is
  free, so the cheap, local and bulky end of the market genuinely lives there —
  furniture, appliances, garden equipment, children's things. This is where the
  second source earns its keep.
- **Weak for cars.** Facebook ads carry no registration number, so `verify_car`,
  `lookup_vehicle` and the whole registry cross-check cannot be applied to them.
  A Facebook car ad is an unverifiable claim by a stranger. Prefer FINN for
  vehicles and say why if the user asks for Facebook ones.
- **No seller information exists.** A logged-out reader gets no name, no
  profile, no contact route and no rating. Do not speculate about the seller,
  and tell the user they will have to open the listing themselves to make
  contact.
- **Prices need care.** A free item can render as "$0" even in Norway, because a
  logged-out visitor has no locale context. Sporhund reads the numeric amount
  and omits the currency when the page does not name one, so a listing with a
  price but no currency is normal rather than broken.

## When it is rate-limited

Anonymous browsing is capped — reports put it near 30–60 page loads an hour per
IP address, and Sporhund paces itself to stay well under. If Facebook starts
returning errors, the answer is to **wait**, not to retry harder, not to route
around it, and not to sign in. Say so plainly and fall back to FINN meanwhile.
