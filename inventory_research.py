"""Piece 23.3: web-research overrides for the seed inventory, applied on top of
inventory_seed.py. Each entry corrects/completes specs, attaches datasheet
(manual_url) and purchase (purchase_url) links, records a web-verified price
where one can be fetched, sets Active/Discontinued, and carries a human-readable
flag. Bumping RESEARCH_VERSION re-applies the whole set on next launch.

Ground rules honored here:
- Never overwrite Vixinman's quoted Cost — web prices go in web_price only.
- Never fabricate: unverifiable prices/URLs are left blank and flagged.
- Wholesale-only vendors (ABC Supply, Greentech, BayWa, Fortune) rarely have a
  public per-item page, so purchase_url points at the best public retail listing
  for that exact item, flagged as reference (not necessarily the listed vendor).

Key format: "Category||Make||Model" (exactly as seeded).
"""

RESEARCH_VERSION = 6

RESEARCH = {
    # --- PV sheet — calibration batch -------------------------------------
    "PV Module||Canadian Solar||CS6P 260W Module": {
        "specs": {"Vmp": 30.4, "Imp": 8.56, "Voc": 37.5, "Isc": 9.12},
        "manual_url": "https://s3.amazonaws.com/ecodirect_docs/CANADIAN/"
                      "canadian-solar-cs6p-m-250-260-all-black-data-sheet-151231.pdf",
        "status": "Discontinued",
        "flags": "SPEC CORRECTION — sheet had Vmp 17 / Imp 5.0 / Voc 20 / Isc 5.1 "
                 "(incorrect); CS6P-260P datasheet: Vmp 30.4 / Imp 8.56 / Voc 37.5 "
                 "/ Isc 9.12. Legacy poly module.",
    },
    "PV Module||ET||ET 250": {
        "specs": {"Vmp": 30.34, "Imp": 8.24, "Voc": 37.47, "Isc": 8.76},
        "manual_url": "https://www.solaris-shop.com/"
                      "et-solar-et-p660250wb-250w-poly-solar-panel/",
        "status": "Discontinued",
        "flags": "SPECS COMPLETED from ET-P660250 datasheet (sheet had wattage "
                 "only). Full model likely ET-P660250(WB). Legacy poly module.",
    },
    "PV Module||Canadian Solar||CS7N-710TB-AG": {
        "manual_url": "https://static.csisolar.com/wp-content/uploads/sites/3/2024/"
                      "03/29101600/CS-Datasheet-TOPBiHiKu7-TOPCon_CS7N-TB-AG_"
                      "v1.61_F43M_J5_NA.pdf",
        "purchase_url": "https://a1solarstore.com/canadian-solar-710w-solar-panel-"
                        "132-cells-bifacial-cs7n-tb-ag-710-commercial-496-panels-"
                        "per-container.html",
        "status": "Active",
        "flags": "VERIFY Voc — sheet Voc 48.3 / Vmp 40.4 vs current datasheet STC "
                 "Voc 45.7 / Vmp 38.1 / Isc 14.99 / Imp 14.06 (front-side). Use "
                 "front-side STC for cold-temp string sizing. Retail listing shown "
                 "(A1 SolarStore); listed vendor N. AZ Wind & Sun also stocks it. "
                 "Price on request.",
    },
    "PV Module||Mission Solar||MSE410HTOB": {
        "manual_url": "https://www.solarelectricsupply.com/"
                      "mission-solar-410w-mse410ht0b-residential-solar-module",
        "purchase_url": "https://www.solarelectricsupply.com/"
                        "mission-solar-410w-mse410ht0b-residential-solar-module",
        "status": "Active",
        "flags": "Listed vendor ABC Supply is wholesale (no public per-item page); "
                 "retail listing shown for reference (Solar Electric Supply). "
                 "US-made (San Antonio, TX). Price on request — retail sites block "
                 "automated price fetch.",
    },
    # --- Current-PV purchase URLs (Piece 24.0) — high-use modules only.
    #     Per direction: link the current PV line at product-page depth and
    #     stop there (inverter/battery variants stay at brand-page level).
    "PV Module||Q-Cells||Q.Peak DUO BLK ML-G10+  410": {
        "purchase_url": "https://www.solarelectricsupply.com/"
                        "q-cells-q-peak-duo-blk-ml-g10-plus-410w-residential-solar-panel",
        "status": "Active",
        "flags": "Reference retail (Solar Electric Supply), Q.PEAK DUO BLK ML-G10+ "
                 "410W. Listed vendor N. AZ Wind & Sun carries the ML-G10+ line. "
                 "Price on request.",
    },
    "PV Module||Q-Cells||Q.Peak DUO BLK ML-G10+ 400": {
        "purchase_url": "https://www.solarelectricsupply.com/"
                        "q-cells-q-peak-duo-ml-blk-g10-400w-solar-panel",
        "status": "Active",
        "flags": "Reference retail (Solar Electric Supply), Q.PEAK DUO BLK ML-G10+ "
                 "400W. Price on request.",
    },
    "PV Module||Q-Cells||Q.Peak DUO BLK ML-G10+ 405": {
        "purchase_url": "https://www.solarelectricsupply.com/"
                        "q-cells-q-peak-duo-ml-blk-g10-405w-solar-panel",
        "status": "Active",
        "flags": "Reference retail (Solar Electric Supply), Q.PEAK DUO BLK ML-G10+ "
                 "405W. Price on request.",
    },
    "PV Module||Q-Cells||Q.PEAK DUO XL-G10.3/BFG 480": {
        "purchase_url": "https://www.solarelectricsupply.com/"
                        "q-cells-q-peak-duo-xl-g10-3-480w-solar-panel",
        "status": "Active",
        "flags": "Reference retail (Solar Electric Supply), Q.PEAK DUO XL-G10.3/BFG "
                 "480W bifacial (156 half-cell). Price on request.",
    },
    "PV Module||Mission Solar||MSX10-435HNOB": {
        "purchase_url": "https://ussolarsupplier.com/products/"
                        "mission-solar-435w-n-type-i-topcon-mono-black-solar-panel-"
                        "msx10-435hnob",
        "status": "Active",
        "flags": "Reference retail (US Solar Supplier), exact model MSX10-435HN0B. "
                 "US-made N-type i-TOPCon, black. Price on request.",
    },
    "PV Module||Canadian Solar||CS6.2-66TB-630H": {
        "purchase_url": "https://ussolarsupplier.com/products/"
                        "canadian-solar-cs6-2-66tb-625h-625-watt-n-type-bifacial-topcon",
        "status": "Active",
        "flags": "Reference retail (US Solar Supplier) — closest listed wattage bin "
                 "is 625H; 630H is the same TOPBiHiKu6 CS6.2-66TB family (600–630W). "
                 "Confirm exact 630H bin with vendor. Price on request.",
    },
    "PV Module||Hyundai||HIS-S400YH(BK) 400W Bifacial": {
        "purchase_url": "https://www.greentechrenewables.com/product/"
                        "hyundai-energy-solutions-400w-132-half-cell-1500v-black-"
                        "bifacial-solar-panel-his-s400yhbk",
        "status": "Active",
        "flags": "Reference retail (Greentech Renewables), exact model "
                 "HiS-S400YH(BK), 132 half-cell black bifacial. Price on request.",
    },
    'Battery||Absolyte||100G17': {"specs": {"Voltage": 2.0}, "flags": 'Capacity incomplete — Voltage and/or Ah missing; needs a datasheet lookup.'},
    'Battery||BYD||BYD-HVL-3': {"specs": {"Capacity": 12.0, "Voltage": 350.0, "AH Rating": 80.0}, "flags": 'CAPACITY set to 12.0 kWh (manufacturer rating from description). NOTE: Voltage x Ah = 28.0 kWh differs >20% — check the 350.0V/80.0Ah entries.'},
    'Battery||C&D Technologies||AES 100LC17 - 48V 4 per cell': {"specs": {"Voltage": 48.0}, "flags": 'Capacity incomplete — Voltage and/or Ah missing; needs a datasheet lookup.'},
    'Battery||C&D Technologies||AES 100LC33 - 24volt-3 cell per module': {"specs": {"Capacity": 44.0, "Voltage": 24.0, "AH Rating": 1834.0}, "flags": 'CAPACITY CORRECTED to 44.0 kWh (manufacturer rating; sheet had 0.8).'},
    'Battery||C&D Technologies||AES 100LC33 - 48volt-4 cell per module': {"specs": {"Capacity": 88.032, "Voltage": 48.0, "AH Rating": 1834.0}, "flags": 'CAPACITY CORRECTED to 88.032 kWh (nameplate = 48.0V x 1834.0Ah / 1000; sheet had 70.43).'},
    'Battery||CALB||CA180FI Lithium LifePO4': {"specs": {"Capacity": 0.576, "Voltage": 3.2, "AH Rating": 180.0}, "flags": 'CAPACITY CORRECTED to 0.576 kWh (nameplate = 3.2V x 180.0Ah / 1000; sheet had 0.52).'},
    'Battery||Continental||CBEV-24-DT': {"specs": {"AH Rating": 85.0}, "flags": 'Capacity incomplete — Voltage and/or Ah missing; needs a datasheet lookup.'},
    'Battery||Continental||CBEV-L16-903-DT': {"specs": {"Capacity": 2.34, "Voltage": 6.0, "AH Rating": 390.0}, "flags": 'CAPACITY CORRECTED to 2.34 kWh (nameplate = 6.0V x 390.0Ah / 1000; sheet had 1.87).'},
    'Battery||Continental||Golf Cart CBEV-GC2-DT': {"specs": {"Capacity": 0.44, "Voltage": 2.0, "AH Rating": 220.0}, "flags": 'CAPACITY CORRECTED to 0.44 kWh (nameplate = 2.0V x 220.0Ah / 1000; sheet had 1.3).'},
    'Battery||Full River||DC250-6 6v 250 AH, GC-2, AGM': {"specs": {"Capacity": 1.5, "Voltage": 6.0, "AH Rating": 250.0}, "flags": 'CAPACITY CORRECTED to 1.5 kWh (nameplate = 6.0V x 250.0Ah / 1000; sheet had 0.8).'},
    'Battery||Home Grid||Compact Series': {"specs": {"Capacity": 5.12, "Voltage": 48.0, "AH Rating": 106.0}, "flags": 'CAPACITY CORRECTED to 5.12 kWh (manufacturer rating; sheet had 0.8).'},
    'Battery||Home Grid||HG-FS48100-15OSJ1': {"specs": {"Capacity": 4.3, "Voltage": 48.0, "AH Rating": 100.0}, "flags": 'CAPACITY CORRECTED to 4.3 kWh (manufacturer rating; sheet had 0.8).'},
    "Battery||O'Reilly's or equivalent||Battery": {"flags": 'Capacity incomplete — Voltage and/or Ah missing; needs a datasheet lookup.'},
    'Battery||Precision||PR110-DC+HT': {"specs": {"Capacity": 1.32, "Voltage": 12.0, "AH Rating": 110.0}, "flags": 'CAPACITY CORRECTED to 1.32 kWh (nameplate = 12.0V x 110.0Ah / 1000; sheet had None).'},
    'Battery||SimpliPhi||Ampliphi-3.8-48': {"specs": {"Capacity": 3.8, "Voltage": 48.0, "AH Rating": 75.0}, "flags": 'CAPACITY CORRECTED to 3.8 kWh (manufacturer rating; sheet had 3.0).'},
    'Battery||SOK Battery||S24V100': {"specs": {"Capacity": 2.4, "Voltage": 24.0, "AH Rating": 100.0}, "purchase_url": "https://signaturesolar.com/?s=sok+s24v100", "flags": 'CAPACITY CORRECTED to 2.4 kWh (24V x 100Ah). Reference retail: Signature Solar / SOK direct. Price on request.'},
    'Battery||Trojan||L16RE-2V': {"specs": {"Capacity": 2.22, "Voltage": 2.0, "AH Rating": 1110.0}, "flags": 'CAPACITY CORRECTED to 2.22 kWh (nameplate = 2.0V x 1110.0Ah / 1000; sheet had 2220.0).'},
    'Battery||US Battery||USL16, 12V 385ah': {"specs": {"Capacity": 4.62, "Voltage": 12.0, "AH Rating": 385.0}, "flags": 'CAPACITY CORRECTED to 4.62 kWh (nameplate = 12.0V x 385.0Ah / 1000; sheet had None).'},
    'Battery||US Battery||USL16HCL, 6V, 420ah': {"specs": {"Capacity": 2.52, "Voltage": 6.0, "AH Rating": 420.0}, "flags": 'CAPACITY CORRECTED to 2.52 kWh (nameplate = 6.0V x 420.0Ah / 1000; sheet had None).'},
    # --- Inverter sheet — string-inverter specs + battery/accessory flags ---
    'Inverter||Sol-Ark||Sol-Ark SA-15k-P, HARDENED': {"specs": {"Pout Rated (kW)": 15, "Vin Max": 500, "Vin Min": 175}, "manual_url": 'https://www.sol-ark.com/wp-content/uploads/2024/06/SK150-0001-002-15K-2P-N-EN-Datasheet.pdf', "purchase_url": "https://www.currentconnected.com/product/sol-ark-15k-all-in-one-hybrid-inverter/", "flags": 'Verified: 15kW out, 19.5kW PV max, 3 MPPT 175-425V, Voc max 500V. Reference retail: Current Connected. FCC ID# pending. Price on request.'},
    'Inverter||SMA||SB7.0-1SP-US-41': {"specs": {"Pout Rated (kW)": 7, "Vin Max": 600, "Vin Min": 100}, "manual_url": 'https://s3.amazonaws.com/ecodirect_docs/SMA/Sunny-Boy-US-series/SB3.0-7.7-US-DUS163317W.pdf', "flags": 'Verified: SMA Sunny Boy US, max DC 600V.'},
    'Inverter||SMA||SB7.001SP-US-40': {"specs": {"Pout Rated (kW)": 7, "Vin Max": 600, "Vin Min": 100}, "manual_url": 'https://s3.amazonaws.com/ecodirect_docs/SMA/Sunny-Boy-US-series/SB3.0-7.7-US-DUS163317W.pdf', "flags": 'Verified: SMA Sunny Boy US, max DC 600V (older -40 rev).'},
    'Inverter||SMA||SBSE3.8-US-50 - Hybrid': {"specs": {"Pout Rated (kW)": 3.8, "Vin Max": 600}, "manual_url": 'https://s3.amazonaws.com/ecodirect_docs/SMA/Sunny-Boy-US-series/SB3.0-7.7-US-DUS163317W.pdf', "flags": 'SB Smart Energy hybrid; 600V max DC (US standard) - verify against SBSE datasheet.'},
    'Inverter||SMA||SBSE4.8-US-50 - Hybrid': {"specs": {"Pout Rated (kW)": 4.8, "Vin Max": 600}, "manual_url": 'https://s3.amazonaws.com/ecodirect_docs/SMA/Sunny-Boy-US-series/SB3.0-7.7-US-DUS163317W.pdf', "flags": 'SB Smart Energy hybrid; 600V max DC (US standard) - verify against SBSE datasheet.'},
    'Inverter||SMA||SBSE5.8-US-50 - Hybrid': {"specs": {"Pout Rated (kW)": 5.8, "Vin Max": 600}, "manual_url": 'https://s3.amazonaws.com/ecodirect_docs/SMA/Sunny-Boy-US-series/SB3.0-7.7-US-DUS163317W.pdf', "flags": 'SB Smart Energy hybrid; 600V max DC (US standard) - verify against SBSE datasheet.'},
    'Inverter||GoodWe||GoodWGW5000-MS-US30 - Tigo': {"specs": {"Pout Rated (kW)": 5.0, "Vin Max": 600, "Vin Min": 165}, "manual_url": 'https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_MS-US_Datasheet-EN.pdf', "flags": 'Verified: GoodWe MS-US, max PV 600V.'},
    'Inverter||GoodWe||GoodWGW6000-MS-US30 - Tigo': {"specs": {"Pout Rated (kW)": 6.0, "Vin Max": 600, "Vin Min": 165}, "manual_url": 'https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_MS-US_Datasheet-EN.pdf', "flags": 'Verified: GoodWe MS-US, max PV 600V.'},
    'Inverter||GoodWe||GoodWGW7700-MS-US30 - Tigo': {"specs": {"Pout Rated (kW)": 7.7, "Vin Max": 600, "Vin Min": 165}, "manual_url": 'https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_MS-US_Datasheet-EN.pdf', "flags": 'Verified: GoodWe MS-US, max PV 600V.'},
    'Inverter||GoodWe||GoodWGW9600-MS-US30 - Tigo': {"specs": {"Pout Rated (kW)": 9.6, "Vin Max": 600, "Vin Min": 165}, "manual_url": 'https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_MS-US_Datasheet-EN.pdf', "flags": 'Verified: GoodWe MS-US, max PV 600V.'},
    'Inverter||Solis||1P9K-4G-US': {"specs": {"Pout Rated (kW)": 9, "Vin Max": 600, "Vin Min": 100}, "manual_url": 'https://www.invertersupply.com/media/data/Datasheet_Solis-1P9K-4G-US.pdf', "flags": 'Verified: Solis 1P9K-4G-US, max DC 600V, 4 MPPT.'},
    'Inverter||Magnum||MPSL175-30D': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Outback Power||GS4048A-01': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Samlex||EVO-1212F': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Samlex||EVO-1224F': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Samlex||EVO-1224F-HW': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Samlex||EVO-2212': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Samlex||EVO-2224': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Samlex||PST-2000-12': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    'Inverter||Schneider Electric||Breaker Kit for Conext XW+PDP #RNW865121501': {"flags": 'NOT AN INVERTER — accessory (PDP / connection kit / breaker kit). Recategorize to Electrical.'},
    'Inverter||Schneider Electric||XW Connection kit for Inverter 2 (RNW865102002': {"flags": 'NOT AN INVERTER — accessory (PDP / connection kit / breaker kit). Recategorize to Electrical.'},
    'Inverter||Schneider Electric||XW+ mini Power Distribution Panel RNW865101301': {"flags": 'NOT AN INVERTER — accessory (PDP / connection kit / breaker kit). Recategorize to Electrical.'},
    'Inverter||Schneider Electric||XW+ POWER DISTIBUTION PANEL (RNW865101501)': {"flags": 'NOT AN INVERTER — accessory (PDP / connection kit / breaker kit). Recategorize to Electrical.'},
    'Inverter||Victron||MultiPlus 12V/2000/80A/120V': {"flags": 'Battery-based inverter/charger — no PV MPPT; PV Vin Max n/a (DC input = battery voltage).'},
    # --- Purchase URLs for current-install gear (Piece 23.9) ---
    "Battery||Pytes||V5": {"purchase_url": "https://signaturesolar.com/pytes-v5-lifepo4-battery/", "flags": "Reference retail (Signature Solar); listed vendor NAWS also stocks it. Price on request."},
    "Battery||Pytes||V10": {"purchase_url": "https://www.solar-electric.com/pytes-energy-v10-wall-mount-48v-200-ah-lifepo4-battery-pack.html", "flags": "Purchase page at NAWS (solar-electric.com) — the listed vendor. Price on request."},
    "Battery||Pytes||V16": {"purchase_url": "https://www.self2solar.com/products/pytes-v16-16kwh-51-2v-lfp-battery-10-years-warranty-ul-9540-certificated-with-sol-ark-and-cec-listed", "flags": "Reference retail (Self2Solar); mfr page pytesess.com/Low-Voltage-Battery/V16.html. Price on request."},
    "Inverter||Sol-Ark||SA-15K-2P": {"purchase_url": "https://www.currentconnected.com/product/sol-ark-15k-all-in-one-hybrid-inverter/", "flags": "Reference retail (Current Connected). FCC ID# pending. Price on request."},
    "Inverter||Sol-Ark||SA 8k-P": {"purchase_url": "https://www.solarelectricsupply.com/sol-ark", "flags": "Sol-Ark brand retailer (Solar Electric Supply) — select the 8K model. FCC ID# pending. Price on request."},
    "Inverter||Sol-Ark||SA-12k-P, HARDENED, EMP": {"purchase_url": "https://www.solarelectricsupply.com/sol-ark", "flags": "Sol-Ark brand retailer (Solar Electric Supply) — select the 12K model. FCC ID# pending. Price on request."},
    "Inverter||Sol-Ark||18K-2P": {"purchase_url": "https://www.solarelectricsupply.com/sol-ark", "flags": "Sol-Ark brand retailer (Solar Electric Supply) — select the 18K model. FCC ID# pending. Price on request."},
    "Inverter||SolarEdge||SE 7600H-US000BNU4 (240V)": {"purchase_url": "https://www.solarelectricsupply.com/solaredge-se7600h-us-home-hub-hdwave", "flags": "Reference retail (Solar Electric Supply), SolarEdge Home Hub 7.6kW. FCC ID# pending. Price on request."},
    "Inverter||Solis||S6-EH1P10K-H-US-RSS": {"purchase_url": "https://www.solar-electric.com/solis-s6-eh1p10k-h-us-rss-hybrid-single-phase-inverter.html", "flags": "Purchase page at NAWS (solar-electric.com), Solis S6 hybrid 10kW. FCC ID# pending. Price on request."},

    # === Piece 24.1 — remaining spec-gap completions on the spec-bearing sheets ===
    # --- Generator sheet: real ratings for the gensets/ATS; accessories flagged. ---
    "Generator||Briggs & Stratton||18/18kW (LP/NG) - PP18+": {"specs": {"Rating": 18.0, "Output Breaker (A)": 80.0}, "flags": "Rating filled from Briggs PowerProtect 18kW (matches PP18 / PPDX18+ siblings): 18kW, 80A main breaker."},
    "Generator||Briggs & Stratton||200A ATS old style #071068": {"specs": {"Rating": 200.0, "Output Breaker (A)": 200.0}, "flags": "200A automatic transfer switch — rated 200A (matches the 200A SED transfer-switch rows)."},
    "Generator||Generac||200 A Auto Transfer Switch": {"specs": {"Rating": 200.0, "Output Breaker (A)": 200.0}, "flags": "200A automatic transfer switch — rated 200A."},
    "Generator||Briggs & Stratton||Briggs & Stratton - 809732": {"flags": "Briggs service/replacement part #809732 — not a rated generator or transfer switch; no kW / breaker rating. Recategorize as generator accessory."},
    "Generator||Briggs & Stratton||Voltage Regulator AVR Board for 10k": {"flags": "AVR voltage-regulator control board (10kW gensets) — accessory; no standalone kW / breaker rating."},
    "Generator||EXCELFU||Disconnect Kit": {"flags": "Generator disconnect kit — accessory; no kW / breaker rating."},
    "Generator||Generac||0C3150A": {"flags": "Generac part #0C3150A (control/PCB assembly) — accessory; no kW / breaker rating."},
    "Generator||Generac||6485 maintenance kit": {"flags": "Generac maintenance kit — consumable; no kW / breaker rating."},
    "Generator||Generac||Universal Valve Gaskets": {"flags": "Service gasket set — consumable; no kW / breaker rating."},
    # --- Charge Controller sheet: Max Solar (Watts) at 48V from each datasheet. ---
    "Charge Controller||Morningstar||TS-MPPT-60": {"specs": {"Max Solar (Watts)": 3200.0}, "flags": "Max nominal solar input 3200W @ 48V (TriStar MPPT 60 datasheet; 800/1600/3200W at 12/24/48V)."},
    "Charge Controller||Morningstar||TS-MPPT-60M": {"specs": {"Max Solar (Watts)": 3200.0}, "flags": "Max nominal solar input 3200W @ 48V (TriStar MPPT 60, -M meter variant; same power stage)."},
    "Charge Controller||Outback Power||FlexMax 80": {"specs": {"Max Solar (Watts)": 4000.0}, "flags": "Max PV array 4000W @ 48V (FLEXmax 80 / FM80-150VDC datasheet)."},
    "Charge Controller||Victron||SmartSolar MPPT 150-70-Tr": {"specs": {"Max Solar (Watts)": 4000.0}, "flags": "Max PV power 4000W @ 48V battery (SmartSolar MPPT 150/70 datasheet; 1000/2000/3000/4000W at 12/24/36/48V)."},
    # --- Optimizer sheet: SolarEdge S-series fills; transmitters flagged. ---
    "Optimizer||SolarEdge||S440": {"specs": {"Rating": 440.0, "Vin Max": 60.0, "Isc max": 15.0, "Iin max": 15.0, "Iout max": 15.0, "Vout max": 60.0, "Vout off": 1.0, "Minimum String Length": 8.0, "Maximum String Length": 25.0, "Maximum Power Per String": 5700.0}, "flags": "SolarEdge S-series: rated 440W (relabeled 490W after 09/2025), abs max input 60V, MPPT 8-60V, 15A device rating. String design = SolarEdge NA single-phase constants (min 8 / max 25 / 5700W per string, matching this sheet's P-series). Datasheet PDF fetch was policy-blocked — confirm Isc/output-voltage detail against the installed rev."},
    "Optimizer||SolarEdge||S500B": {"specs": {"Rating": 500.0, "Vin Max": 60.0, "Isc max": 15.0, "Iin max": 15.0, "Iout max": 15.0, "Vout max": 60.0, "Vout off": 1.0, "Minimum String Length": 8.0, "Maximum String Length": 25.0, "Maximum Power Per String": 5700.0}, "flags": "SolarEdge S500B (bifacial-optimized), nameplate 500W, abs max input 60V, MPPT 8-60V, 15A device rating. String design = SolarEdge NA single-phase constants (min 8 / max 25 / 5700W per string). Datasheet PDF fetch was policy-blocked — confirm Isc/output-voltage detail against the installed rev."},
    "Optimizer||AP Smart||RSD-S(single) PLC": {"specs": {"Rating": 1200.0, "Vin Max": 80.0, "Isc max": 15.0, "Iin max": 15.0, "Iout max": 15.0, "Vout max": 1000.0, "Vout off": 0.0, "Minimum String Length": 1.0, "Maximum String Length": 12.0, "Maximum Power Per String": 5000.0}, "flags": "Single-module rapid-shutdown device (RSD-S-PLC family), not a power-producing optimizer. Specs mirrored from the RSD-S-PLC (MC4) sibling; base RSD-S-PLC is 1000V UL / 8-80VDC / device Isc 25A. Confirm 1000V vs 1500V (415002) variant."},
    "Optimizer||AP Smart||APsmart transmitter APS 406001 Single Core": {"flags": "PLC signal transmitter (single-core), not a per-module optimizer — no optimizer electrical specs. One transmitter per array. (Two identical rows on the sheet — dedupe candidate.)"},
    "Optimizer||Tigo||Transmitter Stand Alone (no ps or encl) 490-00000-51": {"flags": "Tigo RSS/Cloud Connect transmitter — accessory, not a per-module optimizer; no optimizer electrical specs."},
    # --- Breaker sheet: Rating decoded from the model number. ---
    "Breaker||MidNite Solar||MNEPV20-600RT": {"specs": {"Rating": 20.0}, "flags": "20A DIN-rail PV breaker, 600VDC rated (MNEPV-20-600RT)."},
    "Breaker||Square D||HOM280": {"specs": {"Rating": 80.0}, "flags": "Square D Homeline HOM280 = 2-pole, 80A (HOM 2 80)."},
}


