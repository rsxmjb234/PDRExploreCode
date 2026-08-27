# Plan: 42 CFR Part 2 Misrouted Source Detection — Candidate Identification

## Goal

Identify Assigning Authorities whose CCD data is disproportionately
substance-use-related — indicating they MAY be a 42 CFR Part 2 program
that is misrouted into the general S3 bucket instead of the
protected 42 CFR bucket. These sources become CANDIDATES FOR RESEARCH —
not determinations.

This is a candidate identification tool. The goal is to build a list of
sources that warrant further research by the Qualified Entity. Deference
should be given to INCLUSION on the candidate list: it is better to flag a
source that turns out to be fine (the QE calls the source and confirms it's
not Part 2) than to miss one that is actually misrouted. The cost of a false
positive is a phone call; the cost of a false negative is a compliance gap.

The QE will then contact the source, perform further research, and make the
actual determination of Part 2 status. Our job is to surface the signal and
explain why it warrants a conversation — not to judge or conclude.

The priority target is the facility that was sent to PDR like a standard 'bucket' 
but whose clinical content shows it may be operating (in whole
or in part) as a 42 CFR Part 2 program. An obviously-named recovery center
with high SUD content is a confirmation case, not the risk case — it's
already presumably known and routed correctly (or already a known misroute).
The risk case is a source, or a specific unit within an
otherwise-general facility, quietly contributing Part 2-covered data through
the standard pipeline.


Our approach will be to run this code against the 42 CFR identified soruces to 
ensure it appropriately flags them as 42 CFR.
And the refine code using that 'known to be 42 CFR" to inform the quality of this code.
then modify this code, based on that discovery.
Once we have a good sense that our code identifies 42 CFR facilities that were submitted
into PDR as 42 CFR reliabley, then we will run the code against non-42 CFR facilities
to find candidates.

## Regulatory Framing: What Makes Something a "Part 2 Program"

42 CFR Part 2 applies to a "program" — federally assisted (nearly all
programs qualify: Medicare/Medicaid, tax-exempt status, DEA registration,
etc. count as federal assistance) — that holds itself out as providing SUD
diagnosis, treatment, or referral for treatment. Two important nuances:

1. **A general facility can contain a Part 2 "identified unit."** A hospital
   overall is not a Part 2 program, but its dedicated detox floor or
   behavioral health/addiction unit can be — even though the hospital's
   overall CCD volume looks mostly like ordinary acute care. This is the
   scenario most likely to be "contributed as a standard facility."
2. **Not all SUD-adjacent care makes something a Part 2 program.** A primary
   care practice where the physician has a buprenorphine waiver and
   occasionally treats OUD as part of general practice is explicitly NOT
   automatically a Part 2 program under the regs, unless the practice is
   identified/held out as an SUD program. Methadone is different: it can
   only be dispensed for OUD through a DEA-certified Opioid Treatment
   Program (OTP), so methadone dispensing is a much stronger signal than
   buprenorphine prescribing.

**Scope limitation:** "Federally assisted" and "holds itself out" are legal/
administrative facts, not something visible in CCD clinical content. This
tool detects a clinical content *pattern* consistent with Part 2 program
activity — it is an investigative signal for compliance to review, not a
legal determination of Part 2 status.

The result is a report on sources where the PDR will follow up with the submitting Qualified entity and ask them to research the sources to include why for each source we believe research is approporiate.  

As such there are 2 outputs we need
A) JSON that we can use athentna to understand patterns.
B) HTML for each source in the form of a letter to the QE explainign what we did, in some detail, and why the data suggests this source may be a 42 CFR


## Reference Architecture (same as FindingEHR)

```
[Athena SQL]  →  [Candidate CSV]  →  [Python Scorer]  →  [Per-CCD JSON]  →  [Report]
     |                                      |
     |  findcandidatesforexplore.sql        |  Downloads CCD from S3
     |  (same query, filter to CCD)         |  Parses XML sections
     |                                      |  Counts SUD indicators
     |                                      |  Writes 1 JSON per CCD
```

Same pattern as `findandsaveEHRfromCCD-EntireCCD.py`:
- DEV/PROD profile switch at top
- Candidate CSV as input (bucket, key, qe, assigning_authority)
- Multi-bucket support
- Restart capability (skip already-scored files)
- Flush progress to disk
- max_files limit


