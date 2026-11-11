"""django-q2 entry points. Arguments are IDs only, and a task returns nothing worth storing."""

from .services import scan_stored_version, sweep_stuck_versions


def scan_version(version_id):
    scan_stored_version(version_id)


def ocr_diff_version(version_id):
    from .ocr_diff import run_ocr_diff

    run_ocr_diff(version_id)


def sweep_stuck():
    sweep_stuck_versions()
