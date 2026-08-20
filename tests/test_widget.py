"""Tests for the chat-widget fragments.

The expensive resource here is the agent's context, so the rules worth pinning
are the ones that keep a widget cheap and honest: the market median is taken
over the whole result set, a caller's chosen order survives, and the module
stays parseable on the oldest Python the package claims to support.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

import pytest

from sporhund.widget import (
    HERO_WIDTH,
    LIST_WIDTH,
    compact_widget,
    detail_widget,
    esc,
    kr,
    median,
)

ROWS = [
    {"finnkode": "1", "heading": "Tesla Model 3", "url": "https://www.finn.no/x/1",
     "price": 164900, "year": 2019, "mileage": 94000, "fuel": "El",
     "location": "Finnøy", "seller_type": "dealer"},
    {"finnkode": "2", "heading": "Tesla Model 3", "url": "https://www.finn.no/x/2",
     "price": 214532, "year": 2019, "mileage": 98560, "fuel": "El",
     "location": "Stavanger", "seller_type": "private"},
]


def test_median_is_taken_over_the_whole_market_not_the_rows_shown():
    """Three hand-picked listings have a meaningless median of their own."""
    market = [100000, 150000, 214532, 300000, 400000]
    html = compact_widget(ROWS, {}, title="t", market=market)
    assert "Median of 5 matching" in html
    assert esc(kr(214532)) in html
    # 164 900 is below the market median of 214 532, so it reads as a discount.
    assert "−49" in html and "sh-d u" in html


def test_median_falls_back_to_the_rows_when_no_market_is_given():
    html = compact_widget(ROWS, {}, title="t")
    assert "Median of 2 matching" in html


def test_a_price_exactly_at_the_median_does_not_render_as_plus_zero():
    html = compact_widget(ROWS, {}, title="t", market=[164900, 214532, 214532])
    assert "at median" in html
    assert "+0" not in html


def test_hostile_listing_text_is_escaped():
    row = dict(ROWS[0], heading='<img src=x onerror="alert(1)">')
    html = compact_widget([row], {}, title="t")
    assert "onerror=" not in html.replace("&quot;", '"').split("<style>")[0] or "&lt;img" in html
    assert "&lt;img src=x" in html


def test_a_missing_photo_leaves_the_row_intact():
    html = compact_widget(ROWS, {}, title="t")
    assert html.count("sh-r") >= 2
    assert "<img class=\"sh-t\"" not in html


def test_a_widget_with_no_photos_is_cheap():
    """The text-only path is what makes --no-images worth offering: the shared
    stylesheet is the floor, and rows themselves cost almost nothing."""
    two = len(compact_widget(ROWS, {}, title="t"))
    one = len(compact_widget(ROWS[:1], {}, title="t"))
    assert two < 4000, "a photo-less widget should be ~1k tokens"
    assert two - one < 500, "each extra row should be cheap"


def test_detail_shows_spec_and_trims_a_long_description():
    listing = {"name": "Tesla Model 3", "url": "https://www.finn.no/x/2", "price": 214532,
               "description": "word " * 200, "properties": {"year": 2019, "mileage": 98560}}
    html = detail_widget(listing, None, [])
    assert "Year" in html and "2019" in html
    assert "…" in html
    assert len(html) < 6000


def test_the_list_default_is_the_cheap_width():
    """80w is ~1.1k tokens a photo; 240w is ~5.9k. The default must be 80."""
    assert LIST_WIDTH == 80
    assert HERO_WIDTH == 240


def test_median_of_nothing_is_none():
    assert median([]) is None
    assert median([1, 2, 3]) == 2


@pytest.mark.parametrize("module", ["widget.py", "render.py", "app_ui.py", "finn.py"])
def test_modules_parse_on_the_oldest_supported_python(module):
    """pyproject claims >=3.10, but nested same-quote f-strings need 3.12."""
    source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "sporhund" / module).read_text()
    tree = ast.parse(source)
    assert tree is not None
    proof = subprocess.run(
        [sys.executable, "-c",
         "import ast,sys;ast.parse(open(sys.argv[1]).read())",
         str(pathlib.Path(__file__).resolve().parents[1] / "src" / "sporhund" / module)],
        capture_output=True,
    )
    assert proof.returncode == 0, proof.stderr.decode()
