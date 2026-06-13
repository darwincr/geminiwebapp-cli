from __future__ import annotations

import logging
import os
import re
import sys
import time

from geminiwebapp_cli.browser import first_visible, goto_domcontentloaded, safe_attr, visible_text
from geminiwebapp_cli.conf import GEMINI_APP_URL, GEMINI_BASE_URL
from geminiwebapp_cli.exceptions import AuthenticationError, GeminiUnavailableError, InteractiveAuthenticationRequired

logger = logging.getLogger(__name__)

SIGN_IN_LOCATORS = [
    lambda p: p.get_by_role("link", name=re.compile("sign in", re.I)),
    lambda p: p.get_by_role("button", name=re.compile("sign in", re.I)),
    lambda p: p.locator('a[href*="accounts.google.com"]'),
    lambda p: p.locator('button:has-text("Sign in")'),
]
AUTHENTICATED_LOCATORS = [
    lambda p: p.locator('rich-textarea textarea'),
    lambda p: p.locator('textarea[aria-label*="Enter a prompt" i]'),
    lambda p: p.locator('textarea[placeholder*="Enter a prompt" i]'),
    lambda p: p.locator('[contenteditable="true"][role="textbox"]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"]'),
    lambda p: p.get_by_role("button", name=re.compile("new chat", re.I)),
    lambda p: p.locator('a[href^="/app/"]'),
]
PROMPT_READY_LOCATORS = AUTHENTICATED_LOCATORS[:5]
ACCOUNT_LOCATORS = [
    lambda p: p.locator('a[href*="myaccount.google.com"]'),
    lambda p: p.locator('button[aria-label*="Google Account" i]'),
    lambda p: p.locator('[aria-label*="Google Account" i]'),
    lambda p: p.locator('img[alt*="Profile" i]'),
]
UNAVAILABLE_LOCATORS = [
    lambda p: p.locator('text=/Gemini isn.t currently supported/i'),
    lambda p: p.locator('text=/Gemini is not available/i'),
    lambda p: p.locator('text=/This service is not available/i'),
]


def _is_google_login_url(url: str) -> bool:
    lower = url.lower()
    return "accounts.google.com" in lower or "/signin" in lower or "/identifier" in lower


def _is_gemini_url(url: str) -> bool:
    return url.lower().startswith(GEMINI_BASE_URL)


def _blocking_state(session, *, timeout_ms: int = 800) -> str | None:
    page = session.page
    locator = first_visible(page, UNAVAILABLE_LOCATORS, timeout_ms=timeout_ms)
    if locator is not None:
        return visible_text(locator) or "Gemini appears unavailable for this account or region"
    return None


def _account_hint(session) -> tuple[str | None, str | None]:
    page = session.page
    locator = first_visible(page, ACCOUNT_LOCATORS, timeout_ms=1000)
    label = safe_attr(locator, "aria-label") or safe_attr(locator, "alt") or visible_text(locator)
    email = None
    if label and "@" in label:
        for part in label.replace("(", " ").replace(")", " ").split():
            if "@" in part:
                email = part.strip(",.;")
                break
    return email, label


def ensure_logged_in(session) -> dict:
    page = session.page
    goto_domcontentloaded(page, GEMINI_APP_URL)

    blocking = _blocking_state(session)
    if blocking:
        raise GeminiUnavailableError(blocking)

    account = _current_authenticated_account(session, timeout_ms=500, include_account_hint=False)
    if account is not None:
        return account

    if _is_google_login_url(page.url) or first_visible(page, SIGN_IN_LOCATORS, timeout_ms=500) is not None:
        raise InteractiveAuthenticationRequired(
            "Interactive authentication is required. Run `geminiwebapp-cli login --interactive --wait --timeout 300`, "
            "complete Google login manually in Camoufox, then rerun this command."
        )

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        blocking = _blocking_state(session)
        if blocking:
            raise GeminiUnavailableError(blocking)
        account = _current_authenticated_account(session, timeout_ms=500, include_account_hint=False)
        if account is not None:
            return account
        if _is_google_login_url(page.url) or first_visible(page, SIGN_IN_LOCATORS, timeout_ms=300) is not None:
            raise InteractiveAuthenticationRequired("Gemini is showing a Google sign-in flow")
        time.sleep(0.5)

    raise AuthenticationError(f"Gemini did not reach an authenticated app page; current URL: {page.url}")


def ensure_prompt_ready(session) -> dict:
    page = session.page
    goto_domcontentloaded(page, GEMINI_APP_URL)

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if _is_gemini_url(page.url) and first_visible(page, PROMPT_READY_LOCATORS, timeout_ms=300) is not None:
            return {"ok": True, "authenticated": True, "state": "logged_in", "email": None, "account": None, "url": page.url}

        blocking = _blocking_state(session, timeout_ms=50)
        if blocking:
            raise GeminiUnavailableError(blocking)

        if _is_google_login_url(page.url) or first_visible(page, SIGN_IN_LOCATORS, timeout_ms=50) is not None:
            raise InteractiveAuthenticationRequired("Gemini is showing a Google sign-in flow")
        time.sleep(0.25)

    raise AuthenticationError(f"Gemini did not show a prompt box; current URL: {page.url}")


def _current_authenticated_account(session, *, timeout_ms: int = 1000, include_account_hint: bool = True) -> dict | None:
    page = session.page
    blocking = _blocking_state(session)
    if blocking:
        raise GeminiUnavailableError(blocking)
    if not _is_gemini_url(page.url):
        return None
    if first_visible(page, AUTHENTICATED_LOCATORS, timeout_ms=timeout_ms) is None:
        return None
    if not include_account_hint:
        return {"ok": True, "authenticated": True, "state": "logged_in", "email": None, "account": None, "url": page.url}
    email, account = _account_hint(session)
    return {"ok": True, "authenticated": True, "state": "logged_in", "email": email, "account": account, "url": page.url}


def auth_status(session) -> dict:
    try:
        return ensure_logged_in(session)
    except InteractiveAuthenticationRequired as exc:
        return {
            "ok": True,
            "authenticated": False,
            "state": "login_required",
            "message": str(exc),
            "next_command": "geminiwebapp-cli login --interactive --wait --timeout 300",
        }
    except GeminiUnavailableError as exc:
        return {"ok": True, "authenticated": False, "state": "unavailable", "message": str(exc)}
    except AuthenticationError as exc:
        return {"ok": True, "authenticated": False, "state": "unknown", "message": str(exc)}


def interactive_auth(session, wait: bool = False, timeout: int = 300) -> dict:
    page = session.page
    goto_domcontentloaded(page, GEMINI_APP_URL)
    if os.environ.get("GEMINIWEBAPP_CLI_WORKER") == "1" and not wait:
        wait = True
    if wait:
        print(f"Complete Google/Gemini login in the Camoufox browser. Waiting up to {timeout} seconds...", file=sys.stderr)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                page.wait_for_load_state("domcontentloaded")
            except Exception:  # noqa: BLE001
                pass
            try:
                account = _current_authenticated_account(session)
                if account is not None:
                    return account
            except GeminiUnavailableError:
                raise
            time.sleep(2)
        raise InteractiveAuthenticationRequired(f"Gemini login was not completed within {timeout} seconds")

    print("Complete Google/Gemini login in the Camoufox browser, then press Enter here.", file=sys.stderr)
    input()
    return ensure_logged_in(session)
