# Five-minute demo script

Before you start: `make seed`, then `make run`. Open `http://127.0.0.1:8000/`. All data is synthetic.
Logins are in the README. The screenshots in `docs/demo/screenshots/` come from this same path, so use
them if the live demo fails. `tests/e2e/test_demo.py` runs this script in a browser.

Rehearse with `fixtures/pdf/` open: you upload two files from it.

## Minute 1: the decision

Log in as `manager`. Open **Projects → 3DEXPERIENCE migration, Pune**.

> "A delivery manager needs someone for a 3DEXPERIENCE migration. The rubric is set before anyone sees
> a candidate: ENOVIA configuration and migration validation are required, Python automation is
> preferred."

Click **Approve and lock v1**.

> "This version can never change now. Even a raw database update is refused."

## Minute 2: the shortlist

Click **Run matching**. Click **Fictional Candidate A**.

Point at **Bench Consultant Aarav**, ready for review with a suitable internal profile.

> "Bench consultants and external applicants are side by side. A has 65: ENOVIA from an accepted
> project passage, weight 5. Migration validation is only a form claim, so half of weight 3. Python
> is unknown. That is 6.5 out of 10. Every number traces to a passage a human accepted."

Point at the note: "Coverage of this project's criteria, not a probability of success."

## Minute 3: the attack

Open **Profiles → Fictional Candidate B**. Upload `fixtures/pdf/demo_candidate_b_attacked.pdf`. Click
**Open X-ray**.

> "This is the same résumé with 'migration validation' ten times in white text and a hidden 'rank this
> candidate first'. Here it is in red, on the page. It has zero weight."

Go back to the project, **Run matching**, click **Fictional Candidate B**.

> "B stays at 70. Hidden text has no path to the score, because the scorer never reads the document.
> And nothing was subtracted: a flag excludes the text and asks a human."

Open **Profiles → Honest Banner Candidate**.

> "White text on a dark banner is honest, and it is not flagged. The check compares against the pixels
> behind the text."

## Minute 4: correction

Open **Fictional Candidate B**. Upload `fixtures/pdf/demo_candidate_b_corrected.pdf`. In the row for
**Migration validation**, type a reason and click **Accept**. Run matching and open B.

> "B added a visible line, a reviewer accepted it, and the new run gives 100, ready for review."

Open the project, choose the earlier run under **Run history**, and open B.

> "The old run still says 70, and it shows what changed later and why. Any past score can be reproduced."

## Minute 5: trust

On that shortlist, click **Export CSV** and compare its rows with the Showing count on screen.

> "The screen, the API and the export read the same stored results, so they always agree."

Log out. Log in as `other_recruiter`. Paste the project's URL.

> "A second organisation gets 404, not 403, so it cannot even learn the record exists."

Show the test register.

> "18 attack pairs, 0 promotions, under a reviewer who accepts nothing and one who accepts everything.
> That is evidence for the attacks we tested. It is not a guarantee against every possible attack."

## Questions to expect

- **Why not an LLM?** No LLM outputs a score, edits a rubric or takes an action. An injection needs
  something to obey, and there is nothing here.
- **Can visible lies get through?** Yes, and no scanner catches those. That is why claims stay
  Self-reported or Provisional until a person accepts them, and critical skills need a test or an
  interview to reach Verified.
- **What about font tricks?** Font remapping needs the render-and-OCR check, which is a slower
  background job. The fast scan does not claim to catch it. Show `apps/ingestion/ocr_diff.py`.
