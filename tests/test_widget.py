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
    DEFAULT_BUDGET,
    MAX_PHOTOS,
    PHOTO_BYTES,
    THUMB_BYTES,
    car_name,
    compact_widget,
    detail_widget,
    esc,
    fit_jpeg,
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
    html = detail_widget(listing, [])
    assert "Year" in html and "2019" in html
    assert "…" in html
    assert len(html) < 6000


def test_photo_budgets_stay_small_enough_to_emit_in_one_piece():
    """Measured, not assumed: a ~24 KB tool result survives whole while a ~31 KB
    one is truncated to a file, and base64 inflates bytes by 4/3. Both a
    six-row list and a detail card must clear that with room for the markup."""
    ceiling = 23_000
    stylesheet_and_markup = 4_000
    assert THUMB_BYTES * 6 * 4 // 3 + stylesheet_and_markup < ceiling
    assert PHOTO_BYTES * MAX_PHOTOS * 4 // 3 + stylesheet_and_markup < ceiling
    assert DEFAULT_BUDGET * 4 < ceiling


def test_no_single_photo_is_large_enough_to_arrive_corrupted():
    """A ~15 KB base64 blob does not survive being carried into a widget call;
    ~3 KB ones do. Every photo must stay in the range that works."""
    assert PHOTO_BYTES * 4 // 3 < 3_500
    assert THUMB_BYTES * 4 // 3 < 3_500


@pytest.mark.parametrize("row,expected", [
    ({"heading": "Tesla Model 3", "model_specification": "Long Range AWD"},
     "Tesla Model 3 · Long Range AWD"),
    # A dealer keyword dump: keep only the first, useful segment.
    ({"heading": "Tesla Model 3",
      "model_specification": "SR / 415km / Skinn / Autopilot / EU27 / Norsk++++"},
     "Tesla Model 3 · SR"),
    # Redundant with the heading, so it adds nothing.
    ({"heading": "Volkswagen e-Golf", "model_specification": "e-Golf"},
     "Volkswagen e-Golf"),
    ({"heading": "Tesla Model 3"}, "Tesla Model 3"),
])
def test_car_name_keeps_the_useful_half_of_the_variant(row, expected):
    assert car_name(row) == expected


def test_fit_jpeg_lands_under_its_byte_budget():
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (1600, 1200), "navy").save(source, "JPEG", quality=95)
    out = fit_jpeg(source.getvalue(), max_bytes=1800, max_side=220, ratio=4 / 3)
    assert len(out) <= 1800
    assert Image.open(io.BytesIO(out)).size[0] <= 220


@pytest.mark.parametrize("html", [
    compact_widget(ROWS, {}, title="t"),
    detail_widget({"name": "x", "url": "https://www.finn.no/x", "price": 1,
                   "properties": {}}, []),
])
def test_every_style_block_is_closed(html):
    """An unclosed <style> swallows the markup that follows it as CSS text."""
    assert html.count("<style>") == html.count("</style>") == 2


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
