# Notice on use, and on FINN.no's terms

**Read this before running the tool, and before building anything on top of it.**

The code is MIT-licensed — the license places no restrictions on you. This
notice exists because *using* the software against FINN.no is a separate
question governed by FINN's terms and Norwegian/EEA law, and because the
design decisions below are what keep that use defensible. They are guidance,
not license terms — but they are well-founded, and ignoring them transfers the
risk to you, the operator.

Sporhund is not affiliated with or endorsed by FINN.no or Vend Marketplaces.

This project is a **personal-use convenience layer** over your own browsing of
FINN.no. It loads the same public pages a person would open in a browser, reads
the structured data FINN already embeds in those pages, and helps *you* keep
track of *your* searches — on *your own machine*.

## What this tool deliberately does and does not do

It **does**:

- fetch a page only when you ask a tool to (one request per action);
- pace requests conservatively (a minimum interval between them);
- keep everything local — search results are returned to you and not stored,
  and watches store only listing ids you have already seen, never a mirror of
  FINN's content;
- fetch listing photos only when explicitly asked, capped in number, into
  memory only, never to disk (see "On listing photos" below);
- present a normal browser identity, because it is loading the same pages a
  person would.

It **does not**, and is deliberately designed never to do:

- run background crawlers, bulk downloads, or mirror FINN's catalogue;
- store, aggregate, publish, or redistribute FINN's listing data;
- power a public service, product, or anything commercial.

## On listing photos

Two different things, with different risk profiles:

- **Image URLs** (in search results and `get_listing`) are just links. Nothing
  is copied, so this carries no more risk than the text already does.
- **Fetching image bytes** (`view_listing_images`) is a reproduction — but it is
  the same act your browser performs when you open the ad, done on demand, for
  your own eyes, held in memory and never saved. FINN's own terms bar copying
  "med unntak av privat bruk" — *except for private use* — and Norwegian
  copyright law has a private-copying exception, so the copying itself sits
  inside the carve-out. The grey part is the automation, which is the same grey
  already accepted for text.

Note that listing photos are usually the **seller's** copyright, not FINN's, and
may contain personal data (faces, plates, home interiors). That is another
reason this tool never stores, republishes, or trains on them. Storing or
sharing fetched images would leave the private-use carve-out immediately.

## On the vehicle registry

`verify_car` and `lookup_vehicle` use Statens vegvesen's open API. That data is
public: offentleglova §7 states that information released under public-access
legislation *"kan brukast til eitkvart formål"* — may be used for any purpose —
subject only to other legislation and third-party rights, and the dataset is
licensed CC-BY 4.0. Attribution is therefore included in every result.

Two obligations follow, and Sporhund is built around them:

- **Keys are personal.** Each user orders their own with their own electronic ID
  and is personally responsible for its use. Sporhund reads your key from your
  own machine and sends it nowhere but Statens vegvesen. It must never be
  bundled with the software, shared, or proxied through a server — that would
  make one person answerable for everyone's queries, and would turn the operator
  into a data controller for other people's processing.
- **Registration and chassis numbers are personal data.** They are therefore
  never cached, logged, or written to disk. The API returns no owner information
  at all, which removes the most sensitive category entirely.

## Why the line is drawn here

FINN.no's terms prohibit automated access and, in the business terms, explicitly
prohibit "AI-driven agents, language models or other automated systems" for
**extraction or commercial reuse** of FINN's content without Vend's written
consent. FINN's content is also protected in Norway/the EEA by database rights
and åndsverkloven, and Norwegian precedent (FINN.no v. Notar "Supersøk", 2004)
shows FINN will act against third parties that build **aggregating or
re-publishing** services on its listings.

Personal, private, on-demand use that does not copy, aggregate, or redistribute
sits in a much more defensible position than a scraping-based service — but it is
still a grey area, not a blessing. This tool is built to stay firmly on the
personal-use side of that line.

**If you ever want to take this beyond personal use, stop and take the sanctioned
route first: FINN's partner API (api@finn.no) or written consent from Vend.**
Get Norwegian legal advice before commercializing anything built here.

This notice is not legal advice.
