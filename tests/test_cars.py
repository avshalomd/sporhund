"""Offline tests for comparable-search derivation and price positioning."""

from __future__ import annotations

import pytest

from sporhund.cars import (
    comparable_filter_steps,
    comparable_query,
    median_of,
    price_position,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Volkswagen Golf VII", "Volkswagen Golf"),
        ("Volkswagen e-Golf VII", "Volkswagen e-Golf"),
        ("Kia e-Soul", "Kia e-Soul"),
        ("Toyota Prius Plug-in Hybrid", "Toyota Prius Plug-in"),  # 3-token cap
        ("Golf selges billig!", "Golf selges billig"),
        ("Mercedes-Benz Vito 113", "Mercedes-Benz Vito 113"),  # 3 tokens, hyphen kept
        ("Volvo XC70 - som ny", "Volvo XC70"),
        ("BMW X3 2019", "BMW X3"),
    ],
)
def test_comparable_query(name: str, expected: str) -> None:
    assert comparable_query(name) == expected


def test_comparable_query_falls_back_to_make() -> None:
    assert comparable_query(None, make="Volkswagen") == "Volkswagen"
    assert comparable_query("", make=None) is None


def test_price_position() -> None:
    pos = price_position(100_000, [80_000, 90_000, 100_000, 120_000, 140_000])
    assert pos["n"] == 5
    assert pos["median"] == 100_000
    assert pos["delta_vs_median"] == 0
    assert pos["percentile"] == 50  # 2 below + half of the 1 equal, of 5

    cheap = price_position(80_000, [100_000, 110_000, 120_000])
    assert cheap["percentile"] == 0
    assert cheap["delta_vs_median"] == -30_000
    assert cheap["delta_vs_median_pct"] == -27

    assert price_position(100_000, []) == {"n": 0}


def test_median_of_ignores_junk() -> None:
    assert median_of([2018, None, 2020, "x", 2019]) == 2019
    assert median_of([]) is None


def test_widening_steps_loosen_monotonically():
    steps = comparable_filter_steps(2019, 68000, year_spread=1, mileage_spread=40000)

    assert [s.get("year_from") for s in steps] == [2018, 2017, 2016, None]
    assert [s.get("year_to") for s in steps] == [2020, 2021, 2022, None]
    # Mileage widens once, then is dropped entirely — a rare car's mileage band
    # is the constraint that bites first.
    assert [s.get("mileage_to") for s in steps] == [108000, 148000, None, None]
    assert all(s["sales_form"] == "1" for s in steps)


def test_widening_never_asks_for_negative_mileage():
    steps = comparable_filter_steps(1986, 10000, year_spread=1, mileage_spread=40000)
    assert [s.get("mileage_from") for s in steps] == [0, 0, None, None]


def test_no_year_or_mileage_collapses_to_a_single_step():
    """Auction ads often carry neither, so every band would be identical."""
    assert comparable_filter_steps(None, None, 1, 40000) == [{"sales_form": "1"}]


def test_year_only_still_widens_but_does_not_repeat_the_last_step():
    steps = comparable_filter_steps(1986, None, year_spread=1, mileage_spread=40000)
    assert [s.get("year_from") for s in steps] == [1985, 1984, 1983, None]
    assert all("mileage_from" not in s for s in steps)
