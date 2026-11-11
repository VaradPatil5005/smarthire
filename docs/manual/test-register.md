# Test register

Real results from `make verify` and `make e2e` on 9 November 2026, on Windows 11 with Python 3.12.6
and PostgreSQL 16.14. All data is synthetic. **These results are evidence for the fixtures and attacks
listed here, not a guarantee against every possible attack.** The labels are developer-authored; no mentor
has reviewed them.

For the later revision and current verification limits, see the
[11 November verification record](verification-2026-11-11.md). Counts in this register
remain the dated baseline, not a new result for that revision.

## Summary

| Check | Command | Result |
| --- | --- | --- |
| Lint and format | `ruff check`, `ruff format --check` | Clean |
| Django checks and migrations | `manage.py check`, `makemigrations --check` | Clean |
| Full suite with coverage | `make test` | 878 passed, 0 failed, 2 deselected (browser tests) |
| Coverage, all apps | `--cov=apps`, statements and branches | 95% (threshold 85%) |
| Coverage, matching and ingestion | by statements, from the same run | About 96% each (threshold 90%) |
| Adversarial suite | `make adversarial` | 116 passed, 0 failed |
| Isolation suite | `make isolation` | 394 passed, 0 failed |
| Browser demo | `make e2e` | 2 passed (the five-minute demo, and the suite's marker check) |
| Static security | `bandit -ll`, `pip-audit` | No findings, no known vulnerabilities |
| Production settings | `check --deploy --fail-level WARNING` | No issues |
| API schema | `spectacular --validate` | 0 errors |
| Clean install | Fresh clone to running seeded app | 180 seconds on 8 November, before the UI rebuild; not repeated. See below |

## Metrics, with denominators

| Metric | Definition | Result |
| --- | --- | --- |
| Attack promotion rate | Score rises or group promotions ÷ attack pairs | **0 of 18 pairs**, run twice: reviewer accepts nothing, and reviewer accepts everything (36 runs) |
| Scanner proofs | Attack fixtures with their named proof layer passing | 18 of 18: 14 at the scanner, 2 as regex notes (`atk_14`, `atk_15`), `atk_16` by the scoring property, `atk_17` by the extractor rule |
| False-flag rate | Benign documents flagged ÷ benign documents | **0 of 9**. Small sample, so weak evidence |
| Red-team bypass regressions | Hiding tricks from the campaign now excluded | 6 of 6, plus a check that a highlight and an underline are not flagged |
| Isolation | Routes classified | 124 of 124: 48 object, 22 collection, 6 public, 2 session, 46 operator admin |
| Isolation breaches | Forbidden reads or writes ÷ attempts | **0** across 70 tenant routes, on every HTTP method, for object routes also compared with an ID that never existed |
| Reproducibility | Identical reruns ÷ reruns | 100% in the tests that rerun stored runs |
| Worked example | Coverage to 2 decimals | 65.00, 70.00 and 100.00 exact, through the whole pipeline |
| Import rehearsal | Rows | 12 rows: 9 imported, 3 withheld. Re-import: 9 profiles, 0 writes |
| Formula escaping | Cases | 24 of 24: 6 prefixes × 2 forms × 2 formats, plus 5 Unicode variants |
| Dashboard against export | Filter combinations | 12 of 12 totals equal |
| Must criteria | Must ACs with a test naming them | 163 of 166. The other 3 are human checks (below). Machine ACs with no test: 0 |

A test naming a criterion shows it claims that criterion. These historical acceptance counts describe
developer-defined criteria and do not substitute for the company's review.

## Not measured

| Matching quality metric | Status at the historical baseline |
| --- | --- |
| Skill precision and recall (experiments A, B, C) | **Not run.** No labelled dataset exists yet. AC-MATCH-27, -28 are Should and unscheduled |
| Precision@3 and reviewer time saved | **Not run.** They need a mentor's labels and a timed session (AC-RANK-25, -26) |
| Historical replay | **Not built.** AC-RANK-24 is Could |

Do not quote a figure for these.

## Human checks still to do

| AC | Check | Who |
| --- | --- | --- |
| AC-DASH-09 | Shortlist, drawer, X-ray and bench by keyboard only: reachable, visible focus, labels, contrast | Varad |
| AC-DASH-16 | Open a formula-injection export in a real spreadsheet; no cell evaluates | Varad |
| AC-DASH-24 | X-ray shows hidden spans in red and still makes sense without colour | Varad |
| AC-AUTH-16 | The eight role examples in `docs/api/examples.md`. They also run as tests | Reviewer |
| Final rehearsal | Fresh clone, README only, the five-minute demo without assistance | Varad |

## Clean install rehearsal

A fresh `git clone`, then the README's steps, ended with the seeded app answering on `/healthz/`,
`/login/`, `/api/docs/` and static files. **180 seconds** in total, 163 of them installing packages.

Limits of this measurement: it used an existing Python 3.12 and a pip cache already on disk, and a
PostgreSQL already running in place of `docker compose`. A first install on a new machine will take
longer. **`docker-compose.yml` and the CI workflow have not been run**, because this machine has no
Docker and the repository has no remote yet.

## Fixture register

Fixtures are in `fixtures/pdf/`, built by `fixtures/generate_fixtures.py`. They regenerate
byte-identically, except `upl_encrypted.pdf`, whose AES salt is random.

| Fixtures | Input | Expected | Actual | Test |
| --- | --- | --- | --- | --- |
| `atk_01`–`03`, `atk_18` | White, near-white, sidebar-matching and white CMYK text | `LOW_CONTRAST`, excluded | Pass | `tests/adversarial/test_scanner_proofs.py` |
| `atk_04` | 1-pt text | `MICRO_FONT` | Pass | same |
| `atk_05`, `sup_06` | Render mode 3, on a normal page and on a page with no image | `RENDER_MODE_3` | Pass | same |
| `atk_06` | Opacity 0 | `ZERO_OPACITY` | Pass | same |
| `atk_07`, `sup_07` | White box over text; zero-area clip | `OCCLUDED_OR_CLIPPED` | Pass | same |
| `atk_08` | Off-page text | `OFF_PAGE` | Pass | same |
| `atk_09` | Layer switched off | `HIDDEN_LAYER` | Pass | same |
| `atk_10` | Long metadata | Recorded, never matched | Pass | same |
| `atk_11` | Unicode tag payload | Decoded for review, stripped | Pass | same |
| `atk_12`, `sup_08`, `sup_10`, `sup_11` | Zero-width, bidi, soft hyphen, ZWJ in Latin | Stripped and counted | Pass | same |
| `atk_13` | Cyrillic homoglyph | `HOMOGLYPH`, token excluded | Pass | same |
| `atk_14`, `atk_15` | Visible instructions | Note only; no credit | Pass | same, and `test_attack_twins.py` |
| `atk_16` | Keyword 50 times | Same credit as once | Pass | `apps/matching/tests/test_scoring.py`, `test_attack_twins.py` |
| `atk_17` | "Never used migration validation" | Cannot be accepted | Pass | `apps/matching/tests/test_runs_and_review.py` |
| All 18 pairs | Attack against clean twin | Identical skills, Coverage, group | Pass | `tests/adversarial/test_attack_twins.py` |
| `ben_01`–`09` | Benign look-alikes | Not flagged | Pass | `tests/adversarial/test_scanner_proofs.py` |
| `sup_01` | Font remapping | Clean in the fast scan; found by OCR | Pass | `apps/ingestion/tests/test_ocr_diff.py` |
| `sup_02`, `sup_03` | Hidden instructions | Flagged; no change to score or rubric | Pass | `test_attack_twins.py` |
| `sup_15` | Flate bomb | `TOO_MUCH_DATA` | Pass | `apps/ingestion/tests/test_upload.py` |
| `upl_*` | Encrypted, corrupt, renamed, too many pages, huge page | Refused or FAILED with a message | Pass | same |

## Historical known defects (9 November)

At the recorded 9 November baseline, no high or medium finding was open. See
`docs/security/redteam-report.md` for that campaign's two open low items and its limitations. Those
fixes passed regression tests but had not had a second red-team pass. This statement does not cover
later changes or replace the [current verification record](verification-2026-11-11.md).
