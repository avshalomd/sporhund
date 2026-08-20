"""Positioning a car against its market comparables on FINN.

The registry says what a car *is*; this says what it *costs* relative to the
cars a buyer would actually cross-shop. Everything here works from FINN's own
listing data — no API key, no external source. Honest limits: these are asking
prices, not sold prices, and free-text matching cannot see trim level or
equipment — the agent reading the result is expected to do that judgment.
"""

from __future__ import annotations

import re
from typing import Any

from .finn import Listing

# "Volkswagen Golf VII" -> "Volkswagen Golf": generation suffixes over-narrow a
# free-text search (ads for the same generation often omit them), while the
# year band below does the same job more reliably.
_GENERATION_RE = re.compile(r"\s+(?:[IVX]+|Mk\s?\d+|\d{4})$", re.I)


def comparable_query(name: str | None, make: str | None = None) -> str | None:
    """Derive the free-text search that finds a car's cross-shopping set."""
    text = (name or "").strip()
    if not text and make:
        return make
    if not text:
        return None
    text = _GENERATION_RE.sub("", text)
    # Trailing sales fluff (" - som ny!", ", lav km") hurts. Split only on a
    # *spaced* dash or on comma/bang, so model-internal hyphens (e-Golf,
    # Plug-in, Mercedes-Benz) survive.
    text = re.split(r"\s[-–]\s|[,!|]", text)[0].strip()
    words = text.split()
    return " ".join(words[:3]) if words else None


def price_position(subject_price: int, comparable_prices: list[int]) -> dict[str, Any]:
    """Where a price sits among comparables. Percentile 0 = cheapest end."""
    prices = sorted(p for p in comparable_prices if p)
    if not prices:
        return {"n": 0}
    below = sum(1 for p in prices if p < subject_price)
    equal = sum(1 for p in prices if p == subject_price)
    n = len(prices)
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) // 2
    return {
        "n": n,
        "percentile": round(100 * (below + equal / 2) / n),
        "median": median,
        "delta_vs_median": subject_price - median,
        "delta_vs_median_pct": round(100 * (subject_price - median) / median) if median else None,
        "min": prices[0],
        "max": prices[-1],
    }


def median_of(values: list[Any]) -> int | None:
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    if not nums:
        return None
    n = len(nums)
    return int(nums[n // 2] if n % 2 else (nums[n // 2 - 1] + nums[n // 2]) / 2)


def brief(l: Listing) -> dict[str, Any]:
    """A comparable, trimmed to what matters for eyeballing the market."""
    d = l.to_dict()
    return {k: d[k] for k in
            ("finnkode", "heading", "price", "year", "mileage", "fuel",
             "location", "seller_type", "url")
            if d.get(k) is not None}


def fuel_matches(a: str | None, b: str | None) -> bool:
    """Loose fuel-label match across FINN's two vocabularies.

    Search docs say "El"/"Hybrid bensin"; item pages say "Elektrisk"/…
    Prefix match either way keeps them comparable without a code table.
    """
    if not a or not b:
        return False
    x, y = a.strip().lower(), b.strip().lower()
    return x.startswith(y) or y.startswith(x)


# Enough comparables for a percentile to mean anything.
MIN_COMPARABLES = 5

# How far to loosen the bands, step by step, when a car is rare: multiply the
# year/mileage spreads, then drop mileage, then drop both. A ±1-year band is
# right for a 2022 Golf and useless for a 1986 one.
_WIDENING = ((1, 1), (2, 2), (3, None), (None, None))


def comparable_filter_steps(
    year: int | None,
    mileage: int | None,
    year_spread: int,
    mileage_spread: int,
) -> list[dict[str, Any]]:
    """Search filters from tightest to loosest, for progressive widening.

    Always sales_form 1 (used cars for sale): leasing ads price a month and
    auctions price a current bid, so neither belongs in an asking-price median.
    """
    steps: list[dict[str, Any]] = []
    for year_mult, mileage_mult in _WIDENING:
        f: dict[str, Any] = {"sales_form": "1"}
        if year and year_mult:
            f["year_from"] = year - year_spread * year_mult
            f["year_to"] = year + year_spread * year_mult
        if isinstance(mileage, int) and mileage_mult:
            f["mileage_from"] = max(0, mileage - mileage_spread * mileage_mult)
            f["mileage_to"] = mileage + mileage_spread * mileage_mult
        if f not in steps:  # collapses to one step when year and mileage are unknown
            steps.append(f)
    return steps
