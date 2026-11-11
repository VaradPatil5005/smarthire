# SmartHireAI
SmartHireAI helps a We.PLM delivery manager shortlist bench consultants and external applicants for a PLM project. Each candidate’s score opens to the requirements and reviewed evidence behind it.

Matches a project's requirements to internal bench consultants and external applicants for a
3DEXPERIENCE consultancy, and shows the evidence behind every score. In our tests, none of the
18 hidden-text attack pairs moved a score.

**The idea: evidence-locked scoring.** A candidate earns points only for a passage a person can see on
the page and a reviewer accepted, or for a form field they confirmed. Hidden text, metadata and
instructions never reach the score, because the scorer never reads the document. No LLM is involved
in scoring.

This is a We.PLM internship project, built with AI assistance. All data is synthetic.

## Quick start

You need Python 3.12 and Git. PostgreSQL assessment setup also needs Docker Desktop or an existing
PostgreSQL 16 server.
After cloning the repository or extracting the submitted source archive, open its root folder.

### Local UI preview

Install the dependencies once:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

On Windows, double-click `start-local.cmd`, or run:

```powershell
& .\.venv\Scripts\python.exe run_local.py
```

Open <http://127.0.0.1:8000/login/> and sign in with `manager` / `demo-only-Plm-2026!`.
Keep the terminal open. If port 8000 is busy, append `--port 8001` and use port 8001 in the URL.
The preview creates its own synthetic SQLite data under `.cache/local-preview/` and ignores `.env`.
PostgreSQL remains the assessment database; use either setup path below for that configuration.

### Windows PowerShell

These commands use the virtual environment directly, so no activation or execution-policy change
is needed. They use explicit environment variables and ignore a local Django `.env` file.
The password below is for a local synthetic demo only. If port 5432 already hosts PostgreSQL,
use that server's connection details and skip `docker compose up`.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DJANGO_LOAD_DOTENV = "0"
$env:DJANGO_SETTINGS_MODULE = "config.settings.dev"
$env:POSTGRES_DB = "smarthire"
$env:POSTGRES_USER = "smarthire"
$env:POSTGRES_PASSWORD = "local-demo-only-change-me"
$env:DATABASE_URL = "postgres://smarthire:local-demo-only-change-me@127.0.0.1:5432/smarthire"
docker compose up -d --wait db
& .\.venv\Scripts\python.exe manage.py migrate
& .\.venv\Scripts\python.exe manage.py seed_demo
& .\.venv\Scripts\python.exe manage.py runserver
```

### Git Bash / Linux / macOS

This path requires `make`. On Windows, use Git Bash.

```bash
cp .env.example .env
```

Edit the copied file: set a local database password in both `POSTGRES_PASSWORD` and `DATABASE_URL`.

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate    # on Windows: source .venv/Scripts/activate
```

```bash
make setup
```

```bash
make seed
```

```bash
make run
```

Open <http://127.0.0.1:8000/>. The earlier clean-install measurement and its limits are in
[the test register](docs/manual/test-register.md). The current submission still needs the human
rehearsal in the [submission checklist](docs/manual/submission-checklist.md).

**No Docker?** Point `DATABASE_URL` in `.env` at any PostgreSQL 16 and run `make setup-local` in place
of `make setup`.

### Demo logins

All accounts are fictional and the password is `demo-only-Plm-2026!`. Set `DEMO_PASSWORD` to change
it. `seed_demo` refuses to run with `DEBUG` off by default.

| Username | Role | Lands on |
| --- | --- | --- |
| `manager` | Delivery manager, We.PLM demo | Bench |
| `recruiter` | Recruiter, We.PLM demo | Projects |
| `admin` | Admin, We.PLM demo | Dashboard |
| `candidate_a`, `candidate_b` | Candidates, We.PLM demo | My profile |
| `other_recruiter` | Recruiter, second organisation | Projects |

## How it works

    Upload → quarantine → scan in a child process → visible text only → proposed evidence
          → a reviewer accepts with a reason → one scoring function → stored, reproducible run

