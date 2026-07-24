# PLAN: Next Code Changes (Both EntireCCD and JustTopOfFile)

Check in current code first, then implement these changes.

---

## Change 1: Add QE and Assigning Authority from Input CSV

**What:** The input CSV already has columns `qe` and `assigning_authority`.
Currently we ignore them. We want to pass them through to the output CSV.

**Where:** Both `findandsaveEHRfromCCD-EntireCCD.py` and `findandsaveEHRfromCCD-JustTopOfFile.py`

**Steps:**
1. Change `read_input_csv_file()` to return a list of dicts (not just keys)
   containing `{"key": ..., "qe": ..., "assigning_authority": ...}`
2. Add `"QE"` and `"Input_Assigning_Authority"` to OUTPUT_FIELDS
   (after FileName, before ProcessingTimeMS)
3. In the processing loop, copy those values into the fingerprints dict
4. These come from the INPUT CSV, not from parsing the CCD

**New column order:**
```
Path, FileName, QE, Input_Assigning_Authority, ProcessingTimeMS, FileSizeBytes, ...
```

---

## Change 2: Remove Weak Signals

**What:** Remove these signals from extraction, OUTPUT_FIELDS, and scoring:
- `templateIds` (Template IDs from ClinicalDocument/templateId)
- `allOIDFamilies` (OID family prefixes from all root attributes)
- `indentStyle` (XML formatting/whitespace analysis)

**Where:** Both scripts

**Steps:**
1. Remove from OUTPUT_FIELDS list
2. Remove extraction code in `extract_all_fingerprint_signals()`
3. Remove from scoring in `make_preliminary_ehr_guess()`
   - Remove Signal Check 3 (standard CCD templateId)
   - Remove Signal Check 4 (XML formatting)
4. Remove `detect_xml_indentation_style()` function entirely
5. Remove `from collections import Counter` import (only used by indent detection)

**Columns being removed:**
- `templateIds`
- `allOIDFamilies`
- `indentStyle`

---

## Change 3: Replace EHR-Guess with Smarter `EHR_Guess` Logic

**What:** Remove the old `EHR-Guess` and `EHR-GuessReason` columns.
Replace with a new, smarter classification:
- `EHR_Guess` — canonical EHR vendor name
- `EHR_Guess_Confidence` — High / Medium / Low
- `EHR_Guess_Reason` — short explanation of which fields drove the guess

**Where:** Both scripts (replace `make_preliminary_ehr_guess()`)

**New function: `classify_ehr_vendor(fingerprints)`**

**Classification rules (in priority order):**

1. Normalize: lowercase, strip whitespace, treat blanks as null
2. Check softwareName / manufacturerModelName for explicit vendor names:
   - Contains "Epic" => EPIC
   - "eClinicalWorks" or "eClinicalWorks CCDA" => eClinicalWorks
   - "athenahealth" => athenahealth
   - "MEDENT" => MEDENT
   - "Cerner" or "Millennium" => Cerner
   - "PointClickCare" => PointClickCare
   - "Netsmart" or "CCD Generator" + manufacturer Netsmart => Netsmart
   - "Practice Fusion" => Practice Fusion
   - "NextGen" => NextGen
   - "Greenway Intergy" => Greenway
   - "SigmaCare" => SigmaCare
   - "Office Practicum" => Office Practicum
   - "MEDITECH" => MEDITECH
   - "InterSystems" or "HealthShare" => InterSystems

3. Generic software names with specific manufacturer:
   - "Document Generation Engine" + manufacturer="athenahealth" => athenahealth
   - "CCD Generator" + manufacturer="Netsmart" => Netsmart
   - "Millennium Clinical Document Generator" + manufacturer="Cerner Corporation" => Cerner

4. Epic OID signal:
   - If hasEpicOID=YES AND no other vendor identified => EPIC (Medium confidence)
   - If hasEpicOID=YES AND another vendor identified => keep that vendor,
     note "conflicting Epic OID" in reason, set confidence to Low

5. If no signal => "UNKNOWN" with Low confidence

**Returns:** tuple of (ehr_guess, confidence, reason)

**New columns replacing old:**
- `EHR_Guess` (replaces `EHR-Guess`)
- `EHR_Guess_Confidence` (new)
- `EHR_Guess_Reason` (replaces `EHR-GuessReason`)

---

## Final OUTPUT_FIELDS After All Changes

```python
OUTPUT_FIELDS = [
    "Path",
    "FileName",
    "QE",
    "Input_Assigning_Authority",
    "ProcessingTimeMS",
    "FileSizeBytes",
    "Assigning-Authority",        # From CCD XML (recordTarget/patientRole/id)
    "OID",
    "softwareName",
    "manufacturerModelName",
    "custodianOrgName",
    "hasEpicOID",
    "epicOIDsFound",
    "EHR_Guess",
    "EHR_Guess_Confidence",
    "EHR_Guess_Reason",
    "Parse_type",
]
```

---

## Files Affected

- `findandsaveEHRfromCCD-EntireCCD.py`
- `findandsaveEHRfromCCD-JustTopOfFile.py`
- `AnalyzeResults/MakeTableResults.sql` (update to match new columns)

---

## Testing

After changes:
1. Delete existing output CSVs
2. Run JustTopOfFile with max_files=5, verify output columns
3. Run EntireCCD with max_files=5, verify output columns match
4. Both should produce identical column headers
5. Spot-check EHR_Guess values against known MEDENT/Epic sources in PROD data
