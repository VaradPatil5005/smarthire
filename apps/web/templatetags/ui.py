"""Small presentation helpers. They hold no rules and read no data beyond what they are given."""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()

_NAV_SECTIONS = {
    "dashboard": {"dashboard", "data-requests"},
    "projects": {"project-list", "project-detail", "project-edit", "shortlist", "result-detail"},
    "profiles": {"profile-list", "profile-detail", "profile-edit", "xray"},
    "bench": {"bench"},
    "utilisation": {"utilisation"},
    "imports": {"import-list", "import-detail", "import-queue"},
}


@register.simple_tag
def icon(name, extra=""):
    """An icon from the sprite. Decorative: nearby text or an aria-label names the action."""
    classes = f"icon {extra}".strip()
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="{}#{}"></use></svg>',
        classes,
        static("img/icons.svg"),
        name,
    )


@register.simple_tag(takes_context=True)
def nav_state(context, section):
    """Mark the current section, for the menu's look and for screen readers."""
    match = getattr(context.get("request"), "resolver_match", None)
    if match and match.url_name in _NAV_SECTIONS.get(section, ()):
        return format_html('class="{}" aria-current="{}"', "pillnav-link active", "page")
    return format_html('class="{}"', "pillnav-link")


@register.filter
def initials(name):
    """Up to two capitals for an avatar. Names with no letters get a neutral mark."""
    letters = [part[0] for part in str(name).split() if part[0].isalpha()]
    return "".join(letters[:2]).upper() or "•"
