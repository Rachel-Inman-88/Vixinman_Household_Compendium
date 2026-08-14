"""Statewide NM utility & AHJ directory — seed batch 10 data.

Source: the July 2026 verified reference set (docs/reference/), which
cross-checked and corrected the June 2026 documents. Verification marks
from the source carry into rule notes as "verify" warnings so they are
visible at point of use. See docs/reference/04_Manual_Review_Log.md for
every flagged item.
"""

# Canonical utility names offered on the job form (retail providers).
UTILITIES_ALL = [
    "MSMEC", "KCEC", "Springer Electric", "JMEC", "PNM", "N/A",
    "Xcel Energy (SPS)", "El Paso Electric", "CNMEC",
    "Continental Divide EC", "Otero County EC", "Sierra EC", "Socorro EC",
    "Farmers EC", "Central Valley EC", "Lea County EC",
    "Roosevelt County EC", "Columbus EC", "Southwestern EC", "NORA",
    "Navopache EC", "Duncan Valley EC", "Rio Grande EC", "NTUA",
    "Los Alamos DPU", "City of T or C", "FEUS", "Gallup Joint Utilities",
    "City of Aztec", "Raton Public Service",
]

COUNTIES_ALL = [f"{c} County" for c in (
    "Bernalillo", "Catron", "Chaves", "Cibola", "Colfax", "Curry", "De Baca",
    "Doña Ana", "Eddy", "Grant", "Guadalupe", "Harding", "Hidalgo", "Lea",
    "Lincoln", "Los Alamos", "Luna", "McKinley", "Mora", "Otero", "Quay",
    "Rio Arriba", "Roosevelt", "San Juan", "San Miguel", "Sandoval",
    "Santa Fe", "Sierra", "Socorro", "Taos", "Torrance", "Union", "Valencia",
)]

# Which retail electric utilities serve each county, listed with the most
# common first — from the verified "Utility by County" table in doc 03 (the
# July 2026 reference set). Co-op boundaries overlap, so several counties list
# more than one; the job form shows a county's utilities in the dropdown and
# the user picks the one on the customer's bill (a Manual override button opens
# the full statewide list for the rare non-standard case). Names match
# UTILITIES_ALL exactly.
COUNTY_UTILITIES = {
    "Bernalillo County": ["PNM", "CNMEC"],
    "Catron County": ["Navopache EC", "Socorro EC"],
    "Chaves County": ["Xcel Energy (SPS)", "Central Valley EC", "Lea County EC",
                      "Otero County EC", "Roosevelt County EC", "CNMEC"],
    "Cibola County": ["Continental Divide EC", "Socorro EC", "NTUA"],
    "Colfax County": ["Springer Electric", "KCEC", "Raton Public Service"],
    "Curry County": ["Xcel Energy (SPS)", "Farmers EC"],
    "De Baca County": ["Farmers EC", "CNMEC", "Roosevelt County EC"],
    "Doña Ana County": ["El Paso Electric"],
    "Eddy County": ["Central Valley EC", "Xcel Energy (SPS)", "Rio Grande EC"],
    "Grant County": ["PNM", "Columbus EC", "Duncan Valley EC"],
    "Guadalupe County": ["MSMEC", "CNMEC", "Farmers EC"],
    "Harding County": ["Springer Electric", "Southwestern EC"],
    "Hidalgo County": ["Columbus EC", "Duncan Valley EC"],
    "Lea County": ["Xcel Energy (SPS)", "Lea County EC"],
    "Lincoln County": ["PNM", "Otero County EC", "CNMEC"],
    "Los Alamos County": ["Los Alamos DPU"],
    "Luna County": ["Columbus EC", "El Paso Electric", "Sierra EC"],
    "McKinley County": ["Continental Divide EC", "Gallup Joint Utilities", "NTUA"],
    "Mora County": ["MSMEC", "KCEC", "Springer Electric"],
    "Otero County": ["Otero County EC", "PNM", "Central Valley EC", "Rio Grande EC"],
    "Quay County": ["Xcel Energy (SPS)", "Farmers EC", "Southwestern EC"],
    "Rio Arriba County": ["KCEC", "JMEC", "NORA"],
    "Roosevelt County": ["Xcel Energy (SPS)", "Roosevelt County EC", "Farmers EC"],
    "San Juan County": ["FEUS", "City of Aztec", "JMEC", "NTUA",
                        "Continental Divide EC"],
    "San Miguel County": ["MSMEC", "PNM", "Springer Electric"],
    "Sandoval County": ["PNM", "JMEC", "CNMEC", "NTUA"],
    "Santa Fe County": ["PNM", "JMEC", "MSMEC", "CNMEC"],
    "Sierra County": ["Sierra EC", "City of T or C"],
    "Socorro County": ["Socorro EC", "PNM"],
    "Taos County": ["KCEC"],
    "Torrance County": ["CNMEC"],
    "Union County": ["Southwestern EC", "Springer Electric"],
    "Valencia County": ["PNM", "Socorro EC", "CNMEC"],
}

