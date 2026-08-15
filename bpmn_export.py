"""Per-project BPMN 2.0 export for Compendium.

Takes the shape of Vixinman's master process ("The Uber Diagram", kept at
docs/The_Uber_Diagram.bpmn) and instantiates it for one project:

- the "Interconnection approval and permitting" box expands into the
  project's actual resolved permit steps, in dependency order (utility
  pre-screening first, zoning clearance before building permit,
  interconnection application last);
- state inspections live in an "Authorities (CID)" lane, utility work
  (meter set, JMEC Letter of Compliance) in the Utility Company lane;
- off-grid projects drop the interconnection and meter-set steps;
- labels are stamped with the project's county and utility;
- payment milestones default to the 50/40/10 schedule, annotated with
  the project's cost method (variants to be defined later);
- service tickets get a visible caveat that the install pipeline is
  provisional for them.

Output is standalone BPMN 2.0 XML with diagram layout, viewable in
bpmn.io / Camunda Modeler / any BPMN viewer.
"""

from xml.sax.saxutils import escape

# Piece 24.5: swim-lanes are the company's functional departments (matching the
# app's DASHBOARD_DEPARTMENTS / role model), plus the two external actors and the
# Compendium automation. Replaces the earlier generic role labels (Foreman, System
# Designer, …). LANE_TO_ROLES in app.py resolves each lane to the real Vixinman roles.
LANES = [
    "Sales", "Design", "Compendium System", "Permits",
    "Purchasing", "Installation", "Finance",
    "Authorities (CID)", "Utility Company", "Executive",
]

# Layout constants
LANE_H = 110
X0, X_STEP = 220, 185
TASK_W, TASK_H = 155, 70
GW = 50
EV = 36

CONNECTION_FIELDS = (
    "pv_utility_connection", "generator_utility_connection",
    "battery_utility_connection",
)

# Piece 18.1: each process step's pipeline status, so generated tasks are
# tagged by stage (standardized department step-lists) and stage transitions
# can be gated on their own steps being done.
STEP_STATUS = {
    # Planning now ends at the signed contract + deposit (Piece 20.6).
    "start": "Planning", "collect": "Planning", "sitevisit": "Planning",
    "loads": "Planning", "draft": "Planning", "finalize": "Planning",
    "contract": "Planning", "dep50": "Planning",
    "compendium": "Prep", "order": "Prep", "finance": "Prep",
    "setdate": "Prep",
    "install": "In Progress", "walkthrough": "In Progress",
    "doctube": "In Progress", "dep40": "In Progress", "monitoring": "In Progress",
    "meterset": "Wrap-up", "cid": "Wrap-up", "fix": "Wrap-up",
    "jmecloc": "Wrap-up", "sticker": "Wrap-up",
    "inv10": "Wrap-up", "saleswalk": "Wrap-up", "review": "Wrap-up", "end": "Wrap-up",
}


def _step_status(nid):
    """Pipeline stage for a node id (the dynamic permit steps are Prep)."""
    if nid.startswith("permit"):
        return "Prep"
    return STEP_STATUS.get(nid, "")


def _rule_item(rule):
    return {"label": rule["label"], "category": rule["category"],
            "notes": rule["notes"], "url": rule["url"],
            "link_text": rule["link_text"], "phone": rule["phone"]}


def _permit_chain(matched, grid_tied):
    """Order the project's resolved permitting steps. Returns a list of
    (task label, [rule detail items]) pairs."""
    seen = set()
    permits = [r for r in matched if r["category"] == "Permit"]
    prescreens = [r for r in matched
                  if "pre-screening" in r["label"].lower()
                  and r["category"] != "Permit"]
    licenses = [r for r in matched if r["category"] == "License"]

    def order(rule):
        label = rule["label"].lower()
        for rank, keyword in enumerate((
                "pre-screening", "zoning", "development permit",
                "building permit", "mhd", "mechanical permit",
                "electrical permit")):
            if keyword in label:
                return rank
        if "interconnection" in label:
            return 98
        return 50

    steps = []
    if licenses:
        steps.append((f"Verify technician licenses ({len(licenses)})",
                      [_rule_item(r) for r in licenses]))
    for rule in sorted(prescreens + permits, key=order):
        if not grid_tied and "interconnection" in rule["label"].lower():
            continue
        if rule["label"] not in seen:
            seen.add(rule["label"])
            steps.append((rule["label"], [_rule_item(rule)]))
    return steps or [("Permitting review", [])]


