"""
Dimension 2: Control Network
Question: What does the decision-making network look like?

Detects (all VERIFIED):
- Director network overlap (co-serving at 2+ other companies)
- Director also controls corporate PSC
- Network size (total unique individuals in director+PSC orbit)
- Decision concentration (% control held by people who are also directors)
- Late additions (directors/PSCs appointed in last 90 days)
- PSC activity index (changes in last 2 years)

REMOVED (unreliable):
- Address matching
- Surname-based family inference
- Young PSC detection
"""

import logging
from datetime import date
from itertools import combinations
from tools.utils import (
    parse_date,
    days_between,
    extract_officer_id,
)

logger = logging.getLogger(__name__)


def analyze(api_client, company_number):
    result = {
        "dimension": "control_network",
        "title": "Connected Parties",
        "icon": "🔗",
        "question": "What does the decision-making network look like?",
        "rating": "clean",
        "summary": "",
        "evidence": [],
        "rating_logic": "",
        "what_to_ask": [],
        "interpretation": {
            "why_matters": [
                "Concentrated decision-making can indicate related party risk",
                "Recent changes may signal ownership restructuring ahead of transactions"
            ],
            "innocent_explanations": [
                "Efficient family business or founder-led structure",
                "Planned succession or legitimate group reorganization"
            ],
            "what_we_checked": [
                "Director overlaps, PSC records, appointment timing"
            ]
        },
    }

    today = date.today()

    # Get officers and PSCs
    officers_data = api_client.get_officers(company_number)
    pscs_data = api_client.get_pscs(company_number)

    directors = []
    if officers_data and "items" in officers_data:
        directors = [
            o for o in officers_data["items"]
            if o.get("officer_role") in ("director", "corporate-director")
            and not o.get("resigned_on")
        ]

    pscs = []
    if pscs_data and "items" in pscs_data:
        pscs = [p for p in pscs_data["items"] if not p.get("ceased_on")]

    ceased_pscs = []
    if pscs_data and "items" in pscs_data:
        ceased_pscs = [p for p in pscs_data["items"] if p.get("ceased_on")]

    if not directors and not pscs:
        result["summary"] = "Insufficient data to assess control network"
        return result

    signals_found = []

    # --- NETWORK SIZE (VERIFIED) ---
    unique_individuals = set()
    for d in directors:
        unique_individuals.add(d.get("name", "").upper())
    for p in pscs:
        if "individual" in p.get("kind", ""):
            unique_individuals.add(p.get("name", "").upper())

    network_size = len(unique_individuals)
    result["evidence"].append({
        "confidence": "verified",
        "severity": "none",
        "type": "network_size",
        "description": f"Control network includes {network_size} unique individual(s)",
        "details": {
            "director_count": len(directors),
            "individual_psc_count": sum(1 for p in pscs if "individual" in p.get("kind", "")),
            "unique_individuals": network_size,
        },
        "source": "officers + PSC endpoints",
        "link": "",
    })

    if network_size > 10:
        signals_found.append("large_network")
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "large_network",
            "description": f"Large control network: {network_size} individuals across directors and PSCs",
            "details": {"network_size": network_size},
            "source": "officers + PSC endpoints",
            "link": "",
        })

    # --- DECISION CONCENTRATION (VERIFIED) ---
    # Check how much control is held by people who are also directors
    director_names = {d.get("name", "").upper() for d in directors}
    total_control_by_directors = 0
    for p in pscs:
        if "individual" in p.get("kind", ""):
            if p.get("name", "").upper() in director_names:
                natures = p.get("natures_of_control", [])
                # Estimate control percentage from natures
                for n in natures:
                    if "75-to-100" in n:
                        total_control_by_directors += 87.5
                    elif "50-to-75" in n:
                        total_control_by_directors += 62.5
                    elif "25-to-50" in n:
                        total_control_by_directors += 37.5

    if total_control_by_directors > 0:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "none",
            "type": "decision_concentration",
            "description": f"Directors hold ~{total_control_by_directors:.0f}% of significant control",
            "details": {"control_by_directors_pct": round(total_control_by_directors, 1)},
            "source": "officers + PSC endpoints",
            "link": "",
        })

    # --- LATE ADDITIONS - DIRECTORS (VERIFIED) ---
    recent_directors = []
    for d in directors:
        appointed = parse_date(d.get("appointed_on"))
        if appointed:
            gap = days_between(appointed, today)
            if gap is not None and gap < 90:
                recent_directors.append(d)
                signals_found.append("recent_director")
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "medium",
                    "type": "recent_director",
                    "description": f"Director {d.get('name', '?')} appointed {gap} days ago ({d.get('appointed_on')})",
                    "details": {
                        "director_name": d.get("name"),
                        "appointed_on": d.get("appointed_on"),
                        "days_ago": gap,
                    },
                    "source": "officers endpoint",
                    "link": "",
                })

    # --- LATE ADDITIONS - PSCs (VERIFIED) ---
    recent_pscs = []
    for p in pscs:
        notified = parse_date(p.get("notified_on"))
        if notified:
            gap = days_between(notified, today)
            if gap is not None and gap < 90:
                recent_pscs.append(p)
                signals_found.append("recent_psc")
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "medium",
                    "type": "recent_psc",
                    "description": f"PSC {p.get('name', '?')} notified {gap} days ago ({p.get('notified_on')})",
                    "details": {
                        "psc_name": p.get("name"),
                        "notified_on": p.get("notified_on"),
                        "days_ago": gap,
                    },
                    "source": "PSC endpoint",
                    "link": "",
                })

    # --- PSC ACTIVITY INDEX (VERIFIED) ---
    # Count PSC changes in last 2 years
    psc_changes_2y = 0
    for p in ceased_pscs:
        ceased = parse_date(p.get("ceased_on"))
        if ceased:
            gap = days_between(ceased, today)
            if gap is not None and gap < 730:
                psc_changes_2y += 1

    # Also count recent additions
    for p in pscs:
        notified = parse_date(p.get("notified_on"))
        if notified:
            gap = days_between(notified, today)
            if gap is not None and gap < 730:
                psc_changes_2y += 1

    if psc_changes_2y > 0:
        severity = "medium" if psc_changes_2y >= 2 else "low"
        result["evidence"].append({
            "confidence": "verified",
            "severity": severity,
            "type": "psc_activity",
            "description": f"{psc_changes_2y} PSC change(s) in last 2 years",
            "details": {"psc_changes_2y": psc_changes_2y},
            "source": "PSC endpoint",
            "link": "",
        })
        if psc_changes_2y >= 2:
            signals_found.append("high_psc_activity")

    # --- DIRECTOR NETWORK OVERLAP (VERIFIED) ---
    director_companies = {}
    for d in directors:
        officer_id = extract_officer_id(d.get("links"))
        if not officer_id:
            continue
        appointments = api_client.get_appointments(officer_id)
        if appointments and "items" in appointments:
            companies = set()
            for appt in appointments["items"]:
                cn = appt.get("appointed_to", {}).get("company_number")
                if cn and cn != company_number and not appt.get("resigned_on"):
                    companies.add(cn)
            director_companies[d.get("name", "?")] = companies

    overlapping_pairs = []
    for (d1_name, d1_cos), (d2_name, d2_cos) in combinations(director_companies.items(), 2):
        overlap = d1_cos & d2_cos
        if len(overlap) >= 2:
            overlapping_pairs.append((d1_name, d2_name, len(overlap)))
            signals_found.append("director_network_overlap")
            result["evidence"].append({
                "confidence": "verified",
                "severity": "low",
                "type": "director_network_overlap",
                "description": f"{d1_name} and {d2_name} are both current directors of {len(overlap)} other companies",
                "details": {
                    "directors": [d1_name, d2_name],
                    "shared_company_count": len(overlap),
                },
                "source": "appointments endpoint",
                "link": "",
            })

    # Check for dense network (3+ directors all sharing 2+ companies)
    if len(overlapping_pairs) >= 3:
        signals_found.append("dense_network")
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "dense_director_network",
            "description": f"Dense director network: {len(overlapping_pairs)} pairs of directors share multiple company appointments",
            "details": {"overlapping_pairs": len(overlapping_pairs)},
            "source": "appointments endpoint",
            "link": "",
        })

    # --- DIRECTOR CONTROLS CORPORATE PSC (VERIFIED) ---
    corporate_pscs = [p for p in pscs if "corporate" in p.get("kind", "")]
    for cp in corporate_pscs:
        psc_id = cp.get("identification", {})
        psc_reg = psc_id.get("registration_number")
        if not psc_reg:
            continue

        psc_officers = api_client.get_officers(psc_reg)
        if not psc_officers or "items" not in psc_officers:
            continue

        psc_director_names = {
            o.get("name", "").upper()
            for o in psc_officers["items"]
            if not o.get("resigned_on")
        }

        for d in directors:
            if d.get("name", "").upper() in psc_director_names:
                signals_found.append("director_controls_psc")
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "low",
                    "type": "director_controls_psc",
                    "description": f"{d.get('name')} is director of both target company and its PSC ({cp.get('name', '?')})",
                    "details": {
                        "director": d.get("name"),
                        "psc_company": cp.get("name"),
                        "psc_company_number": psc_reg,
                    },
                    "source": "officers + PSC endpoints",
                    "link": "",
                })

    # --- NO SIGNALS = CLEAN ---
    if not signals_found:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "none",
            "type": "clean_network",
            "description": "No concerning control network patterns detected",
            "details": {},
            "source": "officers + PSC endpoints",
            "link": "",
        })

    # --- RATING LOGIC ---
    # Combined signals
    recent_director_and_psc = recent_directors and recent_pscs

    if recent_director_and_psc:
        result["rating"] = "investigate"
        result["rating_logic"] = "Director and PSC both changed in last 90 days"
        result["summary"] = "Recent board and ownership changes (last 90 days)"
    elif "dense_network" in signals_found:
        result["rating"] = "investigate"
        result["rating_logic"] = "Dense director network — multiple pairs share other company appointments"
        result["summary"] = "Dense director network — directors share multiple other appointments"
    elif recent_pscs:
        result["rating"] = "investigate"
        result["rating_logic"] = "PSC change in last 90 days"
        result["summary"] = f"Recent PSC change: {recent_pscs[0].get('name', '?')}"
    elif "large_network" in signals_found:
        result["rating"] = "investigate"
        result["rating_logic"] = f"Large control network ({network_size} individuals)"
        result["summary"] = f"Large control network: {network_size} individuals"
    elif "high_psc_activity" in signals_found:
        result["rating"] = "investigate"
        result["rating_logic"] = f"{psc_changes_2y} PSC changes in last 2 years"
        result["summary"] = f"High PSC activity: {psc_changes_2y} changes in 2 years"
    else:
        result["rating"] = "clean"
        result["rating_logic"] = "No concerning control network patterns"
        result["summary"] = f"Clean control network ({len(directors)} directors, {len(pscs)} PSCs)"

    # What to ask
    if recent_director_and_psc:
        result["what_to_ask"].append("What prompted the recent changes to both board and ownership?")
    if recent_directors:
        result["what_to_ask"].append(f"What is the background of {recent_directors[0].get('name', 'the new director')}?")
    if recent_pscs:
        result["what_to_ask"].append("What prompted the recent ownership change?")
    if overlapping_pairs:
        d1, d2, _ = overlapping_pairs[0]
        result["what_to_ask"].append(f"What is the history of the business relationship between {d1} and {d2}?")

    return result
