"""
Dimension 5: Ownership Clarity
Question: Is it clear who controls this company and why?

Detects (all VERIFIED):
- Corporate PSCs, offshore/foreign PSCs, trusts
- Missing PSC info (statements)
- PSC churn
- Ownership depth (layers within CH-traceable entities)
- Entities in orbit (companies within 1-2 hops via PSC + officers)
- Dormant/dissolved clutter in orbit

Explicit disclaimer: Asset location (IP, property, contracts) cannot be determined from CH.
"""

import logging
from datetime import date
from tools.utils import parse_date, days_between, company_house_url, extract_officer_id

logger = logging.getLogger(__name__)


def _trace_ownership(api_client, company_number, depth=0, max_depth=3, visited=None):
    """Recursively trace PSC ownership chain."""
    if visited is None:
        visited = set()
    if company_number in visited or depth > max_depth:
        return {"untraceable": True, "layers": [], "depth": depth}
    visited.add(company_number)

    pscs_data = api_client.get_pscs(company_number)
    items = pscs_data.get("items", []) if pscs_data else []

    layers = []
    for psc in items:
        if psc.get("ceased_on"):
            continue
        kind = psc.get("kind", "")
        entry = {
            "name": psc.get("name", "Unknown"),
            "kind": kind,
            "natures_of_control": psc.get("natures_of_control", []),
            "depth": depth,
            "company_number": company_number,
        }

        if "individual" in kind:
            entry["terminal"] = True
            entry["nationality"] = psc.get("nationality", "")
        elif "corporate" in kind:
            entry["terminal"] = False
            ident = psc.get("identification", {})
            reg_number = ident.get("registration_number")
            place = ident.get("place_registered", "")
            country = ident.get("country_registered", "")
            entry["registration_number"] = reg_number
            entry["jurisdiction"] = f"{place} {country}".strip()

            if reg_number and (
                "england" in place.lower()
                or "wales" in place.lower()
                or "united kingdom" in (country or "").lower()
                or "companies house" in place.lower()
                or (reg_number.isdigit() and len(reg_number) == 8)
            ):
                sub = _trace_ownership(api_client, reg_number, depth + 1, max_depth, visited)
                entry["sub_layers"] = sub.get("layers", [])
                entry["untraceable"] = sub.get("untraceable", False)
            else:
                entry["foreign"] = True
                entry["terminal"] = True
        elif "legal-person" in kind:
            entry["terminal"] = True
            entry["is_trust"] = True

        layers.append(entry)

    return {"layers": layers, "depth": depth, "untraceable": False}


def _get_orbit_entities(api_client, company_number, directors):
    """
    Get all companies in the 'orbit' — companies connected via PSC or director appointments.
    Returns counts of active, dormant, and dissolved entities.
    """
    orbit_companies = set()

    # Get PSC companies
    pscs_data = api_client.get_pscs(company_number)
    if pscs_data and "items" in pscs_data:
        for psc in pscs_data["items"]:
            if "corporate" in psc.get("kind", ""):
                reg = psc.get("identification", {}).get("registration_number")
                if reg:
                    orbit_companies.add(reg)

    # Get companies from director appointments
    for d in directors[:3]:  # Limit to avoid too many API calls
        officer_id = extract_officer_id(d.get("links"))
        if not officer_id:
            continue
        appointments = api_client.get_appointments(officer_id)
        if appointments and "items" in appointments:
            for appt in appointments["items"]:
                cn = appt.get("appointed_to", {}).get("company_number")
                if cn and cn != company_number:
                    orbit_companies.add(cn)

    # Classify orbit companies
    active_count = 0
    dormant_count = 0
    dissolved_count = 0

    for cn in list(orbit_companies)[:20]:  # Limit to 20 to avoid rate limits
        profile = api_client.get_company(cn)
        if not profile:
            continue
        status = profile.get("company_status", "")
        if status == "dissolved":
            dissolved_count += 1
        elif status == "active":
            # Check if dormant
            if profile.get("has_been_liquidated") or "dormant" in profile.get("type", "").lower():
                dormant_count += 1
            else:
                active_count += 1
        else:
            active_count += 1

    return {
        "total": len(orbit_companies),
        "sampled": min(len(orbit_companies), 20),
        "active": active_count,
        "dormant": dormant_count,
        "dissolved": dissolved_count,
    }


