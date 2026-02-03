"""
Dimension 3: Filing Discipline
Question: Do they treat statutory obligations seriously?

Detects: late filings, overdue accounts, amendments, ARD changes,
last-minute filing patterns.
"""

import logging
from tools.utils import parse_date, days_between, calculate_accounts_deadline

logger = logging.getLogger(__name__)


def analyze(api_client, company_number):
    result = {
        "dimension": "filing_discipline",
        "title": "Filing Discipline",
        "icon": "📋",
        "question": "Do they treat statutory obligations seriously?",
        "rating": "clean",
        "summary": "",
        "evidence": [],
        "rating_logic": "",
        "what_to_ask": [],
        "interpretation": {
            "why_matters": [
                "Late filings often correlate with weak finance function or cash constraints",
                "Amendments may indicate error-prone accounting processes"
            ],
            "innocent_explanations": [
                "One-off adviser failure or staff turnover",
                "System migration causing timing issues"
            ],
            "what_we_checked": [
                "Filing history, deadline calculations, overdue flags"
            ]
        },
    }

    # Get company profile for overdue flags (no cache — always fresh)
    profile = api_client.get_company(company_number)
    if not profile:
        result["summary"] = "Unable to retrieve company profile"
        result["rating"] = "investigate"
        return result

    accounts = profile.get("accounts", {})
    confirmation = profile.get("confirmation_statement", {})
    company_type = profile.get("type", "ltd")

    # Check currently overdue
    accounts_overdue = accounts.get("overdue", False)
    confirmation_overdue = confirmation.get("overdue", False)

    if accounts_overdue:
        due_on = accounts.get("next_accounts", {}).get("due_on", "unknown")
        result["evidence"].append({
            "confidence": "verified",
            "severity": "high",
            "type": "accounts_overdue",
            "description": f"Accounts currently OVERDUE (due: {due_on})",
            "details": {"due_on": due_on},
            "source": "company profile",
            "link": "",
        })

    if confirmation_overdue:
        next_due = confirmation.get("next_due", "unknown")
        result["evidence"].append({
            "confidence": "verified",
            "severity": "high",
            "type": "confirmation_overdue",
            "description": f"Confirmation statement currently OVERDUE (due: {next_due})",
            "details": {"next_due": next_due},
            "source": "company profile",
            "link": "",
        })

    # Get filing history
    filings_data = api_client.get_filing_history(company_number)
    if not filings_data or "items" not in filings_data:
        result["summary"] = "Limited filing history available"
        if accounts_overdue or confirmation_overdue:
            result["rating"] = "red_flag"
            result["summary"] = "Currently overdue on statutory filings"
        return result

    filings = filings_data["items"]

    # Analyze accounts filings
    accounts_filings = [f for f in filings if f.get("category") == "accounts"]
    late_count = 0
    last_minute_count = 0
    amendment_count = 0
    ard_changes = 0

    for filing in accounts_filings[:10]:  # Last 10 accounts filings
        filing_type = filing.get("type", "")
        filing_date = parse_date(filing.get("date"))

        # Check for amendments
        desc = (filing.get("description", "") + " " + filing_type).upper()
        if "AMENDED" in desc or "REPLACEMENT" in desc:
            amendment_count += 1
            result["evidence"].append({
                "confidence": "verified",
                "severity": "medium",
                "type": "amendment",
                "description": f"Amended/replacement accounts filed on {filing.get('date', '?')}",
                "details": {"type": filing_type, "date": filing.get("date")},
                "source": "filing-history",
                "link": "",
            })

        # Check for ARD changes
        if filing_type == "AA" or "CHANGE OF ACCOUNTING REFERENCE" in desc:
            ard_changes += 1
            result["evidence"].append({
                "confidence": "verified",
                "severity": "low",
                "type": "ard_change",
                "description": f"Accounting reference date changed on {filing.get('date', '?')}",
                "details": {"date": filing.get("date")},
                "source": "filing-history",
                "link": "",
            })

    # Analyze timeliness of accounts filings
    # Look at the made_up_date (period end) and filing date
    for filing in accounts_filings[:5]:  # Last 5 for pattern
        made_up = parse_date(filing.get("description_values", {}).get("made_up_date"))
        filed_on = parse_date(filing.get("date"))

        if not made_up or not filed_on:
            continue

        deadline = calculate_accounts_deadline(made_up, company_type)
        if not deadline:
            continue

        gap = days_between(filed_on, deadline)
        if gap is not None:
            if gap < 0:
                late_count += 1
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "high",
                    "type": "late_filing",
                    "description": f"Accounts for Y/E {made_up} filed {abs(gap)} days late",
                    "details": {
                        "period_end": str(made_up),
                        "filed_on": str(filed_on),
                        "deadline": str(deadline),
                        "days_late": abs(gap),
                    },
                    "source": "filing-history",
                    "link": "",
                })
            elif gap < 14:
                last_minute_count += 1

    if last_minute_count >= 3:
        result["evidence"].append({
            "confidence": "verified",
            "severity": "medium",
            "type": "last_minute_pattern",
            "description": f"{last_minute_count} of last 5 accounts filed within final 14 days of deadline",
            "details": {"count": last_minute_count},
            "source": "filing-history",
            "link": "",
        })

    # --- Rating logic ---
    if accounts_overdue or confirmation_overdue:
        result["rating"] = "red_flag"
        result["rating_logic"] = "Accounts or confirmation statement currently overdue"
        result["summary"] = "Currently overdue on statutory filings"
    elif late_count >= 2:
        result["rating"] = "red_flag"
        result["rating_logic"] = f"{late_count} late filings in recent history"
        result["summary"] = f"{late_count} accounts filed after deadline"
    elif last_minute_count >= 3:
        result["rating"] = "investigate"
        result["rating_logic"] = f"Pattern of last-minute filings ({last_minute_count} of last 5)"
        result["summary"] = "Consistent pattern of last-minute accounts filings"
    elif amendment_count > 0:
        result["rating"] = "investigate"
        result["rating_logic"] = f"{amendment_count} amended/replacement accounts filed"
        result["summary"] = f"{amendment_count} amended or replacement accounts on record"
    elif ard_changes >= 2:
        result["rating"] = "investigate"
        result["rating_logic"] = f"Multiple accounting reference date changes ({ard_changes})"
        result["summary"] = f"Accounting reference date changed {ard_changes} times"
    else:
        result["rating"] = "clean"
        result["rating_logic"] = "Consistent on-time filing with no amendments"
        result["summary"] = "All filings on time with no amendments"

    # What to ask
    if late_count > 0:
        result["what_to_ask"].append("Why were accounts filed late? Was this a one-off or systemic?")
    if amendment_count > 0:
        result["what_to_ask"].append("What was corrected in the amended accounts?")
    if ard_changes > 0:
        result["what_to_ask"].append("Why was the accounting reference date changed?")
    if accounts_overdue:
        result["what_to_ask"].append("When will the overdue accounts be filed?")

    return result
