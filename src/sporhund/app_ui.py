"""MCP Apps views — the listing pages, rendered inside the conversation.

The same design as `render.py`, delivered the other way round. There, Python
builds a finished page and inlines the photos. Here the host renders a `ui://`
resource in a sandboxed iframe, hands it the tool result over postMessage, and
the view draws itself — so photos are loaded straight from FINN's CDN (declared
in the resource's CSP) rather than copied into a file.

Wire format: MCP Apps, `text/html;profile=mcp-app`. The view sends
`ui/initialize`, then `ui/notifications/initialized`, and the host answers with
`ui/notifications/tool-result` carrying the CallToolResult.
"""

from __future__ import annotations

import json

from . import __version__
from .finn import CDN_IMAGE_WIDTHS
from .render import stylesheet

IMAGE_HOST = "https://images.finncdn.no"
FONT_HOSTS = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")

RESULTS_URI = "ui://sporhund/results.html"
LISTING_URI = "ui://sporhund/listing.html"

_BRIDGE = """
var Bridge = (function () {
  var nextId = 1, pending = {}, onResult = null, toolInput = {};
  function send(message) { window.parent.postMessage(message, '*'); }
  function request(method, params) {
    var id = nextId++;
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      send({ jsonrpc: '2.0', id: id, method: method, params: params || {} });
    });
  }
  function notify(method, params) {
    send({ jsonrpc: '2.0', method: method, params: params || {} });
  }
  window.addEventListener('message', function (event) {
    var message = event.data;
    if (!message || message.jsonrpc !== '2.0') return;
    if (message.id !== undefined && pending[message.id]) {
      var waiter = pending[message.id];
      delete pending[message.id];
      if (message.error) { waiter.reject(message.error); } else { waiter.resolve(message.result); }
      return;
    }
    if (message.method === 'ui/notifications/tool-input') {
      /* Arrives before the result, and carries what was actually asked for. */
      toolInput = (message.params && message.params.arguments) || {};
    }
    if (message.method === 'ui/notifications/tool-result' && onResult) {
      onResult(unwrap(message.params), toolInput);
    }
  });
  /* The host sends a CallToolResult; the payload is the structured content,
     with the text block as the fallback for hosts that omit it. */
  function unwrap(result) {
    if (!result) return null;
    if (result.structuredContent) return result.structuredContent;
    var blocks = result.content || [];
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i] && blocks[i].type === 'text') {
        try { return JSON.parse(blocks[i].text); } catch (error) { /* not JSON */ }
      }
    }
    return null;
  }
  /* A 50-result grid is thousands of pixels tall; ask for a frame that fits a
     conversation and let the view scroll inside it. */
  var MAX_HEIGHT = 760;
  function reportSize() {
    var root = document.documentElement;
    notify('ui/notifications/size-changed',
           { width: root.scrollWidth, height: Math.min(root.scrollHeight, MAX_HEIGHT) });
  }
  function start(handler) {
    onResult = function (payload, input) { handler(payload, input || {}); reportSize(); };
    request('ui/initialize', {
      protocolVersion: '2026-01-26',
      capabilities: {},
      clientInfo: { name: 'sporhund-view', version: VERSION }
    }).then(function (result) {
      var context = (result && result.hostContext) || {};
      if (context.theme === 'dark' || context.theme === 'light') {
        document.documentElement.setAttribute('data-theme', context.theme);
      }
    }).catch(function () { /* host without hostContext still gets a view */ })
      .then(function () { notify('ui/notifications/initialized', {}); });
  }
  /* A sandboxed iframe cannot navigate the top window, so hand links back. */
  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[href^="http"]');
    if (!link) return;
    event.preventDefault();
    request('ui/open-link', { url: link.href });
  });
  window.addEventListener('resize', reportSize);
  return { start: start, request: request, notify: notify, reportSize: reportSize };
})();
"""

