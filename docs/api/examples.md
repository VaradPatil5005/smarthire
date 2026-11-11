# API examples

Interactive docs are at `/api/docs/`, and the contract is `docs/contracts/openapi.yaml`. The API uses
session authentication, so log in at `/login/` first; write requests need the CSRF token. Every example
below has an allowed and a denied case for its role, and `apps/web/tests/test_api_examples.py` runs
them all against seeded data.

## Candidate

**Allowed:** read your own profile.

    GET /api/profiles/me/
    200 {"display_name": "Fictional Candidate A", "claims": [...], "uploads": [...], "correction_route": {...}}

**Denied:** approve a rubric.

    POST /api/projects/{id}/rubrics/1/approve/
    403

## Recruiter

**Allowed:** start a run. Repeating the same key and payload returns the same run.

    POST /api/projects/{id}/runs/
    Idempotency-Key: demo-1
    201 {"id": "...", "rubric_version": 1, "dictionary_version": 1, "algorithm_version": "1.1", "run_date": "2026-11-08"}

The same key with a different payload returns 409.

**Denied:** approve a rubric. Only a delivery manager or admin can.

    POST /api/projects/{id}/rubrics/1/approve/
    403

## Delivery manager

**Allowed:** approve and lock a rubric.

    POST /api/projects/{id}/rubrics/1/approve/
    200 {"version": 1, "status": "APPROVED", "skills": [...]}

**Denied:** import a roster. Only an admin can.

    POST /api/imports/
    403

## Admin

**Allowed:** preview an import. Nothing is written until it is confirmed.

    POST /api/imports/   (multipart: file, source_system)
    201 {"status": "PREVIEW", "withheld_count": 3, "rows": [...]}

**Denied:** anything in another organisation. This holds for every role.

    GET /api/projects/{id of another organisation}/
    404

## Other useful routes

| Route | Purpose |
| --- | --- |
| `POST /api/profiles/me/resumes/` | Upload a PDF. Returns 202, and the scan runs in the background |
| `GET /api/resumes/{id}/` | The scan job's result. A candidate sees PENDING, PROCESSED or FAILED |
| `GET /api/resumes/{id}/xray/` | Hidden spans, staff only |
| `GET /api/runs/{id}/results/?group=ready&page=1` | Paginated results with contributions |
| `POST /api/results/{id}/reviews/` | Record a decision. A reason is required |
| `POST /api/runs/{id}/reproduce/` | Recompute a stored run and compare it |
| `GET /api/runs/{id}/export.csv`, `export.xlsx` | Same filters and permissions as the screen |