# ===========================================================================
# Piece 24.2 — Tools & standard-hardware listings (big-box sourcing).
# Keyed by exact tool NAME (as seeded in INVENTORY_TOOLS). Each entry assigns a
# standard make/model, a store listing URL, and an APPROX price flagged for
# verification (retail sites block automated price fetch through this env, and
# prices move). Mixed tier per direction: pro/contractor-grade for daily-abuse,
# accuracy-critical, and safety items; budget / Harbor Freight for occasional
# hand tools & consumables. "/p/" links are exact Home Depot product pages;
# "/s/" links are Home Depot search-listings for the named SKU; a few solar-
# specialty items (MC4 tooling, irradiance meter) are not stocked at big-box and
# are flagged as specialty (solar distributor / Amazon).
# ===========================================================================
TOOLS_RESEARCH_VERSION = 1
TOOLS_RESEARCH = {
    # --- Power tools (PRO — daily abuse) ---
    "Cordless drill/driver": {"make": "Milwaukee", "model": "M18 FUEL 2903-20", "purchase_url": "https://www.homedepot.com/s/Milwaukee%202903-20", "cost": 179.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Impact driver": {"make": "Milwaukee", "model": "M18 FUEL 2953-20", "purchase_url": "https://www.homedepot.com/p/Milwaukee-M18-FUEL-18V-Lithium-Ion-Brushless-Cordless-1-4-in-Hex-Impact-Driver-Tool-Only-2953-20/320326875", "cost": 199.0, "notes": "Pro tier. Home Depot. Tool-only. Approx price — verify at listing."},
    "Hammer drill": {"make": "Milwaukee", "model": "M18 FUEL 2904-20", "purchase_url": "https://www.homedepot.com/p/Milwaukee-M18-FUEL-18V-Lithium-Ion-Brushless-Cordless-1-2-in-Hammer-Drill-Driver-Tool-Only-2904-20/320326855", "cost": 229.0, "notes": "Pro tier. Home Depot. Tool-only. Approx price — verify at listing."},
    "Reciprocating saw (Sawzall)": {"make": "Milwaukee", "model": "M18 SAWZALL 2621-20", "purchase_url": "https://www.homedepot.com/p/Milwaukee-M18-18V-Lithium-Ion-Cordless-SAWZALL-Reciprocating-Saw-Tool-Only-2621-20/205482388", "cost": 149.0, "notes": "Pro tier. Home Depot. Tool-only. Approx price — verify at listing."},
    "Angle grinder": {"make": "DeWalt", "model": "20V MAX XR DCG413B", "purchase_url": "https://www.homedepot.com/p/DEWALT-20V-MAX-XR-Cordless-Brushless-4-5-in-Paddle-Switch-Small-Angle-Grinder-with-Kickback-Brake-Tool-Only-DCG413B/301562545", "cost": 179.0, "notes": "Pro tier. Home Depot. Tool-only, kickback brake. Approx price — verify at listing."},
    "Circular saw": {"make": "Milwaukee", "model": "M18 FUEL 7-1/4 in 2732-20", "purchase_url": "https://www.homedepot.com/p/Milwaukee-M18-FUEL-18V-Lithium-Ion-Brushless-Cordless-7-1-4-in-Circular-Saw-Tool-Only-2732-20/307743783", "cost": 249.0, "notes": "Pro tier. Home Depot. Tool-only. Approx price — verify at listing."},
    # --- Hand tools (mixed) ---
    "Hammer": {"make": "Estwing", "model": "E3-16S 16 oz", "purchase_url": "https://www.homedepot.com/s/Estwing%20E3-16S", "cost": 25.0, "notes": "Standard. Home Depot listing. Approx price — verify at listing."},
    "Rubber mallet": {"make": "Tekton", "model": "16 oz rubber mallet", "purchase_url": "https://www.harborfreight.com/catalogsearch/result?q=rubber%20mallet", "cost": 8.0, "notes": "Budget (Harbor Freight). Approx price — verify at listing."},
    "Pipe cutter": {"make": "RIDGID", "model": "2-A (1/8-2 in) 32820", "purchase_url": "https://www.homedepot.com/p/RIDGID-1-8-in-to-2-in-Model-2-A-Adjustable-Heavy-Duty-Pipe-Cutter-32820/100001470", "cost": 45.0, "notes": "Pro tier. Home Depot. Approx price — verify at listing."},
    "Tubing/conduit cutter": {"make": "RIDGID", "model": "Model 15 (3/16-1-1/8 in) 32920", "purchase_url": "https://www.homedepot.com/p/RIDGID-3-16-in-to-1-1-8-in-Model-15-Screw-Feed-Copper-Pipe-Aluminum-Tubing-Cutter-w-Fold-Away-Reamer-Spare-Wheel-32920/100015820", "cost": 40.0, "notes": "Pro tier. Home Depot. Copper/aluminum tubing & EMT. Approx price — verify at listing."},
    "EMT conduit hand bender": {"make": "Klein Tools", "model": "51611 (1/2-3/4 in EMT)", "purchase_url": "https://www.homedepot.com/s/Klein%201%2F2%20in%20EMT%20conduit%20bender", "cost": 55.0, "notes": "Pro tier. Home Depot listing (Klein/Southwire). Approx price — verify at listing."},
    "PVC cutter": {"make": "RIDGID", "model": "Ratcheting PVC/PEX cutter", "purchase_url": "https://www.homedepot.com/s/RIDGID%20ratcheting%20PVC%20cutter", "cost": 22.0, "notes": "Standard. Home Depot listing. Approx price — verify at listing."},
    "Wire strippers": {"make": "Klein Tools", "model": "11061 self-adjusting", "purchase_url": "https://www.homedepot.com/p/Klein-Tools-8-1-4-in-Self-Adjusting-Wire-Stripper-and-Cutter-for-10-20-AWG-12-22-AWG-12-2-and-14-2-Romex-Wire-11061/206318106", "cost": 22.0, "notes": "Pro tier. Home Depot. Approx price — verify at listing."},
    "MC4 crimp tool": {"make": "IWISS", "model": "Solar PV crimper (2.5-6 mm2)", "purchase_url": "https://www.amazon.com/s?k=IWISS+MC4+solar+crimping+tool", "cost": 35.0, "notes": "Solar specialty — NOT stocked at big-box; solar distributor / Amazon. Approx price — verify at listing."},
    "MC4 assembly/disassembly tool": {"make": "Generic", "model": "MC4 spanner wrench pair", "purchase_url": "https://www.amazon.com/s?k=MC4+assembly+disassembly+spanner+tool", "cost": 10.0, "notes": "Solar specialty — NOT stocked at big-box; solar distributor / Amazon. Approx price — verify at listing."},
    "Fish tape": {"make": "Klein Tools", "model": "56000 steel 25 ft", "purchase_url": "https://www.homedepot.com/s/Klein%2056000%20fish%20tape", "cost": 28.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Cable cutters": {"make": "Klein Tools", "model": "63050 high-leverage", "purchase_url": "https://www.homedepot.com/s/Klein%2063050%20cable%20cutter", "cost": 42.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Lineman's pliers": {"make": "Klein Tools", "model": "D213-9NE 9 in", "purchase_url": "https://www.homedepot.com/p/Klein-Tools-9-in-High-Leverage-Side-Cutting-Pliers-D213-9NESEN/100352059", "cost": 36.0, "notes": "Pro tier. Home Depot. Approx price — verify at listing."},
    "Needle-nose pliers": {"make": "Klein Tools", "model": "D203-8N 8 in long-nose", "purchase_url": "https://www.homedepot.com/s/Klein%20D203-8N%20long%20nose%20pliers", "cost": 27.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Channel-lock pliers": {"make": "Channellock", "model": "420 9.5 in tongue-and-groove", "purchase_url": "https://www.homedepot.com/s/Channellock%20420", "cost": 22.0, "notes": "Standard. Home Depot listing. Approx price — verify at listing."},
    "Side cutters": {"make": "Klein Tools", "model": "D248-8 diagonal cutters", "purchase_url": "https://www.homedepot.com/s/Klein%20D248-8%20diagonal%20cutters", "cost": 28.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Adjustable wrench": {"make": "Crescent", "model": "AC210VS 10 in", "purchase_url": "https://www.homedepot.com/s/Crescent%2010%20in%20adjustable%20wrench", "cost": 15.0, "notes": "Budget. Home Depot listing (Harbor Freight Pittsburgh is a cheaper alt). Approx price — verify at listing."},
    "Socket set": {"make": "Husky", "model": "Mechanics socket set (1/4 & 3/8 in)", "purchase_url": "https://www.homedepot.com/s/Husky%20mechanics%20socket%20set", "cost": 99.0, "notes": "Budget (house brand). Home Depot listing. Approx price — verify at listing."},
    "Nut driver set": {"make": "Klein Tools", "model": "647M 7-pc metric nut driver", "purchase_url": "https://www.homedepot.com/s/Klein%20nut%20driver%20set", "cost": 40.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Screwdriver set": {"make": "Klein Tools", "model": "85074 7-pc", "purchase_url": "https://www.homedepot.com/s/Klein%2085074%20screwdriver%20set", "cost": 45.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Allen/hex key set": {"make": "Bondhus", "model": "SAE + metric hex key set", "purchase_url": "https://www.homedepot.com/s/Bondhus%20hex%20key%20set", "cost": 20.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    "Torque wrench": {"make": "Husky", "model": "1/2 in drive click torque wrench", "purchase_url": "https://www.homedepot.com/s/Husky%201%2F2%20in%20torque%20wrench", "cost": 50.0, "notes": "Standard (accuracy). Home Depot listing. Approx price — verify at listing."},
    "Utility knife": {"make": "Milwaukee", "model": "FASTBACK folding knife", "purchase_url": "https://www.homedepot.com/s/Milwaukee%20FASTBACK%20utility%20knife", "cost": 15.0, "notes": "Standard. Home Depot listing. Approx price — verify at listing."},
    "Caulk gun": {"make": "Newborn", "model": "250 (10 oz)", "purchase_url": "https://www.homedepot.com/s/Newborn%20caulk%20gun", "cost": 12.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    # --- Test equipment (PRO — accuracy) ---
    "Digital multimeter": {"make": "Fluke", "model": "117 True-RMS", "purchase_url": "https://www.homedepot.com/p/FLUKE-117-Electrician-s-True-RMS-Multi-meter-with-Non-Contact-Voltage-2538815/327627711", "cost": 253.0, "notes": "Pro tier. Home Depot. Approx price — verify at listing."},
    "AC/DC clamp meter": {"make": "Klein Tools", "model": "CL800 True-RMS AC/DC", "purchase_url": "https://www.homedepot.com/p/Klein-Tools-600-Amp-AC-DC-True-RMS-Auto-Ranging-Digital-Clamp-Meter-CL800/206517428", "cost": 150.0, "notes": "Pro tier. Home Depot. AC/DC (measures PV DC current). Approx price — verify at listing."},
    "Irradiance meter": {"make": "Amprobe", "model": "SOLAR-100", "purchase_url": "https://www.amazon.com/s?k=Amprobe+SOLAR-100+irradiance+meter", "cost": 150.0, "notes": "Solar specialty — NOT stocked at big-box; solar distributor / Amazon. Approx price — verify at listing."},
    "IR thermometer": {"make": "Klein Tools", "model": "IR1 infrared thermometer", "purchase_url": "https://www.homedepot.com/s/Klein%20IR1%20infrared%20thermometer", "cost": 50.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    "Insulation resistance tester (megohmmeter)": {"make": "Klein Tools", "model": "ET600 megohmmeter", "purchase_url": "https://www.homedepot.com/p/Klein-Tools-Digital-Insulation-Resistance-Tester-Auto-Ranging-TRMS-Multimeter-ET600/312112015", "cost": 230.0, "notes": "Pro tier. Home Depot. 125/250/500/1000V test. Approx price — verify at listing."},
    "Non-contact voltage tester": {"make": "Klein Tools", "model": "NCVT-3PR dual-range", "purchase_url": "https://www.homedepot.com/p/Klein-Tools-Digital-Dual-Range-Non-Contact-Voltage-Tester-with-LED-Flashlight-12-1000V-AC-NCVT-3PR/312665549", "cost": 30.0, "notes": "Pro tier. Home Depot. Approx price — verify at listing."},
    # --- Layout ---
    "Tape measure": {"make": "Milwaukee", "model": "48-22-6825 25 ft compact", "purchase_url": "https://www.homedepot.com/s/Milwaukee%2048-22-6825%2025%20ft%20tape%20measure", "cost": 17.0, "notes": "Standard. Home Depot listing. Approx price — verify at listing."},
    "Chalk line": {"make": "Milwaukee", "model": "Bold-Line chalk reel", "purchase_url": "https://www.homedepot.com/s/Milwaukee%20chalk%20line%20reel", "cost": 12.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    "Speed square": {"make": "Swanson", "model": "S0101 7 in", "purchase_url": "https://www.homedepot.com/s/Swanson%20speed%20square%207%20in", "cost": 10.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    "Torpedo level": {"make": "Empire", "model": "9 in magnetic torpedo", "purchase_url": "https://www.homedepot.com/s/Empire%209%20in%20magnetic%20torpedo%20level", "cost": 12.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    "4 ft level": {"make": "Empire", "model": "48 in box level", "purchase_url": "https://www.homedepot.com/s/Empire%2048%20in%20box%20level", "cost": 60.0, "notes": "Pro tier (accuracy). Home Depot listing (Stabila is a premium alt). Approx price — verify at listing."},
    "Stud finder": {"make": "Franklin", "model": "ProSensor 710", "purchase_url": "https://www.homedepot.com/s/Franklin%20ProSensor%20710", "cost": 50.0, "notes": "Pro tier. Home Depot listing. Approx price — verify at listing."},
    # --- Access & safety (PRO — safety-critical) ---
    "Extension ladder": {"make": "Werner", "model": "D6228-2 28 ft fiberglass Type IA", "purchase_url": "https://www.homedepot.com/p/Werner-28-ft-Fiberglass-Extension-Ladder-27-ft-Reach-Height-with-300-lb-Load-Capacity-Type-IA-Duty-Rating-D6228-2/100659879", "cost": 449.0, "notes": "Pro tier (fiberglass — non-conductive). Home Depot. Approx price — verify at listing."},
    "Step ladder": {"make": "Werner", "model": "6 ft fiberglass (FS206 / NXT1A06)", "purchase_url": "https://www.homedepot.com/p/Werner-6-ft-Fiberglass-Step-Ladder-10-ft-Reach-Height-with-225-lb-Load-Capacity-Type-II-Duty-Rating-FS206/202259337", "cost": 99.0, "notes": "Standard (fiberglass; step up to Type IA NXT1A06 for a crew). Home Depot. Approx price — verify at listing."},
    "Fall-protection harness": {"make": "Guardian", "model": "Rooftop Safe-Tie kit 00815-QC", "purchase_url": "https://www.homedepot.com/p/Guardian-Fall-Protection-Rooftop-Safe-Tie-Bucket-Kit-00815-QC/202898758", "cost": 100.0, "notes": "Pro tier (safety). Home Depot. Harness + lifeline + anchor kit. Approx price — verify at listing."},
    "Roof anchor kit": {"make": "Guardian", "model": "Reusable ridge roof anchor", "purchase_url": "https://www.homedepot.com/s/Guardian%20reusable%20roof%20anchor", "cost": 30.0, "notes": "Pro tier (safety). Home Depot listing. Approx price — verify at listing."},
    "Hard hat": {"make": "Generic", "model": "ANSI Z89.1 Type I hard hat", "purchase_url": "https://www.homedepot.com/s/hard%20hat%20ANSI%20Z89", "cost": 15.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    "Safety glasses": {"make": "Generic", "model": "ANSI Z87.1 safety glasses", "purchase_url": "https://www.homedepot.com/s/safety%20glasses%20ANSI%20Z87", "cost": 8.0, "notes": "Budget. Home Depot listing (buy by the box). Approx price — verify at listing."},
    "Work gloves": {"make": "Generic", "model": "Work gloves", "purchase_url": "https://www.homedepot.com/s/work%20gloves", "cost": 15.0, "notes": "Budget. Home Depot listing. Approx price — verify at listing."},
    "Label printer": {"make": "Brother", "model": "P-touch PT-D210", "purchase_url": "https://www.homedepot.com/s/Brother%20P-touch%20label%20maker", "cost": 40.0, "notes": "Standard. Home Depot listing. Approx price — verify at listing."},
}
