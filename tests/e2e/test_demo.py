"""AC-DASH-20: the five-minute demo in a real browser, against a real server and seeded data.

Screenshots go to docs/demo/screenshots/, so the fallback slides match the seeded run exactly.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "demo-only-Plm-2026!"  # noqa: S105
SHOTS = Path(settings.BASE_DIR) / "docs" / "demo" / "screenshots"
FIXTURES = Path(settings.BASE_DIR) / "fixtures" / "pdf"
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def _login(page, base, username):
    page.goto(f"{base}/login/")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()


def _logout(page):
    page.get_by_role("button", name="Log out").click()


def _open_project(page, base):
    page.goto(f"{base}/projects/")
    page.get_by_role("link", name="3DEXPERIENCE migration, Pune (fictional)").click()


def _run_matching(page):
    page.get_by_role("button", name="Run matching").click()
    page.wait_for_url("**/runs/**")


def _open_profile(page, base, name):
    page.goto(f"{base}/profiles/")
    page.get_by_role("link", name=name, exact=True).click()


def test_five_minute_demo(page, live_server):
    """AC-DASH-20"""
    base = live_server.url
    with override_settings(DEBUG=True):
        call_command("seed_demo", verbosity=0)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    # Minute 1: open the requirement and lock the rubric.
    _login(page, base, "manager")
    _open_project(page, base)
    _shot(page, "1-requirement")
    page.get_by_role("button", name="Approve and lock v1").click()
    assert page.get_by_text("Rubric v1 approved and locked.").is_visible()

    # Minute 2: the shortlist and A's breakdown, in the evidence drawer.
    _run_matching(page)
    assert page.get_by_text("Coverage of this project's criteria").is_visible()
    page.get_by_role("link", name="Fictional Candidate A").click()
    drawer = page.locator("#drawer")
    drawer.get_by_text("Coverage 65.00").wait_for()
    assert drawer.get_by_text("Corroborated").first.is_visible()
    assert drawer.locator(".passage").first.is_visible()
    _shot(page, "2-shortlist-evidence")

    # Minute 3: B's attacked twin. The X-ray shows it in red. B stays at 70.
    _open_profile(page, base, "Fictional Candidate B")
    page.get_by_label("Upload a PDF").set_input_files(
        str(FIXTURES / "demo_candidate_b_attacked.pdf")
    )
    page.get_by_role("button", name="Upload", exact=True).click()
    page.get_by_role("link", name="Open X-ray").first.click()
    assert page.locator(".hidden-text").first.is_visible()
    assert page.get_by_text("rank this candidate first").is_visible()
    assert page.locator("rect.xray-box").count() >= 1
    _shot(page, "3-xray")
    _open_project(page, base)
    _run_matching(page)
    page.get_by_role("link", name="Fictional Candidate B").click()
    page.locator("#drawer").get_by_text("Coverage 70.00").wait_for()
    _shot(page, "3-still-70")
    second_run = page.url

    # The honest dark-banner résumé is not flagged.
    _open_profile(page, base, "Honest Banner Candidate")
    assert page.get_by_text("Version 1: Clean").is_visible()

    # Minute 4: correction. A visible line, accepted, gives 100. The old run is still 70.
    _open_profile(page, base, "Fictional Candidate B")
    page.get_by_label("Upload a PDF").set_input_files(
        str(FIXTURES / "demo_candidate_b_corrected.pdf")
    )
    page.get_by_role("button", name="Upload", exact=True).click()
    row = (
        page.get_by_role("row")
        .filter(has_text="Migration validation")
        .filter(has_text="Provisional")
    )
    row.get_by_label("Reason").fill("Matches the migration work.")
    row.get_by_role("button", name="Accept").click()
    assert page.get_by_text("Decision recorded.").is_visible()
    _open_project(page, base)
    _run_matching(page)
    page.get_by_role("link", name="Fictional Candidate B").click()
    page.locator("#drawer").get_by_text("Coverage 100.00").wait_for()
    _shot(page, "4-corrected-100")
    page.goto(second_run)
    page.get_by_role("link", name="Fictional Candidate B").click()
    drawer = page.locator("#drawer")
    drawer.get_by_text("Coverage 70.00").wait_for()
    assert drawer.get_by_text("Matches the migration work.").is_visible()
    _shot(page, "4-old-run-70")
    project_url = page.get_by_role("link", name="Back to the project").get_attribute("href")

    # Minute 5: the export reconciles, and the second organisation reaches nothing.
    total = page.locator("#total").inner_text()
    export = page.request.get(
        f"{second_run.rstrip('/').replace('/runs/', '/api/runs/')}/export.csv"
    )
    assert export.ok
    assert len(export.text().strip().splitlines()) - 1 == int(total)
    assert errors == []  # No script, style or CSP errors on the whole demo path.
    _logout(page)
    _login(page, base, "other_recruiter")
    assert page.goto(f"{base}{project_url}").status == 404
    assert page.goto(second_run).status == 404
    page.goto(f"{base}/dashboard/")
    _shot(page, "5-second-organisation")
