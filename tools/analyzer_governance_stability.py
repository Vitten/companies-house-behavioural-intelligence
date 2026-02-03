"""
Dimension 4: Governance Stability
Question: Is leadership stable or is there concerning churn?

Detects (all VERIFIED):
- Director turnover, recent changes, sole director risk
- Formation agent addresses, registered office changes
- Timing correlations: director change near accounts filing or PSC change
"""

import logging
from datetime import date
from tools.utils import (
    parse_date,
    days_between,
    is_formation_agent_address,
)

logger = logging.getLogger(__name__)


def analyze(api_client, company_number):
    result = {
        "dimension": "governance_stability",
        "title": "Governance Stability",
        "icon": "🛡️",
        "question": "Is leadership stable or is there concerning churn?",
        "rating": "clean",
        "summary": "",
        "evidence": [],
        "rating_logic": "",
        "what_to_ask": [],
        "interpretation": {
            "why_matters": [
                "High turnover can indicate instability or key person disputes",
                "Timing correlations with filings may suggest governance concerns"
            ],
            "innocent_explanations": [
                "Growth-phase restructuring or internationalization",
                "Planned succession executed smoothly"
            ],
            "what_we_checked": [
                "Director tenure, resignation patterns, address changes"
            ]
        },
    }

    officers_data = api_client.get_officers(company_number)
    if not officers_data or "items" not in officers_data:
        result["summary"] = "Unable to retrieve officer data"
        result["rating"] = "investigate"
        return result

    all_officers = officers_data["items"]
    today = date.today()

    # Separate current and resigned directors
    current_directors = [
        o for o in all_officers
        if o.get("officer_role") in ("director", "corporate-director")
        and not o.get("resigned_on")
    ]
    resigned_directors = [
        o for o in all_officers
        if o.get("officer_role") in ("director", "corporate-director")
        and o.get("resigned_on")
    ]

    current_count = len(current_directors)
    result["evidence"].append({
        "confidence": "verified",
        "severity": "none",
        "type": "director_count",
        "description": f"{current_count} active director(s)",
        "details": {"count": current_count},
        "source": "officers",
        "link": "",
    })

    sole_director = current_count == 1

    # Calculate tenures
    tenures = []
    recent_appointments = []
    recent_appointment_dates = []

    for d in current_directors:
        appointed = parse_date(d.get("appointed_on"))
        if appointed:
            tenure_days = days_between(appointed, today)
            tenure_years = tenure_days / 365.25 if tenure_days else 0
            tenures.append(tenure_years)

            if tenure_days and tenure_days < 90:
                recent_appointments.append(d)
                recent_appointment_dates.append(appointed)
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "medium",
                    "type": "recent_appointment",
                    "description": f"New director {d.get('name', '?')} appointed {d.get('appointed_on')} ({tenure_days} days ago)",
                    "details": {
                        "name": d.get("name"),
                        "appointed_on": d.get("appointed_on"),
                        "days_ago": tenure_days,
                    },
                    "source": "officers",
                    "link": "",
                })

    avg_tenure = sum(tenures) / len(tenures) if tenures else 0
    if tenures:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "none",
            "type": "average_tenure",
            "description": f"Average director tenure: {avg_tenure:.1f} years",
            "details": {"average_years": round(avg_tenure, 1)},
            "source": "officers",
            "link": "",
        })

    # Recent resignations and churn
    changes_last_2y = 0
    short_tenures = 0
    recent_resignation_dates = []

    for d in resigned_directors:
        resigned = parse_date(d.get("resigned_on"))
        appointed = parse_date(d.get("appointed_on"))

        if resigned:
            days_ago = days_between(resigned, today)
            if days_ago is not None and days_ago < 730:
                changes_last_2y += 1
                recent_resignation_dates.append(resigned)
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "low",
                    "type": "resignation",
                    "description": f"{d.get('name', '?')} resigned {d.get('resigned_on')}",
                    "details": {
                        "name": d.get("name"),
                        "resigned_on": d.get("resigned_on"),
                        "appointed_on": d.get("appointed_on"),
                    },
                    "source": "officers",
                    "link": "",
                })

        if appointed and resigned:
            tenure = days_between(appointed, resigned)
            if tenure and tenure < 548:
                short_tenures += 1

    changes_last_2y += len(recent_appointments)

    if short_tenures >= 3:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "short_tenure_pattern",
            "description": f"{short_tenures} directors served less than 18 months in last 5 years",
            "details": {"count": short_tenures},
            "source": "officers",
            "link": "",
        })

    # --- TIMING CORRELATIONS (VERIFIED) ---
    # Get filing history to check for timing correlations
    filings_data = api_client.get_filing_history(company_number)
    accounts_filing_dates = []
    if filings_data and "items" in filings_data:
        for f in filings_data["items"]:
            if f.get("category") == "accounts":
                filed = parse_date(f.get("date"))
                if filed:
                    accounts_filing_dates.append(filed)

    # Get PSC changes
    pscs_data = api_client.get_pscs(company_number)
    psc_change_dates = []
    if pscs_data and "items" in pscs_data:
        for p in pscs_data["items"]:
            notified = parse_date(p.get("notified_on"))
            ceased = parse_date(p.get("ceased_on"))
            if notified:
                psc_change_dates.append(notified)
            if ceased:
                psc_change_dates.append(ceased)

    # Check for timing correlations
    all_director_change_dates = recent_appointment_dates + recent_resignation_dates

    timing_near_accounts = False
    timing_near_psc = False

    for d_date in all_director_change_dates:
        # Check proximity to accounts filing (within 30 days)
        for a_date in accounts_filing_dates[:5]:
            gap = abs(days_between(d_date, a_date) or 999)
            if gap <= 30:
                timing_near_accounts = True
                break

        # Check proximity to PSC change (within 30 days)
        for p_date in psc_change_dates:
            gap = abs(days_between(d_date, p_date) or 999)
            if gap <= 30:
                timing_near_psc = True
                break

    if timing_near_accounts:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "timing_near_accounts",
            "description": "Director change within 30 days of accounts filing",
            "details": {},
            "source": "officers + filing-history",
            "link": "",
        })

    if timing_near_psc:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "timing_near_psc",
            "description": "Director change within 30 days of PSC change",
            "details": {},
            "source": "officers + PSC",
            "link": "",
        })

    # Registered office analysis
    reg_office = api_client.get_registered_office(company_number)
    formation_agent = False
    if reg_office:
        formation_agent = is_formation_agent_address(reg_office)
        if formation_agent:
            result["evidence"].append({
                "confidence": "verified",
                "severity": "medium",
                "type": "formation_agent_address",
                "description": "Registered office is a known formation agent address",
                "details": {"address": reg_office},
                "source": "registered-office-address",
                "link": "",
            })

    # Check for address changes
    address_filings = api_client.get_filing_history(company_number, category="address")
    address_changes = 0
    if address_filings and "items" in address_filings:
        for f in address_filings["items"]:
            filed = parse_date(f.get("date"))
            if filed and days_between(filed, today) and days_between(filed, today) < 1095:
                address_changes += 1

    if address_changes >= 3:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "address_churn",
            "description": f"Registered office changed {address_changes} times in last 3 years",
            "details": {"count": address_changes},
            "source": "filing-history",
            "link": "",
        })

    # --- RATING LOGIC ---
    if changes_last_2y >= 3:
        result["rating"] = "red_flag"
        result["rating_logic"] = f"{changes_last_2y} director changes in last 2 years"
        result["summary"] = f"High director turnover: {changes_last_2y} changes in 2 years"
    elif timing_near_psc and recent_appointments:
        result["rating"] = "investigate"
        result["rating_logic"] = "Director change coincided with PSC change"
        result["summary"] = "Director and ownership change at same time"
    elif recent_appointments:
        result["rating"] = "investigate"
        result["rating_logic"] = "Director appointed in last 3 months"
        result["summary"] = f"Recent board change: new director appointed {recent_appointments[0].get('appointed_on', '?')}"
    elif sole_director:
        result["rating"] = "investigate"
        result["rating_logic"] = "Sole director — key person dependency"
        result["summary"] = "Single director — key person risk"
    elif avg_tenure < 2:
        result["rating"] = "investigate"
        result["rating_logic"] = f"Average director tenure below 2 years ({avg_tenure:.1f}y)"
        result["summary"] = f"Short average director tenure ({avg_tenure:.1f} years)"
    elif formation_agent:
        result["rating"] = "investigate"
        result["rating_logic"] = "Registered at formation agent address"
        result["summary"] = "Registered office is a formation agent address"
    elif address_changes >= 3:
        result["rating"] = "investigate"
        result["rating_logic"] = f"{address_changes} registered office changes in 3 years"
        result["summary"] = f"Registered office changed {address_changes} times in 3 years"
    else:
        result["rating"] = "clean"
        result["rating_logic"] = f"Stable board ({current_count} directors, {avg_tenure:.1f}yr avg tenure)"
        result["summary"] = f"Stable board: {current_count} directors, {avg_tenure:.1f} year average tenure"

    # What to ask
    for d in recent_appointments:
        result["what_to_ask"].append(f"What prompted the appointment of {d.get('name', '?')}?")
    if changes_last_2y > 1:
        result["what_to_ask"].append("Why has there been recent board turnover?")
    if sole_director:
        result["what_to_ask"].append("What succession plan exists if the sole director is unavailable?")
    if formation_agent:
        result["what_to_ask"].append("Why is the registered office at a formation agent rather than the trading address?")
    if timing_near_psc:
        result["what_to_ask"].append("Why did the director and ownership changes happen at the same time?")

    return result
