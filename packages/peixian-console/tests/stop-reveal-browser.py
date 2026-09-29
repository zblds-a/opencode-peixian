"""Focused component check against a local Vite server, without account data."""

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://127.0.0.1:19785/tests/stop-reveal-harness.html")
    visible = page.locator(".smooth-message-text .markdown")
    page.wait_for_function("document.querySelector('.smooth-message-text .markdown')?.innerText?.length > 3")
    before = visible.inner_text()
    page.get_by_role("button", name="Stop", exact=True).click()
    frozen = visible.inner_text()
    assert frozen == before, f"stopping changed visible text: {before!r} -> {frozen!r}"
    page.get_by_role("button", name="Append cache").click()
    page.wait_for_timeout(700)
    assert visible.inner_text() == frozen, "buffered text appeared after stopping"
    page.get_by_role("button", name="Remount").click()
    assert visible.inner_text() == frozen, "remount lost the visible text"
    page.get_by_role("button", name="Resume after failure").click()
    page.wait_for_function("document.querySelector('.smooth-message-text .markdown')?.textContent?.includes('Later buffered content')")
    print("stop freezes immediately; later cache and remount stay frozen; failed-stop resume catches up")
    browser.close()