- **Two numbers.** Coverage is merit. Staffing fit is timing. Neither changes the other.
- **A flag never subtracts.** It excludes the span and shows it to a reviewer in the X-ray panel.
- **Every run pins its inputs**, so any past score can be reproduced.
- **Tenancy.** Organisation comes from the membership. Another organisation's object answers 404,
  exactly like one that never existed.

Rule and worked numbers: [scoring.md](docs/architecture/scoring.md).

## Deliverables

| Deliverable | Where |
| --- | --- |
| Source code | `apps/`, `config/`, `templates/`, `static/` |
| Database schema | [ER diagram and constraints](docs/architecture/er.md), `apps/*/migrations/` |
| API documentation | `/api/docs/` on a running app, [contract](docs/contracts/openapi.yaml), [examples](docs/api/examples.md) |
| Test cases | [Current verification](docs/manual/verification-2026-11-11.md), [historical test register](docs/manual/test-register.md), `apps/*/tests/`, `tests/` |
| User manual | [Candidates](docs/manual/candidate.md), [recruiters](docs/manual/recruiter.md) |
| Final presentation | [Presentation PDF](docs/demo/SmartHireAI_Final_Presentation.pdf), [offline slide deck](docs/demo/SmartHireAI_Final_Presentation.html), [demo script](docs/demo/script.md), [screenshots](docs/demo/screenshots/) |

The [company brief](docs/source/assignment.md) lists the six modules and required deliverables.
The [11 November verification record](docs/manual/verification-2026-11-11.md) states measured results,
checks that still need a suitable host, and known limitations.
The final handover checks are in the [submission checklist](docs/manual/submission-checklist.md).

Also: [architecture decisions](docs/adr/), [historical security test report](docs/security/redteam-report.md) and
[compliance notes](docs/manual/compliance.md).

## Stack

Python 3.12 · Django 5.2 · Django REST Framework · drf-spectacular · PostgreSQL 16 · Bootstrap 5 ·
htmx · PyMuPDF · spaCy (PhraseMatcher) · pandas · django-q2 · pytest · hypothesis · Playwright.

PyMuPDF is AGPL. Review its licensing obligations before distributing the code or using it commercially.

## Tests

```bash
make verify-fast
```

```bash
make verify
```

```bash
make e2e
```

`make e2e` needs a browser once: `python -m playwright install chromium`. `make fixtures` rebuilds the
synthetic PDFs.

Without `make`, the equivalent Windows checks are:

```powershell
& .\.venv\Scripts\ruff.exe check .
& .\.venv\Scripts\ruff.exe format --check .
& .\.venv\Scripts\python.exe manage.py check
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe -m pytest -q -x -m "not slow and not e2e"
```

Run tests only against a dedicated local test database. Django creates a separate test database
and the PostgreSQL user needs permission to create it. Do not point these commands at production.

## Running it for real

`make run` is for local use. It scans uploads inline. A deployment uses
`DJANGO_SETTINGS_MODULE=config.settings.prod`, serves collected static files, runs
`python manage.py qcluster` for background scans, and schedules `python manage.py sweep_stuck_scans`.
Django admin is not mounted in production.

## Known limits

These controls prove the system resists the attacks we tested. They do not prove it resists every
possible attack.

- Visible false claims are not detected. Verify critical skills by test or interview.
- Font remapping needs the slower OCR check (`apps/ingestion/ocr_diff.py`), which needs `tesseract`
  and only adds notes for a reviewer.
- PDF only in v1.
- The scanner's child process has no memory cap on Windows and no network sandbox on a developer
  machine.
- Login throttling uses Django's cache, so a multi-process deployment needs a shared cache.
- Skill extraction uses a controlled vocabulary and spaCy phrase rules. It has no trained matching
  model or LLM. Describe that baseline honestly when discussing the assignment's AI objective.
- Candidate sign-up requires an invitation. Issuing invitations currently uses the Python service,
  with no staff invitation screen. Interview scheduling and email notifications are not implemented.
