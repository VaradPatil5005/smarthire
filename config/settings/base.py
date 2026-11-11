"""Settings shared by every environment. Secrets come only from environment variables."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path):
    """Read a local .env into the environment. A variable already set wins. Never committed."""
    if os.environ.get("DJANGO_LOAD_DOTENV", "1") == "0":
        return
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and not name.lstrip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip())


_load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_q",
    "apps.accounts",
    "apps.tenancy",
    "apps.core",
    "apps.talent",
    "apps.projects",
    "apps.matching",
    "apps.ingestion",
    "apps.onboarding",
    "apps.reports",
    "apps.web",
    "apps.demo",
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
ADMIN_ENABLED = True

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.MembershipMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# PostgreSQL 16 is the assessed database; SQLite is only a local-scratch fallback.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploaded résumés live outside any served path and are reachable only via an authorised view.
PRIVATE_MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))

# Upload and scan limits (docs/requirements/upload-security.md).
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_MAX_PAGES = 10
UPLOAD_MAX_PAGE_POINTS = 3370
UPLOAD_MAX_DECOMPRESSED_BYTES = 100 * 1024 * 1024
UPLOAD_RATE_LIMIT_PER_HOUR = 10
UPLOAD_STORAGE_CAP_BYTES = 50 * 1024 * 1024
SCAN_TIME_LIMIT_SECONDS = 100
SCAN_STUCK_AFTER_SECONDS = 600
SCAN_MIN_CONTRAST_RATIO = 1.5
AUDIT_TEXT_MAX_CHARS = 4000
OCR_DIFF_ENABLED = True

LOGIN_THROTTLE_MAX_FAILURES = 5
LOGIN_THROTTLE_WINDOW_SECONDS = 900

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}
SPECTACULAR_SETTINGS = {
    "DEFAULT_GENERATOR_CLASS": "apps.core.schema.ApprovedSchemaGenerator",
    "TITLE": "SmartHireAI API",
    "DESCRIPTION": "Evidence-locked project-to-talent matching.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
}

# Background jobs use the Django ORM as broker, so no Redis is needed.
Q_CLUSTER = {
    "name": "smarthire",
    "orm": "default",
    "workers": 2,
    "timeout": 120,
    "retry": 180,
    "max_attempts": 1,
}

# IDs and actions only: never résumé text, file contents, tokens or contact fields.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
