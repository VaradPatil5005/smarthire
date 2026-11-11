"""Test settings: fast hashing and isolated file storage. The database comes from DATABASE_URL."""

import tempfile
from pathlib import Path

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-only-not-a-secret"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
OCR_DIFF_ENABLED = False
PRIVATE_MEDIA_ROOT = Path(tempfile.gettempdir()) / "smarthire-test-media"
Q_CLUSTER = {"name": "smarthire-test", "orm": "default", "sync": True, "timeout": 60, "retry": 120}
