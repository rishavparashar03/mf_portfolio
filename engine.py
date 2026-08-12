"""
Core computation engine — a direct, faithful port of the notebook's
MF PORTFOLIO MATRIX logic (cell-2 / cell-3), parameterized so a web
request can supply BENCHES / TARGET / PICKS instead of hardcoding them.
"""
import threading
import time

import requests
import numpy as np
import pandas as pd

API = "https://api.mfapi.in/mf/{}"
SEARCH = "https://api.mfapi.in/mf/search?q={}"
TD = 252
AVOID = ("idcw", "dividend", "payout", "bonus", "regular", "half yearly", "quarterly")

# NAV history only updates once a day, so cache aggressively in-process. This
# also means the same fund used in several plans (Compare) is only fetched
# once per TTL window instead of once per plan.
_CACHE_TTL = 15 * 60
_nav_cache = {}
_cache_lock = threading.Lock()


class EngineError(Exception):
    pass


def search_scheme(q, n=15):
    r = requests.get(SEARCH.format(q), timeout=30).json()
    out = []
    for x in r[:n]:
        out.append({"schemeCode": x.get("schemeCode"), "schemeName": x.get("schemeName")})
    return out


def _fetch_nav_uncached(code):
    last_err = None
    for attempt in range(2):  # one retry — mfapi.in occasionally times out under load
        try:
            j = requests.get(API.format(int(code)), timeout=45).json()
            break
        except Exception as e:
            last_err = e
            j = None
    if j is None:
        raise EngineError(f"code {code}: request failed ({last_err})")
    if not isinstance(j, dict) or "data" not in j or not j["data"]:
        raise EngineError(f"code {code}: no data returned by mfapi.in (check the scheme code)")
    d = pd.DataFrame(j["data"])
    d["date"] = pd.to_datetime(d["date"], format="%d-%m-%Y")
    d["nav"] = pd.to_numeric(d["nav"], errors="coerce")
    s = d.dropna().sort_values("date").set_index("date")["nav"]
    s = s[s > 0]
    s = s[~s.index.duplicated(keep="last")]
    meta = j.get("meta", {}) or {}
    s.name = meta.get("scheme_name", str(code))
    if s.empty:
        raise EngineError(f"code {code}: NAV series is empty after cleaning")
    return s, meta


def fetch_nav(code):
    code = int(code)
    now = time.time()
    with _cache_lock:
        cached = _nav_cache.get(code)
    if cached and now - cached[0] < _CACHE_TTL:
        s, meta = cached[1], cached[2]
        return s.copy(), meta
    s, meta = _fetch_nav_uncached(code)
    with _cache_lock:
        _nav_cache[code] = (now, s, meta)
    return s.copy(), meta


