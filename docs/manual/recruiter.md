# User manual: recruiters, delivery managers and admins

## Who can do what

| Action | Candidate | Recruiter | Delivery manager | Admin |
| --- | --- | --- | --- | --- |
| Own profile, skills, uploads | Yes | | | |
| See profiles, bench, shortlists, X-ray, exports | No (403) | Yes | Yes | Yes |
| Create projects and draft rubrics | No | Yes | Yes | Yes |
| Approve a rubric | No | No | Yes | Yes |
| Record review decisions, run matching | No | Yes | Yes | Yes |
| Import a roster, roll back | No | No | No | Yes |

Anything in another organisation answers 404, whatever your role.

## From rubric to export

1. **Create a project** under Projects, with a start date and the allocation it needs.
2. **Build the rubric.** Add skills as required or preferred, each with a weight above 0 and, if it
   matters, required months. A duplicate is refused, including through an alias such as 3DX.
3. **Approve and lock** (delivery manager or admin). An empty rubric cannot be approved. An approved
   version never changes; adding a skill starts the next version.
4. **Review evidence.** Open a profile. Passages are listed as **Provisional** and count for nothing
   until you accept them, with a reason. "Check wording" means the sentence contains a word such as
   "without", so read it. Negated and aspirational lines cannot be accepted.
5. **Run matching.** The run pins the rubric, dictionary, algorithm and date.
6. **Read the shortlist.** Open a candidate to see each skill, its weight, its factor and the passage.
7. **Export** CSV or XLSX. The export uses the filters on screen, and its totals match.

## What the labels mean

**Coverage** is the share of this project's weighted criteria backed by accepted evidence. It is not
a probability of success. **Staffing fit** is about timing and capacity only, and never changes
Coverage.

| Label | Factor | Meaning |
| --- | --- | --- |
| Corroborated | 1.0 | You accepted a passage from work experience or a project |
| Verified | 1.0 | A test or interview, recorded with a reason |
| Self-reported | 0.5 | A form claim, or an accepted skills-list mention |
| Inferred | 0.5 | Implied by a more specific skill, for example MQL implies 3DEXPERIENCE |
| Provisional | 0 | Found automatically, or imported, and not yet confirmed |
| Unknown | 0 | Nothing found |
| Excluded | 0 | Negated, aspirational or hidden |

**duration estimated** means months were unknown, so 6 was used.

| Group | Meaning |
| --- | --- |
| Ready for review | Every must-have has Corroborated or Verified evidence |
| Needs clarification | A must-have lacks that evidence, or the file could not be read |
| Unmet must-have | A reviewer recorded that a must-have is not met, with a reason |

Ranks restart in each group. Two people with the same rank are an exact tie; the order between them
means nothing.

## The X-ray panel

The X-ray shows text the file contains but a reader would not see, marked on the rendered page. It
carries zero weight and removed no points. **A flag is not proof of cheating.** Accidental hidden text
exists. Decide with the candidate. These checks catch the tricks we tested, not every possible trick.
Text that is visible but false cannot be detected; verify critical skills by test or interview.

## Fix a mistake

| Mistake | Where to fix it |
| --- | --- |
| Wrong profile details, allocation or availability | Profile → **Edit profile** |
| Wrong project name, start date or allocation | Project → **Edit** |
| Wrong weight, importance or months on a draft rubric | Project → rubric row → **Save** |
| A skill that should not be on a draft rubric | Project → rubric row → **Remove** |
| A rubric that is already approved | Add a skill to start the next version. The approved one never changes |
| A wrong review decision | Profile → the row → **Accept instead** or **Exclude instead**, with a reason. Both decisions stay in the history |
| Wrong import columns | Import batch, before confirming → **Apply mapping** |

Negated, aspirational or instruction-like wording can never be accepted, even after an exclusion.

## Data requests

Candidates can ask for a correction or deletion. Open them from the dashboard. **Mark handled**
records that you dealt with it. It does not delete anything, so do the correction or deletion first.

## After a correction

Run matching again. Old runs keep their scores, and opening one shows what changed later and why.

## Import a roster (admin)

1. Under **Imports**, upload a CSV or XLSX and name its source system.
2. Read the preview. Nothing is written until you confirm the counts.
3. Rows that repeat an ID or lack one are withheld, with the row number and reason.
4. A row with no ID that matches someone by phone, email or name goes to the **review queue**. Choose
   Link to existing, Create new person or Skip. Records never merge automatically.
5. **Roll back** reverses one batch only. A field you edited after the import keeps your edit.
   Profiles the batch created are archived, not deleted.

Imported skills earn nothing until confirmed.
