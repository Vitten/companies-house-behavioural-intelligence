# Workflow: Analyze Company Behavioral Intelligence

## Objective
Take a UK company number, run all 6 behavioral dimension analyzers against Companies House data, and return a structured risk profile.

## Inputs
- **Company number**: 8-character UK Companies House number (zero-padded)

## Tools Used
1. `tools/api_client.py` — All Companies House API calls
2. `tools/cache.py` — 24-hour file-based caching
3. `tools/analyzer_director_track_record.py` — Dimension 1
4. `tools/analyzer_related_party.py` — Dimension 2
5. `tools/analyzer_filing_discipline.py` — Dimension 3
6. `tools/analyzer_governance_stability.py` — Dimension 4
7. `tools/analyzer_ownership_clarity.py` — Dimension 5
8. `tools/analyzer_transaction_readiness.py` — Dimension 6

## Steps
1. Validate company number format (8 chars, zero-pad if numeric)
2. Fetch company profile via `api_client.get_company()`
3. If 404 → return "Company not found"
4. Run all 6 analyzers in parallel (`ThreadPoolExecutor`)
5. Each analyzer returns: `{dimension, title, icon, question, rating, summary, evidence[], rating_logic, what_to_ask[]}`
6. Aggregate into response with company profile + all dimensions + metadata

## Expected Output
JSON with:
- `company_profile`: name, number, status, incorporation date, address
- `dimensions`: dict of 6 dimension results
- `metadata`: timestamp, elapsed time

## Error Handling
- **404 Company**: Return friendly error, suggest checking number
- **429 Rate Limit**: Auto-retry with exponential backoff (10s, 30s, 60s)
- **500/503 API**: Retry 3 times, then mark dimension as failed
- **Partial failures**: Return completed dimensions, note failures

## Performance
- Target: <2s first card (via SSE streaming), <8s full analysis
- Caching: 24hr for all endpoints except overdue status (always fresh)
- Rate limit: 600 requests per 5-minute window

## Known Quirks
- Companies House DOB only has month/year, not day
- Some officers don't have extractable officer_id from links
- PSC recursive tracing limited to 3 levels to avoid infinite loops
- Filing deadline calculation differs for first accounts (21 months from incorporation)

## Running the App
```bash
cd "/path/to/project"
python3 app.py
# Open http://localhost:5000
```
