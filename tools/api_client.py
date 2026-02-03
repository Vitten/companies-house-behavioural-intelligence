"""
Companies House API client with rate limiting, caching, and error handling.
All API calls funnel through this module.
"""

import os
import time
import base64
import logging
from collections import deque
from dotenv import load_dotenv
import requests

load_dotenv()
logger = logging.getLogger(__name__)

API_BASE = "https://api.company-information.service.gov.uk"


class RateLimiter:
    """Token bucket rate limiter: 600 requests per 5-minute window."""

    def __init__(self, max_requests=600, window_seconds=300):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests = deque()

    def acquire(self):
        now = time.time()
        while self.requests and self.requests[0] < now - self.window:
            self.requests.popleft()
        if len(self.requests) >= self.max_requests:
            wait_time = self.requests[0] + self.window - now
            logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
            time.sleep(wait_time)
            return self.acquire()
        self.requests.append(now)

    def remaining(self):
        now = time.time()
        while self.requests and self.requests[0] < now - self.window:
            self.requests.popleft()
        return self.max_requests - len(self.requests)


class CompaniesHouseClient:
    """Wrapper for all Companies House API endpoints."""

    def __init__(self, api_key=None, cache=None):
        self.api_key = api_key or os.getenv("COMPANIES_HOUSE_API_KEY")
        if not self.api_key:
            raise ValueError("COMPANIES_HOUSE_API_KEY not set")
        self.auth = base64.b64encode(f"{self.api_key}:".encode()).decode()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Basic {self.auth}",
            "Accept": "application/json",
        })
        self.rate_limiter = RateLimiter()
        self.cache = cache

    def _get(self, path, params=None, cache_ttl=86400):
        """Core GET request with caching, rate limiting, and retries."""
        cache_key = f"{path}:{params}" if params else path

        # Check cache
        if self.cache and cache_ttl > 0:
            cached = self.cache.get(cache_key, ttl=cache_ttl)
            if cached is not None:
                logger.debug(f"Cache hit: {path}")
                return cached

        self.rate_limiter.acquire()
        url = f"{API_BASE}{path}"

        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=30)

                if resp.status_code == 200:
                    data = resp.json()
                    if self.cache and cache_ttl > 0:
                        self.cache.set(cache_key, data)
                    return data
                elif resp.status_code == 404:
                    return None
                elif resp.status_code == 429:
                    wait = [10, 30, 60][attempt]
                    logger.warning(f"429 rate limited, waiting {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                    continue
                else:
                    logger.error(f"API error {resp.status_code}: {path}")
                    if attempt < 2:
                        time.sleep(5)
                        continue
                    return None

            except requests.RequestException as e:
                logger.error(f"Request failed: {path} - {e}")
                if attempt < 2:
                    time.sleep(5)
                    continue
                return None

        return None

    # --- Endpoint methods ---

    def get_company(self, company_number):
        """Company profile including overdue flags."""
        return self._get(f"/company/{company_number}")

    def get_officers(self, company_number, items_per_page=100):
        """All officers (directors, secretaries) for a company."""
        return self._get(
            f"/company/{company_number}/officers",
            params={"items_per_page": items_per_page},
        )

    def get_appointments(self, officer_id, items_per_page=50):
        """All company appointments for a specific officer."""
        return self._get(
            f"/officers/{officer_id}/appointments",
            params={"items_per_page": items_per_page},
        )

    def get_disqualifications(self, officer_id):
        """Check if an officer is disqualified. Returns None if not."""
        return self._get(f"/disqualified-officers/natural/{officer_id}")

    def get_insolvency(self, company_number):
        """Insolvency case details for a company."""
        return self._get(f"/company/{company_number}/insolvency")

    def get_pscs(self, company_number):
        """Persons with Significant Control."""
        return self._get(f"/company/{company_number}/persons-with-significant-control")

    def get_psc_statements(self, company_number):
        """PSC statements (indicates incomplete PSC info)."""
        return self._get(
            f"/company/{company_number}/persons-with-significant-control-statements"
        )

    def get_filing_history(self, company_number, category=None, items_per_page=100):
        """Filing history, optionally filtered by category."""
        params = {"items_per_page": items_per_page}
        if category:
            params["category"] = category
        return self._get(f"/company/{company_number}/filing-history", params=params)

    def get_charges(self, company_number):
        """All charges (mortgages/debentures) for a company."""
        return self._get(f"/company/{company_number}/charges")

    def get_registered_office(self, company_number):
        """Current registered office address."""
        return self._get(f"/company/{company_number}/registered-office-address")
