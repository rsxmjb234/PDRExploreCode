# Measles Candidate Detection — Guidance for Implementation

**Status:** Framework / "end in mind" mockup only. No real data, no real code. This document exists so
that the problem can be handed to a developer (human or AI) and implemented correctly without re-litigating
the basic design decisions already made here.

**Audience:** Whoever (or whatever) builds the real version of this explore. Read this fully before writing
code. If you are an AI assistant picking up this task, treat this file as your spec — the mockups referenced
below show the *shape* of the deliverable, not the real logic (there is no real logic yet).

---

## 1. The One-Sentence Problem

**Find patients whose SHIN-NY data (TRN, ADT, CCD, lab/ORU) shows a pattern consistent with measles, where
no reportable-condition report for measles exists for that patient — i.e., find the unreported hints, not
the already-reported cases.**

## 2. Why This Exists (Context)

- New York State has, at times, declared public health emergencies / heightened alerting around measles
  (see the governor announcement saved alongside this folder for the real-world trigger behind this idea).
- Measles is a **mandated reportable condition**. Confirmed cases already flow to public health through
  that channel. **We are explicitly NOT interested in those.**
- The gap we're trying to close: a patient can have a strongly suggestive clinical picture — fever, rash,
  the "three C's" (cough, coryza, conjunctivitis), a measles-specific lab order — and that picture can exist
  in SHIN-NY data for days before (or without ever) triggering a formal report. SHIN-NY's unique value is
  seeing **across sources** (a lab order here, an ED visit there, a note somewhere else) in a way no single
  EHR does.
- This is explicitly framed as **candidate identification for public-health follow-up**, not diagnosis.
  Nothing in this tool should ever claim a patient "has measles."

### 2a. Realistic Scope — What SHIN-NY Actually Sees

This is one way SHIN-NY *might* be able to help, scoped accurately for an audience that may include people
outside the immediate team:

- PDR centralizes CCDs from **over 2,000 contributing sources** — roughly **200 hospitals** and
  **1,000 lab sources**, plus thousands of non-hospital practices (primary care, pediatrics, urgent care,
  and more).
- **We do not have everyone's data, and we will not catch every potential case.** This is not — and must
  never be described as — a comprehensive surveillance system.
- What we believe is more modest and more defensible: because we see across thousands of non-hospital
  sources that individually have no visibility into each other, we think we can surface a **non-zero
  number of candidates earlier** than they would otherwise be found — potentially before a positive
  diagnosis is reached anywhere else in the system.
- **The value proposition in one sentence:** not "we will catch every measles case," but "we can catch
  some cases earlier than anyone else currently can, because of where we sit in the data." Any real
  implementation should be built — and evaluated — against that specific, modest claim, not against a
  claim of comprehensive coverage. Overstating coverage (explicitly or implicitly) is a credibility risk
  for the whole SHIN-NY, not just this exploration.

## 3. Scope Boundaries (Read This Twice)

| In Scope | Out of Scope |
|---|---|
| Patients with measles-suggestive data | Diagnosing, confirming, or denying measles for any patient |
| Surfacing candidates for human/public-health review | Automated already-reported exclusion (v1 has none — see 2b) |
| Combining signals across TRN, ADT, CCD, and lab (ORU) | Relying on a single data type or a single code match |
| A ranked/tiered candidate list + a letter per candidate | Automated reporting to the state (a human decides whether to report) |

If you find yourself writing code that outputs "Patient X has measles," stop — that's out of scope. The
output is always "Patient X has signals worth a human looking at."

### 3a. v1 Does Not Filter Out Already-Reported Cases

An earlier version of this plan assumed v1 would exclude already-reported cases. That is now explicitly a
**phase-2 feature** (see 2b below), not part of a first implementation. v1 surfaces candidates purely on
signal strength. A reviewer may see a case that public health is already aware of and working — that's an
accepted limitation of v1, not a bug to engineer around before shipping.

## 4. The End in Mind (What "Done" Looks Like)

Four deliverables, in this folder structure (mockups already exist at these paths — treat them as the
visual/structural target, not as real data or real logic):

```
explore/Measles-PotentialCases/
  measles-candidate-detection.html      <- the explore write-up (methodology, open questions, links to the samples below)
  measles-candidate-dashboard.html      <- the "end in mind" patient-level dashboard (mockup, fictitious data)
  measles-epi-report.html               <- the epidemiologic summary report (epi curve, line list, breakdowns)
  letters/
    measles-letter-<lastname>-<firstname>.html   <- one letter per candidate (mockup exists for Rivera, Mateo)
  GUIDANCE.md                           <- this file
```

