# 01 — STATEWIDE LICENSING & COMPLIANCE REFERENCE
*Applies in every NM county. Compiled July 2026 from the June 2026 Compliance Reference Guide + Website List, verified against state/federal sources. See `04_Manual_Review_Log.md` for all flags.*

---

## SECTION 1 — CID: STATEWIDE TRADE PERMIT & LICENSING AUTHORITY

### CID Offices ✅ (verified at rld.nm.gov/construction-industries/, July 2026)

| Office | Address | Phone |
|---|---|---|
| Santa Fe (HQ) | 2550 Cerrillos Road, 3rd Floor, Santa Fe, NM 87505 | (505) 476-4700 |
| Albuquerque | 5500 San Antonio Dr. Suite F, Albuquerque, NM 87109 | (505) 222-9800 ✏️ CORRECTED (docs listed 505-476-4700) |
| Las Cruces | 505 South Main Street, Suite 103, Loretto Town Center, Las Cruces, NM 88001 | (575) 524-6320 ✏️ CORRECTED (docs listed no phone/suite) |

- Statewide toll-free: **877-CID-0979 (877-243-0979)** ✅
- Inspection requests: **CID.Inspection@rld.nm.gov** \| (505) 222-9813 \| online form ✅ — individual inspectors no longer accept requests directly
- ⚠ VERIFY: The zip 87504 appearing in two source docs is the P.O. Box zip; the street address zip is 87505.

### Key CID URLs

| Resource | URL | Status |
|---|---|---|
| CID main page | https://www.rld.nm.gov/construction-industries/ | ✅ (the longer `construction-industries-public-works` URL in two docs reaches the same page) |
| ePermit portal (trade permits statewide) | https://nmrld.my.site.com/MHD/s/ | ✅ live (Salesforce portal; also hosts public permit search). ⚠ VERIFY: legacy portal citizenportal.rld.state.nm.us ("NM ePermits") still resolves — confirm with CID which one applies to your permit type |
| License verification | https://www.rld.nm.gov/about-us/public-information-hub/verify-a-license/ | ✅ |
| Inspection request | https://www.rld.nm.gov/construction-industries/inspection-request/ | ✅ |
| LP Gas Bureau | https://www.rld.nm.gov/construction-industries/find-a-bureau/bureaus/lp-gas/ | ✅ (505) 222-9808 \| cid.lpgas@rld.nm.gov \| Bureau Chief James Morrison (505) 795-1632 |
| Manufactured Housing Division | https://www.rld.nm.gov/manufactured-housing-division/ | ✅ Permitting: Santa Fe (505) 476-4614 · ABQ (505) 222-9870 · Las Cruces (575) 270-2433 · mhd.compliance@rld.nm.gov. ⚠ VERIFY: docs' plan-review email MHDPlan.Review@state.nm.us not found on current site |

### CID Regional Field Offices / Inspector Dispatch ⚠ VERIFY
The regional-office table in the source docs (Las Vegas 2518 Ridgerunner Rd; Roswell 400 N Pennsylvania Ave Suite 441; etc.) could not be confirmed on the current rld.nm.gov site, which lists only Santa Fe, Albuquerque, and Las Cruces offices. The source docs also conflict on which office serves Mora/San Miguel (one says Las Vegas regional office, two say Santa Fe). **Action: call 877-243-0979 to confirm current inspector dispatch for each county.** Remote counties (Catron, Hidalgo, Harding, De Baca, Guadalupe, Quay, Union): plan 3–10 business days for inspections.

## SECTION 2 — LICENSE CLASSIFICATIONS (verified structure; details per NMAC 14.5.2)

