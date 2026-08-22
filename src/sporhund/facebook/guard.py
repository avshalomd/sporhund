"""The logged-out guarantee.

Everything Sporhund reads from Facebook is read as an anonymous visitor, and
that is not a stylistic choice. In *Meta Platforms v. Bright Data* (N.D. Cal.,
January 2024) the court held that Meta's terms of service bind people who are
**logged in**; collecting public data while logged out was not a breach of them.
Meta dropped the case and waived its appeal. A logged-in session would therefore
turn a lawful public read into a terms violation — so "are we logged out?" is a
correctness question here, checked before every scrape, not a preference.

Nothing in this module touches the user's own browser. The session runs in a
profile directory Sporhund owns (see `session.py`); this module is the second
line of defence, which asserts the property directly rather than trusting that
arrangement to hold.
"""

from __future__ import annotations

from typing import Any, Iterable

# Facebook's login state is carried by exactly these two cookies: `c_user` holds
# the account id and `xs` the session secret, and together they *are* the
# session. `datr` and `sb` are browser-identity cookies that anonymous visitors
# receive too, so their presence says nothing about being signed in — checking
# for them would raise false alarms on every healthy guest session.
AUTH_COOKIE_NAMES = frozenset({"c_user", "xs"})


class NotLoggedOutError(RuntimeError):
    """Raised when a session carries signs of a signed-in Facebook account.

    Always fatal. There is no degraded mode that continues with an authenticated
    session, because the legal footing described above does not survive it.
    """


def authenticated_cookie_names(cookies: Iterable[Any]) -> list[str]:
    """Return the names of any signed-in-session cookies present.

    Accepts what Playwright's `BrowserContext.cookies()` returns — dicts with a
    "name" key — and tolerates bare strings so callers can check a name list
    they assembled themselves.
    """
    found: set[str] = set()
    for cookie in cookies:
        if isinstance(cookie, str):
            name = cookie
        elif isinstance(cookie, dict):
            name = str(cookie.get("name", ""))
        else:
            name = str(getattr(cookie, "name", ""))
        # An empty value is a cookie on its way out; Facebook clears `c_user`
        # and `xs` this way on sign-out, and the jar can hold the husk for the
        # rest of the browser's life. Treating that as "logged in" would make
        # the guard fire forever after a single stray sign-in.
        if name in AUTH_COOKIE_NAMES and _has_value(cookie):
            found.add(name)
    return sorted(found)


def _has_value(cookie: Any) -> bool:
    if isinstance(cookie, str):
        return True
    if isinstance(cookie, dict):
        return bool(str(cookie.get("value", "")).strip())
    return bool(str(getattr(cookie, "value", "")).strip())


def assert_logged_out(cookies: Iterable[Any]) -> None:
    """Raise `NotLoggedOutError` if the cookie jar shows a signed-in account.

    Call this after the context is created and again after any navigation that
    could have picked up cookies, which is every one of them.
    """
    present = authenticated_cookie_names(cookies)
    if present:
        raise NotLoggedOutError(
            "Refusing to read Facebook while signed in: found "
            f"{', '.join(present)} in the browser session. Sporhund reads "
            "Facebook only as an anonymous visitor. Delete the Sporhund "
            "browser profile and try again, and never sign a Facebook account "
            "into it."
        )


def page_looks_logged_out(html: str) -> bool | None:
    """Secondary, page-level check on whether Facebook served us a guest view.

    Returns True when the page shows the signed-out affordances, False when it
    shows signed-in ones, and None when neither is recognisable — a rendering
    change should read as "cannot tell", never as a silent pass.

    This is corroboration, not the guarantee: `assert_logged_out` is the check
    that actually decides. Facebook serves logged-out visitors a login form on
    Marketplace pages while still rendering the listing behind it.
    """
    lowered = html.lower()
    signed_in = any(
        marker in lowered
        for marker in ('"is_logged_in":true', 'name="fb_dtsg"', '/logout.php')
    )
    signed_out = any(
        marker in lowered
        for marker in ('name="pass"', 'action="/login', 'id="loginform"')
    )
    if signed_in and not signed_out:
        return False
    if signed_out and not signed_in:
        return True
    return None