### 4a. The Dashboard

A table of candidates, each row showing:

- **First, Last** (as a link to that patient's letter)
- **DOB**
- **Location of most recent encounter** (facility name + city/state, plus the date/type of that encounter)
- **Primary signals** (short pills/tags — e.g. "Measles IgM ordered", "Fever + rash", "Unvaccinated flag")
- **Concern level** (e.g. HIGH / MODERATE) — driven by how many independent signals line up, with a
  measles-specific lab order weighted most heavily

Plus summary KPIs at the top: total candidates, count by concern tier, count already excluded as
already-reported (should always be visible as a QA/sanity check — i.e., prove the exclusion step ran),
and the number of data types scanned.

See `measles-candidate-dashboard.html` for the mockup layout and styling.

### 4a-1. The Epidemiologic Summary Report

This is the deliverable aimed at an epidemiologist reviewing the candidate set, not just a case worker
looking up one patient. It must give a population-level view, not a flat list:

- **Epi curve** — candidate count by most-recent-encounter date, so a reviewer can see at a glance whether
  candidates cluster in time or are scattered.
- **Line list** — the standard outbreak-investigation format: one row per candidate with age/sex, encounter
  date, county/facility, key signals, vaccination status (if known), which data sources contributed a
  signal, report-on-file status, and concern level.
- **Geographic summary** — candidate counts by county/region, to spot geographic clustering.
- **Age distribution and vaccination status** — with an explicit callout when vaccination status is
  unknown for most candidates (a real gap, not something to paper over).
- **Signal source breakdown** — which data types (TRN/ADT/CCD/Lab) contributed a signal, across all
  candidates. This is the evidence for the exploration's core premise: no single data type catches everyone.
- A **"reading this responsibly" section** restating scope limits (not statewide surveillance, not a
  diagnosis, candidates only) so the report cannot be misread as more authoritative than it is.

See `measles-epi-report.html` for the mockup. The candidate dashboard (4a) and this report should
cross-link to each other and back to the explore write-up — do not let a reader land on one without a way
to find the others.

### 4b. The Per-Patient Letter

One letter per candidate, modeled on the same letter pattern used for other PDR data-quality explorations
(see `../42cfr-sample-qe-letter.html` and `../mpi-overlay-sample-qe-letter.html` for sibling examples of
this letter pattern). Required sections:

1. **Patient Identity (for lookup)** — table with:
   - First name
   - Last name
   - Date of birth (and computed age)
   - Address
   - **SOURCE | MRN** (critical — this is the lookup key a reviewer will use to pull the real record)
   - Qualified Entity
2. **Why We Are Flagging This Person** — plain-language summary of the clinical pattern and the fact that
   no matching report exists.
3. **What We Found and Where** — a table: signal, data type (TRN/ADT/CCD/Lab), where in that data type,
   and the specific detail (code, date, note text, etc.).
4. **Methodology Used** — the same methodology described in `measles-candidate-detection.html`, restated
   briefly and linked back to it. Must explicitly state the already-reported-exclusion step ran for this
   patient.
5. **Suggested Next Step** — review at the source using SOURCE|MRN, confirm clinically, and report if
   warranted. Never instructs the system to report automatically.
6. A **"this is a candidate, not a determination"** disclaimer, every time, without exception.

See `letters/measles-letter-rivera-mateo.html` for the full mockup (fictitious patient, fictitious data).

### 4c. Fictitious Data Rules (apply to all mockups/demos)

- Every mockup page must carry a visible "fictitious data" banner.
- Never reuse a real patient's identity, even partially, for demo data.
- Keep demo addresses, MRNs, and facility names obviously synthetic but realistic in *shape* (so the layout
  reads correctly).

## 5. The Four Data Types and What to Look For (First-Pass Signal Catalog)

This is a **starting point**, not a finished code set. Expect to validate against real feeds and revise.

| Data Type | Where to Look | Example Signals |
|---|---|---|
| **Lab (ORU)** | Result observations (OBX) | Measles IgM / IgG serology; measles PCR/RNA; rubeola testing |
| **CCD** | Problem list, encounter diagnoses, observations | ICD-10 `B05.x`; SNOMED measles findings; "febrile rash illness," "rule out measles," "viral exanthem" |
| **ADT** | Admit/visit reason, diagnosis segments | ED/inpatient visits for fever + rash; isolation/airborne-precaution flags; pediatric febrile rash presentations |
| **TRN** | Discharge summaries / transition notes | Narrative mentions of measles, rubeola, Koplik spots, maculopapular rash + fever + coryza/conjunctivitis |

**Clinical shorthand worth encoding as a rule-of-thumb weight:** classic measles = fever + the "three C's"
(cough, coryza, conjunctivitis) → followed by a maculopapular rash, sometimes with Koplik spots. A
*combination* of these across data types is a stronger signal than any single code match in one source.

## 6. Scoring / Concern-Level Approach (Design Intent, Not Final Algorithm)

- Score per patient, not per document. Multiple documents/encounters for the same patient should roll up.
- Weight a **measles-specific lab order or result** (IgM/PCR) higher than a non-specific sign (e.g., "rash").
- Independent signals from **different data types landing in the same encounter window** should raise
  concern more than the same signal repeated once.
- Produce at least two concern tiers (e.g., HIGH / MODERATE) so a reviewer can triage. Do not produce a
  false sense of precision — this is pattern-matching, not a validated clinical score.
- **Always exclude patients with a matching reportable-condition report for measles before scoring/surfacing
  them.** This exclusion step is the whole point of the tool and must be auditable (show its effect in the
  dashboard KPIs, per Section 4a).

## 7. Open Questions the Implementer Must Resolve

These were deliberately left open in the explore write-up (`measles-candidate-detection.html`). Don't guess
silently — flag your assumptions explicitly if you resolve them without stakeholder input:

1. **Sampling** — recent window statewide, or focused on regions with known outbreak activity?
2. **Code reality check** — which measles LOINC/SNOMED/ICD-10 codes actually appear in real PDR feeds vs.
   which ones we're assuming exist? (Don't trust Section 5 as ground truth — validate against real data.)
