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
  constants). Also has `compute_compare()`, which runs `compute()` once per
  plan and merges each plan's buy-&-hold CAGR/volatility column into one
  table per window, and an in-process NAV cache so the same fund reused
  across plans/benchmarks isn't refetched from `mfapi.in` every time.
- `app.py` — Flask app: serves the frontend and exposes
  `POST /api/compute` (one plan's matrices as JSON),
  `POST /api/export` (one plan's `.xlsx`, same layout as the notebook's
  `mf_matrix.xlsx`), `POST /api/compare_export` (merged CAGR/volatility
  `.xlsx` across all plans), plus `GET /api/search?q=` for fund-name lookup
  (proxies `api.mfapi.in`, used by the "Search" button next to each row).
- `templates/index.html` + `static/app.js` + `static/style.css` — the
  frontend, with two tabs:
  - **Builder** — named Plans (each with its own Picks + Target
    allocation; per-pick "weight" optionally tilts the split within a
    class, defaults to equal). Benchmarks and Options (years back, CAGR
    windows) are shared across all plans.
  - **Compare plans** — runs every plan against the shared benchmarks and
    renders a merged table + Chart.js line chart per CAGR window and for
    volatility, plus an "all plans" Excel export.

## Why a local app instead of a hosted page

`api.mfapi.in` (the NAV data source) doesn't send CORS headers, so a
browser-only page can't call it directly, and it can't be published as a
Claude Artifact either — Artifacts run under a strict content policy that
only allows two specific capabilities (file downloads and connected-app
calls), not arbitrary outbound API calls. A tiny backend that can reach the
internet is required; this app is that backend plus its frontend, run with
one command.
