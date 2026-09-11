# Requirement: Capture Data About Every ADT for a Tracking Database

## Why

Every ADT file is already downloaded and parsed into memory during the scan
(to check for known AA|MRN matches). Since that work is already being done,
we should also capture a record describing each ADT and make it available for
a tracking database — regardless of whether that file matched a known
candidate.

This does not need to be perfect. The goal is: capture what we can, in a
structured way, so we have *something* to load into a tracking database,
rather than nothing. We can refine the fields captured over time.

## Requirement

For **every ADT file successfully parsed** (whether or not it matched a known
AA|MRN pair), write one tracking record capturing what we found in that file.

- This applies to every file that passes download + parse, not just matches.
  (Files that fail download/parse still go to the errors log per the main
  requirements; they do not get a tracking record for now.)
- Output format: a flat CSV / NDJSON file (`06-Results/Output/{DEV|PROD}/`),
  same restart-safe and flush-every-50 rules as the rest of the scan — this is
  not a separate pass, it is captured in the same pass that already reads
  each file.
- This is a new, distinct output alongside candidate coverage (Output A) and
  match detail (Output B) from the main requirements — call it **Output D:
  ADT tracking records**.

### What we capture — v1 (interim, superseded below)

Initial placeholder, kept here for history: `adt_date_time`, `assigning_authority`,
`mrn` — one row per PID-3 identifier found. **Superseded by v2 below**, now
that the real schema has been provided.

### What we capture — v2 (mirrors NYEC_EG_Operational_Database_Schema.csv)

The extract shall mirror the columns defined in
`01-RequirementsAndPlans/NYEC_EG_Operational_Database_Schema.csv`, in the same
order, so this output can be loaded straight into the operational tracking
database with minimal remapping.

**Rule for fields we can't populate:** if a column in that schema requires
something we don't have access to from the raw ADT text alone (an external
crosswalk, an MPID/UPI lookup service, a mapping table maintained elsewhere),
**that column is skipped — omitted from our extract entirely**, rather than
emitted as an always-blank column. (Stated assumption — if you'd rather keep
the column present-but-blank for strict schema parity, say so and we'll
switch.)

#### Columns captured directly from the ADT

| Column | Source | Notes |
|---|---|---|
| `transaction_id` | Composed from other captured ADT values (see below) | No PHI in this ID |
| `message_datetime` | MSH-7 | |
| `facility_oid` | MSH-4, component 2 | Requires parsing MSH-4 (currently we only read MSH-7/9) |
| `facility_name` | EVN-7, component 1 | Requires parsing the EVN segment (not currently parsed) |
| `facility_part2_flag` | PV1-39 | Requires parsing PV1 (not currently parsed) |
| `facility_OMH_flag` | PV1-39 | Same source field as `facility_part2_flag` — schema lists both against PV1-39; captured as-is, flagged as a possible schema ambiguity to confirm |
| `facility_OPWDD_flag` | PV1-39 | Same note as above |
| `source_qe_id` | MSH-5, or MSH-6 if MSH-5 is blank (per schema note: "for originating QE from TechBD-sourced ADTs") | Simple fallback rule; refine if a real sample shows this is wrong |
| `facility_mrn` | PID-3, component 1 | This is the same value as `mrn` in v1 — the field name changes to match the target schema |
| `patient_last_name` | PID-5, component 1 | Requires parsing PID-5 (not currently parsed) |
| `patient_first_name` | PID-5, component 2 | |
| `patient_dob` | PID-7 | |
| `admit_date` | PV1-44 | |
| `discharge_date` | PV1-45 | |
| `encounter_id` | PV1-19 | |
| `account_number` | PID-18 | |
| `chief_complaint` | PV2-3, component 2 | Requires parsing PV2 (not currently parsed) |
| `discharge_disposition_code` | PV1-36 | |
| `diagnosis_code` | DG1-3, component 1 (one per DG1 segment) | See "Diagnosis array" below |
| `diagnosis_code_system` | DG1-3, component 3 | |
| `diagnosis_code_type` | DG1-6, component 1 | |

