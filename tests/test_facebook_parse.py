"""Tests for reading Facebook's payloads, against data captured from a live page.

The fixture is real, so these assert the awkward parts rather than the happy
path: the free listing whose rendered price says "$0" in Norway, the absent
seller, and the duplicate-reference problem that a naive walker turns into
repeated results. All offline.
"""

from __future__ import annotations

import json
from pathlib import Path

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
