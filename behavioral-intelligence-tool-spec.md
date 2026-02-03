# Behavioral Intelligence Tool
## Product Specification

**Purpose:** Surface soft behavioral signals about company owners and directors that indicate risk—the patterns that waste a year of diligence when missed.

**Design Philosophy:** No blended scores. Each behavioral dimension stands alone with a clear rating and expandable evidence trail. The user sees the facts and draws their own conclusions.

---

## 1. The Problem This Solves

Hard financial metrics (balance sheet, P&L) are table stakes—any searcher can request management accounts. What kills deals late in the process are the **behavioral patterns** that only emerge through systematic registry analysis:

- An owner who previously put a company into administration
- A director's son working in the business under a different surname
- A pattern of late filings suggesting operational chaos
- Rapid director turnover before a sale process
- Offshore ownership chains obscuring who really controls the company

These signals are all in Companies House—but scattered across endpoints and requiring cross-referencing to surface. This tool assembles them into a single behavioral profile.

---

## 2. User Experience

### 2.1 Input

Single input field: **UK Company Number** (8 characters)

Optional: Company name search with autocomplete that resolves to company number.

### 2.2 Output: Dimension Cards

The screen displays **6 behavioral dimension cards** in a grid (2×3 or responsive single column on mobile).

Each card shows:
- **Dimension name** and one-line description
- **Rating badge**: Clean (green) / Investigate (amber) / Red Flag (red)
- **Summary line**: One sentence explaining the rating
- **Expand/collapse control**: Click to reveal evidence

### 2.3 Expanded View

When a dimension card is expanded, it reveals:
- **The question being answered** (e.g., "Have these directors been associated with failed companies?")
- **Evidence items**: Each piece of data that contributed to the rating, with:
  - What was found
  - Where it came from (API endpoint reference)
  - Why it matters
  - Link to Companies House source (where applicable)
- **Rating logic**: Explicit explanation of how evidence → rating

### 2.4 Visual Design Principles

- **No composite scores**: Each dimension rated independently
- **Evidence-first**: Rating is always backed by expandable detail
- **Scannable**: A user should understand the risk profile in 10 seconds
- **Actionable**: Each red flag includes "what to ask" guidance

---

## 3. Behavioral Dimensions

### 3.1 Director Track Record

**Question:** Have these directors been associated with companies that failed?

**What we're detecting:**
- Directors who were present when a company entered liquidation, administration, or CVA
- Formal disqualifications (statutory ban from acting as director)
- Pattern of multiple failures (serial failure risk)
- Timing: Did they resign just before insolvency (rats leaving ship)?

**API Flow:**

```
1. GET /company/{company_number}/officers
   → Extract officer_id for each current director

2. GET /officers/{officer_id}/appointments
   → Returns ALL companies this person has been associated with
   → Check appointed_to.company_status for each:
     - "liquidation"
     - "administration"  
     - "receivership"
     - "voluntary-arrangement"
     - "insolvency-proceedings"

3. For flagged companies:
   GET /company/{flagged_company_number}/insolvency
   → Get insolvency case details (date, type, practitioners)

4. GET /disqualified-officers/natural/{officer_id}
   → Check for formal disqualification (404 = not disqualified)
```

**Evidence to Display:**

| Evidence Item | Source | Display Format |
|---------------|--------|----------------|
| Failed company name | appointments endpoint | "ACME LTD (12345678) - Liquidation" |
| Director's role | appointments endpoint | "Director from 2018-03-15 to 2022-01-10" |
| Insolvency date | insolvency endpoint | "Entered CVL on 2022-06-20" |
| Timing assessment | Calculated | "Director was present at failure" or "Resigned 3 months before insolvency" |
| Disqualification | disqualified-officers endpoint | "Disqualified until 2028-05-01 - Reason: [reason]" |

**Rating Logic:**

| Condition | Rating |
|-----------|--------|
| Any director formally disqualified | 🔴 Red Flag |
| Director present at 2+ insolvencies | 🔴 Red Flag |
| Director present at 1 insolvency | 🟡 Investigate |
| Director resigned within 6 months before insolvency | 🟡 Investigate |
| No insolvency associations found | 🟢 Clean |

**"What to Ask" Guidance:**
- "Ask the seller to explain their involvement in [COMPANY NAME]'s insolvency"
- "Request the IP's report from the [COMPANY NAME] liquidation"
- "Verify the circumstances were external (industry downturn, COVID) vs. management failure"

