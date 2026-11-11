"""Local development settings. Never used for the assessed deployment."""

from .base import *  # noqa: F403
from .base import SECRET_KEY as _BASE_SECRET_KEY

DEBUG = True
SECRET_KEY = _BASE_SECRET_KEY or "dev-only-not-a-secret"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
OCR_DIFF_ENABLED = False  # Slow, and needs tesseract. Production turns it on.
# Scans run inline so `make run` needs no second process. Production uses `manage.py qcluster`.
Q_CLUSTER = {"name": "smarthire-dev", "orm": "default", "sync": True, "timeout": 120, "retry": 180}
