# 42 CFR Candidate Identification — Implementation Plan

## Architecture: Modular Checkers + Master Orchestrator

Each signal check is its own Python file. This makes it easy to:
- Add/remove/modify a single check without touching the others
- Test each check independently against sample CCDs
- See exactly which check flagged what in the output
- Iterate on one check during Phase 1 calibration without risk to others

```
03-SupportingCode/
|
|-- config.py                  # DEV/PROD profiles, AWS settings, thresholds
|
|-- checkers/                  # Each check is its own module
|   |-- __init__.py
|   |-- check_diagnoses.py    # ICD-10 F10-F19 (excl F17)
|   |-- check_medications.py  # MAT meds with signal strength weighting
|   |-- check_billing_codes.py # OTP/SUD HCPCS/CPT codes
|   |-- check_encounters.py   # SUD encounter types (detox, IOP, OTP)
|   |-- check_procedures.py   # UDS, SBIRT, counseling procedures
|   |-- check_facility_name.py # Custodian org name keyword match
|
|-- extract_identity.py        # EHR name, custodian, address, location, date
|-- score_ccd.py               # Downloads 1 CCD, runs all checkers, writes JSON
|-- aggregate_sources.py       # Reads scored JSONs, computes prevalence, classifies
|-- generate_qe_letters.py     # Builds per-source HTML letter for the QE
|-- run_pipeline.py            # End-to-end: score -> aggregate -> letters
```


## TODO — Build Order

### 1. config.py
- [x] DEV/PROD profile switch (same pattern as FindEHR)
- [x] AWS_PROFILE, CANDIDATES_CSV, ALLOWED_BUCKETS, MAX_FILES
- [x] OUTPUT_DIR for scored JSONs
- [x] Thresholds: HIGH/MODERATE/LOW/NOT_CANDIDATE prevalence cutoffs
- [x] CDA namespace constant
- [x] LOINC section template IDs for medications, encounters, procedures, problems

### 2. checkers/check_diagnoses.py
- [x] Input: parsed XML root + namespace
- [x] Looks in Encounters section entryRelationship for encounter diagnoses
- [x] Also looks in Problems section (weak signal — flagged separately)
- [x] Matches ICD-10 codes starting with F1 (F10-F19), excludes F17
- [x] Returns: dict with sud_diagnoses_count, diagnosis codes found, is_weak_only

### 3. checkers/check_medications.py
- [x] Input: parsed XML root + namespace
- [x] Looks in Medications section for active meds (effectiveTime with high value)
- [x] Matches by RxNorm code or displayName keyword
- [x] Classifies each hit as STRONG (methadone), MODERATE (buprenorphine etc), WEAK (naloxone etc)
- [x] Returns: dict with mat_medications_count, mat_strong_signal_count,
      mat_moderate_signal_count, methadone_dispensed, med codes found

### 4. checkers/check_billing_codes.py
- [x] Input: parsed XML root + namespace
- [x] Scans all code elements across encounters/procedures for HCPCS/CPT matches
- [x] Matches: H0020, S0109, H0015, H0005, H0004, H0001, G2067-G2078, 99408, 99409, 80305-80307
- [x] Returns: dict with sud_billing_code_hit (bool), billing codes found

### 5. checkers/check_encounters.py
- [x] Input: parsed XML root + namespace
- [x] Looks in Encounters section for encounter type codes/displayNames
- [x] Keyword match: detox, IOP, residential treatment, OTP, substance use/abuse, addiction
- [x] Returns: dict with sud_encounters_count, encounter descriptions found

### 6. checkers/check_procedures.py
- [x] Input: parsed XML root + namespace
- [x] Looks in Procedures section for procedure codes/displayNames
- [x] Matches: UDS (80305-80307), SBIRT (99408/99409), counseling keywords
- [x] Returns: dict with sud_procedures_count, procedure codes found

### 7. checkers/check_facility_name.py
- [x] Input: custodian_org_name string (already extracted)
- [x] Keyword match: recovery, addiction, substance, methadone, opioid treatment,
      behavioral health, detox, MAT, suboxone