# ---------------------------------------------------------------------------
# New utility contact rules (Link) and special-step rules (Compliance),
# keyed on the job's utility provider.
# ---------------------------------------------------------------------------
_U = "utility_provider"

UTILITY_RULES_V10 = [
    dict(field_name=_U, field_value="Xcel Energy (SPS)", category="Link",
         label="Xcel/SPS — DER Interconnection Portal",
         url="https://my.xcelenergy.com", link_text="Xcel Energy Portal",
         notes="eastern/SE NM (Clovis, Roswell, Carlsbad, Hobbs areas); SolarProgramNM@xcelenergy.com; NM Installer Guide on xcelenergy.com"),
    dict(field_name=_U, field_value="El Paso Electric", category="Link",
         label="EPE — DG Interconnection Portal",
         url="https://solarium3.epelectric.com/DGInterconnection/Forms/NM.aspx",
         link_text="EPE Interconnection Portal",
         phone="915-872-4595 / 575-526-5555",
         notes="Dona Ana County; smallrenewables@epelectric.com; AHJ inspection proof required; EPE inspects + sets meter before energizing"),
    dict(field_name=_U, field_value="El Paso Electric", category="Compliance",
         label="EPE application: $150 fee (1-25 kW); no Sign-Up NM/Budget Billing",
         url="https://www.epelectric.com", link_text="El Paso Electric",
         notes="customer must not be enrolled in Sign-Up NM or Budget Billing plans"),
    dict(field_name=_U, field_value="CNMEC", category="Link",
         label="CNMEC — Net Metering",
         url="https://www.cnmec.org/net-metering", link_text="CNMEC Net Metering",
         phone="505-832-4483 / 800-339-2521",
         notes="Simplified application (NM Interconnection Manual p.24) for most residential; over 25 kW email Clint Pierce; W-9 required for REC payments; verify reported monthly solar surcharge — not on current site"),
    dict(field_name=_U, field_value="Continental Divide EC", category="Link",
         label="Continental Divide EC — contacts",
         url="https://www.cdec.coop", link_text="Continental Divide EC",
         phone="505-285-6656 Grants / 505-863-3641 Gallup",
         notes="Cibola/McKinley + adjacent"),  # V11: co-op contacts verified (doc 03)
    dict(field_name=_U, field_value="Otero County EC", category="Link",
         label="Otero County EC — contacts",
         url="https://www.ote-coop.com", link_text="Otero County EC",
         phone="575-682-2521 / 800-548-4660",
         notes="Cloudcroft HQ; Alto 575-336-4550; Carrizozo 575-648-2352; billing@ote-coop.com"),
    dict(field_name=_U, field_value="Sierra EC", category="Link",
         label="Sierra EC — contacts",
         url="https://www.secpower.com", link_text="Sierra EC",
         phone="575-744-5231",
         notes="Elephant Butte; sierra@secpower.com"),
    dict(field_name=_U, field_value="Socorro EC", category="Link",
         label="Socorro EC — contacts",
         url="https://www.socorroelectric.com", link_text="Socorro EC",
         phone="575-835-0560 / 800-351-7575",
         notes="service@socorroelectric.com"),
    dict(field_name=_U, field_value="Farmers EC", category="Link",
         label="Farmers EC — contacts",
         url="https://www.fecnm.org", link_text="Farmers EC",
         phone="575-762-2116 / 800-445-8541",
         notes="Clovis-Fort Sumner area; verify domain"),
    dict(field_name=_U, field_value="Central Valley EC", category="Link",
         label="Central Valley EC — contacts",
         url="https://www.cvecoop.org", link_text="Central Valley EC",
         phone="575-746-3571 Artesia / 575-752-3366 Hagerman",
         notes="rural Eddy/Chaves; verify domain"),
    dict(field_name=_U, field_value="Lea County EC", category="Link",
         label="Lea County EC — contacts",
         url="https://www.lcecnet.com", link_text="Lea County EC",
         phone="575-396-3631 / 24-hr 800-510-5232",
         notes="Lovington; Tatum 575-398-2233"),
    dict(field_name=_U, field_value="Roosevelt County EC", category="Link",
         label="Roosevelt County EC — contacts",
         url="https://www.rcec.coop", link_text="Roosevelt County EC",
         phone="575-356-4491", notes="Portales"),
    dict(field_name=_U, field_value="Columbus EC", category="Link",
         label="Columbus EC — contacts",
         url="https://www.columbusco-op.org", link_text="Columbus EC",
         phone="575-546-8838 / 800-950-2667",
         notes="Deming; outage 800-228-0579"),
    dict(field_name=_U, field_value="Southwestern EC", category="Link",
         label="Southwestern EC — contacts",
         url="https://www.swec-coop.org", link_text="Southwestern EC",
         phone="575-374-2451 / 866-374-2451", notes="Clayton"),
    dict(field_name=_U, field_value="NORA", category="Link",
         label="Northern Rio Arriba EC — contacts",
         url="https://www.noraelectric.org", link_text="NORA Electric",
         phone="575-756-2181",
         notes="Chama area; nora@noraelectric.org"),
    dict(field_name=_U, field_value="Navopache EC", category="Link",
         label="Navopache EC — contacts",
         url="https://www.navopache.org", link_text="Navopache EC",
         phone="575-533-6328 Reserve / 800-543-6324",
         notes="Catron County (AZ-based co-op)"),
    dict(field_name=_U, field_value="Duncan Valley EC", category="Link",
         label="Duncan Valley EC — contacts",
         phone="928-359-2503 / 800-669-2503",
         notes="Grant/Hidalgo counties (AZ-based co-op)"),
    dict(field_name=_U, field_value="Rio Grande EC", category="Link",
         label="Rio Grande EC — contacts",
         phone="830-563-2444 / 800-749-1509",
         notes="Eddy/Otero fringes (TX-based co-op)"),
    dict(field_name=_U, field_value="NTUA", category="Link",
         label="NTUA — Navajo Tribal Utility Authority",
         url="https://www.ntua.com", link_text="NTUA",
         phone="800-528-5011",
         notes="Navajo Nation; tribal permitting applies — CID does NOT; no public net-metering contact — verify per project"),
    dict(field_name=_U, field_value="Los Alamos DPU", category="Compliance",
         label="Los Alamos DPU: Customer-Owned Generation application",
         url="https://www.losalamosnm.gov/Business/Apply-for-a-permit/Solar-Power-Installation",
         link_text="Los Alamos DPU Solar Page",
         phone="505-662-8035 (Mariano Valdez)",
         notes="NOT under NMPRC Rule 568: 10 kW cap; system sized to prior 12-month usage; wholesale-rate credits; DPU approval before Community Development permit"),
    dict(field_name=_U, field_value="City of T or C", category="Link",
         label="City of T or C Electric — interconnection",
         url="https://www.torcnm.org", link_text="City of T or C Solar Page",
         phone="575-894-6673 ext. 372",
         notes="municipal utility; simplified path up to 10 kW, standard above; all paperwork before interconnection; written approval before parallel operation"),
    dict(field_name=_U, field_value="FEUS", category="Compliance",
         label="FEUS: CONFIRM net-metering status before quoting",
         url="https://www.fmtn.org", link_text="City of Farmington",
         notes="conflicting information (2017 closure vs 2022 net-metering rates) — call FEUS before any Farmington sale; new systems likely bidirectional metering at non-1:1 credit"),
    dict(field_name=_U, field_value="Gallup Joint Utilities", category="Link",
         label="Gallup Joint Utilities — contacts",
         url="https://utilities.gallupnm.gov", link_text="Gallup Joint Utilities",
         phone="505-863-1241 (city hall)",  # V11: city-hall line no longer flagged (doc 02/03)
         notes="municipal electric; net metering offered — verify current terms"),
    dict(field_name=_U, field_value="City of Aztec", category="Link",
         label="City of Aztec Electric — contacts",
         url="https://www.aztecnm.gov", link_text="City of Aztec",
         phone="505-334-7670",
         notes="verify interconnection/net-metering terms — not published online"),
    dict(field_name=_U, field_value="Raton Public Service", category="Link",
         label="Raton Public Service — contacts",
         url="https://www.ratonnm.gov", link_text="Raton Public Service",
         phone="575-445-9861",
         notes="serves Raton city; verify solar/net-metering terms — not published online"),
]