def build_project_bpmn(project, matched, materials_note="", docs_note=""):
    grid_tied = any((project[f] or "") in ("Grid-tie", "Backup system")
                    for f in CONNECTION_FIELDS)
    county = (project["county"] or "").strip()
    utility = (project["utility_provider"] or "").strip()
    service_project = "Technician Service" in (project["products"] or "")
    jmec_loc = any(r["label"].startswith("JMEC Letter of Compliance")
                   for r in matched)

    nodes, flows, annotations = [], [], []
    details = {}

    def add(nid, ntype, name, lane, colx, items=None):
        nodes.append(dict(id=nid, type=ntype, name=name, lane=lane, col=colx))
        details[nid] = {"name": name, "lane": lane, "items": items or [],
                        "kind": ntype, "order": len(nodes),
                        "status": _step_status(nid)}
        return nid

    def link(a, b, label=""):
        flows.append((a, b, label))

    # Product/finance-driven conditionals (Piece 20.6).
    products = project["products"] or ""
    has_monitoring = ("PV Systems" in products) or ("Battery Banks" in products)
    cost = (project["cost_method"] or "").strip()
    needs_finance_step = (
        "finance" in cost.lower()                                   # financed
        or (project["tax_credit"] or "").strip().lower() == "yes"        # rebate/ITC paperwork
        or grid_tied)                                               # interconnection paperwork

    # --- Proposal: intake → walkthrough → loads → design → contract → deposit
    c = 0
    add("start", "startEvent", "Client Interest in Vixinman Designs", "Sales", c); c += 1
    add("collect", "userTask", "Client Intake & Questionnaire", "Sales", c); c += 1
    add("sitevisit", "userTask", "Site Visit: Pictures, walkthrough", "Sales", c); c += 1
    add("loads", "userTask", "Record Electric Loads / Load Calculation", "Sales", c); c += 1
    add("draft", "task", "Draft and Review Design", "Design", c); c += 1
    add("finalize", "userTask", "Finalize and approve Design", "Design", c); c += 1
    add("contract", "task", "Client Signs Contract", "Sales", c); c += 1
    add("dep50", "task", "50% Deposit Received", "Finance", c); c += 1
    # Prep begins: the software generates the task list (chart-only — no
    # to-do is created for it), then the parallel prep work fans out.
    add("compendium", "serviceTask", "Compendium generates tasks, lists & this chart",
        "Compendium System", c); c += 1
    add("split", "parallelGateway", "", "Permits", c); c += 1

    for a, b in [("start", "collect"), ("collect", "sitevisit"),
                 ("sitevisit", "loads"), ("loads", "draft"), ("draft", "finalize"),
                 ("finalize", "contract"), ("contract", "dep50"),
                 ("dep50", "compendium"), ("compendium", "split")]:
        link(a, b)

    # Parallel Prep branches off the split: procurement, the finance/rebate
    # milestone (when relevant), and the project-specific permitting chain.
    chain = _permit_chain(matched, grid_tied)
    add("order", "userTask", "Order all components and materials", "Purchasing", c)
    if needs_finance_step:
        add("finance", "task", "Confirm financing / rebate paperwork",
            "Finance", c)
    prev = "split"
    for i, (label, items) in enumerate(chain):
        nid = f"permit{i}"
        add(nid, "userTask", label, "Permits", c, items)
        link(prev, nid)
        prev = nid
        c += 1
    add("join", "parallelGateway", "", "Permits", c); c += 1
    link(prev, "join")
    link("split", "order")
    link("order", "join")
    if needs_finance_step:
        link("split", "finance")
        link("finance", "join")

    add("setdate", "userTask", "Set Installation Date", "Installation", c); c += 1
    # --- Installation ---
    add("install", "userTask", "Site Installation", "Installation", c); c += 1
    add("walkthrough", "task", "Crew Install Walkthrough", "Installation", c); c += 1
    add("doctube", "task", "Doc Tube and Pictures", "Installation", c); c += 1
    add("dep40", "task", "40% Deposit", "Finance", c); c += 1
    for a, b in [("join", "setdate"), ("setdate", "install"),
                 ("install", "walkthrough"), ("walkthrough", "doctube"),
                 ("doctube", "dep40")]:
        link(a, b)
    prev = "dep40"
    if has_monitoring:   # only systems that actually report (PV / battery)
        add("monitoring", "task", "Set up Monitoring", "Installation", c); c += 1
        link("dep40", "monitoring")
        prev = "monitoring"

    # --- Inspections: CID final inspection first; the utility sets the meter
    # only after it passes (the real interconnection sequence).
    cid_items = [_rule_item(r) for r in matched
                 if "Inspection" in r["label"] and r["category"] == "Compliance"]
    cid_label = f"Final CID Inspection — {county}" if county else "Final CID Inspection"
    add("cid", "task", cid_label, "Authorities (CID)", c, cid_items); c += 1
    link(prev, "cid")
    add("passgw", "exclusiveGateway", "Inspection passed?", "Authorities (CID)", c)
    add("fix", "task", "Correct & Re-inspect", "Installation", c); c += 1
    link("cid", "passgw")
    link("passgw", "fix", "No")
    link("fix", "cid")

    # Yes branch: meter set (grid-tie) → JMEC Letter of Compliance (JMEC) → sticker
    prev, yes_label = "passgw", "Yes"
    if grid_tied:
        utility_items = [_rule_item(r) for r in matched
                         if r["field_name"] == "utility_provider"]
        meter_label = f"Meter set by {utility}" if utility else "Meter set by Utility"
        add("meterset", "task", meter_label, "Utility Company", c, utility_items); c += 1
        link(prev, "meterset", yes_label if prev == "passgw" else "")
        prev, yes_label = "meterset", ""
    if jmec_loc:
        loc_items = [_rule_item(r) for r in matched
                     if r["label"].startswith("JMEC Letter of Compliance")]
        add("jmecloc", "task", "Letter of Compliance to JMEC (electrician)",
            "Utility Company", c, loc_items); c += 1
        link(prev, "jmecloc", yes_label if prev == "passgw" else "")
        prev, yes_label = "jmecloc", ""
    add("sticker", "task", "Photograph Final Inspection Sticker", "Installation", c); c += 1
    link(prev, "sticker", yes_label if prev == "passgw" else "")
    # --- Closing ---
    add("inv10", "task", "Final 10% Invoice", "Finance", c); c += 1
    add("saleswalk", "task", "Final Client Walkthrough (Sales)", "Sales", c); c += 1
    add("review", "task", "Client Review & Sign-off", "Sales", c); c += 1
    add("end", "endEvent", "Close Out & Submit Final Paperwork", "Executive", c); c += 1
    for a, b in [("sticker", "inv10"), ("inv10", "saleswalk"),
                 ("saleswalk", "review"), ("review", "end")]:
        link(a, b)

    # Annotations
    cost = (project["cost_method"] or "").strip()
    annotations.append(("ann_pay", "dep50",
                        f"Payment schedule: default 50/40/10"
                        + (f" (cost method: {cost})" if cost else "")))
    if service_project:
        annotations.append(("ann_service", "start",
                            "Service ticket: simplified service process "
                            "pending — install pipeline shown provisionally"))
    if materials_note:
        annotations.append(("ann_materials", "order", materials_note))
    if docs_note:
        annotations.append(("ann_docs", "compendium", docs_note))

    return _render_xml(project, nodes, flows, annotations), details


