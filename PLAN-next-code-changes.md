# CHANGE LOG: Code Changes Applied

This document tracks all code changes made to the EHR detection scripts.
Dan: read this to understand what changed and why.

---

## Change 1: Add QE and Assigning Authority from Input CSV
**Status: DONE**

**What:** The input CSV has columns `qe` and `assigning_authority`.
We now pass them through to the output CSV so you can see them alongside
the EHR classification results.

**What was changed:**
- `read_input_csv_file()` now returns a list of dicts (not just key strings)
  containing `{"key": ..., "qe": ..., "assigning_authority": ...}`
- Added `"QE"` and `"Input_Assigning_Authority"` to OUTPUT_FIELDS
- Processing loop copies those values into each output row

---

## Change 2: Remove Weak Signals
**Status: DONE**

**What:** Removed signals that didn't contribute meaningfully to classification:
- `templateIds` (Template IDs from ClinicalDocument/templateId)
- `allOIDFamilies` (OID family prefixes from all root attributes)
- `indentStyle` (XML formatting/whitespace analysis)

**What was removed:**
- Columns from OUTPUT_FIELDS
- Extraction code in `extract_all_fingerprint_signals()`
- `detect_xml_indentation_style()` function entirely
- `from collections import Counter` import

---

## Change 3: Replace EHR-Guess with Smarter Classification
**Status: DONE**

**What:** Replaced the old weighted scoring (`make_preliminary_ehr_guess`)
with a new function `classify_ehr_vendor()` that does explicit vendor
pattern matching on softwareName and manufacturerModelName.

**New columns:**
- `EHR_Guess` — canonical EHR vendor name (EPIC, MEDENT, Cerner, etc.)
- `EHR_Guess_Confidence` — High / Medium / Low
- `EHR_Guess_Reason` — which fields drove the guess

**Classification rules:**
1. Check softwareName + manufacturerModelName for known vendor keywords
2. Handle generic software names with specific manufacturers
3. If no match => "UNKNOWN" with Low confidence

**Vendors detected:**
Epic, eClinicalWorks, athenahealth, MEDENT, Cerner, PointClickCare,
Netsmart, Practice Fusion, NextGen, Greenway, SigmaCare, Office Practicum,
MEDITECH, InterSystems

---

## Change 4: Rename Assigning-Authority Column
**Status: DONE**

**What:** Renamed `"Assigning-Authority"` to `"Assigning-Authority-ParsedFromS3"`
to clarify this value comes from parsing the CCD XML (recordTarget/patientRole/id),
not from the input CSV.

---

## Change 5: Remove Epic OID Signal Entirely
**Status: DONE**

**What:** Removed `hasEpicOID` and `epicOIDsFound` columns and all related logic.
The EHR classification is now based entirely on `softwareName` and
`manufacturerModelName` — the OID scanning was redundant.

**What was removed:**
- `hasEpicOID` and `epicOIDsFound` from OUTPUT_FIELDS
- All OID scanning code in `extract_all_fingerprint_signals()`
- `EPIC_OID_FAMILY` constant
- Epic OID fallback rule in `classify_ehr_vendor()`
- `hasEpicOID` print statements in the processing loop

---

## Change 6: Fix max_files Batch Logic
**Status: DONE**

**What:** Fixed a bug where `max_files=200` would only look at the first 200
rows from the input CSV, then say "all done" if those were already processed.

**Fix:** Now reads ALL rows from the input CSV first, filters out
already-processed files, THEN applies max_files as a cap on how many
remaining files to process this run. This gives you the NEXT batch,
not the first batch.

---

## Final OUTPUT_FIELDS (Current State)

```python
OUTPUT_FIELDS = [
    "Path",                           # Full S3 path (s3://bucket/key)
    "FileName",                       # Just the filename
    "QE",                             # QE from input CSV
    "Input_Assigning_Authority",      # Assigning authority from input CSV
    "ProcessingTimeMS",               # Time to download + extract (ms)
    "FileSizeBytes",                  # File size downloaded
    "Assigning-Authority-ParsedFromS3", # From CCD XML parsing
    "OID",                            # Patient ID root OID
    "softwareName",                   # From assignedAuthoringDevice
    "manufacturerModelName",          # Backup software identifier
    "custodianOrgName",               # Organization hosting/sending the CCD
    "EHR_Guess",                      # Canonical EHR vendor name
    "EHR_Guess_Confidence",           # High / Medium / Low
    "EHR_Guess_Reason",               # Which fields drove the guess
    "Parse_type",                     # "TopOnly" or "Entire"
]
```

---

## Files Affected

- `findandsaveEHRfromCCD-EntireCCD.py` — Full file download + XML parser version
- `findandsaveEHRfromCCD-JustTopOfFile.py` — First 100KB + regex version
- `AnalyzeResults/MakeTableResults.sql` — Athena table definition (updated)

---

## How to Run

1. Delete any existing output CSV (to pick up new column format)
2. Set `ACTIVE_PROFILE = "DEV"` or `"PROD"`
3. Set `max_files` in the DEV/PROD dict to control batch size
4. Run: `python findandsaveEHRfromCCD-EntireCCD.py`
   or: `python findandsaveEHRfromCCD-JustTopOfFile.py`
5. On subsequent runs, it automatically skips already-processed files
6. Results flush to disk every 200 records (crash protection)

---

## Testing Performed

- JustTopOfFile: 200 DEV files, 157ms avg per record
- EntireCCD: 3 DEV files, 343ms avg per record
- Both produce identical column headers
- Restart logic confirmed working (skips done files, processes next batch)
