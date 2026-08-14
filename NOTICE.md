# Notice on use, and on FINN.no's terms

**Read this before running the tool, and before ever considering making it public or commercial.**

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
- present a normal browser identity, because it is loading the same pages a
  person would.

It **does not**, and must not be changed to do:

- run background crawlers, bulk downloads, or mirror FINN's catalogue;
- store, aggregate, publish, or redistribute FINN's listing data;
- power a public service, product, or anything commercial.

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
