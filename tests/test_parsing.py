"""Parser tests that run against locally-saved FINN pages.

The fixtures are intentionally NOT committed (they contain FINN's content, which
this project does not redistribute — see NOTICE.md, and note `*.html` is
git-ignored). To run these tests, save a few pages yourself first:

    python tests/refresh_fixtures.py

Without fixtures present, the tests skip rather than fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sporhund.finn import (
    _canonical_item_url,
    _coerce_price,
    _parse_listing,
    _parse_search,
    resize_image_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str | None:
    p = FIXTURES / name
    return p.read_text(encoding="utf-8") if p.exists() else None


@pytest.mark.parametrize(
    "fixture,vertical,required_extra",
    [
        ("torget_search.html", "torget", None),
        ("car_search.html", "car", "year"),
        ("job_search.html", "job", None),
    ],
)
def test_parse_search(fixture: str, vertical: str, required_extra: str | None) -> None:
    html = _read(fixture)
    if html is None:
        pytest.skip(f"fixture {fixture} not present")
    result = _parse_search(html, vertical)
    assert result.listings, "expected at least one listing"
    assert result.total_matches and result.total_matches > 0
    first = result.listings[0]
    assert first.finnkode.isdigit()
    assert first.heading
    assert first.url.startswith("https://www.finn.no/")
    if required_extra:
        assert any(
            required_extra in l.to_dict() for l in result.listings
        ), f"expected some listing to expose '{required_extra}'"


def test_parse_torget_listing() -> None:
    html = _read("item.html")
    if html is None:
        pytest.skip("fixture item.html not present")
    data = _parse_listing(html, "https://www.finn.no/recommerce/forsale/item/235798748")
    assert data.get("name")
    assert data.get("description")


def test_torget_description_is_not_the_seo_stub() -> None:
    """JSON-LD truncates at ~160 chars; we must return the seller's full text."""
    html = _read("item.html")
    if html is None:
        pytest.skip("fixture item.html not present")
    data = _parse_listing(html, "https://www.finn.no/recommerce/forsale/item/235798748")
    description = data["description"]
    assert len(description) > 400, f"description looks truncated: {len(description)}"
    assert "<" not in description, "markup leaked into the description"
    assert "&nbsp;" not in description and "&amp;" not in description


def test_search_reports_trade_type() -> None:
    """Giveaways and wanted-to-buy ads must be distinguishable from real sales."""
    html = _read("torget_search.html")
    if html is None:
        pytest.skip("fixture torget_search.html not present")
    result = _parse_search(html, "torget")
    trade_types = {l.trade_type for l in result.listings}
    assert trade_types - {None}, "expected at least one trade_type label"


def test_prices_are_always_ints() -> None:
    """Cross-vertical comparison breaks if one path returns '13500' as a string."""
    for fixture, url in (
        ("item.html", "https://www.finn.no/recommerce/forsale/item/235798748"),
        ("car_item.html", "https://www.finn.no/mobility/item/473244106"),
    ):
        html = _read(fixture)
        if html is None:
            continue
        price = _parse_listing(html, url).get("price")
        assert price is None or isinstance(price, int), f"{fixture}: {price!r}"

    for fixture, vertical in (("torget_search.html", "torget"), ("car_search.html", "car")):
        html = _read(fixture)
        if html is None:
            continue
        for listing in _parse_search(html, vertical).listings:
            assert listing.price is None or isinstance(listing.price, int)


def test_car_page_carrying_both_formats_still_gets_rich_data() -> None:
    """Some car pages ship JSON-LD *and* data-props.

    JSON-LD alone yields a name and price but none of the car detail, so the
    two sources must be merged rather than treated as either/or.
    """
    html = _read("car_item_with_ld.html")
    if html is None:
        pytest.skip("fixture car_item_with_ld.html not present")
    data = _parse_listing(html, "https://www.finn.no/mobility/item/473250077")
    props = data.get("properties") or {}
    assert props.get("year") and props.get("mileage")
    assert data.get("equipment"), "equipment lost when JSON-LD is also present"
    assert isinstance(data.get("price"), int)


def test_search_results_carry_a_thumbnail() -> None:
    html = _read("torget_search.html")
    if html is None:
        pytest.skip("fixture torget_search.html not present")
    result = _parse_search(html, "torget")
    with_images = [l for l in result.listings if l.image_url]
    assert with_images, "expected most listings to have a thumbnail"
    assert all(
        l.image_url.startswith("https://images.finncdn.no/") for l in with_images
    )


