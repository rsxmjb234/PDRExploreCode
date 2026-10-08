# Technical Plan: Measles Candidate Detection — v1 Implementation

**Relationship to GUIDANCE.md:** that document is the spec — read it first. This document is the
engineering plan for turning it into real, runnable code: what gets built, in what order, modeled on
which existing code in this repo, and what v1 deliberately does NOT attempt yet.

## 1. What v1 Actually Builds

Per GUIDANCE.md Section 4, the full "end in mind" is four deliverables (dashboard, epi report, per-patient
letters, write-up). **v1 builds the data pipeline that produces the candidate list and per-patient
findings** — the raw material those deliverables are generated from. It does not yet build the HTML
dashboard/epi-report generators; those are a follow-on step once we've seen what real candidates look like
(the mockups already show the target shape — see Section 9, Next Steps).

v1 scope, concretely:
1. SQL to find CCD and TRN candidates (recent-window, statewide) — see Section 3.
2. A scoring engine that downloads each candidate file, scans it for measles signals (per GUIDANCE.md
   Section 5), and writes one flat JSON record per file (modeled on `score_ccd.py` in 42CFRQualityCheck).
3. A per-patient aggregator that rolls up signals across all files/data-types for the same patient into one
   candidate record with a concern tier (modeled on `aggregate_sources.py`).
4. The same restart/retry/flush resiliency pattern used everywhere else in this repo
   (`findandsaveEHRfromCCD-EntireCCD.py` is the reference implementation).

## 2. Explicit Scope Reduction — ADT and Lab (ORU) Are Deferred, TRN Is Free-Text Only

**Superseded by a direct user instruction mid-build.** This section originally deferred only Lab/ORU; the
scope has since been narrowed further:

- **ADT is out of scope entirely for this pass.** No `check_adt_measles.py`, no ADT candidate SQL, no ADT
  branch in `score_candidate.py`. (An ADT checker and SQL file were drafted and then deliberately removed
  once this instruction arrived — not left in as dead/unused code.)
- **TRN is checked on FREE TEXT ONLY.** `check_trn_measles.py` scans only the narrative lines pulled from
  OBX-5/NTE-3. It does not look at any coded field (no DG1 diagnosis check), even where one happens to be
  present in a TRN file's content.
- **CCD is checked on BOTH coded data AND free text** — this is unchanged from the original plan: ICD-10
  B05.x / SNOMED measles concepts in Problems/Encounters, plus the keyword/three-C's text scan over
  display text and section narrative.
- **Lab/ORU remains deferred** (original Section 2 rationale still applies: no existing precedent in this
  codebase for parsing raw ORU, no sample file examined yet — see below).