| License | Trade | Key Scope |
|---|---|---|
| EE-98 | Electrical | All electrical up to 5,000V — PV, generators, batteries, well pumps (subsumes ES-10R/ES-10) |
| ER-1 | Electrical (residential) | One- and two-family dwellings only |
| MM-3 | HVAC | Mini splits, heat pumps, condensing units, ductwork, controls ≤24V |
| MM-2 | Residential mechanical / natural gas | Residential HVAC and natural-gas piping |
| MM-1 | Mechanical unlimited / plumbing | All mechanical; interior plumbing distribution |
| ES-10R / ES-10 | Well pump | Residential 120/240V ≤15 HP / commercial ≤600V |
| LP-4 / LP-5 | LP Gas | Propane appliances & piping / expanded incl. containers, mobile homes |
| GB-98 / GB-2 / GS-13 | General building | Ground-mount racking structures, roof structural reinforcement |

- Journeyman certificates required per technician (EE-98J, JH, ES-10RJ, etc.); supervision ratios 1:3 residential, 1:2 commercial.
- Exams: PSI — candidate.psiexams.com \| ⚠ UNVERIFIED phone 855-807-3994 (MHD licensing via PSI: 877-663-9267 ✅)
- $10,000 surety bond; license auto-cancels 40 days after bond lapse notice to CID. 16 CE hours / 3-year renewal (EE-98, MM-3); report address changes within 30 days.
- NMAC full text: https://www.srca.nm.gov/parts/title14/14.010.0004.html ✅ ⚠ NOTE: source docs use `.htm` extensions for srca.nm.gov links; current pages use `.html`.

## SECTION 3 — CODES IN FORCE ✅

| Code | NM Adoption | Status |
|---|---|---|
| NEC 2020 (NFPA 70) | 14.10.4 NMAC, effective 3/28/2023 | ✅ CONFIRMED still 2020 edition as of July 2026 |
| IFC 2021 (incl. Ch. 12 Energy Systems, NFPA 855 by reference) | 10.25.5 NMAC (State Fire Marshal) | ⚠ VERIFY edition with local FAHJ; NFPA 855-2026 published 9/2025 but NM adoption unconfirmed |
| IMC 2021 | 14.10.3 NMAC | ⚠ UNVERIFIED |
| IEEE 1547-2018 inverters | Required for new interconnection applications | ✅ PNM requires as of March 2024 |

Key thresholds (unchanged from source docs, code-based): PE stamp >100 kVA 1-φ / >225 kVA 3-φ; rapid shutdown NEC 690.12 roof-mounts (ground-mount exempt — document on plans); double-125% conductor sizing; cold-temperature Voc correction per NEC 690.7 (always in northern NM); ESS per NEC 706 + UL 9540 listing + exterior emergency shutdown on 1–2-family dwellings; NFPA 37 generator clearances (5 ft openings / 10 ft exhaust); burial depths RMC 6" / PVC-80 18" / PVC-40 24" / direct-burial 24".

## SECTION 4 — PERMIT TYPES BY JOB (statewide logic)

| Job | Permit(s) | Issuer | License |
|---|---|---|---|
| Solar PV electrical | Electrical | CID portal or LEA | EE-98 / ER-1 |
| Solar PV roof structural | Building (if reinforcement) | Local AHJ or CID | GB-2 or sub |
| Solar PV ground-mount | Building (structure) | Local AHJ or CID | GB-2 or sub |
| Battery / ESS | Electrical (+ fire review) | CID portal or LEA + FAHJ | EE-98 |
| Generator electrical | Electrical | CID portal or LEA | EE-98 / ER-1 |
| Generator LP gas | LP gas | CID LP Gas Bureau | LP-4 / LP-5 |
| Generator natural gas | Mechanical | CID or LEA | MM-2 |
| Mini split | Mechanical + Electrical | CID or LEA | MM-3/MM-2 + EE-98/ER-1 |
| Well pump | Electrical (+ plumbing if house connection) | CID or LEA | ES-10R/ES-10/EE-98 (+MM-1) |
| Manufactured home roof PV | MHD permit + electrical permit; DAPIA approval pages FIRST | MHD + AHJ | + PE letter |

