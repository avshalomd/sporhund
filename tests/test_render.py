"""Tests for the HTML renderer — all offline, no network and no images.

The rendering functions are pure: they take listing dicts and already-fetched
data URIs, so everything worth asserting can be asserted without touching FINN.
"""

from __future__ import annotations

import re

import pytest

from sporhund.finn import CDN_IMAGE_WIDTHS, resize_image_url, snap_image_width
from sporhund.render import (
    NB_SPACE,
    card,
    data_uri,
    esc,
    kroner,
    listing_page,
    position_bar,
    results_page,
    spec_line,
    stylesheet,
)

ROW = {
    "finnkode": "123",
    "heading": "Volkswagen e-Golf",
    "url": "https://www.finn.no/mobility/item/123",
    "price": 130000,
    "location": "Stavanger",
    "seller_type": "private",
    "year": 2019,
    "mileage": 114500,
    "fuel": "El",
}


def test_price_uses_norwegian_grouping():
    """Non-breaking, so a price never wraps in the middle of the number."""
    assert kroner(130000) == f"130{NB_SPACE}000{NB_SPACE}kr"
    assert kroner(None) == "Price not stated"


def test_spec_line_skips_what_is_missing():
    assert spec_line(ROW) == f"2019 · 114{NB_SPACE}500{NB_SPACE}km · El"
    assert spec_line({"year": 2019}) == "2019"
    assert spec_line({}) == ""


def test_data_uri_round_trips():
    assert data_uri(b"hi", "image/jpeg") == "data:image/jpeg;base64,aGk="


def test_escapes_hostile_listing_text():
    """Headings come from sellers, so they are untrusted input."""
    row = dict(ROW, heading='<img src=x onerror="alert(1)">')
    html = card(row, None)
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html


def test_esc_handles_none_and_numbers():
    assert esc(None) == ""
    assert esc(2019) == "2019"


def test_card_marks_a_private_seller_and_flags_odd_ad_types():
    assert "Private seller" in card(ROW, None)
    flagged = card(dict(ROW, sales_form="Auksjon"), None)
    assert 'class="chip warn">Auksjon' in flagged


def test_card_without_a_photo_still_renders():
    assert "No photo" in card(ROW, None)
    assert "<img" in card(ROW, "data:image/jpeg;base64,aGk=")


def test_position_bar_places_markers_inside_the_track():
    pos = {"n": 35, "percentile": 74, "median": 125000,
           "min": 99532, "max": 169000, "delta_vs_median_pct": 4}
    bar = position_bar(pos, 130000)
    offsets = [float(m) for m in re.findall(r"left:([\d.]+)%", bar)]
    assert len(offsets) == 2
    assert all(0 <= o <= 100 for o in offsets)


def test_position_bar_declines_a_degenerate_range():
    """One comparable, or min == max, cannot be drawn as a position."""
    assert position_bar({"min": 5, "max": 5, "median": 5, "n": 1}, 5) == ""
    assert position_bar({"n": 0}, 100) == ""


def test_a_clean_registry_check_is_shown_rather_than_omitted():
    page = listing_page(
        {"name": "Golf", "url": "https://www.finn.no/x", "price": 1, "properties": {}},
        [],
        registry={"findings": [], "verdict": "Nothing contradicts the ad."},
    )
    assert "Vehicle registry vs. the ad" in page
    assert "Nothing contradicts the ad." in page


def test_registry_section_is_absent_when_the_check_never_ran():
    page = listing_page(
        {"name": "Golf", "url": "https://www.finn.no/x", "price": 1, "properties": {}}, []
    )
    assert "Vehicle registry vs. the ad" not in page


def test_page_declares_a_title_and_stays_self_contained():
    page = results_page([ROW], {}, title="Golfs under 200k", subtitle="9 matches")
    assert "<title>Golfs under 200k</title>" in page
    # Google Fonts is the one external host an artifact may reach.
    hosts = set(re.findall(r'https?://([^/"\')]+)', page)) - {"www.finn.no"}
    assert hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"}


@pytest.mark.parametrize("wanted,expected", [(1, 80), (500, 640), (960, 960), (5000, 1600)])
def test_image_widths_snap_to_the_ladder_the_cdn_actually_serves(wanted, expected):
    """Arbitrary widths 404 on FINN's CDN, which used to lose the photo."""
    assert snap_image_width(wanted) == expected


def test_resize_rewrites_only_the_size_segment():
    url = "https://images.finncdn.no/dynamic/480w/item/123/abc"
    assert resize_image_url(url, 1000) == "https://images.finncdn.no/dynamic/1280w/item/123/abc"
    assert all(isinstance(w, int) for w in CDN_IMAGE_WIDTHS)


def test_every_colour_token_is_defined_on_bare_root():
    """A token defined only under a media query renders unreadable in the
    default 'system' theme — the classic broken-artifact bug."""
    css = stylesheet()
    bare = css.split("@media", 1)[0]
    declared = set(re.findall(r"(--[a-z0-9-]+):", bare))
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))
    assert used <= declared, f"only defined in a theme block: {sorted(used - declared)}"
