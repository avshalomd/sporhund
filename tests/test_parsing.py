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

from finn_agent.finn import _parse_listing, _parse_search

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


def test_price_stats() -> None:
    from finn_agent.finn import Listing, summarize

    listings = [
        Listing(finnkode="1", heading="a", url="u", price=100),
        Listing(finnkode="2", heading="b", url="u", price=200),
        Listing(finnkode="3", heading="c", url="u", price=300),
    ]
    stats = summarize(listings)
    assert stats == {"count": 3, "min": 100, "median": 200, "max": 300, "mean": 200}
