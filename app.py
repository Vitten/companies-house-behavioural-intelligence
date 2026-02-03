"""
Behavioral Intelligence Tool — Flask Backend
Orchestrates all analyzers and serves the frontend.
"""

import json
import logging
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, jsonify, Response, send_from_directory
from dotenv import load_dotenv

load_dotenv()

from tools.api_client import CompaniesHouseClient
from tools.cache import FileCache
from tools.usage_tracker import increment_run, get_stats
from tools import (
    analyzer_director_track_record,
    analyzer_control_network,
    analyzer_filing_discipline,
    analyzer_governance_stability,
    analyzer_ownership_clarity,
    analyzer_transaction_readiness,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend", static_url_path="")

cache = FileCache()
api_client = CompaniesHouseClient(cache=cache)

ANALYZERS = [
    analyzer_director_track_record,
    analyzer_filing_discipline,
    analyzer_governance_stability,
    analyzer_control_network,
    analyzer_ownership_clarity,
    analyzer_transaction_readiness,
]


def validate_company_number(cn):
    """Validate and normalize UK company number (8 chars, zero-padded)."""
    cn = cn.strip().upper()
    cn = re.sub(r"^(SC|NI|OC|SO|NC|R0|AC|FC|GE|LP|NA|IP|SP|IC|SI|NP|NO|RC|NR|CE)", lambda m: m.group(), cn)
    if cn.isdigit():
        cn = cn.zfill(8)
    if len(cn) < 2 or len(cn) > 8:
        return None
    return cn


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "rate_limit_remaining": api_client.rate_limiter.remaining(),
        "cache_size": cache.get_size(),
    })


@app.route("/api/analyze", methods=["POST"])
def analyze_company():
    """Run all 6 behavioral dimensions. Returns complete results."""
    data = request.get_json() or {}
    company_number = data.get("company_number", "")
    cn = validate_company_number(company_number)
    if not cn:
        return jsonify({"error": "Invalid company number"}), 400

    start = time.time()

    profile = api_client.get_company(cn)
    if not profile:
        return jsonify({"error": "Company not found. Check the number and try again."}), 404

    results = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(analyzer.analyze, api_client, cn): analyzer
            for analyzer in ANALYZERS
        }
        for future in as_completed(futures):
            analyzer = futures[future]
            try:
                result = future.result()
                results[result["dimension"]] = result
            except Exception as e:
                dim_name = analyzer.__name__.replace("tools.analyzer_", "").replace("analyzer_", "")
                logger.error(f"Analyzer {dim_name} failed: {e}", exc_info=True)
                results[dim_name] = {
                    "dimension": dim_name,
                    "title": dim_name.replace("_", " ").title(),
                    "rating": "investigate",
                    "summary": "Analysis failed — unable to complete this dimension",
                    "evidence": [],
                    "error": str(e),
                }

    elapsed = time.time() - start
    logger.info(f"Analysis of {cn} completed in {elapsed:.1f}s")

    return jsonify({
        "company_profile": {
            "company_number": cn,
            "company_name": profile.get("company_name", "Unknown"),
            "company_status": profile.get("company_status", ""),
            "type": profile.get("type", ""),
            "date_of_creation": profile.get("date_of_creation", ""),
            "registered_office_address": profile.get("registered_office_address", {}),
            "sic_codes": profile.get("sic_codes", []),
        },
        "dimensions": results,
        "metadata": {
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 1),
        },
    })


@app.route("/api/analyze/stream", methods=["POST"])
def analyze_stream():
    """Stream results via Server-Sent Events as each dimension completes."""
    data = request.get_json() or {}
    company_number = data.get("company_number", "")
    cn = validate_company_number(company_number)
    if not cn:
        return jsonify({"error": "Invalid company number"}), 400

    def generate():
        profile = api_client.get_company(cn)
        if not profile:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Company not found'})}\n\n"
            return

        # Increment usage and get stats
        usage = increment_run(cn)

        profile_data = {
            'company_number': cn,
            'company_name': profile.get('company_name', ''),
            'company_status': profile.get('company_status', ''),
            'type': profile.get('type', ''),
            'date_of_creation': profile.get('date_of_creation', ''),
            'registered_office_address': profile.get('registered_office_address', {}),
            'sic_codes': profile.get('sic_codes', []),
            'usage': usage,
        }

        yield f"data: {json.dumps({'type': 'profile', 'data': profile_data})}\n\n"

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(analyzer.analyze, api_client, cn): analyzer
                for analyzer in ANALYZERS
            }
            for future in as_completed(futures):
                analyzer = futures[future]
                try:
                    result = future.result()
                    yield f"data: {json.dumps({'type': 'dimension', 'data': result})}\n\n"
                except Exception as e:
                    dim_name = analyzer.__name__.replace("tools.analyzer_", "").replace("analyzer_", "")
                    logger.error(f"Analyzer {dim_name} failed: {e}", exc_info=True)
                    yield f"data: {json.dumps({'type': 'dimension', 'data': {'dimension': dim_name, 'title': dim_name.replace('_', ' ').title(), 'rating': 'investigate', 'summary': 'Analysis failed', 'evidence': []}})}\n\n"

        yield f"data: {json.dumps({'type': 'complete'})}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
