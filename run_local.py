"""Start a synthetic local UI preview; PostgreSQL remains the assessment database."""

import argparse
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    root = Path(__file__).resolve().parent
    state = root / ".cache" / "local-preview"
    state.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    os.environ.update(
        DJANGO_LOAD_DOTENV="0",
        DJANGO_SETTINGS_MODULE="config.settings.dev",
        DJANGO_SECRET_KEY=secrets.token_urlsafe(48),
        DATABASE_URL="sqlite:///" + (state / "preview.sqlite3").as_posix(),
        PRIVATE_MEDIA_ROOT=str(state / "private_media"),
        TEMP=str(state),
        TMP=str(state),
    )
    import django

    django.setup()
    from django.core.management import call_command

    from apps.accounts.models import User

    call_command("migrate", interactive=False)
    if not User.objects.exists():
        call_command("seed_demo")
    call_command("check")
    print(f"Local preview: http://127.0.0.1:{args.port}/login/", flush=True)
    print("Synthetic login: manager / demo-only-Plm-2026!", flush=True)
    if not args.prepare_only:
        call_command("runserver", f"127.0.0.1:{args.port}", use_reloader=False)


if __name__ == "__main__":
    main()
