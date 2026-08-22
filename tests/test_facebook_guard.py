"""Tests for the logged-out guarantee.

This guard is the reason the Facebook source is defensible at all, so it is
tested harder than its size suggests: the failure that matters is not a crash
but a silent pass, where a signed-in session gets scraped because the check
looked at the wrong thing. Everything here runs offline and needs no browser.
"""

from __future__ import annotations

import pytest

from sporhund.facebook.guard import (
    NotLoggedOutError,
    assert_logged_out,
    authenticated_cookie_names,
    page_looks_logged_out,
)

GUEST_JAR = [
    {"name": "datr", "value": "abc123"},
    {"name": "sb", "value": "def456"},
    {"name": "wd", "value": "1280x800"},
]


def test_guest_jar_passes():
    assert authenticated_cookie_names(GUEST_JAR) == []
    assert_logged_out(GUEST_JAR)  # does not raise


def test_datr_alone_is_not_a_login():
    """`datr` identifies the browser, not the account — a guest always has one.

    Treating it as a login signal would make every healthy session fail.
    """
    assert authenticated_cookie_names([{"name": "datr", "value": "x"}]) == []


@pytest.mark.parametrize("name", ["c_user", "xs"])
def test_either_session_cookie_trips_the_guard(name):
    jar = GUEST_JAR + [{"name": name, "value": "1234567890"}]
    assert authenticated_cookie_names(jar) == [name]
    with pytest.raises(NotLoggedOutError) as excinfo:
        assert_logged_out(jar)
    assert name in str(excinfo.value)


def test_both_session_cookies_are_both_reported():
    jar = GUEST_JAR + [
        {"name": "c_user", "value": "1"},
        {"name": "xs", "value": "2"},
    ]
    assert authenticated_cookie_names(jar) == ["c_user", "xs"]


def test_emptied_cookie_is_not_a_login():
    """Facebook clears `c_user`/`xs` by blanking them on sign-out.

    The husk can outlive the session in the jar. Counting it would leave the
    guard stuck on for good after one stray sign-in.
    """
    jar = GUEST_JAR + [{"name": "c_user", "value": ""}, {"name": "xs", "value": "  "}]
    assert authenticated_cookie_names(jar) == []
    assert_logged_out(jar)


def test_accepts_objects_and_bare_names():
    class Cookie:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    assert authenticated_cookie_names([Cookie("c_user", "1")]) == ["c_user"]
    assert authenticated_cookie_names(["xs"]) == ["xs"]


def test_page_check_reads_guest_and_signed_in_markers():
    assert page_looks_logged_out('<form action="/login/"><input name="pass">') is True
    assert page_looks_logged_out('{"is_logged_in":true}') is False


def test_page_check_admits_when_it_cannot_tell():
    """An unrecognised page must read as "don't know", never as a pass."""
    assert page_looks_logged_out("<html><body>hello</body></html>") is None
    assert page_looks_logged_out('name="fb_dtsg" ... <input name="pass">') is None