# ---------------------------------------------------------------------------
# County AHJ rules. Plain CID-default counties share one label (only one
# fires per job); counties with their own permit functions get specific
# rules. Trade permits always via the CID ePermit portal.
# ---------------------------------------------------------------------------
_CID_PORTAL = "https://nmrld.my.site.com/MHD/s/"
_CID_LABEL = "CID is your AHJ — structural permits via CID portal"

_PLAIN_CID_COUNTIES = {
    "Catron County": "no local LEA; remote — allow 5-10 business days for inspections; federal land excluded from CID",
    "Chaves County": "City of Roswell 575-624-6700 in-city; rural via CID (Roswell area)",
    "Cibola County": "City of Grants 505-287-7927; Acoma & Laguna Pueblo lands excluded — tribal building officials",
    # Several in-city phones below were carried from doc 04's "could not verify"
    # list in V10; V11 replaces them with doc 02's verified-body numbers.
    "Curry County": "City of Clovis Building & Safety 575-769-7829 in-city",
    "De Baca County": "no county building dept; Fort Sumner village 575-355-2401",
    "Eddy County": "Carlsbad 575-887-1191; Artesia 575-746-2122 in-city",
    "Grant County": "Silver City 575-534-6348 (townofsilvercity.org); county Planning 575-574-0018",
    "Hidalgo County": "Lordsburg 575-542-3421",
    "Lea County": "Hobbs 575-397-9200 (hobbsnm.gov); Lovington 575-396-2884 in-city",
    "Luna County": "City of Deming 575-546-8848 in-city",
    "McKinley County": "Gallup 505-863-1241; county planning 505-863-6866; Navajo Nation & Zuni Pueblo excluded — Navajo Building Codes 928-871-6380",
    "Otero County": "Alamogordo 575-439-4100; Cloudcroft 575-682-2411; Holloman AFB + Mescalero Apache lands excluded",
    "Quay County": "Tucumcari 575-461-3451 — confirm permit function",
    "Roosevelt County": "City of Portales 575-356-6662 in-city",
    "Sierra County": "City of T or C 575-894-6673 ext. 353 in-city",
    "Socorro County": "City of Socorro 575-835-0240 in-city",
    "Torrance County": "Moriarty 505-886-3020; Estancia 505-384-2708; CID Santa Fe office",
    "Union County": "Clayton 575-374-8896 ext 4 — confirm municipal function",
    "Valencia County": "Belen 505-966-2745; Los Lunas 505-839-3840; Isleta Pueblo excluded 505-869-3111; CID Albuquerque office",
}