@pytest.mark.parametrize(
    "fixture,url",
    [
        ("item.html", "https://www.finn.no/recommerce/forsale/item/235798748"),
        ("car_item_with_ld.html", "https://www.finn.no/mobility/item/473250077"),
    ],
)
def test_listing_exposes_image_urls(fixture: str, url: str) -> None:
    """URLs only — get_listing must never download image bytes."""
    html = _read(fixture)
    if html is None:
        pytest.skip(f"fixture {fixture} not present")
    images = _parse_listing(html, url).get("images") or []
    assert images, "expected at least one image URL"
    assert all(u.startswith("https://images.finncdn.no/") for u in images)


@pytest.mark.parametrize(
    "url,width,expected",
    [
        (
            "https://images.finncdn.no/dynamic/default/2024/8/x/1_a.jpg",
            640,
            "https://images.finncdn.no/dynamic/640w/2024/8/x/1_a.jpg",
        ),
        (
            "https://images.finncdn.no/dynamic/1280w/2024/8/x/1_a.jpg",
            480,
            "https://images.finncdn.no/dynamic/480w/2024/8/x/1_a.jpg",
        ),
        (  # car images have no file extension
            "https://images.finncdn.no/dynamic/default/item/473250077/721a2ad2",
            640,
            "https://images.finncdn.no/dynamic/640w/item/473250077/721a2ad2",
        ),
    ],
)
def test_resize_image_url(url: str, width: int, expected: str) -> None:
    assert resize_image_url(url, width) == expected


def test_bare_finnkode_resolves_via_site_root() -> None:
    """A vertical-specific guess 404s for anything that isn't a Torget item."""
    assert _canonical_item_url("473250077") == "https://www.finn.no/473250077"
    assert (
        _canonical_item_url("https://www.finn.no/mobility/item/473250077")
        == "https://www.finn.no/mobility/item/473250077"
    )


def test_refuses_non_finn_urls() -> None:
    from sporhund.finn import FinnError

    with pytest.raises(FinnError):
        _canonical_item_url("https://evil.example.com/item/123456")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("13500", 13500),
        ("13 500 kr", 13500),
        (119000, 119000),
        ({"amount": 2000}, 2000),
        ({"total": 119000, "main": 114468}, 119000),
        (None, None),
        ("", None),
        (True, None),
    ],
)
def test_coerce_price(raw, expected) -> None:
    assert _coerce_price(raw) == expected


def test_parse_car_listing() -> None:
    html = _read("car_item.html")
    if html is None:
        pytest.skip("fixture car_item.html not present")
    data = _parse_listing(html, "https://www.finn.no/mobility/item/473244106")
    assert data.get("name")
    props = data.get("properties") or {}
    assert props.get("year"), "expected the car's year among properties"
    assert props.get("mileage"), "expected the car's mileage among properties"
    assert data.get("price")
    # Condition signals and equipment are the raw material for deal scoring.
    assert props.get("eu_check_next"), "expected the next EU-check date"
    assert props.get("has_known_damages") is not None
    assert isinstance(props.get("transmission"), str), "value-wrapper not unwrapped"
    assert data.get("equipment"), "expected an equipment list"


def test_price_stats() -> None:
    from sporhund.finn import Listing, summarize

    listings = [
        Listing(finnkode="1", heading="a", url="u", price=100),
        Listing(finnkode="2", heading="b", url="u", price=200),
        Listing(finnkode="3", heading="c", url="u", price=300),
    ]
    stats = summarize(listings)
    assert stats == {"count": 3, "min": 100, "median": 200, "max": 300, "mean": 200}


def test_car_description_full_text_not_seo_stub() -> None:
    """Field-tested regression: car pages put the seller's text in a
    whitespace-pre-wrap div under <h2>Beskrivelse</h2>, not in the Torget-style
    data-testid section — extraction returned None and silently fell back to
    the ~156-char JSON-LD stub."""
    html = _read("car_item_description.html")
    if html is None:
        pytest.skip("fixture car_item_description.html not present")
    data = _parse_listing(html, "https://www.finn.no/mobility/item/470979797")
    desc = data.get("description") or ""
    assert len(desc) > 400, f"still the SEO stub: {len(desc)} chars"
    assert "<" not in desc and "&nbsp;" not in desc