def analyze(api_client, company_number):
    result = {
        "dimension": "ownership_clarity",
        "title": "Ownership Clarity",
        "icon": "🏛️",
        "question": "Is it clear who controls this company and why?",
        "rating": "clean",
        "summary": "",
        "evidence": [],
        "rating_logic": "",
        "what_to_ask": [],
        "disclaimer": "Asset location (IP, property, contracts) cannot be determined from Companies House",
        "interpretation": {
            "why_matters": [
                "Complex structures may exist for tax or liability reasons worth understanding",
                "Foreign entities require additional verification steps"
            ],
            "innocent_explanations": [
                "Legitimate holding structure for group operations",
                "Legacy cleanup in progress"
            ],
            "what_we_checked": [
                "PSC records, ownership chain tracing, corporate layers"
            ]
        },
    }

    today = date.today()

    # Get officers for orbit analysis
    officers_data = api_client.get_officers(company_number)
    directors = []
    if officers_data and "items" in officers_data:
        directors = [
            o for o in officers_data["items"]
            if o.get("officer_role") in ("director", "corporate-director")
            and not o.get("resigned_on")
        ]

    # Get PSCs
    pscs_data = api_client.get_pscs(company_number)
    pscs = pscs_data.get("items", []) if pscs_data else []

    # Get PSC statements
    statements_data = api_client.get_psc_statements(company_number)
    statements = statements_data.get("items", []) if statements_data else []

    active_pscs = [p for p in pscs if not p.get("ceased_on")]
    ceased_pscs = [p for p in pscs if p.get("ceased_on")]

    # --- PSC STATEMENTS (VERIFIED) ---
    has_problematic_statement = False
    for s in statements:
        if s.get("ceased_on"):
            continue
        statement = s.get("statement", "")
        if statement in (
            "psc-exists-but-not-identified",
            "psc-details-not-confirmed",
            "steps-to-find-psc-not-yet-completed",
        ):
            has_problematic_statement = True
            result["evidence"].append({
                "confidence": "verified",
                "severity": "high",
                "type": "psc_statement",
                "description": f"PSC statement filed: '{statement.replace('-', ' ')}'",
                "details": {"statement": statement},
                "source": "PSC statements",
                "link": "",
            })

    # --- TRACE OWNERSHIP STRUCTURE (VERIFIED) ---
    ownership = _trace_ownership(api_client, company_number)
    corporate_layers = 0
    foreign_entities = []
    trusts = 0
    max_depth = 0

    def _count_structure(layers, depth=0):
        nonlocal corporate_layers, foreign_entities, trusts, max_depth
        for layer in layers:
            if depth > max_depth:
                max_depth = depth
            if layer.get("is_trust"):
                trusts += 1
            if layer.get("foreign"):
                foreign_entities.append({
                    "name": layer["name"],
                    "jurisdiction": layer.get("jurisdiction", "Unknown"),
                })
            if not layer.get("terminal") or layer.get("sub_layers"):
                corporate_layers += 1
                _count_structure(layer.get("sub_layers", []), depth + 1)

    _count_structure(ownership.get("layers", []))

    # --- ORBIT ANALYSIS (VERIFIED) ---
    orbit = _get_orbit_entities(api_client, company_number, directors)

    result["evidence"].append({
        "confidence": "verified",
        "severity": "none",
        "type": "orbit_summary",
        "description": f"Orbit includes {orbit['total']} connected companies ({orbit['active']} active, {orbit['dormant']} dormant, {orbit['dissolved']} dissolved)",
        "details": orbit,
        "source": "PSC + appointments",
        "link": "",
    })

    # Flag dormant/dissolved clutter
    clutter_count = orbit["dormant"] + orbit["dissolved"]
    if clutter_count >= 5:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "orbit_clutter",
            "description": f"{clutter_count} dormant/dissolved entities in orbit — may indicate complexity or legacy cleanup needed",
            "details": {
                "dormant": orbit["dormant"],
                "dissolved": orbit["dissolved"],
            },
            "source": "PSC + appointments",
            "link": "",
        })

    # --- DISPLAY PSCs (VERIFIED) ---
    for psc in active_pscs:
        kind = psc.get("kind", "")
        name = psc.get("name", "Unknown")
        natures = psc.get("natures_of_control", [])
        control_desc = ", ".join(n.replace("-", " ") for n in natures[:2])

        if "individual" in kind:
            result["evidence"].append({
                "confidence": "verified",
                "severity": "none",
                "type": "individual_psc",
                "description": f"{name} ({psc.get('nationality', 'Unknown nationality')}) — {control_desc}",
                "details": {
                    "name": name,
                    "nationality": psc.get("nationality"),
                    "control": natures,
                },
                "source": "PSC endpoint",
                "link": "",
            })
        elif "corporate" in kind:
            ident = psc.get("identification", {})
            jurisdiction = f"{ident.get('place_registered', '')} {ident.get('country_registered', '')}".strip()
            reg = ident.get("registration_number", "")
            severity = "medium" if jurisdiction and "england" not in jurisdiction.lower() else "low"
            result["evidence"].append({
                "confidence": "verified",
                "severity": severity,
                "type": "corporate_psc",
                "description": f"{name} ({jurisdiction or 'UK'}{', ' + reg if reg else ''}) — {control_desc}",
                "details": {
                    "name": name,
                    "registration_number": reg,
                    "jurisdiction": jurisdiction,
                    "control": natures,
                },
                "source": "PSC endpoint",
                "link": company_house_url(reg) if reg and reg.isdigit() else "",
            })
        elif "legal-person" in kind:
            result["evidence"].append({
                "confidence": "verified",
                "severity": "medium",
                "type": "trust_psc",
                "description": f"{name} (trust/legal person) — {control_desc}",
                "details": {"name": name, "control": natures},
                "source": "PSC endpoint",
                "link": "",
            })

    # --- OWNERSHIP DEPTH (VERIFIED) ---
    if corporate_layers > 0:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "low" if corporate_layers == 1 else "medium",
            "type": "ownership_depth",
            "description": f"{corporate_layers + 1}-layer ownership structure (including target)",
            "details": {
                "corporate_layers": corporate_layers,
                "foreign_count": len(foreign_entities),
                "trust_count": trusts,
            },
            "source": "recursive PSC tracing",
            "link": "",
        })

    # --- PSC CHURN (VERIFIED) ---
    recent_ceased = 0
    for p in ceased_pscs:
        ceased = parse_date(p.get("ceased_on"))
        if ceased and days_between(ceased, today) and days_between(ceased, today) < 730:
            recent_ceased += 1

    if recent_ceased >= 2:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "psc_churn",
            "description": f"{recent_ceased} PSC changes in last 2 years",
            "details": {"count": recent_ceased},
            "source": "PSC endpoint",
            "link": "",
        })

    # --- RATING LOGIC ---
    if has_problematic_statement:
        result["rating"] = "red_flag"
        result["rating_logic"] = "PSC statement indicates unidentified controller"
        result["summary"] = "Company has unidentified person(s) with significant control"
    elif clutter_count >= 5:
        result["rating"] = "investigate"
        result["rating_logic"] = f"{clutter_count} dormant/dissolved entities in orbit"
        result["summary"] = f"{clutter_count} dormant/dissolved entities connected to this company"
    elif foreign_entities:
        result["rating"] = "investigate"
        names = [f["name"] for f in foreign_entities[:2]]
        result["rating_logic"] = f"Foreign entity in ownership chain: {', '.join(names)}"
        result["summary"] = f"Foreign entity in ownership: {names[0]}"
    elif trusts > 0:
        result["rating"] = "investigate"
        result["rating_logic"] = "Trust/legal person in ownership chain"
        result["summary"] = "Trust or legal person in ownership structure"
    elif corporate_layers >= 3:
        result["rating"] = "investigate"
        result["rating_logic"] = f"{corporate_layers}+ corporate layers in ownership"
        result["summary"] = f"Complex {corporate_layers + 1}-layer ownership structure"
    elif recent_ceased >= 2:
        result["rating"] = "investigate"
        result["rating_logic"] = f"{recent_ceased} PSC changes in last 2 years"
        result["summary"] = f"Ownership changed {recent_ceased} times in 2 years"
    else:
        result["rating"] = "clean"
        if active_pscs:
            individual_names = [
                p.get("name", "?") for p in active_pscs if "individual" in p.get("kind", "")
            ]
            if individual_names:
                result["rating_logic"] = "Direct individual UK ownership"
                result["summary"] = f"Clear ownership: {', '.join(individual_names[:2])}"
            else:
                result["rating_logic"] = "Ownership structure traceable"
                result["summary"] = "Ownership structure is traceable"
        else:
            result["rating_logic"] = "No PSC data available"
            result["summary"] = "No PSC information on record"

    # What to ask
    for fe in foreign_entities:
        result["what_to_ask"].append(f"Who is the ultimate beneficial owner of {fe['name']}?")
    if trusts > 0:
        result["what_to_ask"].append("Can we see the trust deed?")
    if corporate_layers > 0:
        result["what_to_ask"].append("Why is ownership structured through holding companies rather than directly?")
    if recent_ceased >= 2:
        result["what_to_ask"].append("What prompted the recent ownership changes?")
    if clutter_count >= 5:
        result["what_to_ask"].append("Are there plans to clean up dormant/dissolved entities in the group?")

    return result