---

### 3.2 Related Party Signals

**Question:** Are there hidden family or business relationships we should know about?

**What we're detecting:**
- Directors/PSCs who share residential addresses (may indicate family relationship)
- Directors with appointments to the same other companies (business network)
- Directors whose other company appointments overlap with PSCs of this company
- Unusual patterns: e.g., young person (by DOB) as PSC of holding company

**API Flow:**

```
1. GET /company/{company_number}/officers
   → Extract all current directors with:
     - address (residential address for service)
     - date_of_birth (month/year only)
     - officer_id

2. GET /company/{company_number}/persons-with-significant-control
   → Extract all PSCs with:
     - address
     - date_of_birth (for individuals)
     - name

3. Cross-reference:
   a) Address matching between directors and PSCs
   b) Address matching between different directors
   
4. For each director:
   GET /officers/{officer_id}/appointments
   → Get all their other company associations
   
5. For each PSC that is a corporate entity:
   GET /company/{psc_company_number}/officers
   → Check if any target company directors also appear here

6. Build relationship graph:
   - Shared addresses → potential family
   - Shared company appointments → business network
   - Director of holding company = PSC of target → control structure
```

**Evidence to Display:**

| Evidence Item | Source | Display Format |
|---------------|--------|----------------|
| Shared address | officers + PSC endpoints | "John Smith (Director) and Jane Smith (PSC) share address: 45 Oak Lane, London" |
| Common directorships | appointments endpoint | "John Smith and Robert Jones are both directors of 3 other companies: [list]" |
| Young PSC | PSC endpoint | "PSC 'Thomas Holdings Ltd' controlled by individual DOB 2001 (age ~24)" |
| Director = Holding company officer | appointments + PSC endpoints | "Director Sarah Mitchell is also director of MITCHELL HOLDINGS LTD, which is the 75% PSC" |

**Pattern Detection Rules:**

```python
def detect_related_party_signals(directors, pscs, appointments):
    signals = []
    
    # 1. Address clustering
    addresses = {}
    for person in directors + pscs:
        addr_key = normalize_address(person.address)
        addresses.setdefault(addr_key, []).append(person)
    
    for addr, people in addresses.items():
        if len(people) > 1:
            signals.append({
                'type': 'shared_address',
                'severity': 'medium',
                'people': people,
                'implication': 'Possible family relationship - different surnames, same address'
            })
    
    # 2. Director network overlap
    director_companies = {d.officer_id: set(a.company_number for a in d.appointments) for d in directors}
    for d1, d2 in combinations(directors, 2):
        overlap = director_companies[d1.officer_id] & director_companies[d2.officer_id]
        if len(overlap) >= 2:
            signals.append({
                'type': 'business_network',
                'severity': 'low',
                'directors': [d1, d2],
                'shared_companies': overlap,
                'implication': 'Directors have prior business relationship'
            })
    
    # 3. Young PSC of holding company
    for psc in pscs:
        if psc.kind == 'individual' and psc.date_of_birth:
            age = calculate_age(psc.date_of_birth)
            if age < 25 and 'ownership-of-shares-75-to-100' in psc.natures_of_control:
                signals.append({
                    'type': 'young_majority_owner',
                    'severity': 'medium',
                    'psc': psc,
                    'implication': 'Young individual holds majority control - verify if nominee for family member'
                })
    
    return signals
```

**Rating Logic:**

| Condition | Rating |
|-----------|--------|
| Shared addresses between differently-surnamed individuals | 🟡 Investigate |
| Director is also officer of PSC company | 🟡 Investigate |
| Multiple overlapping directorships across network | 🟡 Investigate |
| No related party signals detected | 🟢 Clean |
| Note: This dimension rarely goes Red—it surfaces questions, not conclusions |

**"What to Ask" Guidance:**
- "Clarify the relationship between [PERSON A] and [PERSON B] who share an address"
- "Confirm whether [YOUNG PSC] is acting as nominee for another family member"
- "Understand the history of the business relationship between [DIRECTOR 1] and [DIRECTOR 2]"

---

### 3.3 Filing Discipline

**Question:** Do they treat statutory obligations seriously?

**What we're detecting:**
- Pattern of late annual accounts filings
- Overdue accounts or confirmation statement right now
- Filing corrections/amendments (suggests errors or changes to hide something)
- Accounting reference date changes (sometimes used to delay filings)

