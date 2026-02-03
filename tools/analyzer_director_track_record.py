"""
Dimension 1: Director Track Record
Question: Have these directors been associated with companies that failed?

Detects:
- VERIFIED: insolvency associations, disqualifications, dissolution rate,
  appointment churn, median tenure, pre-insolvency resignations
- INFERRED: phoenix patterns (dissolved co → new co with same SIC/name)

Confidence labeling: Each evidence item includes a 'confidence' field.
"""

import logging
from datetime import date
from tools.utils import (
    INSOLVENCY_STATUSES,
    parse_date,
    days_between,
    company_house_url,
    extract_officer_id,
    calculate_dissolution_rate,
    calculate_median_tenure,
    calculate_churn_rate,
    levenshtein_similarity,
    sic_codes_match,
)

logger = logging.getLogger(__name__)


def analyze(api_client, company_number):
    """
    Returns dimension result with confidence-labeled evidence.
    """
    result = {
        "dimension": "director_track_record",
        "title": "Director Track Record",
        "icon": "👥",
        "question": "Have these directors been associated with companies that failed?",
        "rating": "clean",
        "summary": "",
        "evidence": [],
        "rating_logic": "",
        "what_to_ask": [],
        "interpretation": {
            "why_matters": [
                "Past insolvencies may indicate governance issues or value extraction patterns",
                "Serial director metrics reveal professional track record across companies"
            ],
            "innocent_explanations": [
                "External market factors or industry downturns beyond director control",
                "Unlucky timing or legitimate business pivots"
            ],
            "what_we_checked": [
                "Director appointments, insolvency records, disqualifications, dissolution rates"
            ]
        },
    }

    # Get target company profile for SIC codes (needed for phoenix detection)
    target_profile = api_client.get_company(company_number)
    target_sic = target_profile.get("sic_codes", []) if target_profile else []
    target_name = target_profile.get("company_name", "") if target_profile else ""
    target_incorporated = parse_date(target_profile.get("date_of_creation")) if target_profile else None

    officers_data = api_client.get_officers(company_number)
    if not officers_data or "items" not in officers_data:
        result["summary"] = "Unable to retrieve officer data"
        result["rating"] = "investigate"
        return result

    # Filter to current directors only
    directors = [
        o for o in officers_data["items"]
        if o.get("officer_role") in ("director", "corporate-director")
        and not o.get("resigned_on")
    ]

    if not directors:
        result["summary"] = "No current directors found"
        result["rating"] = "investigate"
        return result

    disqualified_count = 0
    insolvency_associations = []
    pre_insolvency_resignations = []
    phoenix_patterns = []
    high_dissolution_directors = []
    high_churn_directors = []

    for director in directors:
        name = director.get("name", "Unknown")
        officer_id = extract_officer_id(director.get("links"))
        if not officer_id:
            continue

        # Check disqualifications (VERIFIED)
        disq = api_client.get_disqualifications(officer_id)
        if disq and disq.get("disqualifications"):
            disqualified_count += 1
            for d in disq["disqualifications"]:
                result["evidence"].append({
                    "confidence": "verified",
                    "severity": "high",
                    "type": "disqualification",
                    "description": f"{name} is disqualified until {d.get('disqualified_until', 'unknown')}",
                    "details": {
                        "director_name": name,
                        "reason": d.get("reason", {}).get("description_identifier", ""),
                        "disqualified_from": d.get("disqualified_from"),
                        "disqualified_until": d.get("disqualified_until"),
                    },
                    "source": "disqualified-officers",
                    "link": "",
                })

        # Get all appointments
        appointments_data = api_client.get_appointments(officer_id)
        if not appointments_data or "items" not in appointments_data:
            continue
        appointments = appointments_data["items"]

        # --- SERIAL DIRECTOR METRICS (VERIFIED) ---
        dissolved, total, dissolution_rate = calculate_dissolution_rate(appointments)
        median_tenure = calculate_median_tenure(appointments)
        churn_rate = calculate_churn_rate(appointments)
        active_count = sum(1 for a in appointments if not a.get("resigned_on"))

        # Report serial director profile
        result["evidence"].append({
            "confidence": "verified",
            "severity": "none",
            "type": "director_profile",
            "description": f"{name}: {total} lifetime appointments ({active_count} active), {dissolved} dissolved ({dissolution_rate:.0f}%)",
            "details": {
                "director_name": name,
                "total_appointments": total,
                "active_appointments": active_count,
                "dissolved_count": dissolved,
                "dissolution_rate": round(dissolution_rate, 1),
                "median_tenure_years": round(median_tenure, 1) if median_tenure else None,
                "churn_rate": round(churn_rate, 2),
            },
            "source": "appointments",
            "link": "",
        })

        # Flag high dissolution rate (VERIFIED)
        if total >= 10 and dissolution_rate > 50:
            high_dissolution_directors.append(name)
            result["evidence"].append({
                "confidence": "verified",
                "severity": "high",
                "type": "high_dissolution_rate",
                "description": f"{name} has {dissolution_rate:.0f}% dissolution rate across {total} companies",
                "details": {
                    "director_name": name,
                    "dissolution_rate": round(dissolution_rate, 1),
                    "total_companies": total,
                    "dissolved_companies": dissolved,
                },
                "source": "appointments",
                "link": "",
            })

        # Flag high churn (VERIFIED)
        if churn_rate > 3:
            high_churn_directors.append(name)
            result["evidence"].append({
                "confidence": "verified",
                "severity": "medium",
                "type": "high_churn",
                "description": f"{name} has high appointment churn ({churn_rate:.1f} new appointments/year)",
                "details": {
                    "director_name": name,
                    "churn_rate": round(churn_rate, 2),
                },
                "source": "appointments",
                "link": "",
            })

        # --- INSOLVENCY ASSOCIATIONS (VERIFIED) ---
        dissolved_companies = []
        for appt in appointments:
            appointed_to = appt.get("appointed_to", {})
            co_status = appointed_to.get("company_status", "")
            co_number = appointed_to.get("company_number", "")
            co_name = appointed_to.get("company_name", "Unknown")

            # Track dissolved companies for phoenix detection
            if co_status == "dissolved" and co_number != company_number:
                dissolved_companies.append({
                    "company_number": co_number,
                    "company_name": co_name,
                    "resigned_on": parse_date(appt.get("resigned_on")),
                    "appointed_on": parse_date(appt.get("appointed_on")),
                })

            if co_status not in INSOLVENCY_STATUSES:
                continue
            if co_number == company_number:
                continue

            appointed_on = parse_date(appt.get("appointed_on"))
            resigned_on = parse_date(appt.get("resigned_on"))

            assessment = "Director was present at failure"
            severity = "high"

            if resigned_on:
                insolvency_data = api_client.get_insolvency(co_number)
                insolvency_date = None

                if insolvency_data and insolvency_data.get("cases"):
                    case = insolvency_data["cases"][0]
                    for case_date in case.get("dates", []):
                        if case_date.get("type") in ("wound-up-on", "instrumented-on", "administration-started-on"):
                            insolvency_date = parse_date(case_date.get("date"))
                            break

                if insolvency_date and resigned_on:
                    gap = days_between(resigned_on, insolvency_date)
                    if gap and 0 < gap < 180:
                        assessment = f"Resigned {gap} days before insolvency"
                        pre_insolvency_resignations.append((name, co_name, gap))
                    elif gap and gap <= 0:
                        assessment = "Director was present at failure"
                    else:
                        assessment = f"Resigned {abs(gap) if gap else '?'} days before insolvency"
                        severity = "medium"

            insolvency_associations.append((name, co_name))

            role_str = f"Director from {appt.get('appointed_on', '?')}"
            if resigned_on:
                role_str += f" to {appt.get('resigned_on', '?')}"

            result["evidence"].append({
                "confidence": "verified",
                "severity": severity,
                "type": "insolvency_association",
                "description": f"{name} — {co_name} ({co_number}) entered {co_status.replace('-', ' ')}",
                "details": {
                    "director_name": name,
                    "company_name": co_name,
                    "company_number": co_number,
                    "director_role": role_str,
                    "insolvency_type": co_status,
                    "assessment": assessment,
                },
                "source": "appointments + insolvency",
                "link": company_house_url(co_number),
            })

        # --- PHOENIX PATTERN DETECTION (INFERRED) ---
        # Check if director was at dissolved company shortly before target incorporated
        if target_incorporated and dissolved_companies:
            for dc in dissolved_companies[:5]:  # Limit to avoid too many API calls
                # Get dissolved company profile for SIC codes and dissolution date
                dc_profile = api_client.get_company(dc["company_number"])
                if not dc_profile:
                    continue

                dc_dissolved_date = parse_date(dc_profile.get("date_of_cessation"))
                dc_sic = dc_profile.get("sic_codes", [])
                dc_name = dc["company_name"]

                if not dc_dissolved_date:
                    continue

                # Check timing: dissolved company ceased within 12 months before target incorporated
                gap = days_between(dc_dissolved_date, target_incorporated)
                if gap is None or gap < 0 or gap > 365:
                    continue

                # Check for phoenix indicators
                sic_match = sic_codes_match(dc_sic, target_sic)
                name_similarity = levenshtein_similarity(dc_name, target_name)

                if sic_match or name_similarity > 0.6:
                    phoenix_patterns.append({
                        "director": name,
                        "dissolved_company": dc_name,
                        "dissolved_number": dc["company_number"],
                        "dissolved_date": str(dc_dissolved_date),
                        "target_incorporated": str(target_incorporated),
                        "gap_days": gap,
                        "sic_match": sic_match,
                        "name_similarity": round(name_similarity, 2),
                    })

                    indicators = []
                    if sic_match:
                        indicators.append("same industry (SIC)")
                    if name_similarity > 0.6:
                        indicators.append(f"similar name ({name_similarity:.0%})")

                    result["evidence"].append({
                        "confidence": "inferred",
                        "severity": "high" if len(phoenix_patterns) > 1 else "medium",
                        "type": "phoenix_pattern",
                        "description": f"Phoenix-likelihood: {dc_name} dissolved {dc_dissolved_date}, {target_name} incorporated {gap} days later ({', '.join(indicators)})",
                        "details": {
                            "director_name": name,
                            "dissolved_company": dc_name,
                            "dissolved_number": dc["company_number"],
                            "dissolved_date": str(dc_dissolved_date),
                            "target_incorporated": str(target_incorporated),
                            "gap_days": gap,
                            "sic_match": sic_match,
                            "name_similarity": round(name_similarity, 2),
                        },
                        "disclaimer": "Cannot verify: asset/staff migration or creditor harm",
                        "source": "appointments + company profiles (inferred pattern)",
                        "link": company_house_url(dc["company_number"]),
                    })

        # Add clean record if no issues for this director
        director_issues = [
            e for e in result["evidence"]
            if e.get("details", {}).get("director_name") == name
            and e["type"] not in ("director_profile",)
            and e["severity"] in ("high", "medium")
        ]
        if not director_issues:
            result["evidence"].append({
                "confidence": "verified",
                "severity": "none",
                "type": "clean_record",
                "description": f"{name} — no insolvencies, disqualifications, or concerning patterns found",
                "details": {"director_name": name},
                "source": "appointments + disqualified-officers",
                "link": "",
            })

    # --- RATING LOGIC ---
    total_insolvency_hits = len(insolvency_associations)

    if disqualified_count > 0:
        result["rating"] = "red_flag"
        result["rating_logic"] = f"{disqualified_count} director(s) formally disqualified"
        result["summary"] = f"{disqualified_count} director(s) disqualified from acting"
    elif high_dissolution_directors:
        result["rating"] = "red_flag"
        result["rating_logic"] = f"Director(s) with >50% dissolution rate: {', '.join(high_dissolution_directors)}"
        result["summary"] = f"High dissolution rate for {high_dissolution_directors[0]}"
    elif total_insolvency_hits >= 2:
        result["rating"] = "red_flag"
        result["rating_logic"] = f"Director(s) associated with {total_insolvency_hits} insolvencies"
        result["summary"] = f"Directors linked to {total_insolvency_hits} previous insolvencies"
    elif len(phoenix_patterns) >= 2:
        result["rating"] = "red_flag"
        result["rating_logic"] = f"Multiple phoenix-like patterns detected ({len(phoenix_patterns)})"
        result["summary"] = "Multiple phoenix-like patterns detected (inferred)"
    elif total_insolvency_hits == 1:
        result["rating"] = "investigate"
        result["rating_logic"] = "1 insolvency association found"
        d_name, co_name = insolvency_associations[0]
        result["summary"] = f"{d_name} associated with 1 previous insolvency ({co_name})"
    elif phoenix_patterns:
        result["rating"] = "investigate"
        result["rating_logic"] = "Phoenix-like pattern detected (inferred)"
        result["summary"] = f"Phoenix-like pattern: {phoenix_patterns[0]['dissolved_company']} → {target_name}"
    elif high_churn_directors:
        result["rating"] = "investigate"
        result["rating_logic"] = f"High appointment churn: {', '.join(high_churn_directors)}"
        result["summary"] = f"High appointment churn for {high_churn_directors[0]}"
    elif pre_insolvency_resignations:
        result["rating"] = "investigate"
        result["rating_logic"] = "Director resigned within 6 months before insolvency at another company"
        result["summary"] = "Director resigned shortly before another company entered insolvency"
    else:
        result["rating"] = "clean"
        result["rating_logic"] = "No insolvency associations, disqualifications, or concerning patterns found"
        result["summary"] = f"All {len(directors)} directors checked — clean track record"

    # What to ask
    for d_name, co_name in insolvency_associations:
        result["what_to_ask"].append(f"Ask {d_name} to explain their involvement in {co_name}'s insolvency")
    if insolvency_associations:
        result["what_to_ask"].append("Request the IP's report to check for findings of director misconduct")
        result["what_to_ask"].append("Verify whether failures were due to external factors vs. management decisions")
    for pp in phoenix_patterns:
        result["what_to_ask"].append(f"Understand the relationship between {pp['dissolved_company']} and {target_name}")

    return result
