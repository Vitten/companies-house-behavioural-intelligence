"""
Dimension 6: Transaction Readiness
Question: How much friction should we expect in executing this deal?

Detects: outstanding charges, all-assets debentures, recent charges,
multiple secured creditors, structure complexity.
"""

import logging
from datetime import date
from tools.utils import parse_date, days_between

logger = logging.getLogger(__name__)


def analyze(api_client, company_number):
    result = {
        "dimension": "transaction_readiness",
        "title": "Closing Friction",
        "icon": "📊",
        "question": "How much friction should we expect in executing this deal?",
        "rating": "clean",
        "summary": "",
        "evidence": [],
        "rating_logic": "",
        "what_to_ask": [],
        "interpretation": {
            "why_matters": [
                "Outstanding charges require lender consent for asset transfers",
                "Multiple creditors may create subordination complexity"
            ],
            "innocent_explanations": [
                "Routine refinancing or growth financing",
                "Standard banking relationship with no unusual terms"
            ],
            "what_we_checked": [
                "Charges register, floating charge coverage, creditor identification"
            ]
        },
    }

    today = date.today()

    # Get charges
    charges_data = api_client.get_charges(company_number)
    charges = charges_data.get("items", []) if charges_data else []

    outstanding = [c for c in charges if c.get("status") == "outstanding"]
    satisfied = [c for c in charges if c.get("status") in ("fully-satisfied", "part-satisfied")]

    # Check for all-assets debenture
    all_assets_debenture = False
    for c in outstanding:
        particulars = c.get("particulars", {})
        if particulars.get("floating_charge_covers_all"):
            all_assets_debenture = True
            persons = ", ".join(
                p.get("name", "Unknown") for p in c.get("persons_entitled", [])
            )
            result["evidence"].append({
                "confidence": "verified",
                "severity": "high",
                "type": "all_assets_debenture",
                "description": f"Floating charge covers ALL assets — held by {persons}. Lender consent required for sale.",
                "details": {
                    "charge_id": c.get("charge_number"),
                    "created_on": c.get("created_on"),
                    "persons_entitled": persons,
                },
                "source": "charges",
                "link": "",
            })

    # List outstanding charges
    for c in outstanding:
        particulars = c.get("particulars", {})
        if particulars.get("floating_charge_covers_all"):
            continue  # already reported above
        persons = ", ".join(
            p.get("name", "Unknown") for p in c.get("persons_entitled", [])
        )
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "outstanding_charge",
            "description": f"Charge to {persons} (created {c.get('created_on', '?')}) — OUTSTANDING",
            "details": {
                "created_on": c.get("created_on"),
                "persons_entitled": persons,
                "description": particulars.get("description", ""),
            },
            "source": "charges",
            "link": "",
        })

    # Recent charges (last 6 months)
    recent_charges = []
    for c in charges:
        created = parse_date(c.get("created_on"))
        if created:
            gap = days_between(created, today)
            if gap is not None and gap < 180:
                recent_charges.append(c)

    if recent_charges:
        for c in recent_charges:
            persons = ", ".join(
                p.get("name", "Unknown") for p in c.get("persons_entitled", [])
            )
            result["evidence"].append({
                "confidence": "verified",
                "severity": "medium",
                "type": "recent_charge",
                "description": f"New charge registered {c.get('created_on', '?')} to {persons}",
                "details": {
                    "created_on": c.get("created_on"),
                    "persons_entitled": persons,
                },
                "source": "charges",
                "link": "",
            })

    # Multiple secured creditors
    creditors = set()
    for c in outstanding:
        for p in c.get("persons_entitled", []):
            creditors.add(p.get("name", "Unknown"))

    if len(creditors) > 1:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "multiple_creditors",
            "description": f"{len(creditors)} secured creditors: {', '.join(creditors)}",
            "details": {"creditors": list(creditors)},
            "source": "charges",
            "link": "",
        })

    # No charges at all — clean signal
    if not charges:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "none",
            "type": "no_charges",
            "description": "No charges registered against this company",
            "details": {},
            "source": "charges",
            "link": "",
        })

    # --- Rating logic ---
    flags = []
    if all_assets_debenture:
        flags.append("All-assets debenture outstanding")
    if recent_charges:
        flags.append(f"Charge created in last 6 months")
    if len(creditors) > 1:
        flags.append(f"Multiple secured creditors ({len(creditors)})")

    if flags:
        result["rating"] = "investigate"
        result["rating_logic"] = "; ".join(flags)
        result["summary"] = flags[0]
    else:
        result["rating"] = "clean"
        if outstanding:
            result["rating_logic"] = f"{len(outstanding)} outstanding charge(s), no concerning patterns"
            result["summary"] = f"{len(outstanding)} charge(s) on record, no red flags"
        else:
            result["rating_logic"] = "No charges, simple structure"
            result["summary"] = "No charges registered — clean transaction path"

    # What to ask
    if all_assets_debenture:
        result["what_to_ask"].append(
            "Has the lender been informed of the potential sale? What's their typical consent process?"
        )
    if recent_charges:
        result["what_to_ask"].append(
            "Why was the recent charge taken out? What were the proceeds used for?"
        )
    if len(creditors) > 1:
        result["what_to_ask"].append(
            "Is there an intercreditor agreement? Understand subordination terms."
        )

    return result