**API Flow:**

```
1. GET /company/{company_number}
   → Check:
     - accounts.overdue (boolean)
     - confirmation_statement.overdue (boolean)
     - accounts.next_accounts.due_on
     - confirmation_statement.next_due

2. GET /company/{company_number}/filing-history?items_per_page=100
   → For each accounts filing (category: "accounts"):
     - Extract filing date
     - Calculate expected deadline (accounting_reference_date + 9 months for private company)
     - Flag if filed in final 14 days or after deadline
   
   → For confirmation statements (category: "confirmation-statement"):
     - Check for gaps > 14 months between filings
   
   → Look for filing types indicating corrections:
     - Type contains "AMENDED"
     - Type contains "REPLACEMENT"
     - Type "AA" (change of accounting reference date)
```

**Deadline Calculation:**

```python
def calculate_accounts_deadline(accounting_reference_date, company_type):
    """
    Private company: ARD + 9 months
    Public company: ARD + 6 months
    First accounts: 21 months from incorporation
    """
    if company_type in ['ltd', 'private-limited']:
        return accounting_reference_date + timedelta(months=9)
    else:
        return accounting_reference_date + timedelta(months=6)

def assess_filing_timeliness(filing_date, deadline):
    days_before = (deadline - filing_date).days
    if days_before < 0:
        return 'late'
    elif days_before < 14:
        return 'last_minute'
    else:
        return 'on_time'
```

**Evidence to Display:**

| Evidence Item | Source | Display Format |
|---------------|--------|----------------|
| Current overdue status | company profile | "⚠️ Accounts currently OVERDUE (due: 2024-12-31)" |
| Late filing instance | filing-history | "Accounts for Y/E 2023-03-31 filed 2024-02-15 (12 days late)" |
| Last-minute pattern | filing-history | "4 of last 5 accounts filed within final 14 days of deadline" |
| Amendment | filing-history | "Amended accounts filed 2023-08-20 replacing original" |
| ARD change | filing-history | "Accounting reference date changed on 2022-05-01" |

**Rating Logic:**

| Condition | Rating |
|-----------|--------|
| Accounts or confirmation statement currently overdue | 🔴 Red Flag |
| 2+ late filings in last 5 years | 🔴 Red Flag |
| Pattern of last-minute filings (3+ of last 5) | 🟡 Investigate |
| Any amended/replacement accounts | 🟡 Investigate |
| Multiple ARD changes | 🟡 Investigate |
| Consistent on-time filing | 🟢 Clean |

**"What to Ask" Guidance:**
- "Why were the 2023 accounts filed late? Was this a one-off or systemic?"
- "What was corrected in the amended accounts filing?"
- "Why was the accounting reference date changed in [YEAR]?"

---

### 3.4 Governance Stability

**Question:** Is leadership stable or is there concerning churn?

**What we're detecting:**
- High director turnover (multiple resignations/appointments in short period)
- Recent director changes (within last 6 months—possible pre-transaction positioning)
- Sole director risk (key person dependency)
- Registered office changes (especially to/from formation agent addresses)
- Very short director tenures historically

**API Flow:**

```
1. GET /company/{company_number}/officers
   → For current directors:
     - Count active directors
     - Calculate tenure (today - appointed_on)
   
   → For resigned directors:
     - Count resignations in last 3 years
     - Identify any appointed then resigned within 12 months

2. GET /company/{company_number}/registered-office-address
   → Current address

3. GET /company/{company_number}/filing-history?category=address
   → Count address changes
   → Check if any addresses match known formation agents
```

**Formation Agent Address Detection:**

```python
FORMATION_AGENT_INDICATORS = [
    '71-75 shelton street',
    '20-22 wenlock road', 
    '85 great portland street',
    'kemp house',
    '27 old gloucester street',
    # Add known formation agent addresses
]

def is_formation_agent_address(address):
    normalized = normalize_address(address)
    return any(indicator in normalized for indicator in FORMATION_AGENT_INDICATORS)
```

**Evidence to Display:**

