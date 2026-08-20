"""Dev tool: render the MCP Apps views against a stand-in host, to look at them.

The real host is Claude Desktop. This is a minimal fake one: it embeds the view
in an iframe, answers `ui/initialize`, and posts a real tool result — enough to
see whether the view draws itself and whether the photos load from FINN's CDN.

    uv run python tests/preview_views.py            # both views
    uv run python tests/preview_views.py --dark
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import pathlib

from sporhund.app_ui import listing_view, results_view
from sporhund.server import get_listing, search_finn

OUT = pathlib.Path(__file__).resolve().parents[1] / ".preview"

HARNESS = """<!doctype html><html><head><meta charset="utf-8">
<title>%(name)s — host stand-in</title>
<style>
  body { margin:0; background:%(bg)s; font:13px ui-monospace,monospace; color:%(fg)s; }
  header { padding:8px 12px; opacity:.65; }
  iframe { width:100%%; height:%(height)spx; border:0; display:block; }
</style></head><body>
<header>host stand-in · %(name)s · theme %(theme)s</header>
<iframe id="view" srcdoc="%(srcdoc)s"></iframe>
<script>
var RESULT = %(result)s, INPUT = %(input)s, THEME = %(theme_json)s;
var view = document.getElementById('view');
function post(message) { view.contentWindow.postMessage(message, '*'); }
window.addEventListener('message', function (event) {
  var message = event.data;
  if (!message || message.jsonrpc !== '2.0') return;
  if (message.method === 'ui/initialize') {
    post({ jsonrpc: '2.0', id: message.id, result: {
      protocolVersion: '2026-01-26',
      hostContext: { theme: THEME, locale: 'nb-NO' },
      hostCapabilities: {}
    }});
  } else if (message.method === 'ui/notifications/initialized') {
    post({ jsonrpc: '2.0', method: 'ui/notifications/tool-input',
           params: { arguments: INPUT } });
    post({ jsonrpc: '2.0', method: 'ui/notifications/tool-result',
           params: { content: [], structuredContent: RESULT } });
  } else if (message.method === 'ui/notifications/size-changed') {
    view.style.height = Math.max(320, message.params.height + 24) + 'px';
  } else if (message.id !== undefined) {
    post({ jsonrpc: '2.0', id: message.id, result: {} });  /* ui/open-link etc. */
  }
});
</script></body></html>"""


def write(name: str, view_html: str, result: dict, tool_input: dict, theme: str) -> pathlib.Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / f"view-{name}.html"
    path.write_text(HARNESS % {
        "name": name,
        "theme": theme,
        "theme_json": json.dumps(theme),
        "bg": "#0f1413" if theme == "dark" else "#f2f5f4",
        "fg": "#e7ecea" if theme == "dark" else "#141a19",
        "height": 900,
        "srcdoc": html.escape(view_html, quote=True),
        "result": json.dumps(result),
        "input": json.dumps(tool_input),
    }, encoding="utf-8")
    return path


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--query", default="vintage kamera")
    parser.add_argument("--finnkode", default="256110421")
    args = parser.parse_args()

    search = await search_finn(vertical="torget", query=args.query)
    print(write("results", results_view(), search,
                {"vertical": "torget", "query": args.query}, args.theme))

    listing = await get_listing(args.finnkode)
    print(write("listing", listing_view(), listing,
                {"finnkode_or_url": args.finnkode}, args.theme))


if __name__ == "__main__":
    asyncio.run(main())
