# MF Portfolio Matrix — website

A small local web app that reproduces the notebook's output (CAGR matrices,
calendar-year volatility, correlations) for any set of benchmarks, picks and
target allocation you enter in the browser.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## How it's built

- `engine.py` — the computation engine, a direct port of the notebook's
  `cagr_matrix` / `vol_matrix` / correlation logic, parameterized by
  whatever benchmarks/picks/target you pass in (instead of hardcoded
  constants).
- `app.py` — Flask app: serves the frontend and exposes
  `POST /api/compute` (returns the matrices as JSON) and
  `POST /api/export` (returns an `.xlsx` file, same layout as the notebook's
  `mf_matrix.xlsx`), plus `GET /api/search?q=` for fund-name lookup
  (proxies `api.mfapi.in`, used by the "Search" button next to each row).
- `templates/index.html` + `static/app.js` + `static/style.css` — the
  frontend: editable tables for benchmarks/picks/target, a run button, and
  rendered result tables.

## Why a local app instead of a hosted page

`api.mfapi.in` (the NAV data source) doesn't send CORS headers, so a
browser-only page can't call it directly, and it can't be published as a
Claude Artifact either — Artifacts run under a strict content policy that
only allows two specific capabilities (file downloads and connected-app
calls), not arbitrary outbound API calls. A tiny backend that can reach the
internet is required; this app is that backend plus its frontend, run with
one command.
