"""Save a few FINN pages locally so the parser tests have something to run on.

These pages are for your own local testing only and are git-ignored; do not
commit or share them (see NOTICE.md). Run:

    python tests/refresh_fixtures.py
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
PAGES = {
    "torget_search.html": "https://www.finn.no/recommerce/forsale/search?q=sykkel",
    "car_search.html": "https://www.finn.no/mobility/search/car?q=golf",
    "job_search.html": "https://www.finn.no/job/search?q=utvikler",
    "item.html": "https://www.finn.no/recommerce/forsale/search?q=sykkel",  # replace with a real item URL
}


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=20) as c:
        for name, url in PAGES.items():
            r = c.get(url)
            (FIXTURES / name).write_text(r.text, encoding="utf-8")
            print(f"{r.status_code}  {name}  <- {url}")
            time.sleep(2)  # polite pacing


if __name__ == "__main__":
    main()