**OSE (wells):** Well drilling/permits are OSE scope, separate from CID. ✅ District VII, 301 East 9th Street / P.O. Box 481, Cimarron, NM 87714 \| (575) 376-2918 — covers Clayton, Tucumcari, Canadian River basins (northeastern NM). Well Driller License Coordinator: ⚠ VERIFY Robert Helton, (505) 827-7838, nm.driller@ose.nm.gov. https://www.ose.nm.gov/WR/well_drilling.php

**EPA Section 608** ✅ epa.gov/section608 — per-technician certification, applies on every refrigerant touch. AIM Act: new residential HVAC refrigerant GWP <750 since 1/1/2025 (R-454B, R-32 — A2L handling training required).

## SECTION 5 — INCENTIVES & TAX (verified July 2026)

| Incentive | Amount | Status |
|---|---|---|
| NM New Solar Market Development Tax Credit (NSMDTC) | **10% of equipment+materials+labor, max $6,000** | ✅ per EMNRD page (dated 2/5/2026). Apply at https://www.emnrd.nm.gov/ecmd/tax-incentives/solar-market-development-tax-credit/ (portal: wwwapps.emnrd.nm.gov/ECMD/NSMDSubmissions). ✏️ CORRECTED: docs' URL path `/sed/renewable-energy/` is outdated |
| "Solar + Battery ≥15 kWh = 20% credit up to $12,000/yr" | — | ⚠ VERIFY — **NOT found on the current EMNRD page.** Do not quote to customers until confirmed with EMNRD |
| Annual statewide cap "$30M" / "eligible through 2031" | — | ⚠ VERIFY — not shown on EMNRD page; confirm against current statute |
| Federal residential ITC (25D) | **Expired — no credit for expenditures after Dec 31, 2025** | ✅ confirmed, IRS OBBB FAQ (P.L. 119-21, July 4, 2025) |
| Federal commercial ITC (48E) | 30% with placed-in-service/construction deadlines | ⚠ VERIFY project-by-project — OBBB tightened timelines for wind/solar; consult tax professional |
| GRT deduction — solar systems | Full deduction on qualifying equipment + labor | ✅ NMSA 7-9-112 exists (implementing reg 3.2.247 NMAC). Cite on every invoice |
| Property tax exemption (residential solar) | Value excluded from assessment | ⚠ UNVERIFIED (NMSA 7-36-27.1 — not re-checked; low risk) |

## SECTION 6 — SERVICE & WARRANTY WORK (carried forward from source guide — code-based, low change risk)
License scope covers install/alter/repair/service. Component repair (filters, motors, boards, refrigerant top-off) = no permit; equipment replacement/relocation or wiring modification = permit. EPA 608 on every refrigerant touch. Track staggered 3-year renewals; bond continuity; workers' comp endorsement for roof/energized work; keep service records, permits, as-builts; verify manufacturer authorized-dealer status; identify tribal land at intake.

## SECTION 7 — CROSS-CUTTING STATE CONTACTS

| Agency | Contact | Status |
|---|---|---|
| NM PRC (utility regulation, Rule 17.9.568) | **https://www.prc.nm.gov** \| 1-888-427-5772 | ✅ ✏️ CORRECTED: nmprc.state.nm.us (in Website List doc) is a **dead domain** |
| NM State Fire Marshal | dhsem.nm.gov/state-fire-marshal/ | ⚠ UNVERIFIED |
| NM Taxation & Revenue | tax.newmexico.gov | ✅ (domain live) |
| NM EMNRD / ECMD | emnrd.nm.gov | ✅ |
| NMED (Hermits Peak free well testing — Mora, San Miguel, Taos) | env.nm.gov/drinking-water/hermits-peak-calf-canyon/ | ⚠ UNVERIFIED — program continuation not re-checked |
| NM Secretary of State (business reg.) | sos.nm.gov/business-services/ | ⚠ UNVERIFIED |
| Workers' Comp Administration | workerscomp.nm.gov | ⚠ UNVERIFIED |
| NM Indian Affairs Dept | iad.state.nm.us | ⚠ UNVERIFIED — state agency URLs migrating off state.nm.us; check for .gov successor |
