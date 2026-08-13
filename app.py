import io
import traceback

from flask import Flask, request, jsonify, send_file, render_template
import pandas as pd

from engine import (
    compute, compute_compare, compute_sip, result_to_json,
    search_scheme_fast, prime_scheme_cache_async, EngineError,
)

app = Flask(__name__)
prime_scheme_cache_async()  # warm the full-scheme-list cache in the background so search is fast from the first real query

DEFAULTS = {
    "benches": [
        {"code": 120716, "label": "NIFTY50"},
        {"code": 147625, "label": "NIFTY500"},
    ],
    "target": {"equity": 0.70, "gold & silver": 0.30},
    "picks": [
        {"cls": "equity", "code": 101762, "label": "HDFC Flexi", "weight": 1},
        {"cls": "gold & silver", "code": 119132, "label": "HDFC Gold", "weight": 1},
    ],
    "wins": [1, 2, 3, 5],
    "years_back": 10,
}


@app.route("/")
def index():
    return render_template("index.html", defaults=DEFAULTS)


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    try:
        return jsonify(search_scheme_fast(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


def _parse_payload(payload):
    benches = payload.get("benches", [])
    target = payload.get("target", {})
    picks = payload.get("picks", [])
    wins = payload.get("wins", [1, 2, 3, 5])
    years_back = int(payload.get("years_back", 10))
    return benches, target, picks, wins, years_back


@app.route("/api/compute", methods=["POST"])
def api_compute():
    payload = request.get_json(force=True) or {}
    benches, target, picks, wins, years_back = _parse_payload(payload)
    try:
        result = compute(benches, target, picks, wins, years_back)
        return jsonify(result_to_json(result))
    except EngineError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error: {e}"}), 500


def _blocks_to_xlsx(blocks, sheet_name="matrix"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        row = 0
        for tag, d in blocks.items():
            pd.DataFrame([[tag]]).to_excel(xl, sheet_name=sheet_name, startrow=row, index=False, header=False)
            d.to_excel(xl, sheet_name=sheet_name, startrow=row + 1)
            row += len(d) + 4
    buf.seek(0)
    return buf


@app.route("/api/export", methods=["POST"])
def api_export():
    payload = request.get_json(force=True) or {}
    benches, target, picks, wins, years_back = _parse_payload(payload)
    try:
        result = compute(benches, target, picks, wins, years_back)
    except EngineError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    blocks = dict(result["blocks"])
    blocks["CORRELATION (full period)"] = result["corr_full"]
    blocks["CORRELATION (last 3 years)"] = result["corr_last3"]

    buf = _blocks_to_xlsx(blocks)
    return send_file(buf, as_attachment=True, download_name="mf_matrix.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/compare_export", methods=["POST"])
def api_compare_export():
    payload = request.get_json(force=True) or {}
    benches = payload.get("benches", [])
    plans = payload.get("plans", [])
    wins = payload.get("wins", [1, 2, 3, 5])
    years_back = int(payload.get("years_back", 10))
    try:
        result = compute_compare(benches, plans, wins, years_back)
    except EngineError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    blocks = {f"{y} YR CAGR % — compare": df for y, df in result["cagr"].items()}
    blocks["CALENDAR-YEAR VOLATILITY % — compare"] = result["vol"]

    buf = _blocks_to_xlsx(blocks, sheet_name="compare")
    return send_file(buf, as_attachment=True, download_name="mf_plans_compare.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/sip", methods=["POST"])
def api_sip():
    payload = request.get_json(force=True) or {}
    benches = payload.get("benches", [])
    plans = payload.get("plans", [])
    monthly_sip = payload.get("monthly_sip")
    stepup_pct = payload.get("stepup_pct") or 0
    start_date = payload.get("start_date")
    end_date = payload.get("end_date") or None
    rebalance_years = payload.get("rebalance_years") or None
    harvest_ltcg = bool(payload.get("harvest_ltcg"))
    try:
        monthly_sip = float(monthly_sip)
    except (TypeError, ValueError):
        return jsonify({"error": "Monthly SIP amount must be a number."}), 400
    if rebalance_years is not None:
        try:
            rebalance_years = float(rebalance_years)
        except (TypeError, ValueError):
            return jsonify({"error": "Rebalance interval must be a number."}), 400
    try:
        result = compute_sip(benches, plans, monthly_sip, float(stepup_pct), start_date, rebalance_years, harvest_ltcg, end_date)
        return jsonify(result)
    except EngineError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error: {e}"}), 500


if __name__ == "__main__":
    # threaded=True lets several plans' /api/compute calls (Compare tab) run
    # concurrently instead of queueing one after another on the dev server.
    app.run(debug=True, port=5000, threaded=True)