**Why ADT was dropped:** explicit user instruction ("for this pass, only focus on CCD's and TRN's... ignore
ADT's and labs"). No code-quality or data-availability reason — this is a scoping choice, not a technical
finding, and ADT support should be straightforward to re-add later by restoring the deleted
`check_adt_measles.py`/`find_adt_measles_candidates.sql` pattern (same shape as the CCD/TRN checkers already
built) once this pass's results have been reviewed.

**Why TRN is free-text only:** explicit user instruction, consistent with the pre-existing TRNMessageMix
finding that TRN content type is not reliable/known ahead of time (it's PDR's term of art for a raw feed,
not a real HL7 message type) — so building a coded-field check against TRN's DG1 segment, when a given TRN
file might not even carry one in any consistent way, risks the same "guessing at a layout we haven't
confirmed" mistake Section 2 already flagged for Lab/ORU.

**Why Lab/ORU is still deferred:** every other project in this repo (FindEHR, 42CFRQualityCheck,
DataCodingQualityStandards) finds its candidates by scanning CCD files via SQL + S3, and TRNMessageMix
already has a working "find TRN candidates" SQL pattern to copy. There is no existing precedent anywhere in
this codebase for locating or parsing raw ORU lab messages, and no sample ORU file has been examined yet.

v2 should add ADT support, ORU scanning, and/or TRN coded-field checking once each one has a real sample
file examined and its layout confirmed — the same way `parse_adt.py` in ADTScanForCandidates was only
expanded to new segments after the real schema was confirmed.

## 3. Candidate SQL (Section 02-SupportingSQL)

Two SQL files, one per in-scope data type, each modeled on the existing patterns in this repo:

- `find_ccd_measles_candidates.sql` — modeled on `Shared/findcandidatesforexplore.sql`. CCD files only,
  recent window (default last 10 days — adjustable, see GUIDANCE.md open question #2), statewide (all
  sources), capped per assigning authority so no single huge source dominates the sample.
- `find_trn_measles_candidates.sql` — copied from TRNMessageMix's existing
  `find_trn_candidates.sql` (same TRN-in-path filter), window adjusted to match this project's recent-window
  intent instead of TRNMessageMix's 10-20-day-old window.

(`find_adt_measles_candidates.sql` was drafted and then deleted — see Section 2.)

**Per GUIDANCE.md Section 3a (the explore-loop step 1):** recency matters far more than depth — these
queries intentionally do NOT sample years of history. Default window and per-source cap are both named
constants at the top of each SQL file so they're easy to find and adjust without re-deriving the query.

**Window anchor — most recent inventory, not wall-clock `current_timestamp` (explicit user instruction):**
both SQL files first compute `MAX(last_modified_date)` from the inventory table as an anchor, then look
back `RECENT_WINDOW_DAYS` (10, for this POC) **from that anchor**, not from wall-clock now. Rationale: if
the inventory table lags behind real time by even a day, `current_timestamp - interval '10' day` silently
scans a window that doesn't line up with the actual most-recent data present — defeating the entire point
of a recency-first SQL for an exploration where "time matters." Both files originally used
`current_timestamp` directly; this was corrected per direct instruction mid-build. The anchor subquery
costs one extra scan of the production buckets' `last_modified_date` column — acceptable for this POC's
data volume (same kind of relative-date tradeoff TRNMessageMix's SQL already flagged and proceeded with); a
future revision could swap to a partition-pruned `MAX(dt)` anchor if this becomes a real cost concern.

**Open item (GUIDANCE.md Section 7, Q1):** statewide vs. regionally focused is explicitly left open. v1
ships statewide (matches the explore write-up's step-1 answer in `measles-candidate-detection.html`); a
future revision could add a county/region filter if outbreak activity concentrates geographically.

## 4. Signal Definitions (Section 03-SupportingCode/checkers)

One checker module per in-scope data type, mirroring the `checkers/` package structure in 42CFRQualityCheck
(`check_diagnoses.py`, `check_medications.py`, etc.) — each takes a parsed document and returns a dict of
signal hits plus human-readable finding strings (same `top_sud_findings`-style pattern already proven out in
42CFRQualityCheck's letter generator).

- `check_ccd_measles.py` — CODED DATA + FREE TEXT. Scans Problems/Encounters sections for measles-related
  codes AND display/narrative text:
  - ICD-10: `B05` and all `B05.x` children (measles with/without complications)
  - SNOMED: measles disease and finding concepts (e.g. `14189004` Measles)
  - Text fallback (problem/encounter display text + section narrative, case-insensitive substring):
    "measles", "rubeola", "febrile rash illness", "rule out measles", "viral exanthem", "koplik"
- `check_trn_measles.py` — FREE TEXT ONLY (see Section 2). Scans discharge-summary/transition-note
  **narrative text only** (OBX-5/NTE-3, extracted by `parse_trn.py`) for the same keyword set, plus the
  clinical-shorthand pattern below. Does not check any coded field.

(`check_adt_measles.py` was drafted and then deleted — see Section 2.)

**Clinical shorthand rule (GUIDANCE.md Section 5, "three C's"):** a dedicated small helper
(`three_cs_pattern.py`, shared by both checkers) does a simple co-occurrence text scan for fever +
(cough OR coryza OR conjunctivitis) + rash within the same note/section — this is intentionally crude
substring matching, not NLP, consistent with GUIDANCE.md's framing that this is "pattern-matching, not a
validated clinical score."

**All code lists above are starting points per GUIDANCE.md Section 7, Q2 — not validated against real PDR
data yet.** Each checker module keeps its code/keyword lists as a clearly-labeled constant at the top of the
file specifically so they're easy to find and revise once real data is examined (same convention
42CFRQualityCheck used for its SNOMED/ICD-10 lists, which were revised multiple times after looking at real
DEV data).

## 5. Scoring (Section 03-SupportingCode/score_model.py)

Per GUIDANCE.md Section 6:

- Score is per **patient**, not per document — multiple documents/encounters for the same patient roll up
  (see Section 6, aggregator).
- A measles-specific **lab order or result** would be weighted highest, but since Lab/ORU is deferred (see
  Section 2), v1's highest-weighted signal is a **measles-specific diagnosis code** (ICD-10 `B05.x` or the
  SNOMED measles concept) hit in a CCD diagnosis segment — the only in-scope data type that carries a coded
  field this pass (TRN is free-text only, ADT is out of scope — see Section 2).
- The "three C's + rash" co-occurrence pattern (Section 4) is a secondary, moderate-weight signal — stronger
  than a single keyword hit, weaker than a coded diagnosis.
- A single bare keyword hit (e.g. "rash" alone, with no code and no three-C's co-occurrence) is the weakest
  signal tier.
- **Independent signals from different data types in the same encounter-date window raise concern more than
  the same signal repeated** (GUIDANCE.md Section 6, bullet 3) — the aggregator checks data-type diversity
  per patient, not just signal count, before assigning HIGH.
- Two tiers only for v1: **HIGH** (coded diagnosis hit, or three-C's pattern corroborated by a second data
  type) and **MODERATE** (everything else that scored above zero). This matches GUIDANCE.md Section 6's "at
  least two concern tiers" instruction without inventing a third tier not asked for.

## 6. Per-Patient Aggregation (Section 03-SupportingCode/aggregate_candidates.py)

Modeled on `aggregate_sources.py`, but the grouping key changes: 42CFRQualityCheck rolls up by
assigning_authority (a **source**); this project rolls up by **patient** (per GUIDANCE.md Section 6, bullet
1). Patient identity key = normalized (assigning_authority, MRN) pair — same normalization approach already
proven out in ADTScanForCandidates' `load_lookup.py` (`normalize_aa`/`normalize_mrn`), reused here rather
than re-invented.

Per GUIDANCE.md Section 3a, v1 explicitly does **not** implement the already-reported exclusion step — that
is a named phase-2 feature, not a v1 gap. The output format still reserves a column for it (see Section 7)
so phase 2 is a column-fill, not a schema change.

## 7. Output Columns (two outputs, matching the dashboard/letter inputs GUIDANCE.md Section 4 will need)

**Output A — `candidate_findings.csv`** (one row per file scanned, every file, match or not — same
"capture everything we touch" philosophy as ADTScanForCandidates' Output D):
`path, bucket, data_type (CCD|TRN this pass), assigning_authority, qe, mrn, patient_last_name,
patient_first_name, patient_dob, encounter_date, encounter_location, signal_type, signal_detail
(code/text/section), concern_contribution`

**Output B — `patient_candidates.csv`** (one row per patient, the primary deliverable — same "rollup is the
deliverable, not the per-file list" lesson from ADTScanForCandidates' Output A):
`assigning_authority, qe, mrn, patient_last_name, patient_first_name, patient_dob, most_recent_encounter_date,
most_recent_encounter_location, data_types_contributing (pipe-delimited), signal_summary (pipe-delimited,
human-readable), concern_level (HIGH|MODERATE), already_reported_status (always "NOT CHECKED - v1" — see
Section 6), source_file_count`

Column names deliberately echo the field types the GUIDANCE.md mockups already show (dashboard columns in
Section 4a, letter sections in Section 4b) so a future HTML-generator step is a straightforward mapping, not
a redesign.

## 8. Resiliency (applies identically to every script that touches S3)

Exactly the pattern in `findandsaveEHRfromCCD-EntireCCD.py`, reused rather than reinvented:
- Restart-safe: load already-processed paths from the existing output CSV at startup, skip them.
- Flush every 200 processed files (this repo's default; no crash history reported for this project yet, so
  no reason to tighten to 50 the way ADTScanForCandidates did).
- `max_files` applied AFTER restart-filtering, so each run advances through the next batch.
- DEV/PROD profile pattern identical to every other project (`student1` / `nyec.ccda.learning` for DEV).

## 9. Explicitly Deferred (Not Gaps — Named Follow-Ups)

- ADT scanning entirely, for this pass (Section 2 — explicit user instruction, not a technical finding).
- TRN coded-field checking (Section 2 — TRN is free-text only this pass).
- Lab/ORU scanning (Section 2).
- Already-reported exclusion (GUIDANCE.md Section 3a — named phase-2 in the spec itself).
- HTML dashboard/epi-report/letter generation (GUIDANCE.md Section 4) — v1 produces the CSV data those are
  built from; wiring that data into the existing mockup HTML templates is a follow-on step once real
  candidate data exists to look at.
- Validating signal definitions against known/reported cases (GUIDANCE.md Section 2a's "explore loop" step
  3) — requires a real list of confirmed cases to validate against, which doesn't exist yet in this repo.
- Fictitious-data mockups already exist in this folder for the dashboard/epi-report/letters — v1 does not
  touch those; they remain the "end in mind" reference until the HTML-generation follow-on step above.

## 10. Build Order

1. `config.py` — DEV/PROD profiles (copy pattern from ADTScanForCandidates/FindEHR).
2. `normalize.py` — normalize_aa/normalize_mrn (same approach as ADTScanForCandidates' `load_lookup.py`,
   reimplemented locally rather than cross-imported — see Section 6) + text-matching helpers.
3. SQL files (Section 3) — CCD and TRN only.
4. `checkers/` package (`check_ccd_measles.py`, `check_trn_measles.py`) + `three_cs_pattern.py` (Section 4).
5. `score_model.py` (Section 5).
6. `score_candidate.py` — per-file worker (modeled on `score_ccd.py`), dispatches to the right checker by
   data type: CCD (XML) or TRN (HL7v2 free text via `parse_trn.py`). No ADT branch this pass.
7. `run_pipeline.py` — main driver: reads candidate CSV(s), restart/flush loop (Section 8), writes Output A.
8. `aggregate_candidates.py` — reads Output A, writes Output B (Section 6).
9. `cleanup_run.py` — same convention as every other project.
