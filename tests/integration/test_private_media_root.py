"""Uploads written during a test run stay in that run's temporary directory."""

from pathlib import Path

from django.conf import settings

from config.settings import test as test_settings


def test_private_media_root_is_per_run(tmp_path_factory):
    root = Path(settings.PRIVATE_MEDIA_ROOT)

    assert root.is_dir()
    assert root.is_relative_to(tmp_path_factory.getbasetemp())
    assert root != test_settings.PRIVATE_MEDIA_ROOT