3. **Signal combination** — exact method for combining weak signals across TRN/ADT/CCD/lab into one score.
4. **Report matching** — how do we reliably determine "already reported"? Matching a data hint to a
   submitted reportable-condition report (by patient + encounter + date) is itself a nontrivial problem —
   do not assume a trivial join exists.
5. **False-positive tolerance** — what's acceptable for a list meant for public-health follow-up? Too loose
   wastes reviewer time and erodes trust in the tool; too tight misses real cases.
6. **Distribution** — who receives the candidate list, in what form, how often, with what access controls?
   (This likely has privacy/PHI handling implications beyond this document's scope — loop in Privacy &
   Security before anything touches real data.)

## 8. Explicit Non-Goals

- This is **not** a replacement for mandated reporting. It supplements it by finding what wasn't reported.
- This is **not** a diagnostic tool. No output should be interpreted or presented as a diagnosis.
- This is **not** meant to auto-notify the state or any external party. A human reviews every candidate.
- This is **not**, at this stage, meant to run against real PHI. Everything built so far is a mockup with
  fictitious data; moving to real data requires explicit sign-off and privacy/security review first.

## 9. Relationship to Sibling Explorations

This follows the same "basic explore loop" used elsewhere in this project (see `explore.html` and
`explore/42cfr-candidate-identification.html`, `explore/mpi-overlay-detection.html` for sibling patterns):

1. Decide on a sample methodology.
2. Decide what to look for.
3. See what we find.
4. Loop 2 and 3 until the results feel trustworthy.

The letter format and "candidate, not determination" framing are intentionally consistent with the 42 CFR
and MPI overlay explorations so that reviewers across different explore topics see a familiar pattern.

## 10. Definition of Done for a Real Implementation

A real (non-mockup) version of this is done when:

- [ ] Real signal definitions have been validated against actual PDR data (not just assumed from Section 5).
- [ ] The already-reported exclusion logic is implemented, tested, and its effect is visible/auditable.
- [ ] A scoring/tiering approach exists and has been sanity-checked (does it produce an unreasonable number
      of candidates? does it miss obvious cases from historical data, if any are available for testing?).
- [ ] Per-patient letters generate correctly with accurate SOURCE|MRN for lookup.
- [ ] Privacy & Security has reviewed the approach before it touches any real patient data.
- [ ] The "candidate, not determination" framing is preserved in every surface (dashboard, letter, any
      future reporting/export).