def test_car_private_seller_is_not_labeled_dealer() -> None:
    """Car docs carry dealer_segment as a label; 'Privat' must map to private."""
    from sporhund.finn import _seller_type

    assert _seller_type({"dealer_segment": "Privat"}) == "private"
    assert _seller_type({"dealer_segment": "Merkeforhandler"}) == "dealer"
    assert _seller_type({"dealer_segment": "Forhandler"}) == "dealer"
    assert _seller_type({"flags": ["private"]}) == "private"
    assert _seller_type({}) is None


def test_filter_metadata_is_parsed() -> None:
    """get_search_filters feeds on the same page state searches use."""
    import base64 as b64
    import json as jsonlib
    import re as relib

    from sporhund.finn import _decode_state, _find_results, _parse_filters

    html = _read("car_search.html")
    if html is None:
        pytest.skip("fixture car_search.html not present")
    results = _find_results(_decode_state(html))
    parsed = _parse_filters(results["filters"])
    by_name = {f["name"]: f for f in parsed}

    fuel = by_name.get("fuel")
    assert fuel and any(
        v["label"] == "Hybrid bensin" and v["value"] == "6" for v in fuel["values"]
    )
    seg = by_name.get("dealer_segment")
    assert seg and any(
        v["label"] == "Privat" and v["value"] == "3" for v in seg["values"]
    ), "car vertical: Privat must be dealer_segment=3"
    price = by_name.get("price")
    assert price and price.get("type") == "range"
    assert price.get("params") == ["price_from", "price_to"]
    location = by_name.get("location")
    assert location and any(v.get("children") for v in location["values"]), (
        "counties should carry municipality children"
    )


def test_ignored_filters_detection() -> None:
    """FINN applies unknown params to nothing; we must surface that.

    metadata.params echoes even unrecognized names, so detection must use
    selected_filters — the list of filters that actually took effect.
    """
    from sporhund.finn import _applied_filter_params

    html = _read("car_search.html")
    if html is None:
        pytest.skip("fixture car_search.html not present")
    applied = _applied_filter_params(html)
    assert isinstance(applied, set)
    # fixture fetched with ?q=golf only — no filter params were applied
    assert "number_of_seats_from" not in applied


def test_car_search_docs_expose_the_verification_fields() -> None:
    """regno/chassis/fuel/make/model/sales_form live on the search docs."""
    html = _read("car_search.html")
    if html is None:
        pytest.skip("fixture car_search.html not present")
    listings = _parse_search(html, "car").listings
    with_regno = [l for l in listings if l.extra.get("registration_number")]
    assert with_regno, "expected registration numbers on search results"
    assert any(l.extra.get("fuel") for l in listings)
    assert any(l.extra.get("make") and l.extra.get("model") for l in listings)
    assert all(
        l.extra.get("sales_form") in (None, "Bruktbil til salgs", "Nybil til salgs",
                                      "Bud ønskes", "Leasing", "Auksjon")
        or isinstance(l.extra.get("sales_form"), str)
        for l in listings
    ), "sales_form codes must be mapped to labels"


def test_job_docs_expose_positions_count() -> None:
    html = _read("job_search.html")
    if html is None:
        pytest.skip("fixture job_search.html not present")
    listings = _parse_search(html, "job").listings
    assert any(isinstance(l.extra.get("no_of_positions"), int) for l in listings)


def test_description_unsafe_beats_the_stub_and_is_clean() -> None:
    """Dealer ads may render no pre-wrap block; the payload's raw HTML
    description (7 800 chars on the fixture) must be used and cleaned."""
    html = _read("car_item_with_ld.html")
    if html is None:
        pytest.skip("fixture car_item_with_ld.html not present")
    desc = _parse_listing(html, "u").get("description") or ""
    assert len(desc) > 1000, f"expected the full dealer description, got {len(desc)}"
    assert "<strong>" not in desc and "<br" not in desc and "&nbsp;" not in desc


def test_fuel_matches_across_vocabularies() -> None:
    from sporhund.cars import fuel_matches

    assert fuel_matches("Elektrisk", "El")
    assert fuel_matches("El", "Elektrisk")
    assert fuel_matches("Bensin", "Bensin")
    assert not fuel_matches("Bensin", "Diesel")
    assert not fuel_matches(None, "El")
    # different drivetrains must not match — neither label prefixes the other
    assert not fuel_matches("Hybrid bensin", "Bensin")
