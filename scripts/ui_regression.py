"""Fast browser smoke test for the finalized judge interface."""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8501"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="networkidle", timeout=90_000)

    page.get_by_role("heading", name="CNC Part Analyzer").wait_for(timeout=30_000)
    assert page.get_by_role("button", name="Run demo").is_visible()
    assert page.get_by_text("Upload the available Excel, PDF, and IGES files").is_visible()
    print("PASS  simple start screen")

    page.get_by_role("button", name="Run demo").click()
    page.get_by_role("heading", name="Part 2280").wait_for(timeout=240_000)
    page.get_by_text("Consistent", exact=True).wait_for(timeout=30_000)
    body = page.locator("body").inner_text()
    assert "Consistent" in body
    assert "120 × 75 × 10 mm" in body
    assert page.get_by_role("tab", name="Overview").is_visible()
    assert page.get_by_role("tab", name="Evidence").is_visible()
    assert page.get_by_role("tab", name="Ask DeepSeek").is_visible()
    print("PASS  demo analysis")

    page.get_by_role("tab", name="Ask DeepSeek").click()
    page.get_by_role("button", name="What are the dimensions?").wait_for(timeout=10_000)
    print("PASS  simplified DeepSeek tab")

    browser.close()

print("3/3 UI checks passed")
