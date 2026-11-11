"""Browser checks for the shipped motion layer, using synthetic markup and actual assets.

These checks need no database, external network, or personal data. The browser is the same
Playwright Chromium used by the main demo test. Marked e2e to keep verify-fast independent of it.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
STATIC = Path(__file__).resolve().parents[2] / "static"

MARKUP = """<!doctype html><html lang="en"><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
content="default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'">
<link rel="stylesheet" href="/vendor/bootstrap.min.css">
<link rel="stylesheet" href="/css/app.css">
</head><body>
<header class="hero"><div class="hero-bar"><a class="wordmark" href="/">SMARTHIRE</a></div>
<div class="hero-row"><div><h1>Projects</h1>
<p class="hero-sub">Synthetic motion test</p></div></div>
<a class="metal-card" href="#details"><h2>Sample project</h2><strong>3</strong></a></header>
<main id="main" class="page" tabindex="-1">
<section class="panel"><h2>Evidence</h2><ul class="rows">
<li class="row-item">First synthetic candidate</li>
<li class="row-item">Second synthetic candidate</li></ul>
<span class="score">70.00</span>
<svg class="meter" viewBox="0 0 100 6"><rect class="meter-value" width="70" height="6"/></svg>
<details class="fold" id="details"><summary>More details</summary>
<div class="fold-body"><p>Visible accepted evidence.</p></div></details>
<label for="password">Password</label><input id="password" type="password">
<button type="button" data-toggle-password="password" aria-label="Show characters"
aria-pressed="false">Show</button>
</section><div class="panel drawer" id="drawer" tabindex="-1" aria-live="polite">
<p>Select a candidate.</p></div></main>
<nav class="pillnav" aria-label="Main"><a class="pillnav-link active" href="/"
aria-current="page">Projects</a><a class="pillnav-link" href="/profiles/">Profiles</a></nav>
<script src="/js/app.js"></script></body></html>"""


def load_motion_page(page, fragment="", *, reduced_motion="no-preference"):
    """Serve only our fixture and existing static assets under a strict same-origin policy."""
    page.emulate_media(reduced_motion=reduced_motion)

    def respond(route):
        path = route.request.url.split("motion.test", 1)[1].split("#", 1)[0]
        if path in ("/", "/profiles/"):
            markup = MARKUP
            if path == "/profiles/":
                markup = markup.replace(
                    'class="pillnav-link active" href="/"\naria-current="page"',
                    'class="pillnav-link" href="/"',
                ).replace(
                    'class="pillnav-link" href="/profiles/"',
                    'class="pillnav-link active" href="/profiles/" aria-current="page"',
                )
            route.fulfill(body=markup, content_type="text/html")
            return
        relative = path.lstrip("/")
        asset = STATIC / relative
        if asset.is_file():
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404, body="Missing test asset")

    page.route("https://motion.test/**", respond)
    page.goto(f"https://motion.test/{fragment}")


@pytest.mark.parametrize("fragment", ["#%", "#%5B", "#not%20a%20selector", "#%E0%A4%A"])
def test_malformed_fragment_does_not_break_other_controls(page, fragment):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    load_motion_page(page, fragment)
    page.get_by_role("button", name="Show characters").click()
    assert page.get_by_label("Password", exact=True).get_attribute("type") == "text"
    assert errors == []


def test_fragment_opens_the_requested_native_disclosure(page):
    load_motion_page(page, "#details")
    assert page.locator("#details").get_attribute("open") is not None


def test_entrances_preserve_the_rendered_score_and_meter(page):
    """Decorative arrivals never interpolate or replace the stored scoring output."""
    load_motion_page(page)
    for selector in (".metal-card", ".panel", ".pillnav"):
        assert (
            page.locator(selector).first.evaluate("node => getComputedStyle(node).animationName")
            != "none"
        )
    page.evaluate("document.getAnimations().forEach(animation => animation.finish())")
    assert page.locator(".score").inner_text() == "70.00"
    assert page.locator(".meter-value").get_attribute("width") == "70"
    assert page.locator(".panel").first.is_visible()


def test_reduced_motion_keeps_the_final_interface_visible(page):
    load_motion_page(page, reduced_motion="reduce")
    running = page.evaluate(
        "document.getAnimations().filter(animation => animation.playState === 'running').length"
    )
    assert running == 0
    assert page.locator(".panel").first.is_visible()
    expect(page.locator(".panel").first).to_have_css("opacity", "1")
    assert page.locator(".score").inner_text() == "70.00"
    assert page.locator(".meter-value").get_attribute("width") == "70"


def test_native_interface_remains_usable_without_javascript(browser):
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        load_motion_page(page)
        assert page.locator(".panel").first.is_visible()
        assert page.locator(".metal-card").is_visible()
        expect(page.locator(".panel").first).to_have_css("opacity", "1")
        page.get_by_label("Password", exact=True).fill("synthetic-password")
        assert page.get_by_label("Password", exact=True).input_value() == "synthetic-password"
        page.get_by_text("More details", exact=True).click()
        assert page.locator("#details").get_attribute("open") is not None
    finally:
        context.close()


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_drawer_busy_state_focus_and_motion_follow_the_request(page, reduced_motion):
    load_motion_page(page, reduced_motion=reduced_motion)
    drawer = page.locator("#drawer")
    page.evaluate(
        """() => document.dispatchEvent(new CustomEvent('htmx:beforeRequest', {
          detail: {target: document.getElementById('drawer')}
        }))"""
    )
    assert drawer.get_attribute("aria-busy") == "true"
    page.evaluate(
        """() => document.dispatchEvent(new CustomEvent('htmx:afterRequest', {
          detail: {target: document.getElementById('drawer')}
        }))"""
    )
    assert drawer.get_attribute("aria-busy") in (None, "false")
    state = page.evaluate(
        """() => {
          const drawer = document.getElementById('drawer');
          document.dispatchEvent(new CustomEvent('htmx:afterSwap', {detail: {target: drawer}}));
          const running = drawer.getAnimations().filter(animation =>
            animation.playState === 'running').length;
          return {
            focused: document.activeElement === drawer,
            running: running
          };
        }"""
    )
    assert state["focused"]
    assert (state["running"] > 0) is (reduced_motion == "no-preference")


def test_enabling_reduced_motion_cancels_an_in_progress_drawer_arrival(page):
    load_motion_page(page)
    page.evaluate(
        """() => {
          const drawer = document.getElementById('drawer');
          document.dispatchEvent(new CustomEvent('htmx:afterSwap', {detail: {target: drawer}}));
          drawer.getAnimations().forEach(animation => animation.pause());
        }"""
    )
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("document.getElementById('drawer').getAnimations().length === 0")
    expect(page.locator("#drawer")).to_have_css("opacity", "1")


def test_ordinary_navigation_preserves_destinations_and_has_no_page_errors(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    load_motion_page(page)
    for name, destination in (("Profiles", "/profiles/"), ("Projects", "/")) * 3:
        page.locator(".pillnav").get_by_role("link", name=name, exact=True).click()
        page.wait_for_url(f"https://motion.test{destination}")
        expect(page.locator('.pillnav [aria-current="page"]')).to_have_text(name)
    assert errors == []