## What We Score Per CCD

For each CCD, count total clinical entries and how many are SUD-related.

### SUD Indicators to Detect:

| Category | Where in CCD | What to Match |
|----------|-------------|---------------|
| SUD Diagnoses | Problems section (`value` codes) | ICD-10 F10–F19 (any code starting with F1) |
| MAT Medications | Medications section (`manufacturedMaterial/code`) | Buprenorphine, methadone, naltrexone, naloxone, acamprosate, disulfiram (by RxNorm code or displayName) |
| SUD Encounters | Encounters section (`code`) | Detox, IOP, residential treatment, OTP visits (by SNOMED/CPT code or displayName keywords) |
| SUD Procedures | Procedures section (`code`) | Urine drug screens, SBIRT, addiction counseling (by CPT/SNOMED code or displayName keywords) |
| Facility Name | Custodian org name | Contains: "recovery", "addiction", "substance", "methadone", "opioid treatment", "behavioral health" — see "Facility Name Logic" below for how this is actually used |
| Service Location | componentOf/encompassingEncounter/location/healthCareFacility/location/name | The specific unit/floor/department (e.g., "Outpatient Addiction Services", "Detox Unit Floor 3"). Distinct from custodian which is the overall organization. |


### Specific Code Matches:

**ICD-10 (Problems):**
- F10.x = Alcohol-related disorders
- F11.x = Opioid-related disorders
- F12.x = Cannabis-related disorders
- F13.x = Sedative-related disorders
- F14.x = Cocaine-related disorders
- F15.x = Stimulant-related disorders
- F16.x = Hallucinogen-related disorders
- F17.x = Nicotine dependence (exclude — not Part 2)
- F18.x = Inhalant-related disorders
- F19.x = Other psychoactive substance disorders

**MAT Medications — NOT equal weight (by displayName keyword or RxNorm code):**

Methadone is only legally dispensed for OUD through a DEA-certified Opioid
Treatment Program, so it is a much stronger Part 2 signal than the other
MAT drugs, which are also used in ordinary office-based practice:

- Strong signal (OTP-only): methadone (when dispensed/administered, not
  just listed on a med rec list — see encounter-tied rules below)
- Moderate signal (office-based, common outside Part 2): buprenorphine,
  suboxone, subutex, sublocade, naltrexone, vivitrol
- Weak/supportive signal only (not indicative alone): naloxone, narcan
  (increasingly prescribed broadly as harm-reduction, not SUD-program-specific),
  acamprosate, campral, disulfiram, antabuse

**OTP/SUD Billing Codes (HCPCS/CPT) — prefer these over keyword matching
when present, since they are unambiguous:**

| Code | Description |
|------|-------------|
| H0020 | Methadone administration/dispensing |
| S0109 | Methadone, oral, dispensed |
| H0015 | Intensive outpatient treatment (substance use) |
| H0005 | Group counseling, substance use |
| H0004 | Individual counseling, substance use |
| H0001 | Alcohol/drug assessment |
| G2067-G2078 | Medicare OTP bundled payment codes (weekly MAT bundles) |
| 99408/99409 | SBIRT - alcohol/substance screening and brief intervention |
| 80305-80307 | Drug test presumptive/definitive (context-dependent, weak alone) |

**Encounter/Procedure Keywords (displayName) - used only when a billing
code match isn't available:**
- detox, detoxification
- intensive outpatient, IOP
- residential treatment
- opioid treatment program, OTP
- substance abuse, substance use
- addiction counseling
- drug screen, urine drug, UDS


## Output JSON Per CCD

IMPORTANT: JSON must be Athena-friendly:
- Flat structure only — no nested objects or arrays (Athena struggles with these)
- One JSON object per line (newline-delimited JSON / NDJSON) OR one file per record
- No arrays inside fields — use pipe-separated strings if multiple values
- Keep field names simple, lowercase, no special characters
- Include the CCD creation date (from the CCD header) for time-based analysis

