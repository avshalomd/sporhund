"""Statens vegvesen vehicle-registry lookups.

This is the enrichment that makes a car listing checkable: the ad is what the
seller typed, this is what the state registry holds. Data is licensed CC-BY 4.0
and carries no owner information.

Your API key is personal — tied to your own electronic ID, and you are
responsible for its use. Sporhund therefore reads *your* key from your own
machine and never bundles, proxies or transmits it anywhere except to Statens
vegvesen. Registration and chassis numbers count as personal data, so nothing
here is cached or logged.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from .config import get_secret, secret_locations

API_KEY_NAME = "VEGVESEN_API_KEY"
ENDPOINT = "https://akfell-datautlevering.atlas.vegvesen.no/enkeltoppslag/kjoretoydata"
ORDER_KEY_URL = (
    "https://www.vegvesen.no/kjoretoy/eie/kjoretoyopplysninger/bestill-api-nokkel/"
)
ATTRIBUTION = "Data from Statens vegvesen (Kjøretøyregisteret), licensed CC-BY 4.0."

_MIN_INTERVAL_S = 0.5
# Norwegian plates: two letters + five digits; personal plates vary, so stay loose.
_PLATE_RE = re.compile(r"^[A-ZÆØÅ]{2}\s?\d{4,5}$", re.I)


class VegvesenError(RuntimeError):
    """Raised when the registry cannot be reached or the key is unusable."""


class MissingApiKey(VegvesenError):
    def __init__(self) -> None:
        super().__init__(
            f"No {API_KEY_NAME} configured, so official vehicle-registry data is "
            "unavailable (FINN-only comparisons still work). Order a personal key "
            f"at {ORDER_KEY_URL} and put it in one of: "
            + ", ".join(secret_locations())
        )


def has_api_key() -> bool:
    return get_secret(API_KEY_NAME) is not None


def normalize_plate(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def looks_like_plate(value: str) -> bool:
    return bool(_PLATE_RE.match(value.strip()))


class VegvesenClient:
    def __init__(self) -> None:
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def lookup(
        self, *, plate: str | None = None, vin: str | None = None
    ) -> dict[str, Any]:
        """Look up one vehicle by registration number or chassis number."""
        if not plate and not vin:
            raise VegvesenError("Provide either a registration number or a VIN.")
        key = get_secret(API_KEY_NAME)
        if not key:
            raise MissingApiKey()

        params = {}
        if plate:
            params["kjennemerke"] = normalize_plate(plate)
        if vin:
            params["understellsnummer"] = vin.strip().upper()

        async with self._lock:
            wait = _MIN_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(
                        ENDPOINT,
                        params=params,
                        headers={
                            "SVV-Authorization": f"Apikey {key}",
                            "Accept": "application/json",
                        },
                    )
            finally:
                self._last_request = time.monotonic()

        if resp.status_code in (401, 403):
            raise VegvesenError(
                "Statens vegvesen rejected the API key (HTTP "
                f"{resp.status_code}). Check that it is active on Din side and "
                "copied exactly."
            )
        if resp.status_code == 404:
            raise VegvesenError("No vehicle found for that registration/chassis number.")
        if resp.status_code == 429:
            raise VegvesenError("Rate limit reached (50 000 lookups per key per day).")
        if resp.status_code != 200:
            raise VegvesenError(f"Registry returned HTTP {resp.status_code}.")
        try:
            return resp.json()
        except ValueError as exc:
            raise VegvesenError(f"Registry returned unreadable data: {exc}") from exc


# -- normalising the registry's deeply nested schema ---------------------------

def _dig(node: Any, *keys: str) -> Any:
    """Walk nested dicts/lists safely; lists are entered at their first item."""
    for key in keys:
        if isinstance(node, list):
            node = node[0] if node else None
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, list) and node and isinstance(node[0], (str, int, float)):
        return node[0]
    return node


def _code(node: Any) -> str | None:
    """Autosys wraps enums as {kodeVerdi, kodeBeskrivelse}; take the label."""
    if isinstance(node, list):
        node = node[0] if node else None
    if isinstance(node, dict):
        return node.get("kodeBeskrivelse") or node.get("kodeNavn") or node.get("kodeVerdi")
    return node if isinstance(node, str) else None


def _first_sentence(text: str | None) -> str | None:
    """Usage codes carry paragraphs of statute; the label alone is the useful bit."""
    if not text:
        return None
    head = text.split(".")[0].strip()
    return head or text.strip()


def summarize_vehicle(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten one registry response into the facts a buyer actually weighs."""
    entries = raw.get("kjoretoydataListe") or []
    if not entries:
        raise VegvesenError("Registry returned no vehicle record.")
    v = entries[0]
    reg = v.get("registrering") or {}
    tek = _dig(v, "godkjenning", "tekniskGodkjenning", "tekniskeData") or {}
    pkk = v.get("periodiskKjoretoyKontroll") or {}

    out: dict[str, Any] = {
        "plate": _dig(v, "kjoretoyId", "kjennemerke"),
        "vin": _dig(v, "kjoretoyId", "understellsnummer"),
        "first_registered_norway": _dig(
            v, "forstegangsregistrering", "registrertForstegangNorgeDato"
        ),
        "registration_status": _code(reg.get("registreringsstatus")),
        "deregistered_since": reg.get("avregistrertSidenDato"),
        "usage_type": _first_sentence(_code(reg.get("kjoringensArt"))),
        "eu_control_due": pkk.get("kontrollfrist"),
        "eu_control_last_passed": pkk.get("sistGodkjent"),
        "make": _dig(tek, "generelt", "merke", "merke"),
        "model": _dig(tek, "generelt", "handelsbetegnelse"),
        "body_type": _code(_dig(tek, "karosseriOgLasteplan", "karosseritype")),
        "doors": _dig(tek, "karosseriOgLasteplan", "antallDorer"),
        "seats": _dig(tek, "persontall", "sitteplasserTotalt"),
        "transmission": _code(_dig(tek, "motorOgDrivverk", "girkassetype")),
        "fuel": _code(_dig(tek, "motorOgDrivverk", "motor", "drivstoff", "drivstoffKode")),
        "curb_weight_kg": _dig(tek, "vekter", "egenvekt"),
        "max_weight_kg": _dig(tek, "vekter", "tillattTotalvekt"),
        "towing_braked_kg": _dig(tek, "vekter", "tillattTilhengervektMedBrems"),
        "range_km": _dig(
            tek, "miljodata", "miljoOgdrivstoffGruppe", "forbrukOgUtslipp", "rekkeviddeKm"
        ),
        "euro_class": _code(_dig(tek, "miljodata", "euroKlasse")),
    }
    power = _dig(tek, "motorOgDrivverk", "motor", "drivstoff", "maksEffektPrTime")
    if power:
        out["max_power_kw"] = power
    remarks = [
        r.get("merknad")
        for r in (_dig(v, "godkjenning", "kjoretoymerknad") or [])
        if isinstance(r, dict) and r.get("merknad")
    ] if isinstance(_dig(v, "godkjenning", "kjoretoymerknad"), list) else []
    if remarks:
        out["official_remarks"] = remarks
    out["source"] = ATTRIBUTION
    return {k: val for k, val in out.items() if val is not None}


