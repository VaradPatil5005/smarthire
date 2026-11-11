# Verification record - 11 November 2026

This record separates measured results from checks still needed on the submission host.
All test and demonstration data is synthetic. Historical coverage results remain dated
9 November in the [test register](test-register.md).

## Recorded checks

| Check | Recorded evidence |
| --- | --- |
| Required fast verification | `make verify-fast`: **951 passed, 4 skipped, 17 deselected**, 227.83 seconds |
| Environment | Python 3.12, isolated SQLite scratch database, `DJANGO_LOAD_DOTENV=0`, writable scratch temporary directory |
| Lint, format, Django checks and migration drift | Passed as part of the fast verification |
| Static security | Bandit reported no medium/high findings in `apps/` and `config/` |
| Production configuration | `check --deploy --fail-level WARNING` passed with ephemeral configuration |
| Browser motion | Ten core cases plus ordinary-navigation and live-preference regression checks passed |
| Navigation and fallback | Five normal links, blocked storage, reduced motion and keyboard Enter passed without browser errors |
| Responsive UI | Twelve desktop/mobile renders and four curve stages inspected, with no horizontal overflow |
| Synthetic workflow | CSRF-enforced Django Client plus Chromium bridge exercised approval, 65/70/100/historical-70 scores, X-ray, CSV totals and other-organisation 404s |
| API contract | 36 paths, 49 operations, 46 schemas; four schema tests and 27 actual synthetic response checks passed |
| Presentation | Ten-slide PDF and offline HTML deck rendered and independently inspected |

These results were recorded before assembling the company-only source package. The package removes
development coordination files and does not change application behaviour. Its checksum and file
manifest identify the handover snapshot. The fast-gate count above is not a new execution against an
extracted package.

## Verification limits

- Four skipped tests require PostgreSQL. PostgreSQL and normal live TCP browser connections were
  blocked by the session environment. Run the PostgreSQL-specific tests on a suitable host.
- The Chromium bridge exercised rendered UI with synthetic requests through Django's test client.
  It reconstructed known fixture uploads and followed redirects. This does not test live HTTP upload
  transport, a reverse proxy, HTTPS cookies, production workers or a live PostgreSQL connection.
- The final slow suite and a fresh coverage measurement were not rerun. The historical 95% coverage
  is a dated result, not the current revision's measurement.
- A fresh dependency vulnerability audit was not established during this pass. The historical
  dependency-audit result is not a fresh guarantee.
- Clean PostgreSQL setup, Docker/CI startup and the five-minute demonstration still need a host
  rehearsal. Manual keyboard, spreadsheet export and X-ray checks remain human acceptance steps.

## Remaining engineering work

| Area | Known limit or check to complete |
| --- | --- |
| PostgreSQL migration | Apply all migrations, including the approved-rubric immutability trigger, to an empty PostgreSQL 16 database and run insertion/move/concurrency tests |
| Concurrent uploads | Profile locking does not yet cover all quota/version checks. Test simultaneous first uploads and quota-boundary uploads before handling real data |
| Concurrent rubric changes | Approval's nonempty check and concurrent deletion need consistent parent locking and a PostgreSQL race test |
| Change explanations | Some rubric-only and availability-only changes lack a complete explanation history |
| API/form validation | Some candidate month inputs still use integer coercion; project web forms and import rows need stricter type, date and field-length validation |
| Concurrent imports | Shared source keys across batches need concurrency checks and consistent locking; request-layer import limits also need verification |
| Login throttling | The current cache is per process. A deployment needs a shared cache and trusted proxy configuration |
| Worker isolation | Child-process timeouts and a scrubbed environment exist. OS memory and network isolation still need deployment controls |
| Score policy | Resume replacement and older accepted evidence, and duration on Verified skills, require explicit product-owner examples before changing scoring semantics |
| Privacy operations | Data requests do not implement erasure or a retention engine. Agree and implement deletion, backup and incident procedures before real use |

## Matching quality and feature limits

The extractor uses spaCy phrase rules and a controlled vocabulary. It has no trained semantic model
or LLM. A 24-snippet developer-authored synthetic diagnostic reported 21 true positives, zero false
positives and one false negative out of 22 expected positive mentions with the seeded vocabulary.
That is a development diagnostic without independent labels or a holdout set. It does not measure
PDF/OCR quality, real shortlist suitability, fairness, hiring outcomes or reviewer time saved.

Real-project Precision@3, historical replay and time-saved studies remain unmeasured or unimplemented.
Candidate registration is invitation-based, with no staff invitation-management screen or password
reset flow. Uploads are PDF only. Interview scheduling and email notifications are not implemented.
The utilisation dashboard summarises current allocation rather than dated bookings or forecasting.

Keep the approved [Scoring Rule v1.1](../architecture/scoring.md) unchanged until any policy change
has explicit approval. See the [submission checklist](submission-checklist.md) for the final handover
and [compliance notes](compliance.md) for deployment planning.
