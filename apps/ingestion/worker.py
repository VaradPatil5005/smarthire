"""Child-process entry point: do one job on one file, print JSON to stdout, touch nothing else.

The parent starts this with a scrubbed environment, so it holds no secrets or database URL and
imports no Django settings. It never writes to the database. Only the parent does.
"""

import json
import sys

from apps.ingestion.ocr_core import text_missing_from_render
from apps.ingestion.scanner import Limits, ScanFailure, scan_pdf


def main(argv):
    if argv[0] == "ocr":
        _mode, path, executable = argv
        sys.stdout.write(json.dumps({"missing": text_missing_from_render(path, executable)}))
        return 0
    path, preview_dir, limits_json = argv
    limits = Limits(**json.loads(limits_json))
    try:
        result = scan_pdf(path, limits, preview_dir=preview_dir or None)
    except ScanFailure as failure:
        result = {"failure": failure.code}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
