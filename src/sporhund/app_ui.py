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

IMAGE_HOST = "https://images.finncdn.no"
FONT_HOSTS = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")

def stylesheet() -> str:
    """Tokens first, components second — so both themes resolve as a set.

    Every colour is defined on bare :root and only *redefined* in the theme
    blocks; a colour whose only definition sits behind a media query never
    applies in the un-stamped "system" state.
    """
    return """
    :root {
      --paper:#f2f5f4; --card:#fdfefe; --ink:#141a19; --ink-2:#5c6866;
      --rule:#d5dcda; --accent:#1d5c58; --accent-soft:#e3edeb;
      --flag:#93361f; --flag-soft:#f6e6e1; --ok:#2b6647;
      --shadow:0 1px 2px rgba(20,26,25,.06), 0 8px 24px -16px rgba(20,26,25,.28);
      --sans:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
      --mono:"IBM Plex Mono",ui-monospace,"SF Mono",monospace;
      --serif:"IBM Plex Serif",Georgia,serif;
    }
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) {
        --paper:#0f1413; --card:#161d1c; --ink:#e7ecea; --ink-2:#95a3a0;
        --rule:#28312f; --accent:#74c0b7; --accent-soft:#172a28;
        --flag:#e2907a; --flag-soft:#2b1c18; --ok:#6cbf97;
        --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
      }
    }
    :root[data-theme="dark"] {
      --paper:#0f1413; --card:#161d1c; --ink:#e7ecea; --ink-2:#95a3a0;
      --rule:#28312f; --accent:#74c0b7; --accent-soft:#172a28;
      --flag:#e2907a; --flag-soft:#2b1c18; --ok:#6cbf97;
      --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
    }

    body { background:var(--paper); color:var(--ink); font-family:var(--sans);
           line-height:1.5; margin:0; padding:clamp(16px,3vw,40px); }
    .wrap { max-width:1180px; margin:0 auto; display:flex; flex-direction:column; gap:28px; }
    a { color:var(--accent); }
    img { max-width:100%; display:block; }
    figure { margin:0; }

    /* Masthead ------------------------------------------------------------ */
    .head { display:flex; flex-direction:column; gap:6px;
            border-bottom:1px solid var(--rule); padding-bottom:18px; }
    .eyebrow { font-family:var(--mono); font-size:.72rem; letter-spacing:.14em;
               text-transform:uppercase; color:var(--accent); }
    .head h1 { font-size:clamp(1.5rem,3.2vw,2.1rem); font-weight:600; margin:0;
               text-wrap:balance; letter-spacing:-.015em; }
    .head .sub { color:var(--ink-2); font-size:.9rem; font-family:var(--mono); }

    /* Results grid -------------------------------------------------------- */
    .grid { display:grid; gap:20px;
            grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); }
    .card { background:var(--card); border:1px solid var(--rule); border-radius:4px;
            overflow:hidden; display:flex; flex-direction:column;
            box-shadow:var(--shadow); transition:transform .12s ease; }
    .card:hover, .card:focus-within { transform:translateY(-2px); }
    .thumb { aspect-ratio:4/3; background:var(--accent-soft); overflow:hidden; }
    .thumb img { width:100%; height:100%; object-fit:cover; }
    .thumb.empty { display:grid; place-items:center; color:var(--ink-2);
                   font-family:var(--mono); font-size:.72rem; letter-spacing:.1em; }
    .card-body { padding:14px 15px 16px; display:flex; flex-direction:column; gap:7px; flex:1; }
    .price { font-family:var(--mono); font-size:1.22rem; font-weight:600;
             font-variant-numeric:tabular-nums; letter-spacing:-.02em; }
    .card h2 { font-size:.94rem; font-weight:600; margin:0; line-height:1.32;
               text-wrap:balance; }
    .card h2 a { color:inherit; text-decoration:none; }
    .card h2 a:hover { text-decoration:underline; }
    .card h2 a:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
    .meta { font-family:var(--mono); font-size:.75rem; color:var(--ink-2);
            font-variant-numeric:tabular-nums; }
    .chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:auto; padding-top:4px; }
    .chip { font-family:var(--mono); font-size:.66rem; letter-spacing:.06em;
            text-transform:uppercase; padding:2px 7px; border-radius:2px;
            background:var(--accent-soft); color:var(--accent); }
    .chip.warn { background:var(--flag-soft); color:var(--flag); }

    /* Detail view --------------------------------------------------------- */
    .dossier { display:grid; gap:28px; grid-template-columns:minmax(0,1.45fr) minmax(270px,1fr); }
    @media (max-width:880px) { .dossier { grid-template-columns:1fr; } }
    .stage { background:var(--card); border:1px solid var(--rule); border-radius:4px;
             overflow:hidden; box-shadow:var(--shadow); }
    .stage img { width:100%; aspect-ratio:4/3; object-fit:contain; background:var(--accent-soft); }
    .strip { display:flex; gap:8px; overflow-x:auto; padding:10px; }
    .strip button { flex:0 0 76px; padding:0; border:1px solid var(--rule);
                    border-radius:3px; overflow:hidden; background:none; cursor:pointer; }
    .strip button[aria-current="true"] { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); }
    .strip button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    .strip img { width:100%; aspect-ratio:4/3; object-fit:cover; }

    .facts { display:flex; flex-direction:column; gap:16px; }
    .headline-price { font-family:var(--mono); font-size:1.85rem; font-weight:600;
                      font-variant-numeric:tabular-nums; letter-spacing:-.03em; }
    dl.spec { display:grid; grid-template-columns:auto 1fr; gap:0; margin:0;
              border-top:1px solid var(--rule); }
    dl.spec dt, dl.spec dd { padding:7px 0; border-bottom:1px solid var(--rule); margin:0; }
    dl.spec dt { font-family:var(--mono); font-size:.72rem; letter-spacing:.08em;
                 text-transform:uppercase; color:var(--ink-2); padding-right:18px; }
    dl.spec dd { font-family:var(--mono); font-size:.85rem; text-align:right;
                 font-variant-numeric:tabular-nums; }

    section.block { display:flex; flex-direction:column; gap:12px; }
    section.block > h2 { font-size:.78rem; font-family:var(--mono); letter-spacing:.14em;
                         text-transform:uppercase; color:var(--accent); margin:0;
                         padding-bottom:8px; border-bottom:1px solid var(--rule); }
    /* The seller's own words, set apart from our data by the serif. */
    .prose { font-family:var(--serif); font-size:.96rem; line-height:1.62;
             max-width:66ch; white-space:pre-wrap; }
    .equipment { display:flex; flex-wrap:wrap; gap:6px; padding:0; margin:0; list-style:none; }
    .equipment li { font-size:.78rem; padding:3px 9px; border:1px solid var(--rule);
                    border-radius:2px; color:var(--ink-2); }

    .findings { display:flex; flex-direction:column; gap:8px; padding:0; margin:0; list-style:none; }
    .finding { display:flex; gap:11px; align-items:flex-start; padding:11px 13px;
               background:var(--card); border:1px solid var(--rule);
               border-left:3px solid var(--ink-2); border-radius:3px; font-size:.88rem; }
    .finding.warn { border-left-color:var(--flag); }
    .finding.ok { border-left-color:var(--ok); }
    .finding .tag { font-family:var(--mono); font-size:.66rem; letter-spacing:.08em;
                    text-transform:uppercase; color:var(--ink-2); flex:0 0 62px; padding-top:2px; }

    /* Price-position bar -------------------------------------------------- */
    .bar { display:flex; flex-direction:column; gap:9px; }
    .bar-track { position:relative; height:8px; border-radius:4px;
                 background:linear-gradient(90deg,var(--accent-soft),var(--rule)); }
    .bar-median, .bar-subject { position:absolute; top:50%; }
    .bar-median { width:2px; height:16px; background:var(--ink-2); transform:translate(-1px,-50%); }
    .bar-subject { width:13px; height:13px; border-radius:50%; background:var(--accent);
                   border:2px solid var(--card); transform:translate(-50%,-50%); }
    .bar-ends { display:flex; justify-content:space-between; font-family:var(--mono);
                font-size:.72rem; color:var(--ink-2); font-variant-numeric:tabular-nums; }
    .bar-caption { color:var(--ink); }
    .bar figcaption { font-size:.85rem; color:var(--ink-2); max-width:60ch; }

    .foot { border-top:1px solid var(--rule); padding-top:16px; font-size:.78rem;
            color:var(--ink-2); font-family:var(--mono); line-height:1.7; }
    .scroll-x { overflow-x:auto; }
    @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
    """


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