def compute(benches, target, picks, wins, years_back):
    """
    benches: [{code, label}]
    target : {class_name: weight}
    picks  : [{cls, code, label}]
    wins   : [1,2,3,5,...] CAGR windows in years
    years_back: how many calendar years to show
    returns dict with 'info', 'blocks', 'corr'
    """
    if not picks:
        raise EngineError("Add at least one pick (fund).")
    if not target:
        raise EngineError("Target allocation is empty.")

    navs, info = {}, []
    for p in picks:
        s, meta = fetch_nav(p["code"])
        navs[p["label"]] = s
        info.append({
            "role": "pick", "cls": p["cls"], "code": p["code"], "label": p["label"],
            "scheme_name": meta.get("scheme_name", s.name),
            "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        })

    CLS = {p["label"]: p["cls"] for p in picks}
    # optional per-pick weight (relative share *within* its class). Default 1.0 for
    # everyone -> equal split, same as before. Set a custom number on one/more picks
    # (in the Picks table) to tilt the split within that class; unedited picks stay equal.
    WEIGHT = {}
    for p in picks:
        try:
            w = float(p.get("weight")) if p.get("weight") not in (None, "") else 1.0
        except (TypeError, ValueError):
            w = 1.0
        WEIGHT[p["label"]] = w if w > 0 else 1.0
    missing = sorted(set(CLS.values()) - set(target.keys()))
    if missing:
        raise EngineError(f"No target weight given for class(es): {', '.join(missing)}")

    LAST = max(s.index[-1] for s in navs.values())
    ASOF = [min(pd.Timestamp(y, 12, 31), LAST)
            for y in range(LAST.year - years_back + 1, LAST.year + 1)]
    DAILY = {k: s.resample("D").last().ffill() for k, s in navs.items()}

    BS, BL = {}, []
    for b in benches:
        s, meta = fetch_nav(b["code"])
        BS[b["label"]] = s
        DAILY[b["label"]] = s.resample("D").last().ffill()
        BL.append(b["label"])
        info.append({
            "role": "bench", "cls": None, "code": b["code"], "label": b["label"],
            "scheme_name": meta.get("scheme_name", s.name),
            "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        })

    def row_weights(avail):
        live = [k for k in avail.index if avail[k]]
        if not live:
            return pd.Series(0.0, index=avail.index)
        present = {CLS[k] for k in live}
        tot = sum(target[c] for c in present)
        w = {}
        for c in present:
            mem = [k for k in live if CLS[k] == c]
            mem_w = {k: WEIGHT.get(k, 1.0) for k in mem}
            mem_tot = sum(mem_w.values()) or 1.0
            for k in mem:
                w[k] = target[c] / tot * (mem_w[k] / mem_tot)
        return pd.Series(w).reindex(avail.index).fillna(0.0)

    def growth(k, d0, d1):
        c = DAILY[k]
        if d0 < c.index[0]:
            return np.nan
        a, b = c.asof(d0), c.asof(d1)
        return b / a if a == a and b == b and a > 0 else np.nan

    def port_cagr(d_end, years, rebalance):
        if rebalance:
            bounds = [d_end - pd.DateOffset(years=years - i) for i in range(years)] + [d_end]
        else:
            bounds = [d_end - pd.DateOffset(years=years), d_end]
        G = 1.0
        for p0, p1 in zip(bounds[:-1], bounds[1:]):
            g = pd.Series({k: growth(k, p0, p1) for k in navs})
            wv = row_weights(g.notna())
            if wv.sum() == 0:
                return np.nan
            G *= (g.fillna(0) * wv).sum()
        return G ** (1 / years) - 1

    def cagr_matrix(years):
        cols = list(navs) + BL
        out = {k: {d.year: (lambda g: g ** (1 / years) - 1 if g == g else np.nan)(
            growth(k, d - pd.DateOffset(years=years), d)) for d in ASOF} for k in cols}
        m = pd.DataFrame(out)[cols]
        m["PORT_BH"] = [port_cagr(d, years, False) for d in ASOF]
        m["PORT_REBAL"] = [port_cagr(d, years, True) for d in ASOF]
        for b in BL:
            m[f"EXC_{b}"] = m["PORT_BH"] - m[b]
        m.index.name = "year"
        return (m * 100).round(2)

    def vol_matrix():
        R = pd.DataFrame({k: np.log(s / s.shift(1)).dropna()
                           for k, s in list(navs.items()) + list(BS.items())})
        yrs = [d.year for d in ASOF]
        cols = list(navs) + BL
        m = pd.DataFrame({k: R[k].groupby(R.index.year).apply(
            lambda x: x.std() * np.sqrt(TD) if x.notna().sum() > 20 else np.nan) for k in cols}).reindex(yrs)[cols]
        Wm = m[list(navs)].notna().apply(row_weights, axis=1)
        port = {}
        for y in yrs:
            c = [x for x in Wm.columns if Wm.loc[y, x] > 0]
            sub = R.loc[R.index.year == y, c].dropna()
            port[y] = (sub * Wm.loc[y, c]).sum(axis=1).std() * np.sqrt(TD) if len(sub) > 20 else np.nan
        m = m.copy()
        m["PORTFOLIO"] = pd.Series(port)
        m.index.name = "year"
        return (m * 100).round(2)

    blocks = {f"{y} YR CAGR %": cagr_matrix(y) for y in wins}
    blocks["CALENDAR-YEAR VOLATILITY %"] = vol_matrix()

    # correlation
    Rfull = pd.DataFrame({k: np.log(s / s.shift(1)) for k, s in DAILY.items()}).dropna()
    corr_full = Rfull.corr().round(2)
    corr_last3 = Rfull[Rfull.index >= Rfull.index[-1] - pd.DateOffset(years=3)].corr().round(2)

    return {
        "info": info,
        "blocks": blocks,
        "corr_full": corr_full,
        "corr_last3": corr_last3,
    }


def df_to_json(df):
    return {
        "index": [str(i) for i in df.index],
        "columns": [str(c) for c in df.columns],
        "data": [[None if (isinstance(v, float) and (v != v)) else (v.item() if hasattr(v, "item") else v)
                   for v in row] for row in df.to_numpy().tolist()],
    }


def result_to_json(result):
    return {
        "info": result["info"],
        "blocks": {name: df_to_json(df) for name, df in result["blocks"].items()},
        "corr_full": df_to_json(result["corr_full"]),
        "corr_last3": df_to_json(result["corr_last3"]),
    }
