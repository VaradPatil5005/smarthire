# Submission checklist

Submission target: 11 November 2026. This checklist records the final human handover. Unchecked
items are work to perform, not implied passes. Use synthetic data throughout.
The [verification record](verification-2026-11-11.md) contains the current findings and
verification limits. A synthetic extraction diagnostic is not a real-project matching-quality study.

## What to submit

| Company deliverable | Repository entry point | Final check |
| --- | --- | --- |
| Source code | `apps/`, `config/`, `templates/`, `static/`, dependency locks | Fresh copy installs from the README |
| Database schema | `docs/architecture/er.md`, `apps/*/migrations/` | Migrations apply to an empty PostgreSQL 16 database |
| API documentation | `docs/contracts/openapi.yaml`, `docs/api/examples.md`, running `/api/docs/` | One allowed and denied example per role |
| Test cases | `docs/manual/test-register.md`, app tests, `tests/` | Current commands and results accompany the submission |
| User manual | `docs/manual/candidate.md`, `docs/manual/recruiter.md` | A new user can finish each workflow |
| Final presentation | `docs/demo/SmartHireAI_Final_Presentation.pdf`, `.html`, `script.md` | Five-minute rehearsal, with PDF as offline fallback |

The HTML deck works offline. Open it in a browser and use Left/Right, Home/End or its buttons.
The PDF contains the same slides. Screenshots in the deck are the recorded synthetic demo from
9 November, before the final motion pass. Run the live app to show the current motion.

## Human rehearsal

- [ ] Start from a fresh clone or extracted source archive using only the README, on PostgreSQL 16.
- [ ] Log in as `manager`, `recruiter`, `admin`, `candidate_a` and `other_recruiter` and confirm each home.
- [ ] Follow `docs/demo/script.md` from rubric approval through matching, the attacked PDF, correction,
      historical run, export and the second organisation's 404.
- [ ] Try a failed PDF upload and recover through the manual skill form.
- [ ] Use keyboard only for navigation, filters, evidence, X-ray and form validation. Confirm visible
      focus and meaningful labels. Try the OS reduced-motion setting.
- [ ] Open CSV and XLSX exports in a spreadsheet and confirm formula-looking values remain text.
- [ ] Read the X-ray without relying on red alone. Explain that a flag excludes a span and removes no points.
- [ ] Open the presentation PDF offline and rehearse for five minutes. Keep original screenshots available.
- [ ] Confirm the repository URL or archive opens on another machine and contains the required files.

## Repository handover

- [ ] Include the company brief, application code, migrations, dependency locks, synthetic fixtures,
      technical documentation, test cases, user manuals and presentation.
- [ ] Exclude `.env`, virtual environments, `.tools/`, caches, databases, `private_media/`, personal files
      and real resumes. Use the company source package instead of copying the whole working folder.
- [ ] Exclude development prompts, agent configuration, internal coordination records, build plans
      and research planning documents from the company handover.
- [ ] Check `git status --short` for intended changes, untracked deliverables and accidental local files.
- [ ] Record the submitted source snapshot and verification results. For an archive, retain its checksum.
      Do not reuse an older test count as a new result.
- [ ] Run `make verify-fast`, the full suite/coverage, security checks, schema validation and browser checks
      as documented. If a check cannot run, state why and keep the last measured result dated.
- [ ] Provide the repository link or source archive, the PDF deck, demo credentials and the README entry point.

## Questions to answer plainly

| Evaluator question | Accurate answer |
| --- | --- |
| Where is the AI? | spaCy phrase matching and aliases propose skills. A reviewer controls accepted evidence. No trained model or LLM assigns scores. Ask whether that baseline satisfies the intended AI requirement. |
| What does 70 mean? | Coverage of one approved project's weighted criteria, with evidence and duration factors. It is not a hiring-success probability. |
| Does the scanner catch every attack? | No. It has evidence for named synthetic attacks. Visible false claims still need verification. |
| Can candidates register? | Yes, through a single-use invitation. Staff invitation issuance currently uses the Python service, not a UI. |
| Are the bonuses complete? | PDF parsing and utilisation are implemented. AI model suggestions, interview scheduling and email notifications are not implemented. |
| Is this ready for real candidate data? | A deployment still needs privacy review, retention and deletion procedures, operating controls, host isolation and real-project evaluation. |

## After the deadline

Prioritise a mentor-labelled matching benchmark and a shadow review with timed manual comparison.
Then consider staff invitation management and optional interview/calendar features. Avoid changing
the approved scoring rule or adding untested features immediately before the submission.
