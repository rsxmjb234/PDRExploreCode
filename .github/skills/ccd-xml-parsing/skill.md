# CCD XML Parsing Skill

## Description
Parse CDA/CCD XML documents and extract structured clinical and metadata fields.

## Key Knowledge

### CDA Namespace
All CDA elements use namespace: `urn:hl7-org:v3`

### Common XPath Patterns
- Patient name: `//recordTarget/patientRole/patient/name/family`
- Software name: `//assignedAuthoringDevice/softwareName`
- Custodian org: `//custodian/assignedCustodian/representedCustodianOrganization/name`
- Template IDs: `//ClinicalDocument/templateId`
- Sections: `//component/structuredBody/component/section`
- Patient IDs: `//recordTarget/patientRole/id`

### Epic OID Family
Epic's registered OID root: `1.2.840.114350`

### Epic Section Order (LOINC codes)
1. 48765-2 — Allergies
2. 10160-0 — Medications
3. 11450-4 — Problems
4. 30954-2 — Results
5. 8716-3  — Vital Signs
6. 47519-4 — Procedures

## Usage
Use Python's `xml.etree.ElementTree` with namespace-qualified XPaths:
```python
ns = "urn:hl7-org:v3"
root.find(f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}softwareName")
```