_SHARED = """
var WIDTHS = %(widths)s;
function snapWidth(wanted) {
  for (var i = 0; i < WIDTHS.length; i++) { if (WIDTHS[i] >= wanted) return WIDTHS[i]; }
  return WIDTHS[WIDTHS.length - 1];
}
/* FINN's CDN 404s on any width outside its ladder, so ask for a real one. */
function sized(url, width) {
  if (!url) return '';
  return url.replace(/(\\/dynamic\\/)[^/]+(\\/)/, '$1' + snapWidth(width) + 'w$2');
}
function esc(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
var NB = '\\u00a0';
function kroner(value) {
  if (typeof value !== 'number') return 'Price not stated';
  return String(Math.round(value)).replace(/\\B(?=(\\d{3})+(?!\\d))/g, NB) + NB + 'kr';
}
function num(value, unit) {
  if (typeof value !== 'number') return null;
  var text = String(Math.round(value)).replace(/\\B(?=(\\d{3})+(?!\\d))/g, NB);
  return unit ? text + NB + unit : text;
}
function specLine(row) {
  return [typeof row.year === 'number' ? row.year : null, num(row.mileage, 'km'),
          row.fuel, row.transmission].filter(Boolean).join(' · ');
}
function chips(row) {
  var out = [];
  if (row.seller_type) {
    out.push(['', row.seller_type === 'private' ? 'Private seller' : 'Dealer']);
  }
  if (row.trade_type && row.trade_type.toLowerCase() !== 'til salgs') out.push([' warn', row.trade_type]);
  if (row.sales_form && row.sales_form.toLowerCase().indexOf('bruktbil') !== 0) {
    out.push([' warn', row.sales_form]);
  }
  return out.map(function (chip) {
    return '<span class="chip' + chip[0] + '">' + esc(chip[1]) + '</span>';
  }).join('');
}
function fail(message) {
  document.getElementById('root').innerHTML =
    '<div class="head"><div class="eyebrow">Sporhund</div><h1>' + esc(message) + '</h1></div>';
  Bridge.reportSize();
}
"""


def _document(title: str, body: str, script: str) -> str:
    """A standalone iframe document — unlike an artifact, it owns its own head."""
    fonts = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        "family=IBM+Plex+Mono:wght@400;500;600&"
        "family=IBM+Plex+Sans:wght@400;500;600;700&"
        'family=IBM+Plex+Serif:wght@400&display=swap">'
    )
    shared = _SHARED % {"widths": json.dumps(list(CDN_IMAGE_WIDTHS))}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>{fonts}
<style>{stylesheet()}
body {{ padding:14px; }}
.wrap {{ gap:18px; }}
</style></head>
<body><div class="wrap" id="root"></div>
<script>
var VERSION = {json.dumps(__version__)};
{_BRIDGE}
{shared}
{script}
</script></body></html>"""


_RESULTS_SCRIPT = """
function card(row) {
  var thumb = row.image_url
    ? '<div class="thumb"><img src="' + esc(sized(row.image_url, 480)) + '" alt="" loading="lazy"></div>'
    : '<div class="thumb empty">No photo</div>';
  var line = specLine(row);
  return '<article class="card">' + thumb +
    '<div class="card-body">' +
      '<div class="price">' + esc(kroner(row.price)) + '</div>' +
      '<h2><a href="' + esc(row.url) + '">' + esc(row.heading) + '</a></h2>' +
      (line ? '<div class="meta">' + esc(line) + '</div>' : '') +
      (row.location ? '<div class="meta">' + esc(row.location) + '</div>' : '') +
      '<div class="chips">' + chips(row) + '</div>' +
    '</div></article>';
}
Bridge.start(function (payload, input) {
  if (!payload || !payload.listings) { return fail('No results to show.'); }
  var rows = payload.listings;
  var stats = payload.price_stats || {};
  var subtitle = [
    payload.total_matches !== undefined && payload.total_matches !== null
      ? payload.total_matches + ' matches' : null,
    'showing ' + rows.length,
    typeof stats.median === 'number' ? 'median ' + kroner(stats.median) : null
  ].filter(Boolean).join(' · ');
  var warnings = [];
  if (payload.ignored_filters && payload.ignored_filters.length) {
    warnings.push('FINN ignored these filters: ' + payload.ignored_filters.join(', '));
  }
  if (payload.price_stats_note) warnings.push(payload.price_stats_note);
  document.getElementById('root').innerHTML =
    '<header class="head"><div class="eyebrow">Sporhund · FINN.no</div>' +
    '<h1>' + esc(input.query || payload.vertical || 'Results') + '</h1>' +
    '<div class="sub">' + esc(subtitle) + '</div></header>' +
    warnings.map(function (w) {
      return '<div class="finding warn"><span class="tag">note</span><span>' + esc(w) + '</span></div>';
    }).join('') +
    '<div class="grid">' + rows.map(card).join('') + '</div>';
});
"""

_LISTING_SCRIPT = """
var SPEC = [['year','Year',''],['mileage','Mileage','km'],['fuel','Fuel',''],
  ['transmission','Transmission',''],['power_hp','Power','hp'],['owners','Owners',''],
  ['first_registration','First registered',''],['eu_check_next','Next EU check',''],
  ['body_type','Body',''],['wheel_drive','Drive',''],['no_of_seats','Seats',''],
  ['registration_number','Registration',''],['sales_form','Sales form',''],
  ['condition','Condition','']];