#### Columns skipped (require a lookup/crosswalk we don't have)

Per the instruction to skip anything not derivable from the ADT itself:

| Column | Why it's skipped |
|---|---|
| `alert_type` | Needs the AlertTypeCrosswalk (Excel) mapping MSH-9 event + PV1-2 patient class — crosswalk not available to this scan |
| `source_qe_mpid` | Needs a UPI/SMPI lookup service call |
| `target_qe_id` | Needs a UPI/SMPI lookup service call |
| `target_qe_mpid` | Needs a UPI/SMPI lookup service call |
| `discharge_disposition_text` | Needs the Zen mapping table for `discharge_disposition_code` → text |

#### Diagnosis array → flat columns

The schema represents diagnoses as a JSON array (one entry per DG1 segment).
Per this project's flat-CSV convention (no nested JSON; pipe-delimited
multi-values), a message with multiple DG1 segments produces pipe-delimited
values in `diagnosis_code` / `diagnosis_code_system` / `diagnosis_code_type`,
aligned by position (item 1 of each list belongs to the same DG1 segment).
Blank if the message has no DG1 segments.

#### `transaction_id` — needs a concrete rule (open assumption)

The schema says only "unique ID composed of concatenated ADT values, no PHI."
Proposed rule, pending confirmation: concatenate `message_datetime` +
`facility_oid` + `encounter_id` (falling back to available fields if any are
blank) — none of those three are PHI on their own. Flag if a different
construction is expected.

#### Granularity change: one row per ADT message, not per PID-3 identifier

v1 wrote one row per PID-3 identifier found. The v2 schema is transaction/
encounter-level (`transaction_id`, `encounter_id`, admit/discharge dates,
diagnoses) — that's **one row per ADT message**, not per identifier. Where a
message's PID-3 repeats multiple identifiers, `facility_mrn` captures
component 1 of the **first** PID-3 repeat only (the schema has a single MRN
column, not a list) — stated assumption, confirm against a real sample.

#### New final column — match against the missing-consent MRN list

At the **end of the row** (after all schema columns above), add one more
column not present in the operational schema:

- `found_in_missing_mrn_list` — `yes` / `no`. Set to `yes` if this message's
  patient identifier matches one of the ~35,000 known AA|MRN pairs (people
  NOT added to the Opt-Out/consent database) — the exact same matching logic
  already used for Output A/B in the main scan requirements (PID-3 component
  1 = MRN, component 4 = assigning authority, both normalized).
- Note: the assigning authority (PID-3 component 4) is used internally to do
  this match even though the operational schema has no AA column of its own
  — it's not exported as a column, it's only used to decide this flag.

### Design note: keep this decoupled from the schema

Implemented as its own module (`capture_adt_record.py`) with a single
function that takes the already-parsed ADT data and returns a flat dict (or
list of dicts). If the schema changes again, only that function's output
mapping needs to change — the scan/restart/parallelism logic is untouched.

### Loading into the actual tracking database

Out of scope for this requirement: how the CSV output gets loaded into the
operational tracking database (separate load step, Athena, or direct DB
load) is a follow-up decision. This requirement only covers *capturing* the
data during the scan.

## Open Items

1. **Parser expansion needed.** `parse_adt.py` currently only reads
   MSH-7/9 and PID-3. v2 requires parsing MSH-4/5/6, EVN-7, PID-5/7/18,
   PV1-2/19/36/39/44/45, PV2-3, and DG1-3/6. This is a real code change, not
   just a mapping change in `capture_adt_record.py`.
2. **Confirm on a real ADT sample once available:** the `transaction_id`
   construction rule, the PV1-39 → three separate flag columns mapping, and
   the "first PID-3 repeat only" assumption for `facility_mrn`.
3. Decide whether skipped (lookup-dependent) columns should be omitted
   entirely (current assumption) or emitted blank for strict schema parity.
