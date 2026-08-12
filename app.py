import io
import traceback

from flask import Flask, request, jsonify, send_file, render_template
import pandas as pd

from engine import compute, result_to_json, search_scheme, EngineError

app = Flask(__name__)

DEFAULTS = {
    "benches": [
        {"code": 120716, "label": "NIFTY50"},
        {"code": 147625, "label": "NIFTY500"},
    ],
    "target": {"gold": 0.30, "equity": 0.70},
    "picks": [
        {"cls": "gold", "code": 119132, "label": "Gold", "weight": 1},
        {"cls": "equity", "code": 149383, "label": "Axis", "weight": 1},
        {"cls": "equity", "code": 147704, "label": "Motilal", "weight": 1},
        {"cls": "equity", "code": 120357, "label": "Invesco", "weight": 1},
        {"cls": "equity", "code": 120596, "label": "ICICI", "weight": 1},
        {"cls": "equity", "code": 148404, "label": "BOI", "weight": 1},
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
        return jsonify(search_scheme(q))
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

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        row = 0
        for tag, d in blocks.items():
            pd.DataFrame([[tag]]).to_excel(xl, sheet_name="matrix", startrow=row, index=False, header=False)
            d.to_excel(xl, sheet_name="matrix", startrow=row + 1)
            row += len(d) + 4
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="mf_matrix.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    # threaded=True lets several plans' /api/compute calls (Compare tab) run
    # concurrently instead of queueing one after another on the dev server.
    app.run(debug=True, port=5000, threaded=True)