COUNTY_RULES_V10 = [
    dict(field_name="county", field_value=county, category="Link",
         label=_CID_LABEL, url=_CID_PORTAL,
         link_text="NM CID Online Permit Portal",
         phone="877-243-0979", notes=notes)
    for county, notes in _PLAIN_CID_COUNTIES.items()
] + [
    dict(field_name="county", field_value="Bernalillo County", category="Link",
         label="Bernalillo County AHJ — Albuquerque is an LEA",
         url="https://www.cabq.gov/planning/building-safety-division",
         link_text="ABQ Building Safety Division",
         phone="505-924-3320",
         notes="in-city: ABQ Building Safety (Tyler EnerGov portal; request current roof-solar checklist — old PDF is dead; PV over 200A needs NM EE stamp; commercial PV = plan review); unincorporated: county Planning 505-314-0350 + Accela portal; trade permits via CID"),
    dict(field_name="county", field_value="Sandoval County", category="Link",
         label="Sandoval County AHJ — zoning first, then CID; Rio Rancho is an LEA",
         url="https://rrnm.gov/77/Building-Division",
         link_text="Rio Rancho Building Division",
         phone="RR 505-891-5006 / county P&Z 505-867-7628",
         notes="county P&Z issues zoning compliance FIRST, then CID building permit; Rio Rancho requires PNM Notice of Complete + Technical Screening Review copies BEFORE permit application; pueblo & Navajo chapter lands excluded"),
    dict(field_name="county", field_value="Lincoln County", category="Permit",
         label="Lincoln County Building Dept permit (unincorporated)",
         phone="575-258-1232",  # V11: doc 02 verified body
         notes="300 Central Ave, Carrizozo; Ruidoso 575-258-4343; Ruidoso Downs 575-378-4422 in-city"),
    dict(field_name="county", field_value="San Juan County", category="Link",
         label="San Juan County AHJ — Farmington is an LEA",
         url="https://www.fmtn.org", link_text="City of Farmington",
         phone="Farmington 505-327-7701 / county 505-334-4550",  # V11: doc 02 verified body
         notes="Aztec 505-334-7605; Bloomfield 505-632-6300; Navajo Nation land excluded; FEUS net-metering status must be confirmed before quoting"),
    dict(field_name="county", field_value="Los Alamos County", category="Permit",
         label="Los Alamos Community Development permit",
         url="https://www.losalamosnm.gov/Business/Apply-for-a-permit/Solar-Power-Installation",
         link_text="Los Alamos Solar Permit Page",
         phone="505-662-8120",
         notes="entire county is one incorporated entity; trades via CID; DPU approval required before the Community Development permit"),
    dict(field_name="county", field_value="Doña Ana County", category="Link",
         label="Doña Ana AHJ — Las Cruces is an LEA",
         url="https://www.lascruces.gov/2220/Apply-for-a-Permit",
         link_text="Las Cruces Permit Portal",
         phone="LC 575-528-3059 / county 575-647-7350",
         notes="Las Cruces expedited over-the-counter residential PV (up to 10 kW, no batteries, load-side); commercial always full plan review; CID Las Cruces office 575-524-6320"),
]

