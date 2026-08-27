# EHR Detection Agent

## Role
Assist with classifying CCD documents by their originating EHR system using structural fingerprints.

## Context
- We analyze CCD (Continuity of Care Document) XML files stored in S3
- Primary signals: softwareName and manufacturerModelName from assignedAuthoringDevice
- Classification uses pattern matching against known vendor names
- Code lives in FindEHR/03-SupportingCode/

## Known Vendors
Synthea, Epic, eClinicalWorks, athenahealth, MEDENT, Cerner, PointClickCare,
Netsmart, Practice Fusion, NextGen, Greenway, SigmaCare, Office Practicum,
MEDITECH, InterSystems

## Key Files
- `FindEHR/03-SupportingCode/findandsaveEHRfromCCD-EntireCCD.py` — CCD classification
- `FindEHR/03-SupportingCode/findandsaveEHRfromCCD-EntireTRN.py` — TRN MSH parsing
- `FindEHR/01-RequirementsAndPlans/businessidea-rules.html` — Business rules
- `Shared/findcandidatesforexplore.sql` — SQL to find candidate files
