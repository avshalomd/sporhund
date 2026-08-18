"""Tests for registry normalising and ad-vs-registry comparison.

These run offline against a trimmed sample of the Autosys response shape, so
no API key and no network are needed.
"""

from __future__ import annotations

import pytest

from sporhund.vegvesen import compare_claims, summarize_vehicle

SAMPLE = {
    "kjoretoydataListe": [
        {
            "kjoretoyId": {"kjennemerke": "EV 12138", "understellsnummer": "WVWZZZ1"},
            "forstegangsregistrering": {"registrertForstegangNorgeDato": "2018-08-08"},
            "registrering": {
                "registreringsstatus": {"kodeBeskrivelse": "Avregistrert"},
                "avregistrertSidenDato": "2026-06-11T18:03:14.17+02:00",
                "kjoringensArt": {
                    "kodeBeskrivelse": "Utleievogn. Leaset kjøretøy som ikke "
                    "registreres på grunnlag av løyve etter samferdselslovgivningen."
                },
            },
            "periodiskKjoretoyKontroll": {
                "kontrollfrist": "2028-08-31",
                "sistGodkjent": "2026-08-10",
            },
            "godkjenning": {
                "kjoretoymerknad": [{"merknad": "Egenvekt er veiledende"}],
                "tekniskGodkjenning": {
                    "tekniskeData": {
                        "generelt": {
                            "merke": [{"merke": "VOLKSWAGEN"}],
                            "handelsbetegnelse": ["GOLF"],
                        },
                        "karosseriOgLasteplan": {"antallDorer": [5]},
                        "persontall": {"sitteplasserTotalt": 5},
                        "motorOgDrivverk": {
                            "girkassetype": {"kodeBeskrivelse": "Automat"},
                            "motor": [
                                {"drivstoff": [{"drivstoffKode": {"kodeBeskrivelse": "Elektrisk"}}]}
                            ],
                        },
                        "vekter": {"egenvekt": 1540, "tillattTotalvekt": 2020},
                    }
                },
            },
        }
    ]
}


def test_summarize_flattens_the_nested_schema() -> None:
    v = summarize_vehicle(SAMPLE)
    assert v["plate"] == "EV 12138"
    assert v["registration_status"] == "Avregistrert"
    assert v["first_registered_norway"] == "2018-08-08"
    assert v["eu_control_due"] == "2028-08-31"
    assert v["make"] == "VOLKSWAGEN" and v["model"] == "GOLF"
    assert v["transmission"] == "Automat" and v["fuel"] == "Elektrisk"
    assert v["seats"] == 5 and v["doors"] == 5
    assert "Statens vegvesen" in v["source"]


def test_usage_type_drops_the_statutory_boilerplate() -> None:
    """The full legal definition runs to paragraphs; only the label is useful."""
    assert summarize_vehicle(SAMPLE)["usage_type"] == "Utleievogn"


def test_summarize_rejects_an_empty_response() -> None:
    from sporhund.vegvesen import VegvesenError

    with pytest.raises(VegvesenError):
        summarize_vehicle({"kjoretoydataListe": []})


def test_clean_car_produces_no_findings() -> None:
    official = {
        "registration_status": "Registrert",
        "eu_control_due": "2028-03-11",
        "first_registered_norway": "2016-09-07",
        "usage_type": "Annen egentransport",
        "transmission": "Automat",
    }
    claimed = {"year": 2016, "eu_check_next": "2028-03-11", "transmission": "Automat"}
    assert compare_claims(claimed, official, "2026-08-18") == []


@pytest.mark.parametrize(
    "claimed,official,expected_issue,severity",
    [
        ({}, {"registration_status": "Avregistrert", "deregistered_since": "2025-12-12T00:00:00+01:00"},
         "Currently deregistered", "info"),
        ({}, {"eu_control_due": "2025-01-01"}, "EU control overdue", "high"),
        ({"eu_check_next": "2027-01-01"}, {"eu_control_due": "2027-06-21"},
         "EU-control date disagrees", "medium"),
        ({"year": 2019}, {"first_registered_norway": "2023-04-01"}, "Likely imported", "medium"),
        ({}, {"usage_type": "Utleievogn"}, "Notable previous use", "high"),
        ({}, {"usage_type": "Drosje"}, "Notable previous use", "high"),
        ({"transmission": "Manuell"}, {"transmission": "Automat"},
         "Transmission disagrees", "low"),
    ],
)
def test_each_discrepancy_is_caught(claimed, official, expected_issue, severity) -> None:
    findings = compare_claims(claimed, official, "2026-08-18")
    match = [f for f in findings if f["issue"] == expected_issue]
    assert match, f"expected {expected_issue!r}, got {[f['issue'] for f in findings]}"
    assert match[0]["severity"] == severity


def test_registration_lag_is_not_reported_as_a_mismatch() -> None:
    """A late-2018 car first registered in early 2019 is entirely normal."""
    findings = compare_claims(
        {"year": 2018}, {"first_registered_norway": "2019-01-15"}, "2026-08-18"
    )
    assert findings == []


def test_doors_are_never_compared() -> None:
    """Door-counting conventions differ ad-vs-registry; the check was pure noise."""
    findings = compare_claims({"no_of_doors": 5}, {"doors": 4}, "2026-08-18")
    assert findings == []


def test_deregistered_is_informational_not_alarming() -> None:
    """Roughly half of live listings are temporarily deregistered — routine."""
    f = compare_claims(
        {}, {"registration_status": "Avregistrert", "deregistered_since": "2026-07-29T12:00:00+02:00"},
        "2026-08-18",
    )
    assert len(f) == 1 and f[0]["severity"] == "info"
    assert "test-driven" in f[0]["detail"]