# ---------------------------------------------------------------------------
# Other new rules
# ---------------------------------------------------------------------------
OTHER_RULES_V10 = [
    dict(field_name="tax_credit", field_value="Yes", category="Compliance",
         label="Confirm tax-credit eligibility BEFORE quoting",
         url="https://www.irs.gov/credits-deductions/residential-clean-energy-credit",
         link_text="IRS — Residential Clean Energy Credit",
         notes="federal residential ITC (25D) EXPIRED for expenditures after 12/31/2025 (P.L. 119-21); NSMDTC 10%/$6,000 active; commercial 48E deadlines tightened — client should consult a tax professional"),
    dict(field_name="pv_mounting_type", field_value="Ground mount",
         category="License",
         label="GB-2 / GB-98 General Building License",
         url="https://www.rld.nm.gov/about-us/public-information-hub/verify-a-license/",
         link_text="NM CID — Verify a License",
         notes="ground-mount racking structures (also applies to roof structural reinforcement work)"),
]

NEW_RULES_V10 = UTILITY_RULES_V10 + COUNTY_RULES_V10 + OTHER_RULES_V10

# ---------------------------------------------------------------------------
# Corrections to existing rules (Manual Review Log items A1-A22 + B1).
# No apostrophes in any SQL string literal.
# ---------------------------------------------------------------------------
CORRECTIONS_V10 = [
    # A9: NMPRC domain is dead — repoint every rule using it.
    "UPDATE resource_rules SET url = 'https://www.prc.nm.gov',"
    " link_text = 'NM PRC — Electric Utility Rules (17.9.568)'"
    " WHERE url LIKE '%nmprc.state.nm.us%'",
    # A22: srca.nm.gov pages now use .html
    "UPDATE resource_rules SET url = 'https://www.srca.nm.gov/parts/title14/14.010.0004.html'"
    " WHERE url = 'https://www.srca.nm.gov/parts/title14/14.010.0004.htm'",
    "UPDATE resource_rules SET url = 'https://www.srca.nm.gov/parts/title10/10.025.0005.html'"
    " WHERE url = 'https://www.srca.nm.gov/parts/title10/10.025.0005.htm'",
    # A10 + B1: EMNRD path moved; 20% battery tier unconfirmed — correct the merged SMDTC rule.
    "UPDATE resource_rules SET"
    " label = 'NSMDTC Application (10%, max $6,000)',"
    " url = 'https://www.emnrd.nm.gov/ecmd/tax-incentives/solar-market-development-tax-credit/',"
    " link_text = 'NM EMNRD — NSMDTC',"
    " notes = 'client files; 10% of equipment+materials+labor per current EMNRD page; the 20%/$12,000 battery tier is NOT confirmed — do not quote until verified with EMNRD'"
    " WHERE label = 'SMDTC 20% Credit Application'",
    # D1: CID short URL
    "UPDATE resource_rules SET url = 'https://www.rld.nm.gov/construction-industries/'"
    " WHERE url = 'https://www.rld.nm.gov/construction-industries-public-works/construction-industries/'",
    # License rules point at the verification page (actionable per tech).
    "UPDATE resource_rules SET"
    " url = 'https://www.rld.nm.gov/about-us/public-information-hub/verify-a-license/',"
    " link_text = 'NM CID — Verify a License'"
    " WHERE category = 'License' AND url = 'https://www.rld.nm.gov/construction-industries/'",
    # D7 + B9: MHD division URL + permitting phones
    "UPDATE resource_rules SET"
    " url = 'https://www.rld.nm.gov/manufactured-housing-division/',"
    " link_text = 'NM Manufactured Housing Division',"
    " phone = '505-476-4614 SF / 505-222-9870 ABQ / 575-270-2433 LC',"
    " notes = 'manufactured homes; DAPIA approval pages FIRST; mhd.compliance@rld.nm.gov'"
    " WHERE label = 'MHD Permit'",
    # LP Gas Bureau direct page + phone
    "UPDATE resource_rules SET"
    " url = 'https://www.rld.nm.gov/construction-industries/find-a-bureau/bureaus/lp-gas/',"
    " link_text = 'NM CID — LP Gas Bureau', phone = '505-222-9808',"
    " notes = 'if gas-fueled; cid.lpgas@rld.nm.gov'"
    " WHERE label = 'LP-4/LP-5 or MM-2 Gas License'",
    # Inspections: CID central inspection-request channel (inspectors no
    # longer take direct requests).
    "UPDATE resource_rules SET"
    " url = 'https://www.rld.nm.gov/construction-industries/inspection-request/',"
    " link_text = 'CID Inspection Request', phone = '505-222-9813',"
    " notes = 'request via CID.Inspection@rld.nm.gov or the online form — individual inspectors no longer accept direct requests'"
    " WHERE label IN ('Rough-in Inspection', 'Final Inspection', 'Electrical Inspection')",
    # A1/A2: MSMEC phones corrected
    "UPDATE resource_rules SET phone = '575-387-2205 / 800-421-6773',"
    " notes = 'two tiers (up to 10 kW / over 10 kW); customer signs; approval before construction; Pecos district 505-757-6490; rebates thernandez@morasanmiguel.coop (verify contact)'"
    " WHERE label = 'MSMEC — Interconnection Forms Hub'",
    # PNM: dedicated solar line + process facts
    "UPDATE resource_rules SET phone = '505-241-2750 solar line / 888-342-5766'"
    " WHERE label = 'PNM — Solar Interconnection & Net Metering'",
    "UPDATE resource_rules SET"
    " phone = '505-241-2750 (M-F 7:30-3:30)',"
    " notes = 'SolarPV@pnmresources.com; customer signs; $50 fee under 100 kW (verify current); IEEE 1547-2018 inverters required since 3/2024; nine months to complete after technical screening; visible-air-gap lockable disconnect; weatherproof one-line at point of service; Rio Rancho permits need Notice of Complete + Technical Screening copies first'"
    " WHERE label = 'PNM portal application — customer-signed, $50 fee (<100 kW)'",
    # KCEC hub currency warning
    "UPDATE resource_rules SET"
    " notes = 'full application after pre-screening approval; NM Interconnection Manual p.24; hub page last updated 2022 — verify form currency at job start'"
    " WHERE label = 'KCEC — Net-Metering Hub & Applications'",
    # JMEC: fee + verified contact
    "UPDATE resource_rules SET"
    " phone = '505-753-2105 / 888-755-2105; Jeanelle Anaya 505-367-1144',"
    " notes = 'all-in-one packet; $50 application fee; net metering up to 30 kW, 1:1 credit, April settle-up; janaya@jemezcoop.org'"
    " WHERE label = 'JMEC — Solar Applications & Requirements Packet'",
    # GRT: statute citation
    "UPDATE resource_rules SET"
    " notes = 'cite NMSA 7-9-112 (reg 3.2.247 NMAC) on every invoice'"
    " WHERE label = 'GRT Exemption on Invoice'",
    # OSE: district + coordinator contact
    "UPDATE resource_rules SET"
    " phone = '575-376-2918 (District VII, Cimarron)',"
    " notes = 'well drilling is outside Vixinman scope — subcontract to an OSE-licensed driller; new wells only; driller license coordinator nm.driller@ose.nm.gov (verify contact)'"
    " WHERE label = 'New well? OSE well drilling permit — SUBCONTRACT'",
    # NMED: Hermits Peak program caveat
    "UPDATE resource_rules SET"
    " notes = 'new wells only; drilling contractor scope; Hermits Peak burn-scar free testing (Mora/San Miguel/Taos) — verify program still active'"
    " WHERE label = 'New well? NMED water quality testing — subcontracted scope'",
    # CID dispatch uncertainty (B5/B6) on the shared CID-AHJ rules
    "UPDATE resource_rules SET"
    " notes = notes || '; CID regional dispatch unconfirmed — call 877-243-0979'"
    " WHERE label = 'CID is your AHJ — structural permits via CID portal'"
    " AND field_value IN ('Mora County', 'San Miguel County', 'Colfax County', 'Harding County', 'Guadalupe County')",
    # A5: Santa Fe city line on the county rule; Taos municipal contacts + pueblo caveat
    "UPDATE resource_rules SET"
    " notes = 'unincorporated county: required for PV even without structural work; online via geocivix; expedited ~5 days; David Ruiz 505-986-6371; City of Santa Fe is an LEA — 505-955-6571, permitcounter@santafenm.gov'"
    " WHERE label = 'Santa Fe County Development Permit (PV Solar)'",
    "UPDATE resource_rules SET"
    " notes = 'unincorporated county: required before the building permit; call office after online submittal; $80 re-inspection fee; Town of Taos 575-751-2017, Taos Ski Valley 575-776-8220 x4, Red River 575-754-2277 have own AHJs; Taos Pueblo sovereign — CID/county codes do not apply'"
    " WHERE label = 'Taos County Solar Array Zoning Clearance — FIRST'",
    "UPDATE resource_rules SET"
    " notes = 'single form covers solar/residential; 3-5 days; site visit arranged; NMDOT access permit if state road involved; Espanola 505-747-6100 in-city; NORA serves the Chama area'"
    " WHERE label = 'Rio Arriba County Development Permit'",
]