| Evidence Item | Source | Display Format |
|---------------|--------|----------------|
| Current director count | officers endpoint | "2 active directors" |
| Average tenure | officers endpoint | "Average director tenure: 4.2 years" |
| Recent appointment | officers endpoint | "New director appointed 2024-09-01 (4 months ago)" |
| Resignation | officers endpoint | "Previous director resigned 2024-08-15 after 2 years" |
| Short tenure pattern | officers endpoint | "3 directors served less than 18 months in last 5 years" |
| Formation agent address | registered-office | "Registered office is a known formation agent address" |
| Address changes | filing-history | "Registered office changed 3 times in last 3 years" |

**Rating Logic:**

| Condition | Rating |
|-----------|--------|
| Director appointed in last 3 months | 🟡 Investigate |
| 3+ director changes in last 2 years | 🔴 Red Flag |
| Sole director | 🟡 Investigate |
| Average tenure < 2 years | 🟡 Investigate |
| Formation agent address | 🟡 Investigate |
| 3+ registered office changes in 3 years | 🟡 Investigate |
| Stable board (2+ directors, 3+ year average tenure) | 🟢 Clean |

**"What to Ask" Guidance:**
- "Why did [DIRECTOR NAME] leave in [DATE]? Can we speak with them?"
- "What prompted the recent board change?"
- "Why is the registered office at a formation agent rather than trading address?"

---

### 3.5 Ownership Clarity

**Question:** Is it clear who controls this company and why?

**What we're detecting:**
- Corporate PSCs (company owns company—adds complexity)
- Offshore/foreign PSCs (hard to trace further)
- Trust or legal person PSCs (requires deed review)
- Missing or unclear PSC information (statements instead of actual PSCs)
- PSC churn (frequent ownership changes)
- Control structure complexity (multiple layers)

**API Flow:**

```
1. GET /company/{company_number}/persons-with-significant-control
   → Categorize each PSC:
     - kind: "individual-person-with-significant-control" → terminal (good)
     - kind: "corporate-entity-person-with-significant-control" → trace further
     - kind: "legal-person-person-with-significant-control" → trust (complex)
   
   → For corporate PSCs, check identification.place_registered:
     - UK company number → can trace (call recursively)
     - Foreign jurisdiction → terminal but flag

2. GET /company/{company_number}/persons-with-significant-control-statements
   → Flag any statements (indicates PSC information incomplete):
     - "psc-exists-but-not-identified"
     - "psc-details-not-confirmed"
     - "steps-to-find-psc-not-yet-completed"

3. For UK corporate PSCs (recursive, max 3 levels):
   GET /company/{psc_company_number}/persons-with-significant-control
   → Continue until hitting individuals or foreign entities
```

**Structure Complexity Calculation:**

```python
def calculate_ownership_complexity(pscs, depth=0, max_depth=3):
    complexity = {
        'depth': depth,
        'individual_owners': 0,
        'corporate_layers': 0,
        'foreign_entities': [],
        'trusts': 0,
        'untraceable': False
    }
    
    for psc in pscs:
        if psc.kind == 'individual-person-with-significant-control':
            complexity['individual_owners'] += 1
            
        elif psc.kind == 'corporate-entity-person-with-significant-control':
            complexity['corporate_layers'] += 1
            
            if is_uk_company(psc.identification):
                if depth < max_depth:
                    sub_pscs = fetch_pscs(psc.identification.registration_number)
                    sub_complexity = calculate_ownership_complexity(sub_pscs, depth + 1)
                    # Merge sub_complexity into complexity
                else:
                    complexity['untraceable'] = True
            else:
                complexity['foreign_entities'].append({
                    'name': psc.name,
                    'jurisdiction': psc.identification.place_registered
                })
                
        elif psc.kind == 'legal-person-person-with-significant-control':
            complexity['trusts'] += 1
    
    return complexity
```

**Evidence to Display:**

| Evidence Item | Source | Display Format |
|---------------|--------|----------------|
| Direct individual owner | PSC endpoint | "John Smith (UK) owns 75-100% directly" |
| Corporate PSC | PSC endpoint | "HOLDCO LIMITED (UK company 87654321) owns 75-100%" |
| Foreign PSC | PSC endpoint | "OFFSHORE INC (British Virgin Islands) owns 50-75%" |
| Trust PSC | PSC endpoint | "SMITH FAMILY TRUST controls via right to appoint directors" |
| PSC statement | PSC statements | "⚠️ Statement filed: 'PSC exists but not identified'" |
| Ownership depth | calculated | "3-layer structure: Target ← Holdco ← Offshore entity" |
| Ceased PSC | PSC endpoint | "Previous PSC 'ABC Ltd' ceased control 2023-06-01" |