```json
{
  "assigning_authority": "2.16.840.1.113883.3.1042.5.1",
  "qe": "healthix",
  "bucket": "nyec-pdr-prod-healthix",
  "key": "2.16.840.1.113883.3.1042.5.1/ccd/2026/Jul/21/...",
  "path": "s3://nyec-pdr-prod-healthix/...",
  "ccd_created_date": "2026-07-21",
  "ehr_software_name": "Epic",
  "custodian_org_name": "Sunrise Recovery Center",
  "custodian_org_address": "123 Main St, Albany, NY 12205",
  "service_location_name": "Outpatient Addiction Services",
  "processing_time_ms": 250,
  "file_size_bytes": 350000,
  "sud_indicator_count": 5,
  "has_sud_content": true,
  "sud_diagnoses_count": 2,
  "mat_medications_count": 1,
  "mat_strong_signal_count": 0,
  "mat_moderate_signal_count": 1,
  "sud_encounters_count": 1,
  "sud_procedures_count": 1,
  "sud_billing_code_hit": true,
  "methadone_dispensed": false,
  "facility_name_flags": "recovery|addiction",
  "facility_name_is_generic": false,
  "top_sud_codes": "F11.20|buprenorphine|urine drug screen"
}
```

### Source Identity Fields

These three fields give the QE enough context to identify the source without
needing to open the CCD themselves:

**ehr_software_name** — Same logic as FindEHR: extract from
`assignedAuthoringDevice/softwareName`. Imperfect (some CCDs won't have it),
but good enough for context. Tells the QE what system the source is on.

**custodian_org_name** — From `representedCustodianOrganization/name`. This
is the facility name as it appears in the CCD header. Already in the plan.

**custodian_org_address** — From `representedCustodianOrganization/addr`.
CDA addr elements contain streetAddressLine, city, state, postalCode.
Concatenate into a single flat string (e.g., "123 Main St, Albany, NY 12205").
If the addr element is missing or empty, use empty string "".
This gives the QE a way to physically locate the source for research.

XPath for address:
```
custodian/assignedCustodian/representedCustodianOrganization/addr
  -> streetAddressLine (may have multiple, join with space)
  -> city
  -> state
  -> postalCode
```

### CCD Created Date

Extract from the CCD header's `effectiveTime` element:
```xml
<effectiveTime value="20260721143022-0400"/>
```
Parse the first 8 characters as YYYY-MM-DD. This tells us when the clinical
document was generated — important for time-series analysis.

### Athena Compatibility Notes

- No nested JSON objects (Athena's JSON SerDe handles flat fields easily)
- No arrays (use pipe-separated strings for multi-value fields like `top_sud_codes`)
- Field names must be valid Athena column names (lowercase, underscores, no hyphens)
- One JSON per file OR newline-delimited JSON — both work with Athena
- Avoid `null` values where possible — use empty string "" instead
- No special characters in string values that would break CSV/JSON parsing


## Scoring Approach

### Per CCD: Absolute Count of SUD Indicators

For each CCD, count the total number of SUD indicators found (not a percentage).
A CCD either "has SUD content" or it doesn't. Even 1 indicator counts.

Output per CCD:
- `sud_indicator_count` — total SUD signals found in this CCD (0, 1, 2, 5, etc.)
- `has_sud_content` — boolean: is sud_indicator_count > 0?
- Individual counts: `sud_diagnoses_count`, `mat_medications_count`, etc.

Example:
- Patient on methadone + has F11.20 diagnosis + 3 urine drug screens = 5 indicators
- Patient with only a smoking history (F17.x) and no other SUD = 0 indicators (F17 excluded)

### Two Levels of Aggregation: Source AND Service Location

A source-only rollup will miss the priority case: a Part 2 "identified unit"
operating inside an otherwise-general facility. If a hospital contributes
1,000 CCDs and 150 come from its addiction medicine unit, the source-level
prevalence is only 15% (looks CLEAR) even though that unit is ~100% Part 2
activity. So we aggregate at BOTH levels and flag on whichever is higher:

```
# Level 1: whole source (AA)
ccds_with_sud = COUNT of CCDs where has_sud_content = true
ccds_sampled = total CCDs scored for this source
sud_prevalence_source = ccds_with_sud / ccds_sampled

# Level 2: service_location_name within that source
# (group by assigning_authority + service_location_name)
ccds_with_sud_at_location = COUNT where has_sud_content = true, same location
ccds_sampled_at_location = total CCDs scored for that location
sud_prevalence_location = ccds_with_sud_at_location / ccds_sampled_at_location
```

Report both. A source with low overall prevalence but one location at 80%+
is arguably the highest-priority finding — it's an identified unit quietly
contributing Part 2 data under the umbrella of a "standard" facility AA.

### Flagging Logic — Deference to Inclusion

Because this is candidate identification (not a determination), we err on
the side of INCLUSION. The bar for "put it on the list for QE research" is
deliberately low. A false positive costs the QE one phone call. A false
negative leaves a possible compliance gap undetected and un-investigated.

Apply the same thresholds at both the source level and the location level;
take the higher of the two as the source's overall classification, but keep
the location-level detail in the letter so the QE can see WHERE within
the source the signal is concentrated.

| sud_prevalence | Classification | Action |
|----------------|---------------|--------|
| > 50% of CCDs have SUD content | CANDIDATE - HIGH | Letter to QE, high confidence research warranted |
| 25-50% | CANDIDATE - MODERATE | Letter to QE, elevated signal warrants a conversation |
| 10-25% | CANDIDATE - LOW | Letter to QE, noting signal is above general-population baseline |
| < 10% | NOT A CANDIDATE | No letter — consistent with general population background rate |

Additionally, ANY source or location where `strong_signal_prevalence > 0`
(even a single CCD with methadone dispensing or an OTP billing code hit)
becomes at minimum a CANDIDATE - LOW regardless of overall sud_prevalence.
These specific signals are strong enough that even one occurrence warrants
a question to the QE.

The insight: a general hospital might have 5-15% of CCDs with any SUD indicator
(because some patients have substance use issues). A dedicated treatment facility,
or an identified unit within a larger facility, will have 50-80%+ because that's
close to its entire patient population.

Note: thresholds are a starting point, not fixed. Refine them using the
validation approach below (known 42 CFR sources) before running against the
general population.

### Signal Strength Matters, Not Just Count

Because methadone dispensing and OTP billing codes are much stronger Part 2
signals than buprenorphine or naloxone, prevalence alone can both overstate
and understate risk. A CCD's `sud_indicator_count` should be supplemented by
whether it contains a *strong* signal (methadone dispensed, or an OTP billing
code hit) versus only *moderate/weak* signals (buprenorphine alone, naloxone
alone). At the source/location level, also compute:

```
strong_signal_prevalence = CCDs with methadone_dispensed OR sud_billing_code_hit / ccds_sampled
```

A location with low overall SUD prevalence but a nonzero `strong_signal_prevalence`
still deserves review — it suggests OTP-billed activity is present even if
diluted by a larger general population.

### Facility Name Logic (Inverted Priority)

Facility name is used to PRIORITIZE, not just to additively flag:

- **Named + high prevalence** ("Sunrise Recovery Center" at 70%): confirmation
  case. Likely already known internally. Check routing, but this is not the
  interesting discovery.
- **Generic name + high prevalence** ("Memorial Hospital", "City Medical
  Associates" at 70%, or a specific `service_location_name` at 70% within a
  generic-named parent): this is the priority case — a facility or unit that
  reads as standard care but functions as a Part 2 program. This is what
  "contributed as a standard facility" means, and where investigation
  should be focused first.
- **Named + low prevalence**: possible false-name / dual-purpose facility
  that doesn't currently trigger the SUD content threshold — worth a lighter
  periodic recheck but not a priority.

Compute `facility_name_is_generic` (true when custodian org name does NOT
match the recovery/addiction/methadone/behavioral-health keyword list) so
the report can sort flagged results with generic-name + high-prevalence
first.

### What Counts vs What Doesn't

We ONLY count SUD indicators that are part of THIS encounter's care — not
historical patient data that the facility is merely documenting.

**Count these (evidence the facility is providing SUD care):**
- Medications with `author` or `performer` from this facility (prescribed here)
- Encounter diagnoses (the reason for THIS visit, not the problem list)
- Procedures performed at this encounter (drug screens ordered here)
- Encounters coded as SUD treatment types (IOP, detox, OTP visits)

**Do NOT count these (patient history, not facility activity):**
- Medication reconciliation entries (patient says "I take methadone" but it
  was prescribed elsewhere). In CDA these typically appear with a different
  `statusCode` or lack an `author` element from this facility.
- Problem list entries that are chronic/historical (ongoing diagnosis carried
  forward but not actively treated at this encounter)
- Social history noting past substance use

**How to distinguish in the CCD:**

| Signal | Active/This Encounter | Historical/Reported |
|--------|----------------------|---------------------|
| Medications | Has `author` or `effectiveTime` matching encounter date | No author, or `statusCode="completed"` with old date |
| Diagnoses | In `encounter/entryRelationship` (encounter diagnosis) | In Problems section only (problem list) |
| Procedures | `effectiveTime` within encounter date range | Procedure dated outside this encounter |

**Practical simplification for V1:**
- Count medications section entries only if they have an `effectiveTime` with a
  `high` value (active/current) — exclude historical/discontinued
- Count encounter diagnoses (inside the Encounters section) rather than the
  Problems section (which is the ongoing problem list)
- Count procedures only from the Procedures section (assumed to be this encounter)
- The Problems section is a WEAK signal — use it for corroboration but don't
  count it as primary evidence

This means: a patient who presents at an ER and mentions "I'm on methadone from
my clinic" will NOT trigger a flag — because the methadone wasn't prescribed here
and the encounter diagnosis will be whatever brought them to the ER.


## Routing Check

For each candidate source, determine its current routing as context for the QE:
- Check the S3 path: is it in a 42 CFR-designated bucket/prefix?
- If in general bucket → POTENTIALLY MISROUTED (this is the interesting case —
  flag for QE research)
- If already in 42 CFR bucket → ALREADY SEGREGATED (informational only; the
  QE may still want to confirm the routing is correct, but there's no urgency)

The routing check is a simple string match on the S3 path — no additional
S3 calls needed (we already have the path from the candidate CSV).


## Outputs

The end product is a communication FROM the PDR TO the Qualified Entity
asking them to research specific sources and explain why the data
contributes to a concern. Two distinct outputs serve two purposes:

### Output A: JSON (Athena-queryable pattern analysis)

Per-CCD JSON as described above (flat, NDJSON or one-per-file). This feeds
Athena so analysts can:
- Query patterns across all sources/locations/time periods
- Build dashboards on SUD prevalence trends
- Cross-reference with other datasets (EHR vendor, volume, etc.)
- Support the evidence backing each QE letter

This is the analytical backbone — it stays in S3 and gets queried at will.

### Output B: Per-Source HTML Letter to the QE

For each source (or location within a source) classified as CANDIDATE - HIGH,
CANDIDATE - MODERATE, or CANDIDATE - LOW, generate one HTML document
structured as a professional letter/memo to the responsible Qualified
Entity. The letter must:

1. **State who it's addressed to:** QE name, source AA, date generated
2. **Explain what was done:** "The PDR sampled N CCDs contributed by
   [source AA] through [QE] and scored each for indicators of substance
   use disorder treatment activity, specifically looking for patterns
   consistent with 42 CFR Part 2-covered care."
3. **Present the findings with specifics:**
   - SUD prevalence (X of N sampled CCDs contained SUD indicators)
   - Strong-signal prevalence (methadone dispensing, OTP billing codes)
   - If location-specific: which service_location_name concentrated the signal
   - Top indicator categories (e.g., "12 CCDs contained F11.x opioid
     diagnoses, 8 contained methadone administration, 5 contained OTP
     billing codes H0020/S0109")
   - Example codes found (de-identified — no patient data, just the code
     patterns observed: "F11.20 appeared in 60% of flagged CCDs")
4. **State why this warrants investigation:** Tie findings back to regulatory
   language — "These patterns are consistent with a program that holds itself
   out as providing SUD diagnosis and treatment. Under 42 CFR Part 2, such
   programs require heightened confidentiality protections and segregated
   data routing. The current contribution path does not route through the
   protected 42 CFR pipeline."
5. **Request specific action:** "Please research this source and confirm
   whether [source AA / location name] operates as or contains an identified
   SUD treatment unit, and advise the PDR on appropriate data handling."
6. **Include a disclaimer:** "This analysis identifies clinical content
   patterns only. It is not a legal determination of Part 2 status.
   The QE's research and response will inform any routing changes."

**Letter formatting:**
- Professional, neutral tone — not accusatory (this is a request to research,
  not an accusation)
- Color-coded severity banner at top (Red = CANDIDATE - HIGH,
  Orange = CANDIDATE - MODERATE, Yellow = CANDIDATE - LOW)
- Summary stats table
- Detail section with specific indicators found
- Footer with methodology note and date range of sampled CCDs
- Self-contained HTML (inline CSS, no external dependencies) so it can be
  emailed or printed as-is

**File naming:** `42CFR_inquiry_{qe}_{assigning_authority}_{date}.html`

### What Goes in the Report vs What Stays in JSON Only

| Data Point | In Letter? | In JSON? |
|-----------|-----------|---------|
| Source AA / QE / location | Yes | Yes |
| SUD prevalence % | Yes | Yes |
| Strong signal prevalence | Yes | Yes |
| Top indicator codes (aggregated) | Yes | Yes |
| Individual CCD-level detail | No | Yes |
| Patient-identifiable info | Never | Never |
| Specific S3 paths | No | Yes |
| Processing metadata (time, size) | No | Yes |
| Current bucket / routing status | Yes | Yes |


## Sampling

- 20 CCDs per source (same as coding quality — adjustable)
- Use same `findcandidatesforexplore.sql` candidate list (filter to CCD only)
- Same restart/dedup logic as FindingEHR


## Scripts to Build

| Script | Purpose |
|--------|---------|
| `score_42cfr.py` | Core scorer: download CCD, count SUD indicators, write JSON (Output A) |
| `aggregate_42cfr.py` | Read scored JSONs, aggregate per source/location, classify, check routing |
| `generate_qe_letters.py` | For each FLAGGED/REVIEW source, generate per-source HTML letter (Output B) |
| `0. run_42cfr_pipeline.py` | End-to-end: score -> aggregate -> generate letters |

All follow the same DEV/PROD profile pattern with:
- `AWS_PROFILE`, `CANDIDATES_CSV`, `ALLOWED_BUCKETS`, `MAX_FILES` at top
- Restart support (skip already-scored)
- Date-stamped output


## Validation Approach — Calibrate Against Known 42 CFR Sources First

Before running this against the general population to find candidates, we
validate the scorer against sources we already know are 42 CFR Part 2
(sources already submitted into PDR as 42 CFR-designated). This tells us
whether our indicators and thresholds actually work before we trust them
on unknown sources.

**Phase 1 — Calibration:**
1. Run the scorer against CCDs from known 42 CFR-identified sources
2. Confirm they score as CANDIDATE - HIGH (or at least MODERATE) reliably
3. If known 42 CFR sources score low or CLEAR, that means our indicators
   are missing something — investigate which signals should have fired
   and didn't (wrong codes, wrong section, encounter-tied logic too strict, etc.)
4. Refine the indicator list / weighting / thresholds based on what we learn
5. Re-run against the same known sources until they reliably score as
   candidates

**Phase 2 — Sanity check on normal population:**
Use existing Synthea CCDs (general population synthetic data, no SUD
content) to confirm the scorer does NOT flag normal data — everything
should score CLEAR/NOT A CANDIDATE. This guards against a scorer that's so
loose it flags everything.

**Phase 3 — General population candidate run:**
Only once Phase 1 and Phase 2 both look right do we run the scorer against
the broader (non-42-CFR-designated) population to generate the actual
candidate list and QE letters. This is the real deliverable — Phases 1-2
are calibration, not the end product.

For synthetic positive testing during development: create 2-3 synthetic
CCDs with injected F10-F19 codes and MAT medications and confirm they score
as candidates.


## Compliance Note

This tool identifies CANDIDATES for research — it does not make a Part 2
determination and does not move data or change access controls. The QE
performs the actual research and determination; remediation (if any) is a
manual operational step taken after the QE's research and any subsequent
compliance review.

Because we defer to inclusion, expect some candidates to resolve as "not
Part 2" after QE research — that is an expected and acceptable outcome of
this approach, not a scorer failure.