# ---------------------------------------------------------------------------
# Batch 11 — reconcile against the VERIFIED BODY of docs 01-03 (the user
# confirmed 01-03; 00 and 04 were unchanged). Two kinds of fix:
#   (a) county in-city phones carried from doc 04's "could not verify" list in
#       V10 are replaced with doc 02's verified-body numbers, and
#   (b) items docs 01-03 now show verified lose their stale "verify" flag.
# County updates are generated straight from the corrected _PLAIN_CID_COUNTIES
# dict so the migration always matches the seed. Each update is keyed on
# (label, field_value) for precision. No apostrophes in any SQL literal.
# ---------------------------------------------------------------------------
_V11_COUNTY_FIXES = [
    "Curry County", "De Baca County", "Eddy County", "Grant County",
    "McKinley County", "Otero County", "Torrance County", "Union County",
    "Valencia County",
]

CORRECTIONS_V11 = [
    "UPDATE resource_rules SET notes = '{}'"
    " WHERE label = '{}' AND field_value = '{}'".format(
        _PLAIN_CID_COUNTIES[c].replace("'", ""), _CID_LABEL, c)
    for c in _V11_COUNTY_FIXES
] + [
    # Lincoln County — doc 02 verified: building dept 575-258-1232, Ruidoso 575-258-4343
    "UPDATE resource_rules SET phone = '575-258-1232',"
    " notes = '300 Central Ave, Carrizozo; Ruidoso 575-258-4343; Ruidoso Downs 575-378-4422 in-city'"
    " WHERE label = 'Lincoln County Building Dept permit (unincorporated)'",
    # San Juan County — doc 02 verified LEA/county/city numbers
    "UPDATE resource_rules SET phone = 'Farmington 505-327-7701 / county 505-334-4550',"
    " notes = 'Aztec 505-334-7605; Bloomfield 505-632-6300; Navajo Nation land excluded; FEUS net-metering status must be confirmed before quoting'"
    " WHERE label = 'San Juan County AHJ — Farmington is an LEA'",
    # Continental Divide EC — doc 03 verifies the co-op contacts; drop stale domain flag
    "UPDATE resource_rules SET notes = 'Cibola/McKinley + adjacent'"
    " WHERE label = 'Continental Divide EC — contacts'",
    # Gallup Joint Utilities — doc 02/03 no longer flag the city-hall line
    "UPDATE resource_rules SET phone = '505-863-1241 (city hall)'"
    " WHERE label = 'Gallup Joint Utilities — contacts'",
    # KCEC — doc 03 verifies the net-metering hub as current (July 2026)
    "UPDATE resource_rules SET"
    " notes = 'pre-screening application required FIRST, then full application (NM Interconnection Manual p.24); net-metering hub verified current July 2026; over 25 kW contact Richard Martinez (verify)'"
    " WHERE label = 'KCEC — Net-Metering Hub & Applications'",
]
