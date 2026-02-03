"""
Usage Tracker — File-based JSON storage for usage statistics.
Tracks global runs and per-company run counts.
"""

import json
import os
import time
from pathlib import Path
from threading import Lock

# Store in .tmp directory
STATS_FILE = Path(__file__).parent.parent / ".tmp" / "usage_stats.json"

_lock = Lock()


def _ensure_file():
    """Ensure the stats file and directory exist."""
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATS_FILE.exists():
        _write_stats({"global_runs": 0, "companies": {}})


def _read_stats():
    """Read stats from file."""
    _ensure_file()
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"global_runs": 0, "companies": {}}


def _write_stats(stats):
    """Write stats to file."""
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def increment_run(company_number: str) -> dict:
    """
    Increment run count for a company and global total.
    Returns the updated stats for this company.
    """
    with _lock:
        stats = _read_stats()

        # Increment global
        stats["global_runs"] = stats.get("global_runs", 0) + 1

        # Initialize company if not exists
        if company_number not in stats["companies"]:
            stats["companies"][company_number] = {
                "runs": 0,
                "first_run": None,
                "last_run": None,
            }

        company_stats = stats["companies"][company_number]
        company_stats["runs"] = company_stats.get("runs", 0) + 1

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not company_stats.get("first_run"):
            company_stats["first_run"] = now
        company_stats["last_run"] = now

        _write_stats(stats)

        return {
            "global_runs": stats["global_runs"],
            "company_runs": company_stats["runs"],
            "first_run": company_stats["first_run"],
            "last_run": company_stats["last_run"],
        }


def get_stats(company_number: str = None) -> dict:
    """
    Get usage stats. If company_number provided, includes that company's stats.
    """
    stats = _read_stats()

    result = {
        "global_runs": stats.get("global_runs", 0),
    }

    if company_number and company_number in stats.get("companies", {}):
        company_stats = stats["companies"][company_number]
        result["company_runs"] = company_stats.get("runs", 0)
        result["first_run"] = company_stats.get("first_run")
        result["last_run"] = company_stats.get("last_run")
    else:
        result["company_runs"] = 0
        result["first_run"] = None
        result["last_run"] = None

    return result
