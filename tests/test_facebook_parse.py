"""Tests for reading Facebook's payloads, against data captured from a live page.

The fixture is real, so these assert the awkward parts rather than the happy
path: the free listing whose rendered price says "$0" in Norway, the absent
seller, and the duplicate-reference problem that a naive walker turns into
repeated results. All offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sporhund.facebook import parse

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "facebook_search.json").read_text()
)
LISTINGS = FIXTURE["listings"]


def test_normalizes_a_real_listing():
    row = parse.normalize(LISTINGS[0])
    assert row["source"] == "facebook"
    assert row["id"] == "1626888188872834"
    assert row["heading"] == "Sofa i god stand"
    assert row["price"] == 2500
    assert row["currency"] == "NOK"
    assert row["location"] == "Oslo, Norway"
    assert row["url"].endswith("/marketplace/item/1626888188872834/")
    assert row["published"].startswith("2026-")


def test_free_item_keeps_its_amount_and_drops_the_wrong_currency():
    """A free Oslo listing renders as "$0" for logged-out visitors.

    The numeric amount is still right, so the price is read from that and the
    dollar sign is simply not reported as a currency — reporting USD here would
    be worse than reporting nothing.
    """
    row = parse.normalize(LISTINGS[1])
    assert row["price"] == 0
    assert row["currency"] is None


@pytest.mark.parametrize(
    "formatted, amount, expected",
    [
        ("kr 4 000", "4000.00", "NOK"),   # what a Norwegian-locale page renders
        ("kr 1", "1.00", "NOK"),
        ("NOK2,500", "2500.00", "NOK"),   # what an English-locale page renders
        ("kr 0", "0.00", None),           # free: no meaningful currency
        ("USD 0", "0.00", None),          # Facebook's fallback for a free item
        ("$0", "0.00", None),
        ("", "1500.00", None),            # nothing rendered, nothing invented
    ],
)
def test_currency_survives_both_locales_and_the_free_item_fallback(
    formatted, amount, expected
):
    """Live pages render prices differently from the captured fixture.

    The fixture was taken in an English locale and the scraper runs in a
    Norwegian one, so both forms have to parse. The zero cases are the reason
    the price is not simply trusted: Facebook labels free listings in a currency
    that has nothing to do with where they are.
    """
    row = parse.normalize(
        {
            "id": "1",
            "marketplace_listing_title": "x",
            "listing_price": {"formatted_amount": formatted, "amount": amount},
        }
    )
    assert row["currency"] == expected
    assert row["price"] == int(round(float(amount)))


def test_item_pages_state_their_own_currency_and_place():
    """Item pages use a different shape from search cards, for both fields.

    The currency is given outright rather than rendered into the string, the
    formatted amount sits under another key, and `location` holds bare
    coordinates with the place name moved to `location_text`. Reading only the
    search-card shape yielded a listing with no location and no currency.
    """
    row = parse.normalize(
        {
            "id": "1",
            "marketplace_listing_title": "Sofa i god stand",
            "listing_price": {
                "formatted_amount_zeros_stripped": "kr 2 500",
                "amount": "2500.00",
                "currency": "NOK",
            },
            "location": {"latitude": 59.9111, "longitude": 10.7501},
            "location_text": {"text": "Oslo, Norge"},
        }
    )
    assert row["price"] == 2500
    assert row["currency"] == "NOK"
    assert row["location"] == "Oslo, Norge"
    assert row["extra"]["coordinates"] == {"lat": 59.9111, "lon": 10.7501}


def test_no_seller_identity_is_carried():
    """Logged-out pages carry no seller, and nothing should invent one."""
    assert all(l["marketplace_listing_seller"] is None for l in LISTINGS)
    row = parse.normalize(LISTINGS[0])
    assert "seller" not in json.dumps(row).lower()


def test_walker_finds_listings_at_any_depth():
    buried = {"data": {"feed": {"edges": [{"node": {"listing": LISTINGS[0]}}]}}}
    found = parse.find_listings(buried)
    assert len(found) == 1
    assert found[0]["id"] == LISTINGS[0]["id"]


def test_repeated_references_yield_one_row():
    """Relay stores reach the same object by several paths."""
    doubled = {"a": LISTINGS[0], "b": {"c": LISTINGS[0]}, "d": LISTINGS[1]}
    assert sorted(l["id"] for l in parse.find_listings(doubled)) == sorted(
        [LISTINGS[0]["id"], LISTINGS[1]["id"]]
    )


def test_reads_listings_out_of_a_rendered_page():
    html = (
        "<html><script type=\"application/json\" data-sjs>"
        + json.dumps({"require": [["x", {"result": {"items": LISTINGS}}]]})
        + "</script><script type=\"application/json\">not json at all</script></html>"
    )
    rows = parse.listings_from_html(html)
    assert len(rows) == 3
    assert {r["heading"] for r in rows} == {"Sofa i god stand", "Sofa", "Fin sofa"}


def test_missing_fields_do_not_raise():
    assert parse.normalize({"id": "1", "marketplace_listing_title": "x"})["price"] is None
    assert parse.normalize({})["heading"] == "(no title)"


def _item_page(extra_script: str = "") -> str:
    """A stand-in item page, shaped like the real one.

    On a real page the description and attributes hang off the listing object
    while the photos sit on a neighbouring node, with the hero also exposed as
    an og:image tag. The fake keeps that arrangement, because it is exactly what
    the parser has to cope with.
    """
    listing = dict(LISTINGS[0])
    listing["redacted_description"] = {"text": "Ikke royk og ikke dyr"}
    listing["attribute_data"] = [
        {"attribute_name": "Condition", "value": "used_good", "label": "Used - Good"}
    ]
    photos = {
        "listing_photos": [
            {"image": {"uri": "https://scontent.example/photo-a.jpg"}},
            {"image": {"uri": "https://scontent.example/photo-b.jpg"}},
        ]
    }
    return (
        '<meta property="og:image" content="https://scontent.example/hero.jpg">'
        '<script type="application/json">'
        + json.dumps({"listing": listing, "media": photos})
        + "</script>"
        + extra_script
    )


def test_item_page_yields_description_and_attributes():
    row = parse.detail_from_html(_item_page())
    assert row["description"] == "Ikke royk og ikke dyr"
    assert row["attributes"] == {"Condition": "Used - Good"}
    assert row["heading"] == "Sofa i god stand"


def test_item_page_collects_photos_with_the_hero_first():
    row = parse.detail_from_html(_item_page())
    assert row["image_urls"][0].endswith("hero.jpg")
    assert len(row["image_urls"]) == 3
    assert len(set(row["image_urls"])) == 3


def test_item_page_prefers_the_richest_copy_of_the_listing():
    """One page carries the same listing several times, most copies half-filled."""
    thin = json.dumps(
        {"thin": {"id": LISTINGS[0]["id"], "marketplace_listing_title": "Sofa i god stand"}}
    )
    row = parse.detail_from_html(
        _item_page('<script type="application/json">' + thin + "</script>")
    )
    assert "description" in row


def test_item_page_without_listings_returns_none():
    assert parse.detail_from_html("<html>nothing here</html>") is None


def _recommendations() -> str:
    """"Today's picks" — unrelated ads Facebook staples onto every item page.

    Given far more fields than the listing itself, because that is what made
    this a bug in the first place.
    """
    fat = dict(LISTINGS[2])
    fat.update({f"filler_{i}": i for i in range(40)})
    return (
        '<script type="application/json">'
        + json.dumps({"picks": [fat]})
        + "</script>"
    )


def test_item_page_returns_the_listing_asked_for_not_the_richest_on_the_page():
    """A page's fattest object is often a recommendation, not the item.

    Live, this returned a house in Lunner when a sofa in Oslo was requested.
    """
    html = _item_page(_recommendations())
    row = parse.detail_from_html(html, LISTINGS[0]["id"])
    assert row["id"] == LISTINGS[0]["id"]
    assert row["heading"] == "Sofa i god stand"


def test_item_page_returns_none_rather_than_a_neighbour():
    """Missing the requested listing must not silently yield a different one."""
    html = _item_page(_recommendations())
    assert parse.detail_from_html(html, "999999999999") is None
