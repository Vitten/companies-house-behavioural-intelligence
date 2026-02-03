"""
Shared utility functions used across analyzers.
"""

import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta


# Known formation agent address fragments (lowercase)
FORMATION_AGENT_INDICATORS = [
    "71-75 shelton street",
    "20-22 wenlock road",
    "85 great portland street",
    "kemp house",
    "27 old gloucester street",
    "128 city road",
    "suite 4 lincoln house",
    "167-169 great portland street",
    "c/o companies house",
    "lenta business centre",
    "63/66 hatton garden",
]

# Company statuses indicating insolvency
INSOLVENCY_STATUSES = {
    "liquidation",
    "administration",
    "receivership",
    "voluntary-arrangement",
    "insolvency-proceedings",
}

CH_BASE_URL = "https://find-and-update.company-information.service.gov.uk"


def normalize_address(address):
    """Normalize an address dict or string for comparison."""
    if isinstance(address, dict):
        parts = [
            address.get("address_line_1", ""),
            address.get("address_line_2", ""),
            address.get("locality", ""),
            address.get("postal_code", ""),
        ]
        raw = " ".join(parts)
    else:
        raw = str(address)
    return re.sub(r"[^a-z0-9 ]", "", raw.lower()).strip()


def calculate_age(dob_dict):
    """Calculate age from Companies House DOB dict {month, year}."""
    if not dob_dict or "year" not in dob_dict or "month" not in dob_dict:
        return None
    birth = date(dob_dict["year"], dob_dict["month"], 1)
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, 1))


def is_formation_agent_address(address):
    """Check if address matches known formation agent patterns."""
    normalized = normalize_address(address)
    return any(indicator in normalized for indicator in FORMATION_AGENT_INDICATORS)


def parse_date(date_str):
    """Parse a YYYY-MM-DD date string to a date object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def days_between(d1, d2):
    """Days between two dates (positive if d2 > d1)."""
    if not d1 or not d2:
        return None
    return (d2 - d1).days


def calculate_accounts_deadline(ard_date, company_type="ltd"):
    """
    Calculate accounts filing deadline.
    Private company: ARD + 9 months
    Public company: ARD + 6 months
    """
    if not ard_date:
        return None
    months = 6 if company_type in ("plc", "public-limited") else 9
    return ard_date + relativedelta(months=months)


def company_house_url(company_number):
    """Generate Companies House web URL for a company."""
    return f"{CH_BASE_URL}/company/{company_number}"


def officer_url(officer_id):
    """Generate Companies House web URL for an officer."""
    return f"{CH_BASE_URL}/officers/{officer_id}/appointments"


def extract_officer_id(links):
    """Extract officer_id from the links dict in an officers response."""
    if not links:
        return None
    # e.g. "/officers/abc123/appointments" -> "abc123"
    officer_link = links.get("officer", {}).get("appointments", "")
    if not officer_link:
        # Try self link
        officer_link = links.get("self", "")
    parts = officer_link.split("/")
    for i, part in enumerate(parts):
        if part == "officers" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def levenshtein_similarity(s1, s2):
    """
    Calculate similarity ratio between two strings using Levenshtein distance.
    Returns a float between 0 (completely different) and 1 (identical).
    """
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    # Create distance matrix
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)

    distance = dp[len1][len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len)


def calculate_dissolution_rate(appointments):
    """
    Calculate the dissolution rate from a list of appointments.
    Returns (dissolved_count, total_count, rate_percentage).
    """
    if not appointments:
        return 0, 0, 0.0

    total = len(appointments)
    dissolved = sum(
        1 for a in appointments
        if a.get("appointed_to", {}).get("company_status") == "dissolved"
    )
    rate = (dissolved / total * 100) if total > 0 else 0.0
    return dissolved, total, rate


def calculate_median_tenure(appointments):
    """
    Calculate median tenure in years from a list of appointments.
    Only includes appointments with both appointed_on date.
    """
    tenures = []
    today = date.today()

    for appt in appointments:
        appointed = parse_date(appt.get("appointed_on"))
        resigned = parse_date(appt.get("resigned_on"))
        if not appointed:
            continue
        end = resigned if resigned else today
        tenure_days = (end - appointed).days
        if tenure_days >= 0:
            tenures.append(tenure_days / 365.25)

    if not tenures:
        return None
    tenures.sort()
    mid = len(tenures) // 2
    if len(tenures) % 2 == 0:
        return (tenures[mid - 1] + tenures[mid]) / 2
    return tenures[mid]


def calculate_churn_rate(appointments):
    """
    Calculate appointment churn rate (new appointments per year).
    Based on the date range of all appointments.
    """
    if not appointments:
        return 0.0

    dates = []
    for appt in appointments:
        d = parse_date(appt.get("appointed_on"))
        if d:
            dates.append(d)

    if len(dates) < 2:
        return 0.0

    dates.sort()
    span_years = (dates[-1] - dates[0]).days / 365.25
    if span_years < 0.5:
        return 0.0

    return len(appointments) / span_years


def sic_codes_match(sic1, sic2):
    """
    Check if two lists of SIC codes have any overlap.
    SIC codes are 5-digit strings.
    """
    if not sic1 or not sic2:
        return False
    set1 = set(sic1) if isinstance(sic1, list) else {sic1}
    set2 = set(sic2) if isinstance(sic2, list) else {sic2}
    return bool(set1 & set2)