**Rating Logic:**

| Condition | Rating |
|-----------|--------|
| PSC statement indicating unidentified controller | 🔴 Red Flag |
| Foreign entity in ownership chain | 🟡 Investigate |
| Trust/legal person in ownership chain | 🟡 Investigate |
| 3+ corporate layers | 🟡 Investigate |
| 2+ PSC changes in last 2 years | 🟡 Investigate |
| Direct individual UK ownership | 🟢 Clean |

**"What to Ask" Guidance:**
- "Who is the ultimate beneficial owner of [OFFSHORE ENTITY]?"
- "Can we see the trust deed for [TRUST NAME]?"
- "Why is ownership structured through [HOLDCO] rather than directly?"
- "What prompted the ownership change in [DATE]?"

---

### 3.6 Transaction Readiness

**Question:** How much friction should we expect in executing this deal?

**What we're detecting:**
- Outstanding charges (existing lender consents required)
- All-assets debenture (lender has significant control)
- Recent charge activity (possible cash stress)
- Multiple secured creditors (complex intercreditor dynamics)
- Structure complexity (multiple entities to acquire)
- Governance gaps (missing secretary, incomplete registers)

**API Flow:**

```
1. GET /company/{company_number}/charges
   → Count outstanding charges
   → Identify all-assets debentures (particulars.floating_charge_covers_all = true)
   → Check for charges created in last 6 months
   → List all persons_entitled (secured creditors)

2. GET /company/{company_number}
   → Check has_charges flag
   → Check company_status for any concerning states

3. GET /company/{company_number}/registers
   → Check register locations (if not held at Companies House, adds diligence step)
```

**Evidence to Display:**

| Evidence Item | Source | Display Format |
|---------------|--------|----------------|
| Outstanding charge | charges endpoint | "Charge to Barclays Bank plc (created 2020-03-15) - OUTSTANDING" |
| All-assets debenture | charges endpoint | "⚠️ Floating charge covers ALL assets - lender consent required for sale" |
| Recent charge | charges endpoint | "New charge registered 2024-08-01 (5 months ago)" |
| Multiple lenders | charges endpoint | "2 secured creditors: Barclays, HSBC" |
| Satisfied charge | charges endpoint | "Previous charge to NatWest satisfied 2023-01-15" |
| Ownership layers | PSC analysis | "Acquisition requires control of 2 entities" |

**Transaction Friction Scoring:**

```python
def assess_transaction_friction(charges, structure_complexity, governance):
    friction_points = []
    
    # Charges
    outstanding = [c for c in charges if c.status == 'outstanding']
    if any(c.particulars.floating_charge_covers_all for c in outstanding):
        friction_points.append({
            'issue': 'All-assets debenture',
            'impact': 'Lender consent required; expect 2-4 weeks for approval process',
            'action': 'Engage lender early; request consent letter template'
        })
    
    if len(set(c.persons_entitled[0].name for c in outstanding)) > 1:
        friction_points.append({
            'issue': 'Multiple secured creditors',
            'impact': 'Intercreditor dynamics; potential competing interests',
            'action': 'Review intercreditor agreement; understand subordination'
        })
    
    recent_charges = [c for c in charges if (today - c.created_on).days < 180]
    if recent_charges:
        friction_points.append({
            'issue': 'Recent charge activity',
            'impact': 'May indicate recent refinancing or cash stress',
            'action': 'Understand reason for recent borrowing'
        })
    
    # Structure
    if structure_complexity['corporate_layers'] > 1:
        friction_points.append({
            'issue': f"{structure_complexity['corporate_layers']} corporate layers",
            'impact': 'Share purchase may require multiple SPAs or upstream consents',
            'action': 'Map all entities; confirm which shares are being acquired'
        })
    
    if structure_complexity['foreign_entities']:
        friction_points.append({
            'issue': 'Foreign entity in structure',
            'impact': 'May require foreign legal opinion; withholding tax considerations',
            'action': 'Engage local counsel in relevant jurisdiction'
        })
    
    return friction_points
```

**Rating Logic:**

| Condition | Rating |
|-----------|--------|
| All-assets debenture outstanding | 🟡 Investigate |
| Charge created in last 6 months | 🟡 Investigate |
| Multiple secured creditors | 🟡 Investigate |
| Multi-entity structure | 🟡 Investigate |
| Foreign elements in structure | 🟡 Investigate |
| No charges, simple structure | 🟢 Clean |
| Note: This dimension is about friction, not red flags—rarely goes Red |

