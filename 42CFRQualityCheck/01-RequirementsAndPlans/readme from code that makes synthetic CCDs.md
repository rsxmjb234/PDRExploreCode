# GenerateSyntheticCCDs

Generate synthetic C-CDA (Continuity of Care Documents) using [Synthea](https://github.com/synthetichealth/synthea), classify each one as **Part 2** (substance use disorder data) or **Standard** (everything else), stamp each with a realistic NYEC facility name and Assigning Authority, and upload them to two S3 prefixes for testing.

## How It Works (Overview)

The pipeline generates a large, unfiltered population and then sorts the resulting documents:

```
[Generate N patients in Synthea]
        |
        v
[Split every CCD by content]
   |                    |
   v                    v
 Part2 (SUD)        Standard (non-SUD)
   |                    |
   v                    v
[Assign facility name + Assigning Authority to each]
   |                    |
   v                    v
s3://.../42CFRStyleCCDs/    s3://.../42CFRTesting-Not42CFR/
```

We do **not** use Synthea's keep-patient filter to force every record to be SUD. That approach is slow and rejects too many patients. Instead we generate a big batch, then classify the output. SUD documents (opioid diagnoses, methadone/buprenorphine/naltrexone, etc.) go to Part 2; all others go to Standard. This produces both datasets from a single Synthea run and keeps as much data as possible.

## S3 Targets

| Dataset | S3 Location | Contents |
|---------|-------------|----------|
| Part 2 | `s3://nyec.ccda.learning/42CFRStyleCCDs/` | CCDs containing substance use disorder / MAT content |
| Standard | `s3://nyec.ccda.learning/42CFRTesting-Not42CFR/` | CCDs with no SUD content (normal clinical data) |

## Pipeline Steps

### 1. Generate Patients with Synthea

Config lives in `config/synthea_nyec.properties` (CCDA export on, all other formats off). Population size is set there (`generate.default_population`) or overridden on the command line with `-p`.

Because opioid/SUD prevalence in Synthea is only ~5%, generate a large batch to get a meaningful number of Part 2 records. For example, 5,000 patients yields roughly 300-400 SUD documents and ~5,000 standard ones.

```powershell
# From the synthea/ directory (config already copied in)
.\run_synthea.bat "New York" -p 5000 -c synthea_nyec.properties -s 77777
```

- `"New York"` sets state-specific demographics, providers, and geography.
- `-p 5000` sets the population.
- `-s 77777` sets a seed so repeat runs produce different patients (change it each run).

Output lands in `synthea/output/ccda/`.

### 2. Split into Part 2 and Standard

`scripts/split_all.py` scans every generated CCD and copies it into one of two folders based on whether it contains SUD content. **No file limit** — it takes everything.

```powershell
python scripts\split_all.py "synthea\output\ccda" "output\raw_part2_new" "output\raw_standard_new"
```

A document is classified as **Part 2** if it contains any of these strong SUD markers:
- Dependent drug abuse, Opioid abuse, Opioid dependence, Opioid use disorder
- Drug rehabilitation and detoxification, Drug addiction counseling/therapy
- methadone hydrochloride, buprenorphine/naloxone, Naltrexone hydrochloride

Everything else is **Standard**.

### 3. Assign Facility Name + Assigning Authority

`scripts/assign_aa.py` rewrites each CCD so it looks like it came from a real NYEC facility. It reads `assigningauthority.md` and, for the requested `--type`, round-robins through the entries, setting on each document:

- Every `assigningAuthorityName` attribute (patient IDs, custodian, etc.) to the literal AA value (e.g. `rochester|FLACRA`)
- Organization `<name>` elements (custodian, author, informant, performer) to the facility name (e.g. `Edgewater Health Broadway Clinic`)

Run it once per dataset:

```powershell
python scripts\assign_aa.py --input-dir "output\raw_part2_new"    --output-dir "output\part2_new"    --aa-file "assigningauthority.md" --type part2
python scripts\assign_aa.py --input-dir "output\raw_standard_new" --output-dir "output\standard_new" --aa-file "assigningauthority.md" --type standard
```

### 4. Upload to S3 (Resumable, Skips Existing)

`scripts/upload_s3.py` lists what's already in the target prefix and only uploads files that aren't there yet. It uploads in batches (default 500) so a large set can be pushed in several runs without re-uploading anything.

```powershell
# Part 2
python scripts\upload_s3.py --local-dir "output\part2_new"    --bucket nyec.ccda.learning --prefix 42CFRStyleCCDs        --profile student1 --batch 500

# Standard (run repeatedly until it reports 0 needing upload)
python scripts\upload_s3.py --local-dir "output\standard_new" --bucket nyec.ccda.learning --prefix 42CFRTesting-Not42CFR --profile student1 --batch 500
```

Each run reports how many are already in S3, how many still need uploading, and how many it pushed this batch. Re-run the same command to continue where it left off. Nothing is ever deleted or re-uploaded.

### 5. Validate

```powershell
aws s3 ls s3://nyec.ccda.learning/42CFRStyleCCDs/        --profile student1 | Measure-Object -Line
aws s3 ls s3://nyec.ccda.learning/42CFRTesting-Not42CFR/ --profile student1 | Measure-Object -Line
```

Spot-check a document to confirm the `assigningAuthorityName` and facility name were applied:

```powershell
Select-String -Path "output\part2_new\*.xml" -Pattern 'assigningAuthorityName="[^"]+"' | Select-Object -First 3
```

## The Assigning Authority File

`assigningauthority.md` is a 3-column CSV:

| Column | Meaning | Example |
|--------|---------|---------|
| `Type` | `part2` or `standard` — which dataset the entry belongs to | `part2` |
| `AA_MRN` | The literal `assigningAuthorityName` value. The `\|` is part of the value, not a separator. | `rochester\|FLACRA` |
| `Name` | The facility name written into org elements | `Edgewater Health Broadway Clinic` |

Notes:
- Facility names that contain a comma **must be wrapped in double quotes**, e.g. `"Cayuga Counseling Services, Inc."`. The parser uses standard CSV rules, so quoted commas are handled correctly.
- `part2` entries are substance use / behavioral health facilities. `standard` entries are general clinical organizations.
- Entries are assigned round-robin, so documents are spread across all facilities of the chosen type.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/split_all.py` | Classify every CCD as Part 2 (SUD) or Standard and copy into two folders |
| `scripts/assign_aa.py` | Stamp each CCD with a facility name and Assigning Authority (`--type part2` or `--type standard`) |
| `scripts/upload_s3.py` | Upload to S3, skipping files already present, in batches |
| `scripts/filter_opioid_ccds.py` | Helper to pull only SUD documents up to a target count (used for fixed-size Part 2 sets) |
| `generate_ccds.ps1` | End-to-end orchestration for a single run (generate → assign → upload) |

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Java JDK | 11+ | Run Synthea |
| Gradle | (bundled with Synthea) | Build Synthea |
| Python | 3.x | Split, assign, upload scripts (standard library only) |
| AWS CLI | 2.x | Upload to S3, using the `student1` profile |
| Git | any | Clone Synthea |

## Quick Start

```powershell
# 1. Clone Synthea (once) and copy config in
git clone https://github.com/synthetichealth/synthea.git synthea
Copy-Item config\synthea_nyec.properties synthea\synthea_nyec.properties -Force

# 2. Generate a large population
cd synthea
.\run_synthea.bat "New York" -p 5000 -c synthea_nyec.properties -s 77777
cd ..

# 3. Split into Part 2 and Standard
python scripts\split_all.py "synthea\output\ccda" "output\raw_part2_new" "output\raw_standard_new"

# 4. Assign facility names + Assigning Authorities
python scripts\assign_aa.py --input-dir "output\raw_part2_new"    --output-dir "output\part2_new"    --aa-file "assigningauthority.md" --type part2
python scripts\assign_aa.py --input-dir "output\raw_standard_new" --output-dir "output\standard_new" --aa-file "assigningauthority.md" --type standard

# 5. Upload (repeat the standard command until it reports 0 needing upload)
python scripts\upload_s3.py --local-dir "output\part2_new"    --bucket nyec.ccda.learning --prefix 42CFRStyleCCDs        --profile student1 --batch 500
python scripts\upload_s3.py --local-dir "output\standard_new" --bucket nyec.ccda.learning --prefix 42CFRTesting-Not42CFR --profile student1 --batch 500
```

## Notes

- Synthea generates realistic but entirely fictional patient data — safe for testing and development. No real PHI is involved.
- The C-CDA files conform to the HL7 CDA R2 standard.
- Each patient produces one C-CDA file containing their full medical history.
- Adding more data is additive: generate another batch with a new seed, split, assign, and upload. The upload script skips anything already in S3, so re-running is safe.
- `synthea/` and `output/` are git-ignored (see `.gitignore`) — the documents live in S3, not in the repo.
- "Synthia" in conversation refers to **Synthea** (`synthetichealth/synthea` on GitHub).
