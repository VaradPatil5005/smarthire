# SmartHireAI setup, development and quality checks.
PY ?= python
APPS := apps config

.PHONY: setup setup-local db-start db-stop lock seed run lint check test-fast verify-fast test adversarial isolation security deploy-check e2e fixtures verify

setup:
	$(PY) -m pip install -r requirements-dev.txt
	docker compose up -d --wait db
	$(PY) manage.py migrate

# For a machine without Docker: install dependencies and use an existing PostgreSQL 16 server.
setup-local:
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) manage.py migrate

db-start:
	pg_ctl -D .tools/pgdata status >/dev/null 2>&1 || pg_ctl -D .tools/pgdata -l .tools/pg.log -o "-c listen_addresses=127.0.0.1 -p 5432" -w start >/dev/null 2>&1 </dev/null

db-stop:
	pg_ctl -D .tools/pgdata stop

lock:
	uv pip compile --universal --python-version 3.12 --generate-hashes -o requirements.txt requirements.in
	uv pip compile --universal --python-version 3.12 --generate-hashes -o requirements-dev.txt requirements-dev.in

seed:
	$(PY) manage.py seed_demo

run:
	$(PY) manage.py runserver

lint:
	ruff check .
	ruff format --check .

check:
	$(PY) manage.py check
	$(PY) manage.py makemigrations --check --dry-run

test-fast:
	$(PY) -m pytest -q -x -m "not slow and not e2e"

# Fast quality checks.
verify-fast: lint check test-fast

test:
	$(PY) -m pytest -q -m "not e2e" --cov=apps --cov-report=term-missing --cov-fail-under=85

adversarial:
	$(PY) -m pytest -q tests/adversarial

isolation:
	$(PY) -m pytest -q tests/isolation

security:
	bandit -q -r $(APPS) -ll
	pip-audit -r requirements.txt

deploy-check:
	DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=$$($(PY) -c 'import secrets; print(secrets.token_urlsafe(64))') \
	DJANGO_ALLOWED_HOSTS=example.test $(PY) manage.py check --deploy --fail-level WARNING

e2e:
	DJANGO_ALLOW_ASYNC_UNSAFE=true $(PY) -m pytest -q tests/e2e

fixtures:
	$(PY) fixtures/generate_fixtures.py

# Full quality checks.
verify: lint check test adversarial isolation security deploy-check