**"What to Ask" Guidance:**
- "Has the lender been informed of the potential sale? What's their typical consent process?"
- "Why was the recent charge taken out? What were the proceeds used for?"
- "Can the structure be simplified pre-completion?"

---

## 4. API Endpoint Reference

### 4.1 Required Endpoints

| Endpoint | Purpose | Dimensions Using It |
|----------|---------|---------------------|
| `GET /company/{n}` | Company profile, overdue flags | Filing Discipline, Transaction Readiness |
| `GET /company/{n}/officers` | Director list with addresses, DOBs | Director Track Record, Related Party, Governance |
| `GET /officers/{id}/appointments` | All companies per director | Director Track Record, Related Party |
| `GET /disqualified-officers/natural/{id}` | Disqualification check | Director Track Record |
| `GET /company/{n}/insolvency` | Insolvency case details | Director Track Record |
| `GET /company/{n}/persons-with-significant-control` | PSC list | Related Party, Ownership Clarity |
| `GET /company/{n}/persons-with-significant-control-statements` | PSC statements | Ownership Clarity |
| `GET /company/{n}/filing-history` | All filings | Filing Discipline, Governance |
| `GET /company/{n}/charges` | Charge list | Transaction Readiness |
| `GET /company/{n}/registered-office-address` | Current address | Governance Stability |

### 4.2 API Call Budget

| Analysis Depth | Estimated Calls | Rate Limit Impact |
|----------------|-----------------|-------------------|
| Basic (no director tracing) | 8-10 | ~60 companies/5min |
| Standard (director history) | 15-25 | ~25 companies/5min |
| Full (recursive PSC tracing) | 25-40 | ~15 companies/5min |

### 4.3 Authentication

```
Authorization: Basic {base64(api_key + ':')}
```

All endpoints require API key authentication. Rate limit: 600 requests per 5-minute window.

---

## 5. User Interface Specification

### 5.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [Logo]  Companies House Behavioral Intelligence                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Company Number: [________12345678________] [Analyze]          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   EXAMPLE MANUFACTURING LIMITED                                 │
│   Company #12345678 • Incorporated 2015 • Active                │
│   123 Industrial Way, Birmingham B1 1AA                         │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐  │
│  │ 👥 Director Track Record│  │ 🔗 Related Party Signals    │  │
│  │ ──────────────────────  │  │ ────────────────────────    │  │
│  │ [🔴 RED FLAG]           │  │ [🟡 INVESTIGATE]            │  │
│  │                         │  │                             │  │
│  │ 1 director associated   │  │ 2 individuals share         │  │
│  │ with previous CVA       │  │ residential address         │  │
│  │                         │  │                             │  │
│  │ [▼ Show Details]        │  │ [▼ Show Details]            │  │
│  └─────────────────────────┘  └─────────────────────────────┘  │
│                                                                 │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐  │
│  │ 📋 Filing Discipline    │  │ 🛡️ Governance Stability     │  │
│  │ ──────────────────────  │  │ ────────────────────────    │  │
│  │ [🟢 CLEAN]              │  │ [🟢 CLEAN]                  │  │
│  │                         │  │                             │  │
│  │ All filings on time     │  │ Stable board, 4yr avg       │  │
│  │ for last 5 years        │  │ tenure, no recent changes   │  │
│  │                         │  │                             │  │
│  │ [▼ Show Details]        │  │ [▼ Show Details]            │  │
│  └─────────────────────────┘  └─────────────────────────────┘  │
│                                                                 │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐  │
│  │ 🏛️ Ownership Clarity    │  │ 📊 Transaction Readiness    │  │
│  │ ──────────────────────  │  │ ────────────────────────    │  │
│  │ [🟡 INVESTIGATE]        │  │ [🟡 INVESTIGATE]            │  │
│  │                         │  │                             │  │
│  │ 2-layer corporate       │  │ All-assets debenture        │  │
│  │ structure via Holdco    │  │ requires lender consent     │  │
│  │                         │  │                             │  │
│  │ [▼ Show Details]        │  │ [▼ Show Details]            │  │
│  └─────────────────────────┘  └─────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Expanded Card View

