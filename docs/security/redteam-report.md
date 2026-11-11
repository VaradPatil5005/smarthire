# Red-team report and remediation history

Historical campaign against commit `bfe5820`, on Windows through Django's test client,
not a deployed server. Every finding was reproduced before remediation. Regression coverage is in
`tests/adversarial/test_redteam_regressions.py`, which fails if a finding returns.
The original remediation did not receive a second complete attack campaign. Later targeted reviews
and regression runs are recorded in the [test register](../manual/test-register.md); they do not
retroactively turn this historical campaign into a fresh deployment assessment.

These results show resistance to the attacks tried. They do not prove resistance to every attack.

## Findings

| # | Severity | Finding | Fix | Status |
| --- | --- | --- | --- | --- |
| 1 | High | Hidden text passed as visible and earned credit if accepted: a box over one keyword in a long line; black text on a black bar overhanging by 1 pt; white in a white box inside a frame; a decoy word over a box; an image over text; opacity 0.11 | Visibility decided per word. Background sampled inside the word box. Opacity composited before contrast. Paint order checked for later opaque fills and images. Glyph must leave ink near its own colour. Reviewers see the rendered line beside the quote | Fixed |
| 2 | High | Login throttle bypassed by padding the username | Throttle keys on the normalised username that authentication uses | Fixed |
| 3 | Medium | A recruiter could review their own profile to READY | Decisions on your own profile are refused | Fixed |
| 4 | Medium | XLSX bomb inflated in the web process | Declared size and compression ratio checked before parsing | Fixed |
| 5 | Medium | PDF decompression limit bypassed by filter chains; huge declared images not counted | Unmeasurable filter chains fail closed; declared image size counted | Fixed |
| 6 | Medium | OCR diff never ran, so font remapping stayed open | Queued after every good scan where enabled, in the child process | Fixed for production settings; off in dev (slow, needs tesseract) |
| 7 | Medium | One bad import row caused a 500 and imported nothing | Dates and integers validated per row; bad rows withheld | Fixed |
| 8 | Medium | Re-importing fewer columns wiped fields | Only columns in the file update | Fixed |
| 9 | Medium | `make deploy-check` failed on schema warnings | Unique operation IDs | Fixed |
| 10 | Low | Bad input caused 500s, and raw values reached logs | Validated: months, notice, span ID, run date, dates, allocation | Fixed |
| 11 | Low | Re-import unarchived a profile without recording it | Recorded, so rollback archives it again | Fixed |
| 12 | Low | `seed_demo --force` could use the known password | `--force` requires `DEMO_PASSWORD` | Fixed |
| 13 | Low | Export escaping missed newline, NBSP and fullwidth forms | Normalised before the check | Fixed; not opened in a real spreadsheet |
| 14 | Low | Throttle is per process with no shared cache; behind a proxy `REMOTE_ADDR` is shared | Not fixed in code | **Open, deployment task**, in the README |
| 15 | Low | Imported claims survive rollback on archived profiles | They earn nothing while unconfirmed | **Open, accepted** |

## What held

Full occlusion, wide bars and text scaling were caught. Candidates got 403 on evidence, X-ray and page
images. Clean and flagged files look the same to a candidate. CSRF held on API and web posts. Revoked
users were denied. All 14 cross-organisation requests returned 404. Candidate PATCH could not change
bench fields, organisation or owner. Identical emails stayed two profiles. In production settings
admin answered 404 and CSP, HSTS, nosniff, frame-deny and secure cookies were present. Logs held no
text, hidden-span, filename, email or phone markers for a normal upload.

## Still not defended

- **Visible false claims.** Nothing automatic can catch these. Verify by test or interview.
- **Font remapping in dev, and anywhere without tesseract.** The fast scan reads what the font map says.
- **Partial cover of a word.** A word with under half its letters covered stays visible, so a reader
  would see most of it too.
- **Parser containment.** The child has a scrubbed environment and time limit, but no enforced OS
  memory cap, restricted filesystem or network sandbox. It shares the application OS user. See the
  [verification record](../manual/verification-2026-11-11.md) for deployment and concurrency limitations.