function specTable(props) {
  var rows = SPEC.map(function (entry) {
    var value = props[entry[0]];
    if (value === undefined || value === null || value === '') return '';
    if (typeof value === 'boolean') value = value ? 'Yes' : 'No';
    else if (typeof value === 'number' && entry[2]) value = num(value, entry[2]);
    return '<dt>' + esc(entry[1]) + '</dt><dd>' + esc(value) + '</dd>';
  }).join('');
  return rows ? '<dl class="spec">' + rows + '</dl>' : '';
}

function gallery(images) {
  if (!images || !images.length) return '<div class="stage"><div class="thumb empty">No photos</div></div>';
  var strip = images.length < 2 ? '' : '<div class="strip scroll-x">' + images.map(function (url, i) {
    return '<button type="button" data-full="' + esc(sized(url, 960)) + '"' +
      ' aria-current="' + (i === 0) + '" aria-label="Show photo ' + (i + 1) + ' of ' + images.length + '">' +
      '<img src="' + esc(sized(url, 240)) + '" alt="" loading="lazy"></button>';
  }).join('') + '</div>';
  return '<div class="stage"><img id="stage-image" src="' + esc(sized(images[0], 960)) +
         '" alt="Listing photo 1 of ' + images.length + '">' + strip + '</div>';
}

function wireGallery() {
  var stage = document.getElementById('stage-image');
  var buttons = [].slice.call(document.querySelectorAll('.strip button'));
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      stage.src = button.getAttribute('data-full');
      stage.alt = button.getAttribute('aria-label') || '';
      buttons.forEach(function (other) {
        other.setAttribute('aria-current', String(other === button));
      });
    });
  });
}

Bridge.start(function (listing) {
  if (!listing || !listing.name) { return fail('No listing to show.'); }
  var props = listing.properties || {};
  var blocks = '';
  if (listing.description) {
    blocks += '<section class="block"><h2>Seller\\u2019s own description</h2>' +
      '<div class="prose">' + esc(listing.description) + '</div></section>';
  }
  if (listing.equipment && listing.equipment.length) {
    blocks += '<section class="block"><h2>Equipment</h2><ul class="equipment">' +
      listing.equipment.map(function (item) { return '<li>' + esc(item) + '</li>'; }).join('') +
      '</ul></section>';
  }
  document.getElementById('root').innerHTML =
    '<header class="head"><div class="eyebrow">Sporhund · FINN.no</div>' +
    '<h1>' + esc(listing.name) + '</h1></header>' +
    '<div class="dossier">' + gallery(listing.images) +
      '<div class="facts"><div class="headline-price">' + esc(kroner(listing.price)) + '</div>' +
      specTable(props) +
      '<a href="' + esc(listing.url) + '">Open the ad on FINN &rarr;</a></div>' +
    '</div>' + blocks;
  wireGallery();
});
"""


def results_view() -> str:
    return _document("FINN results", "", _RESULTS_SCRIPT)


def listing_view() -> str:
    return _document("FINN listing", "", _LISTING_SCRIPT)
