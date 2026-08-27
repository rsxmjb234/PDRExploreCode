# CCD XML Parsing

## CDA Namespace
All CDA elements use: `urn:hl7-org:v3`
```python
ns = "urn:hl7-org:v3"
root.find(f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}softwareName")
```

## Key Locations in a CCD
| Data | XPath |
|------|-------|
| Software name | `//assignedAuthoringDevice/softwareName` |
| Manufacturer | `//assignedAuthoringDevice/manufacturerModelName` |
| Custodian org | `//custodian/assignedCustodian/representedCustodianOrganization/name` |
| Patient IDs | `//recordTarget/patientRole/id` |
| Sections | `//component/structuredBody/component/section` |
| Section LOINC | `section/code/@code` |

## Section LOINC Codes
| Section | LOINC |
|---------|-------|
| Medications | 10160-0 |
| Labs | 30954-2 |
| Problems | 11450-4 |
| Procedures | 47519-4 |
| Encounters | 46240-8 |
| Immunizations | 11369-6 |
| Vital Signs | 8716-3 |
| Allergies | 48765-2 |
| Social History | 29762-2 |
| Plan of Care | 18776-5 |
| Functional Status | 47420-5 |

## TRN (HL7v2) Parsing
TRN files are pipe-delimited, not XML:
```
MSH|^~\&|SendingApp|SendingFacility|ReceivingApp|...
```
MSH-3 = Sending Application (fields[2])
MSH-4 = Sending Facility (fields[3])
