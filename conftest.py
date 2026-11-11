"""Project-wide pytest wiring. Markers and coverage settings live in pyproject.toml."""

import pytest
from django.conf import settings

MARKER_BY_SUITE = {
    "tests/adversarial": "adversarial",
    "tests/e2e": "e2e",
    "tests/isolation": "isolation",
}


def pytest_collection_modifyitems(config, items):
    """Mark tests by suite, so that a browser test can never slip into `make verify-fast`."""
    for item in items:
        location = item.path.relative_to(config.rootpath).as_posix()
        for suite, marker in MARKER_BY_SUITE.items():
            if location.startswith(f"{suite}/"):
                item.add_marker(getattr(pytest.mark, marker))


@pytest.fixture(scope="session", autouse=True)
def private_media_root_per_run(tmp_path_factory):
    """Keep this run's uploads apart from other runs, inside pytest's own temporary directory."""
    original = settings.PRIVATE_MEDIA_ROOT
    settings.PRIVATE_MEDIA_ROOT = tmp_path_factory.mktemp("private-media")
    yield
    settings.PRIVATE_MEDIA_ROOT = original