# -- comparing an advertisement against the registry ---------------------------

NOTABLE_USE = ("drosje", "taxi", "utleie", "øving", "ambulanse", "utrykning")


def compare_claims(
    claimed: dict[str, Any],
    official: dict[str, Any],
    today: str,
    seller_type: str | None = None,
) -> list[dict[str, str]]:
    """Return everything in the registry that contradicts or qualifies an ad."""
    findings: list[dict[str, str]] = []

    def flag(severity: str, issue: str, detail: str) -> None:
        findings.append({"severity": severity, "issue": issue, "detail": detail})

    if "avregistrert" in (official.get("registration_status") or "").lower():
        # Measured on live samples: roughly half of fresh listings are
        # temporarily deregistered — sellers hand in the plates to stop the
        # traffic-insurance fee while the car is up for sale. Routine, but a
        # buyer still needs to know: no test drive on public roads until it is
        # re-registered (or on dealer plates), and re-registration requires a
        # valid EU-kontroll.
        since = (official.get("deregistered_since") or "")[:10]
        flag("info", "Currently deregistered",
             f"Deregistered since {since}. Common while a car is listed for "
             "sale (saves the traffic-insurance fee), but it cannot be "
             "test-driven on public roads until re-registered — plan for that, "
             "and confirm the EU-kontroll is valid, which re-registration requires.")

    due = official.get("eu_control_due")
    if due:
        if due < today:
            flag("high", "EU control overdue",
                 f"The EU-control deadline was {due} and the registry shows no newer pass.")
        stated = claimed.get("eu_check_next")
        if stated and stated != due:
            flag("medium", "EU-control date disagrees",
                 f"The ad says {stated}; the registry says {due}.")

    ad_year, first_no = claimed.get("year"), official.get("first_registered_norway")
    if ad_year and first_no:
        reg_year = int(str(first_no)[:4])
        if reg_year > int(ad_year) + 1:
            flag("medium", "Likely imported",
                 f"Model year {ad_year} but first registered in Norway {first_no}. "
                 "Used imports are typically worth less — confirm the history.")
        elif abs(reg_year - int(ad_year)) > 1:
            flag("medium", "Year disagrees",
                 f"The ad says {ad_year}; first Norwegian registration was {first_no}.")

    usage = official.get("usage_type") or ""
    if any(w in usage.lower() for w in NOTABLE_USE):
        flag("high", "Notable previous use",
             f"Registered use: {usage}. Ex-taxi, rental and driving-school cars carry "
             "far more wear than the odometer suggests.")

    # Doors deliberately not compared: counting conventions differ between ads
    # and the registry (fired on 6 of 10 clean listings in live sampling).
    for ad_key, off_key, label in (
        ("transmission", "transmission", "Transmission"),
        ("no_of_seats", "seats", "Seats"),
    ):
        a, o = claimed.get(ad_key), official.get(off_key)
        if a is not None and o is not None and str(a).lower() != str(o).lower():
            flag("low", f"{label} disagrees", f"Ad: {a} — registry: {o}.")

    return findings