def _render_xml(project, nodes, flows, annotations):
    by_id = {n["id"]: n for n in nodes}
    incoming = {n["id"]: [] for n in nodes}
    outgoing = {n["id"]: [] for n in nodes}
    for i, (a, b, _label) in enumerate(flows):
        incoming[b].append(f"flow{i}")
        outgoing[a].append(f"flow{i}")

    def size(n):
        if n["type"].endswith("Event"):
            return EV, EV
        if n["type"].endswith("Gateway"):
            return GW, GW
        return TASK_W, TASK_H

    def pos(n):
        w, h = size(n)
        x = X0 + n["col"] * X_STEP + (TASK_W - w) // 2
        y = 80 + LANES.index(n["lane"]) * LANE_H + (LANE_H - h) // 2
        return x, y, w, h

    def center(n):
        x, y, w, h = pos(n)
        return x + w // 2, y + h // 2

    max_col = max(n["col"] for n in nodes)
    total_w = X0 + (max_col + 1) * X_STEP + 120

    x = ['<?xml version="1.0" encoding="UTF-8"?>']
    x.append(
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
        ' xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"'
        ' xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"'
        ' xmlns:di="http://www.omg.org/spec/DD/20100524/DI"'
        ' id="compendium_defs" targetNamespace="http://compendium.vixinmandesigns/bpmn"'
        ' exporter="Compendium">')
    x.append('<bpmn:collaboration id="collab"><bpmn:participant id="pool"'
             f' name="Vixinman Designs — {escape(project["job_name"] or "Project")}"'
             ' processRef="proc"/></bpmn:collaboration>')
    x.append('<bpmn:process id="proc" isExecutable="false">')

    x.append('<bpmn:laneSet id="laneset">')
    for i, lane in enumerate(LANES):
        x.append(f'<bpmn:lane id="lane{i}" name="{escape(lane)}">')
        for n in nodes:
            if n["lane"] == lane:
                x.append(f'<bpmn:flowNodeRef>{n["id"]}</bpmn:flowNodeRef>')
        x.append('</bpmn:lane>')
    x.append('</bpmn:laneSet>')

    for n in nodes:
        name = f' name="{escape(n["name"])}"' if n["name"] else ""
        x.append(f'<bpmn:{n["type"]} id="{n["id"]}"{name}>')
        for f in incoming[n["id"]]:
            x.append(f'<bpmn:incoming>{f}</bpmn:incoming>')
        for f in outgoing[n["id"]]:
            x.append(f'<bpmn:outgoing>{f}</bpmn:outgoing>')
        x.append(f'</bpmn:{n["type"]}>')

    for i, (a, b, label) in enumerate(flows):
        name = f' name="{escape(label)}"' if label else ""
        x.append(f'<bpmn:sequenceFlow id="flow{i}"{name}'
                 f' sourceRef="{a}" targetRef="{b}"/>')

    for aid, target, text in annotations:
        x.append(f'<bpmn:textAnnotation id="{aid}">'
                 f'<bpmn:text>{escape(text)}</bpmn:text></bpmn:textAnnotation>')
        x.append(f'<bpmn:association id="{aid}_assoc" sourceRef="{target}"'
                 f' targetRef="{aid}"/>')

    x.append('</bpmn:process>')

    # ---- Diagram layout ----
    x.append('<bpmndi:BPMNDiagram id="diagram"><bpmndi:BPMNPlane id="plane"'
             ' bpmnElement="collab">')
    x.append(f'<bpmndi:BPMNShape id="pool_di" bpmnElement="pool" isHorizontal="true">'
             f'<dc:Bounds x="120" y="80" width="{total_w}"'
             f' height="{len(LANES) * LANE_H}"/></bpmndi:BPMNShape>')
    for i, _lane in enumerate(LANES):
        x.append(f'<bpmndi:BPMNShape id="lane{i}_di" bpmnElement="lane{i}"'
                 f' isHorizontal="true"><dc:Bounds x="150" y="{80 + i * LANE_H}"'
                 f' width="{total_w - 30}" height="{LANE_H}"/></bpmndi:BPMNShape>')
    for n in nodes:
        px, py, w, h = pos(n)
        x.append(f'<bpmndi:BPMNShape id="{n["id"]}_di" bpmnElement="{n["id"]}">'
                 f'<dc:Bounds x="{px}" y="{py}" width="{w}" height="{h}"/>'
                 f'</bpmndi:BPMNShape>')
    for i, (a, b, _label) in enumerate(flows):
        ax, ay = center(by_id[a])
        bx, by_ = center(by_id[b])
        x.append(f'<bpmndi:BPMNEdge id="flow{i}_di" bpmnElement="flow{i}">'
                 f'<di:waypoint x="{ax}" y="{ay}"/>'
                 f'<di:waypoint x="{bx}" y="{by_}"/></bpmndi:BPMNEdge>')
    for aid, target, _text in annotations:
        tx, ty = center(by_id[target])
        x.append(f'<bpmndi:BPMNShape id="{aid}_di" bpmnElement="{aid}">'
                 f'<dc:Bounds x="{tx - 80}" y="{ty - 100}" width="220" height="46"/>'
                 f'</bpmndi:BPMNShape>')
        x.append(f'<bpmndi:BPMNEdge id="{aid}_assoc_di" bpmnElement="{aid}_assoc">'
                 f'<di:waypoint x="{tx}" y="{ty}"/>'
                 f'<di:waypoint x="{tx + 30}" y="{ty - 77}"/></bpmndi:BPMNEdge>')
    x.append('</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>')
    x.append('</bpmn:definitions>')
    return "\n".join(x)
