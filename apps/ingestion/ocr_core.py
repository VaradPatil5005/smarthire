"""Render a PDF and OCR it. Runs in the scanner's child process and imports nothing from Django."""

import re
import subprocess  # nosec B404
import tempfile
from pathlib import Path

import pymupdf

OCR_DPI = 200
MIN_TOKEN_CHARS = 4
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]+")


def _ocr(executable, image_path, timeout):
    completed = subprocess.run(  # noqa: S603  # nosec B603
        [executable, str(image_path), "stdout"],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return completed.stdout.decode("utf-8", errors="replace")


def text_missing_from_render(path, executable, timeout=60):
    """For each page, tokens the file claims to contain that OCR of the render does not show."""
    missing = []
    with pymupdf.open(path, filetype="pdf") as doc, tempfile.TemporaryDirectory() as folder:
        for number, page in enumerate(doc, start=1):
            image = Path(folder) / f"page-{number}.png"
            page.get_pixmap(dpi=OCR_DPI).save(str(image))
            seen = {token.lower() for token in _WORD.findall(_ocr(executable, image, timeout))}
            claimed = {t for t in _WORD.findall(page.get_text()) if len(t) >= MIN_TOKEN_CHARS}
            absent = sorted(t for t in claimed if t.lower() not in seen)
            if absent:
                missing.append({"page": number, "tokens": absent})
    return missing