```
┌─────────────────────────────────────────────────────────────────┐
│ 👥 Director Track Record                          [🔴 RED FLAG] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Question: Have these directors been associated with companies   │
│ that failed?                                                    │
│                                                                 │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ EVIDENCE                                                        │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ⚠️ HIGH SEVERITY                                            │ │
│ │                                                             │ │
│ │ Sarah Mitchell - Director (appointed 2018-03-15)            │ │
│ │                                                             │ │
│ │ Previously director of:                                     │ │
│ │ • MITCHELL TRADING LTD (09876543)                           │ │
│ │   Status: Liquidation                                       │ │
│ │   Role: Director from 2014-06-01 to 2019-02-28              │ │
│ │   Insolvency: Creditors Voluntary Liquidation               │ │
│ │   Date: 2019-03-15                                          │ │
│ │   Assessment: DIRECTOR WAS PRESENT AT FAILURE               │ │
│ │                                                             │ │
│ │   [View on Companies House ↗]                               │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ✓ NO ISSUES                                                 │ │
│ │                                                             │ │
│ │ James Wilson - Director (appointed 2015-03-20)              │ │
│ │                                                             │ │
│ │ 12 other appointments checked - no insolvencies found       │ │
│ │ Not on disqualified directors register                      │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ RATING LOGIC                                                    │
│ • Red Flag: 1 director present at insolvency                    │
│                                                                 │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ WHAT TO ASK                                                     │
│ • "Ask Sarah Mitchell to explain her involvement in MITCHELL    │
│    TRADING LTD's liquidation"                                   │
│ • "Request the liquidator's report - was there any finding of   │
│    director misconduct?"                                        │
│ • "Verify whether the failure was due to external factors       │
│    (market conditions) vs. management decisions"                │
│                                                                 │
│                                                    [▲ Collapse] │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Rating Badge Styles

| Rating | Background | Text | Icon |
|--------|------------|------|------|
| Clean | `#10B981` (emerald-500) | White | ✓ checkmark |
| Investigate | `#F59E0B` (amber-500) | White | ⚠️ warning triangle |
| Red Flag | `#EF4444` (red-500) | White | 🚩 flag |

### 5.4 Responsive Behavior

- **Desktop (>1024px):** 2-column grid of dimension cards
- **Tablet (768-1024px):** 2-column grid, smaller cards
- **Mobile (<768px):** Single column stack

---

## 6. Implementation Notes

### 6.1 Caching Strategy

- Cache company profile data for 24 hours
- Cache officer appointments for 24 hours
- Cache filing history for 24 hours
- Do NOT cache overdue status (check live)

### 6.2 Error Handling

| Error | User Message | Action |
|-------|--------------|--------|
| 404 on company | "Company not found. Check the number and try again." | Show search suggestion |
| 429 rate limit | "We're checking a lot of companies right now. Please wait 30 seconds." | Auto-retry with backoff |
| 500/503 | "Companies House is temporarily unavailable. Please try again." | Retry button |
| Partial data | Show available dimensions; note which couldn't be checked | Continue with warnings |

### 6.3 Performance Targets

| Metric | Target |
|--------|--------|
| Time to first card rendered | < 2 seconds |
| Full analysis complete | < 8 seconds |
| Director history (per director) | < 1 second |

### 6.4 Data Freshness Indicators

Show "Data as of: [date/time]" on each card, reflecting when the Companies House data was retrieved.

---

## 7. Future Enhancements

### 7.1 Phase 2 Candidates

- **Bulk screening:** CSV upload of company numbers with summary export
- **Comparison mode:** Side-by-side view of 2-3 companies
- **Alert/monitoring:** Watch a company and notify on changes
- **PDF export:** One-page summary for deal files

### 7.2 Data Enrichment

- **Gazette notices:** Integrate London Gazette for winding-up petitions
- **Court records:** Check for CCJs against directors
- **Disqualified directors search by name:** Catch aliases

---

## 8. Appendix: Company Status Values

| Status | Meaning | Concern Level |
|--------|---------|---------------|
| `active` | Trading normally | None |
| `dissolved` | No longer exists | N/A (can't acquire) |
| `liquidation` | Being wound up | High |
| `administration` | Under administrator | High |
| `receivership` | Receiver appointed | High |
| `voluntary-arrangement` | CVA in place | High |
| `insolvency-proceedings` | Generic insolvency | High |
| `active-proposal-to-strike-off` | May be struck off soon | Medium |
