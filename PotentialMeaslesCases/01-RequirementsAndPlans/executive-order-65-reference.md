# Reference: NY Executive Order No. 65 — Measles Disaster Emergency

**Purpose of this file:** The "Governor Announcement" folder saved alongside this one only kept leftover
CSS assets, not the actual order text. This file captures the real content so that anyone — human or AI —
building code against the ideas in this folder has the source material and the reasoning behind it, without
having to re-research it.

**Source:** [Executive Order No. 65](https://www.governor.ny.gov/sites/default/files/2026-10/eo-65-measles.pdf),
issued by Governor Kathy Hochul, effective **October 5, 2026**, statewide.

---

## 1. Key Facts Cited in the Order

- As of **October 3, 2026**: **108 measles cases** reported among NY State residents in 2026.
- Of those, **92 cases since July 15, 2026** are among **under-immunized, rural communities in 18 counties**.
  This is the core risk population the order is responding to.
- Neighboring **Pennsylvania**: 977 cases and 5 deaths as of October 2, 2026, in rural counties bordering NY —
  cited as a cross-border spread risk.
- Local health departments are already doing: surveillance, investigation, contact identification and
  monitoring, vaccine administration for exposed contacts and high-risk populations, education and outreach.
- The order finds the outbreak "constitutes an issue of significant public health concern" and that affected
  local governments are unable to respond adequately alone — hence the state disaster emergency declaration.

## 2. What the Order Actually Does (Legal Authority Used)

Declares a State Disaster Emergency under Executive Law Article 2-B §28, directs implementation of the State
Comprehensive Emergency Management Plan (§29), and — critically for ideas below — **temporarily suspends or
modifies specific statutes and regulations** under §29-a for the duration of the emergency. The suspensions
that matter most for SHIN-NY-adjacent ideas:

| Suspended/Modified Provision | Effect |
|---|---|
| Public Health Law §3001(6)(7), 10 NYCRR §800.3(o)(p), §800.15 | EMTs-paramedics and advanced EMS providers may administer MMR vaccine under a **non-patient-specific order**, including in non-emergency settings |
| Education Law §6951, 8 NYCRR §79-5.5 | **Midwives** may administer MMR to any patient under a non-patient-specific order, under physician/NP/PA medical supervision |
| Education Law §6801(2), §6802(22), 8 NYCRR §63.9 | **Pharmacists** may administer MMR to children age 2+ under a non-patient-specific order |
| Education Law §6527(6)(7), §6909(4)(7), 8 NYCRR §64.7 | Physicians/NPs may issue a non-patient-specific regimen so **nurses or other authorized persons** can administer MMR |
| Public Health Law §2168(3), 10 NYCRR §66-1.2 | Suspends the **consent requirement to report** MMR vaccination (age 19+) to NYSIIS/CIR, and requires **all** MMR vaccinations (any age) be reported to NYSIIS or CIR **within 72 hours** of administration |
| Education Law Article 139, Public Health Law §576-b, 10 NYCRR §58-1.7 | **Registered nurses** may order collection/testing of throat, nasopharyngeal, and urine specimens from suspected measles cases, and blood specimens for acute/past measles diagnosis |
| Education Law §6909(4), §6527(6), 8 NYCRR §64.7 | Physicians/NPs may issue a non-patient-specific regimen to nurses to **collect those specimens** and otherwise assist suspected/diagnosed measles patients |
| State Finance Law §112, §163, §97-G; Economic Development Law Art. 4-C | Emergency procurement/contracting flexibility (not directly data-relevant) |

The throughline: the order is rapidly **expanding who can vaccinate and who can order measles testing**,
outside the normal physician-centered workflow, and it is **tightening vaccination reporting speed** (72-hour
NYSIIS/CIR reporting, consent requirement suspended for adults). Both of those create new SHIN-NY-relevant
data problems and opportunities.

## 3. SHIN-NY Opportunity Ideas Surfaced by This Order

These are **beyond** the two ideas already built out in this folder (unreported potential-case candidate
detection, and contact-tracing MPI phone-number augmentation). Each ties directly to a provision above.

### 3a. Monitor the New 72-Hour MMR Reporting Mandate
The order now requires **every** MMR vaccination (not just minors, and without needing adult consent for the
report) to reach NYSIIS/CIR within 72 hours. SHIN-NY sees vaccination events in CCD/immunization data
independently of NYSIIS. **Idea:** cross-reference MMR administration events visible in SHIN-NY data against
NYSIIS/CIR to find vaccinations that are not showing up there within the 72-hour window, and flag the source
— this is a direct, measurable compliance-monitoring use of data SHIN-NY already has.

### 3b. Reconcile Immunization Records From New, Non-Traditional Vaccinators
EMS providers, midwives, pharmacists, and nurses acting under non-patient-specific orders can now give MMR in
places and from providers that may not have ever treated that patient before (e.g., a pop-up vaccination
clinic, an EMS-administered dose in the field). These encounters risk becoming **fragmented, orphaned
immunization records** that never get linked to the patient's longitudinal history. **Idea:** use SHIN-NY's
MPI matching to link these new-vaccinator encounters back to the patient's existing record, so a second
provider doesn't see an incomplete immunization history and over- or under-vaccinate.

### 3c. Let New Vaccinators Check Immunization History Before Dosing — NOW BUILT OUT
A pharmacist or EMT administering MMR under a non-patient-specific order may have **no visibility** into
whether this patient already received MMR. **Idea:** a lightweight lookup (manual or API) that lets an
authorized new-vaccinator type query SHIN-NY for "has this patient already had MMR, and when" before giving a
redundant dose — reduces unnecessary re-vaccination and supports the dosing decisions the order is now asking
non-physicians to make.

This idea has its own explore card and detail page now:
[`explore/immunization-lookup-for-vaccinators.html`](../immunization-lookup-for-vaccinators.html) — covering a
mini-portal for vaccinators who shouldn't get full SHIN-NY clinical access, plus a future immunization-only API
for larger organizations (e.g., CVS) that aren't already connected to the state's immunization systems.

### 3d. Specimen Collection and Testing Throughput Tracking
Registered nurses can now independently order measles specimen collection and testing. This likely increases
testing volume and could create new bottlenecks (lab turnaround, specimen routing). **Idea:** track specimen
collection to result turnaround time using lab (ORU) data SHIN-NY already receives, to help identify where
testing capacity is strained — a population-level operations signal, not a patient-level one.

### 3e. Geographic / Population Vaccination Coverage Gap Analysis
The order explicitly names the risk population: **under-immunized, rural communities in 18 counties**. SHIN-NY
holds longitudinal immunization data across sources. **Idea:** build a population-level (not patient-level)
view of MMR coverage gaps by county/region/practice, to help target where mobile vaccination clinics or
outreach would do the most good — directly supporting the "facilitate and administer vaccinations" purpose
the order cites as a reason state support is needed.

### 3f. Second-Dose (MMR #2) Catch-Up Identification
Since under-immunization is the named risk factor, patients who received a first MMR dose but never got the
second are a specific, identifiable population. **Idea:** use SHIN-NY immunization data to identify patients
with dose 1 but no dose 2, prioritized by proximity to the 18 affected counties, to support a catch-up
outreach campaign during the emergency window.

### 3g. Cross-Border Exposure Signal (Pennsylvania)
The order explicitly cites Pennsylvania's much larger outbreak (977 cases, 5 deaths) in counties bordering
NY as a driver of risk. **Idea:** for patients seen in NY border-county practices, treat recent out-of-state
travel/residence connections to the cited PA outbreak region as an additional (weak, corroborating) signal in
the existing unreported-candidate detection approach — not a new system, but an enrichment to 3b/the
candidate-detection scoring already described in `measles-candidate-detection.html`.

## 4. Why This Matters for Code Built From This Folder

If a developer (human or AI) builds real code against the ideas in `GUIDANCE.md`, this order is the concrete,
dated, legally-grounded reason the work matters right now — and it specifies **exactly which new provider
types, which reporting timelines, and which named counties** are relevant. Any implementation should treat
the 18 named counties and the 72-hour NYSIIS/CIR reporting requirement as real parameters to validate against,
not hypothetical ones.

**NY disaster emergency declarations are capped at 30 calendar days per declaration** under Executive Law
Article 2-B §28, and are routinely extended by a short follow-up order (e.g., a numbered "65.1") if the
underlying issue is still active, rather than being allowed to lapse. (See EO 57 → EO 57.1 for a recent
precedent of this pattern.) Any feature built specifically *because* of this order should track whether it
gets renewed, rather than assuming the underlying need has a fixed end date.