- [x] Returns: dict with facility_name_flags (pipe-delimited matches),
      facility_name_is_generic (bool — true if NO keywords match)

### 8. extract_identity.py
- [x] Input: parsed XML root + namespace
- [x] Extracts: ehr_software_name (assignedAuthoringDevice/softwareName)
- [x] Extracts: custodian_org_name (representedCustodianOrganization/name)
- [x] Extracts: custodian_org_address (addr -> streetAddressLine, city, state, postalCode)
- [x] Extracts: service_location_name (componentOf/encompassingEncounter/location/.../name)
- [x] Extracts: ccd_created_date (effectiveTime value, first 8 chars -> YYYY-MM-DD)
- [x] Returns: dict with all identity fields

### 9. score_ccd.py
- [x] Main worker: given an S3 path, downloads the CCD, parses XML
- [x] Calls extract_identity to get source/facility info
- [x] Calls each checker module in sequence
- [x] Assembles all results into a single flat JSON dict
- [x] Computes sud_indicator_count as sum of all checker counts
- [x] Sets has_sud_content = sud_indicator_count > 0
- [x] Builds top_sud_codes (pipe-delimited top findings)
- [x] Returns the complete JSON record (or writes to file)
- [x] Handles download errors gracefully (returns error record, doesn't crash)

### 10. aggregate_sources.py
- [x] Reads all scored JSON files from the output directory
- [x] Groups by assigning_authority (Level 1) and by AA + service_location (Level 2)
- [x] Computes: sud_prevalence_source, sud_prevalence_location, strong_signal_prevalence
- [x] Classifies each source/location: HIGH / MODERATE / LOW / NOT_CANDIDATE
- [x] Applies strong-signal override (any strong signal -> at minimum LOW)
- [x] Outputs: aggregated CSV with one row per source (or per location)
- [x] Also computes general-population stats for comparison in letters

### 11. generate_qe_letters.py
- [x] Reads the aggregated CSV
- [x] For each source classified as CANDIDATE (any level), generates an HTML letter
- [x] Uses the sample-qe-letter.html as a template structure
- [x] Fills in: source identity, methodology, specific indicators, comparison stats
- [x] Color-codes by severity (RED/ORANGE/YELLOW banner)
- [x] Writes one HTML file per source: 42CFR_inquiry_{qe}_{aa}_{date}.html
- [x] Self-contained (inline CSS, no external dependencies)

### 12. run_pipeline.py
- [x] End-to-end orchestrator
- [x] Step 1: Read candidate CSV, filter to unprocessed files
- [x] Step 2: Call score_ccd for each (with restart/skip logic, flush every 200)
- [x] Step 3: Call aggregate_sources once all scoring is done
- [x] Step 4: Call generate_qe_letters for candidates
- [x] DEV/PROD profile switch at top
- [x] Progress reporting (X of Y processed, estimated time remaining)
- [x] max_files limit respected


## Interface Contract — Every Checker Returns the Same Shape

```python
def check(root, ns):
    """
    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with:
          - One or more count fields (int)
          - One or more detail fields (str, pipe-delimited)
          - All field names are flat, lowercase, underscored (Athena-safe)
    """
```

check_facility_name is the exception — it takes a string, not XML:
```python
def check(custodian_org_name):
    """
    Args:
        custodian_org_name: string from extract_identity

    Returns:
        dict with facility_name_flags, facility_name_is_generic
    """
```


## Testing Strategy

- Phase 1: Run against known 42 CFR sources (from 42 CFR bucket)
  - Expect: most score as CANDIDATE - HIGH
  - If not: inspect which checker(s) returned 0, fix, re-run
- Phase 2: Run against Synthea / general population CCDs
  - Expect: all score as NOT A CANDIDATE
  - If not: checker is too loose, tighten
- DEV mode uses small candidate CSV from learning bucket
- Each checker can be tested independently:
  ```
  python -m checkers.check_diagnoses --file sample.xml
  ```
