# Scoring Rule v1.1

The single source of truth for scores. `apps/matching/scoring.py` implements it; the screen, the API
and the exports all read results it produced. It is a pure function of structured records: rubric
skills, evidence records and availability. It never receives résumé text, and no LLM is involved.

Coverage measures how much of **one project's** rubric is backed by accepted visible evidence. It
is not a probability of success, and every screen that shows it says so.

## 1. Evidence factor e

| Evidence state | e | Label | Bucket |
| --- | --- | --- | --- |
| Accepted visible passage in work experience or a project | 1.0 | Corroborated | matched |
| Verified by test or interview, recorded by a staff role | 1.0 | Verified | matched |
| Accepted bare skills-list mention | 0.5 | Self-reported | unresolved |
| Candidate-confirmed form claim | 0.5 | Self-reported | unresolved |
| Inferred from a child skill in the ontology | 0.5 | Inferred | unresolved |
| Auto-match not yet accepted; imported skill not confirmed | 0 | Provisional | unresolved |
| Nothing visible | 0 | Unknown | missing |
| Negated, aspirational, or only in a hidden span | 0 | Excluded | missing |

A skill is credited once, at its highest evidence level. Repetition adds nothing. Inference runs
child to parent only.

## 2. Coverage

    credit(s)   = e(s) × min(1, verified_months(s) ÷ max(1, required_months(s)))
    Coverage    = 100 × Σ weight(s) × credit(s) ÷ Σ weight(s)
    Mandatory   = the same formula over required skills only

Unknown months on credited evidence count as 6 and show the label "duration estimated". Results are
rounded half-up to 2 decimals. Calculation uses exact fractions, so rounding happens once.

## 3. Staffing fit

A separate number that never changes Coverage.

    Staffing fit = 100 × C_cap × C_date

| Term | Internal consultant | External applicant |
| --- | --- | --- |
| C_cap | min(1, (100 − allocation %) ÷ required allocation %) | 1 |
| Effective start | available_from | run date + notice period |
| C_date | 1 if free by project start, falling linearly to 0.5 at 30 days late, 0 beyond 30 days | same |

If capacity, start date or project start is unknown, Staffing fit is **50.00** with the label
"availability unknown" (flag F-13 resolved this way, so unknown never gives 25). The stored run date
is used, never the system date, so reruns reproduce.

## 4. Review groups

Precedence, first match wins:

1. **Unmet must-have**: a reviewer recorded a required skill as unmet, with a reason, and no later
   acceptance overrides it. Recorded as a `ReviewDecision` with outcome `UNMET` and no span.
2. **Needs clarification**: the file is unreadable, or a required skill is anything other than
   Corroborated or Verified.
3. **Ready for review**: every required skill is Corroborated or Verified. A must-have short of its
   required months still counts as met for grouping; the shortfall lowers Coverage.

Flags never change a group, never subtract points and never reject anyone.

## 5. Default sort

Group (Ready, Needs clarification, Unmet) → Coverage desc → Staffing fit desc → Mandatory coverage
desc → missing must-haves asc → profile ID asc. Resource type is shown and filterable, not a sort key
(D-011). Rank restarts in each group and skips after a tie (1, 1, 3). Equal on every key before
profile ID means an exact tie: same rank, and the ID orders the display without implying merit.

## 6. Worked example

Rubric: ENOVIA configuration (required, 5), Migration validation (required, 3), Python automation
(preferred, 2). Required months are 0 and verified months unknown, so each duration factor is
min(1, 6 ÷ 1) = 1. Σw = 10.

| Candidate | ENOVIA (5) | Migration (3) | Python (2) | Σ w·credit | Coverage | Group |
| --- | --- | --- | --- | --- | --- | --- |
| A | Accepted project passage, 1 → 5 | Form claim, 0.5 → 1.5 | Unknown → 0 | 6.5 | **65.00** | Needs clarification |
| B | Accepted project passage, 1 → 5 | Unknown → 0 | Accepted project passage, 1 → 2 | 7 | **70.00** | Needs clarification |
| B + white text | same; hidden spans excluded | Unknown → 0 | same | 7 | **70.00** | Needs clarification |
| B + accepted visible line | same | Accepted, 1 → 3 | same | 10 | **100.00** | Ready for review |

Duration: one skill, weight 10, e = 1, required 12 months. 3 months → 25.00. 12 → 100.00. 36 → 100.00.
Unknown → 6 ÷ 12 → 50.00.

Staffing fit: allocation 20%, required 100% → C_cap 0.80 → 80.00. Allocation 80%, required 50% →
0.40 → 40.00. Start 0, 15, 30, 31 days late → 100.00, 75.00, 50.00, 0.

## 7. Reproducibility

Every `MatchRun` pins rubric version, dictionary version, algorithm version (`1.1`) and run date, and
stores the exact inputs given to the function for each profile. Reproducing a run calls the same
function on those stored inputs. A later change to a profile, rubric or dictionary cannot alter an
old run. Each result also stores why its score differs from the previous run: review decision ID,
skill, old e, new e and the reviewer's reason.
