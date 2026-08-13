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
ALL_SCHEMES = "https://api.mfapi.in/mf"
TD = 252
AVOID = ("idcw", "dividend", "payout", "bonus", "regular", "half yearly", "quarterly")

# NAV history only updates once a day, so cache aggressively in-process. This
# also means the same fund used in several plans (Compare) is only fetched
# once per TTL window instead of once per plan.
_CACHE_TTL = 15 * 60
_nav_cache = {}
_cache_lock = threading.Lock()

# mfapi.in's own /search endpoint round-trips ~1-1.5s per call, which reads as
# "very slow" when it fires on every keystroke. Instead, pull the full list of
# ~30k schemes ONCE (a few MB, a few seconds) and search it in-memory after
# that -- effectively instant, and matches multi-word queries in any order
# ("hdfc gold" == "gold hdfc"), unlike a plain substring search.
_SCHEMES_TTL = 24 * 60 * 60
_schemes_cache = {"data": None, "ts": 0, "loading": False}
_schemes_lock = threading.Lock()


class EngineError(Exception):
    pass


def search_scheme(q, n=15):
    """Fallback: proxies mfapi.in's own (slower) search directly."""
    r = requests.get(SEARCH.format(q), timeout=30).json()
    out = []
    for x in r[:n]:
        out.append({"schemeCode": x.get("schemeCode"), "schemeName": x.get("schemeName")})
    return out


def _load_all_schemes():
    data = requests.get(ALL_SCHEMES, timeout=60).json()
    with _schemes_lock:
        _schemes_cache["data"] = data
        _schemes_cache["ts"] = time.time()
        _schemes_cache["loading"] = False


def prime_scheme_cache_async():
    """Kick off the one-time full-list fetch in the background (call at app startup)."""
    with _schemes_lock:
        if _schemes_cache["loading"] or _schemes_cache["data"] is not None:
            return
        _schemes_cache["loading"] = True
    threading.Thread(target=_load_all_schemes, daemon=True).start()


def search_scheme_fast(q, n=15):
    with _schemes_lock:
        data = _schemes_cache["data"]
        stale = data is None or (time.time() - _schemes_cache["ts"] > _SCHEMES_TTL)
        loading = _schemes_cache["loading"]
    if stale and not loading:
        prime_scheme_cache_async()
    if data is None:
        # cache not warm yet (e.g. right after startup) -- fall back once so
        # the user still gets results, cache will be instant next time.
        return search_scheme(q, n)

    tokens = [t for t in q.lower().split() if t]
    if not tokens:
        return []
    scored = []
    for x in data:
        name = x.get("schemeName") or ""
        name_lower = name.lower()
        if all(t in name_lower for t in tokens):
            first_pos = min(name_lower.find(t) for t in tokens)
            scored.append((first_pos, len(name), x))
    scored.sort(key=lambda r: (r[0], r[1]))
    return [{"schemeCode": x.get("schemeCode"), "schemeName": x.get("schemeName")} for _, _, x in scored[:n]]


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


def _class_weighting(picks, target):
    """
    Shared by compute() and compute_sip(): builds CLS (label -> class),
    WEIGHT (label -> optional relative weight within its class, default 1.0),
    and a row_weights(avail) closure that, given a boolean Series of which
    picks are currently available, returns each available pick's share of
    the *whole* portfolio -- its class's target weight, split among that
    class's currently-available picks in proportion to WEIGHT.
    """
    CLS = {p["label"]: p["cls"] for p in picks}
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

    return CLS, WEIGHT, row_weights


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

    CLS, WEIGHT, row_weights = _class_weighting(picks, target)

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


def compute_compare(benches, plans, wins, years_back):
    """
    Runs `compute()` once per plan (same benches/wins/years_back shared across
    all of them) and merges each plan's buy-&-hold portfolio column into one
    table per CAGR window + one volatility table, alongside the benchmarks.

    plans: [{"name": str, "picks": [...], "target": {...}}, ...]
    returns {"cagr": {years: DataFrame}, "vol": DataFrame}
    """
    if not plans:
        raise EngineError("Add at least one plan.")

    results = []
    for p in plans:
        name = p.get("name") or f"Plan {len(results) + 1}"
        r = compute(benches, p.get("target", {}), p.get("picks", []), wins, years_back)
        results.append((name, r))

    bench_labels = [b["label"] for b in benches]

    def merge_block(title, plan_col):
        series_list = []
        for name, r in results:
            df = r["blocks"].get(title)
            if df is not None and plan_col in df.columns:
                series_list.append(df[plan_col].rename(name))
        first_df = next((r["blocks"][title] for _, r in results if title in r["blocks"]), None)
        if first_df is not None:
            for b in bench_labels:
                if b in first_df.columns:
                    series_list.append(first_df[b].rename(b))
        if not series_list:
            raise EngineError(f"No data to merge for '{title}'")
        merged = pd.concat(series_list, axis=1).sort_index()
        merged.index.name = "year"
        return merged

    cagr = {y: merge_block(f"{y} YR CAGR %", "PORT_BH") for y in wins}
    vol = merge_block("CALENDAR-YEAR VOLATILITY %", "PORTFOLIO")
    return {"cagr": cagr, "vol": vol}


def _sip_dates(start, end):
    dates, i = [], 0
    while True:
        d = start + pd.DateOffset(months=i)
        if d > end:
            break
        dates.append(d)
        i += 1
    return dates


def _years_elapsed(d, start):
    """Whole years completed since `start`, as of date `d` -- used to apply the
    yearly step-up on each SIP anniversary rather than every calendar year."""
    years = d.year - start.year
    if (d.month, d.day) < (start.month, start.day):
        years -= 1
    return max(years, 0)


def _simulate_single_fund(nav_series, monthly_sip, stepup, start, asof):
    daily = nav_series.resample("D").last().ffill()
    if start < daily.index[0]:
        raise EngineError(
            f"Start date {start.date()} is before this fund's data begins ({daily.index[0].date()})."
        )
    dates = _sip_dates(start, min(asof, daily.index[-1]))
    units = 0.0
    invested = 0.0
    lots = []  # FIFO tax lots, just for the final "sold everything today" estimate below
    series_dates, series_values = [], []
    for d in dates:
        nav = daily.asof(d)
        if not (nav == nav) or nav <= 0:
            continue
        contribution = monthly_sip * ((1 + stepup) ** _years_elapsed(d, start))
        bought = contribution / nav
        units += bought
        lots.append({"date": d, "units": bought, "cost": nav})
        invested += contribution
        series_dates.append(str(d.date()))
        series_values.append(round(units * nav, 2))
    current_nav = daily.asof(asof)
    current_value = round(units * current_nav, 2) if current_nav == current_nav else 0.0

    # A benchmark here is always a single equity index fund, so treat it as
    # the "equity" class for tax purposes: 12-month LT threshold, and its own
    # independent Rs 1.25L/FY exemption (it's a separate hypothetical
    # portfolio from any plan, not sharing exemption room with one).
    liquidation_tax = 0.0
    if current_nav == current_nav:
        lt_gain = st_gain = 0.0
        for lot in lots:
            gain = lot["units"] * (current_nav - lot["cost"])
            if asof > lot["date"] + pd.DateOffset(months=EQUITY_LT_MONTHS):
                lt_gain += gain
            else:
                st_gain += gain
        lt_gain = max(lt_gain, 0.0)
        st_gain = max(st_gain, 0.0)
        taxable_lt = max(lt_gain - EQUITY_LTCG_EXEMPTION, 0.0)
        liquidation_tax = taxable_lt * LTCG_RATE + st_gain * STCG_RATE

    return {
        "invested": round(invested, 2),
        "current_value": current_value,
        "liquidation_tax": round(liquidation_tax, 2),
        "current_value_after_tax": round(current_value - liquidation_tax, 2),
        "series": {"dates": series_dates, "values": series_values},
    }


# Capital-gains assumptions applied when a rebalance sells existing units
# (unrealized/mark-to-market value is never taxed -- only an actual rebalance
# sale triggers this). Simplified per the user's own stated assumptions:
# same LTCG/STCG rates for every asset class, but a longer long-term holding
# threshold for anything that isn't equity (matching gold/debt/etc.).
LTCG_RATE = 0.125
STCG_RATE = 0.20
EQUITY_LT_MONTHS = 12
OTHER_LT_MONTHS = 24
# Sec 112A: the first Rs 1.25L of equity LTCG in a financial year is exempt.
# Only equity LTCG gets this -- not equity STCG, not any non-equity gain.
EQUITY_LTCG_EXEMPTION = 125000.0
_TOL = 0.01  # rupees; avoids churning on floating-point noise


def _is_equity_class(cls):
    return (cls or "").strip().lower() == "equity"


def _lt_months_for_class(cls):
    return EQUITY_LT_MONTHS if _is_equity_class(cls) else OTHER_LT_MONTHS


def _financial_year(d):
    """Indian FY: Apr 1 -> Mar 31, keyed by the year it starts in."""
    return d.year if d.month >= 4 else d.year - 1


def _apply_carryforward(pool, gain, current_fy):
    """Reduce `gain` using loss-carryforward `pool` entries, oldest first,
    dropping anything past its 8-assessment-year expiry first. Mutates
    `pool` in place (consumed/expired entries are removed); returns the
    remaining gain after whatever the pool could absorb."""
    pool[:] = [e for e in pool if current_fy <= e["fy"] + 8]
    for e in pool:
        if gain <= 1e-9:
            break
        take = min(e["amount"], gain)
        e["amount"] -= take
        gain -= take
    pool[:] = [e for e in pool if e["amount"] > 1e-9]
    return gain


def _simulate_portfolio(picks, target, monthly_sip, stepup, start, asof, rebalance_years=None, harvest_ltcg=False):
    if not picks:
        raise EngineError("A plan needs at least one pick.")
    navs = {}
    for p in picks:
        s, _ = fetch_nav(p["code"])
        navs[p["label"]] = s
    DAILY = {k: s.resample("D").last().ffill() for k, s in navs.items()}
    CLS, _, row_weights = _class_weighting(picks, target)

    earliest = min(s.index[0] for s in navs.values())
    if start < earliest:
        raise EngineError(
            f"Start date {start.date()} is before any of this plan's picks existed "
            f"(earliest: {earliest.date()})."
        )

    dates = _sip_dates(start, asof)
    units = {k: 0.0 for k in navs}
    lots = {k: [] for k in navs}  # FIFO tax lots: [{"date", "units", "cost"}]
    invested = 0.0
    rebalances = 0
    tax_paid = 0.0
    harvested_gain_total = 0.0
    fy_equity_ltcg_used = {}  # FY key -> equity LTCG already counted against the Rs 1.25L exemption
    st_loss_cf, lt_loss_cf = [], []  # loss carryforward pools: [{"fy": origin, "amount": rupees}]
    next_rebal = start + pd.DateOffset(years=rebalance_years) if rebalance_years else None
    next_harvest = start + pd.DateOffset(years=1) if harvest_ltcg else None  # harvesting is always yearly
    series_dates, series_values = [], []

    def sell_fifo(k, d, sell_units, nav):
        """Consume `sell_units` from k's oldest lots first; returns (lt_gain, st_gain)."""
        remaining = sell_units
        lt_gain = st_gain = 0.0
        kept = []
        threshold_months = _lt_months_for_class(CLS.get(k))
        for lot in lots[k]:
            if remaining <= 1e-9:
                kept.append(lot)
                continue
            take = min(lot["units"], remaining)
            gain = take * (nav - lot["cost"])
            if d > lot["date"] + pd.DateOffset(months=threshold_months):
                lt_gain += gain
            else:
                st_gain += gain
            remaining -= take
            if take < lot["units"] - 1e-9:
                kept.append({"date": lot["date"], "units": lot["units"] - take, "cost": lot["cost"]})
        lots[k] = kept
        return lt_gain, st_gain

    for d in dates:
        avail = pd.Series({k: (d >= DAILY[k].index[0]) for k in navs})
        wv = row_weights(avail)
        if wv.sum() <= 0:
            continue  # none of this plan's picks exist yet at this date -- skip the contribution
        contribution = monthly_sip * ((1 + stepup) ** _years_elapsed(d, start))
        invested += contribution
        value = 0.0
        for k in navs:
            nav = DAILY[k].asof(d)
            w = wv.get(k, 0.0)
            if w > 0 and nav == nav and nav > 0:
                bought = (contribution * w) / nav
                units[k] += bought
                lots[k].append({"date": d, "units": bought, "cost": nav})
            if nav == nav:
                value += units[k] * nav

        if next_rebal is not None and d >= next_rebal:
            navs_today = {k: DAILY[k].asof(d) for k in navs}
            target_val = {k: value * wv.get(k, 0.0) for k in navs}
            sell_amt = {}
            equity_lt_gain = other_lt_gain = equity_st_gain = other_st_gain = 0.0
            for k in navs:
                nav = navs_today[k]
                cur_val = units[k] * nav if nav == nav else 0.0
                over = cur_val - target_val[k]
                if over > _TOL and nav == nav and nav > 0:
                    sell_units = over / nav
                    lt_gain, st_gain = sell_fifo(k, d, sell_units, nav)
                    units[k] -= sell_units
                    if _is_equity_class(CLS.get(k)):
                        equity_lt_gain += lt_gain
                        equity_st_gain += st_gain
                    else:
                        other_lt_gain += lt_gain
                        other_st_gain += st_gain
                    sell_amt[k] = over

            # ---- intra-event loss offsetting (real ITR rules: a short-term
            # loss can offset short-term OR long-term gains of any asset
            # class; a long-term loss can only offset long-term gains, but
            # still of any class).
            if equity_lt_gain < 0 and other_lt_gain > 0:
                offset = min(-equity_lt_gain, other_lt_gain)
                other_lt_gain -= offset
                equity_lt_gain += offset
            elif other_lt_gain < 0 and equity_lt_gain > 0:
                offset = min(-other_lt_gain, equity_lt_gain)
                equity_lt_gain -= offset
                other_lt_gain += offset

            net_st_gain = equity_st_gain + other_st_gain
            new_st_loss = 0.0
            if net_st_gain < 0:
                st_loss = -net_st_gain
                net_st_gain = 0.0
                reduce = min(st_loss, max(other_lt_gain, 0.0))  # use up the non-exempt LT gain first
                other_lt_gain -= reduce
                st_loss -= reduce
                if st_loss > 0:
                    reduce2 = min(st_loss, max(equity_lt_gain, 0.0))
                    equity_lt_gain -= reduce2
                    st_loss -= reduce2
                new_st_loss = st_loss  # whatever's still unmatched becomes a new carryforward entry

            # any LT loss that intra-event netting couldn't absorb also
            # becomes a new carryforward entry (checked per class bucket,
            # since a bucket can still be negative here if losses exceeded
            # every available gain above).
            new_lt_loss = 0.0
            if equity_lt_gain < 0:
                new_lt_loss += -equity_lt_gain
                equity_lt_gain = 0.0
            if other_lt_gain < 0:
                new_lt_loss += -other_lt_gain
                other_lt_gain = 0.0

            fy = _financial_year(d)
            # ---- apply loss carried forward from EARLIER events/years (oldest
            # first, respecting the 8-assessment-year expiry) to whatever
            # gain is left after this event's own netting above.
            net_st_gain = _apply_carryforward(st_loss_cf, net_st_gain, fy)
            other_lt_gain = _apply_carryforward(st_loss_cf, other_lt_gain, fy)  # leftover ST c/f can hit LT too
            equity_lt_gain = _apply_carryforward(st_loss_cf, equity_lt_gain, fy)
            other_lt_gain = _apply_carryforward(lt_loss_cf, other_lt_gain, fy)
            equity_lt_gain = _apply_carryforward(lt_loss_cf, equity_lt_gain, fy)

            if new_st_loss > _TOL:
                st_loss_cf.append({"fy": fy, "amount": new_st_loss})
            if new_lt_loss > _TOL:
                lt_loss_cf.append({"fy": fy, "amount": new_lt_loss})

            used = fy_equity_ltcg_used.get(fy, 0.0)
            remaining_exemption = max(EQUITY_LTCG_EXEMPTION - used, 0.0)
            taxable_equity_lt = max(equity_lt_gain - remaining_exemption, 0.0)
            fy_equity_ltcg_used[fy] = used + equity_lt_gain
            event_tax = taxable_equity_lt * LTCG_RATE + other_lt_gain * LTCG_RATE + net_st_gain * STCG_RATE
            total_sell = sum(sell_amt.values())
            factor = (total_sell - event_tax) / total_sell if total_sell > 0 else 1.0
            for k in navs:
                nav = navs_today[k]
                cur_val = units[k] * nav if nav == nav else 0.0
                under = target_val[k] - cur_val
                if under > _TOL and nav == nav and nav > 0:
                    buy_units = (under * factor) / nav
                    units[k] += buy_units
                    lots[k].append({"date": d, "units": buy_units, "cost": nav})
            tax_paid += event_tax
            value -= event_tax  # tax leaves the portfolio
            rebalances += 1
            while next_rebal <= d:
                next_rebal += pd.DateOffset(years=rebalance_years)

        # ---- LTCG harvesting: sell (and immediately rebuy) just enough of
        # the equity long-term lots to use up whatever's left of THIS FY's
        # Rs 1.25L exemption -- zero tax, but it resets those units' cost
        # basis (and holding-period clock) to today. Doesn't touch units
        # held, doesn't touch weights, only equity is eligible (matches
        # Sec 112A), and it shares the same exemption bucket a real
        # rebalance sale would draw from.
        if next_harvest is not None and d >= next_harvest:
            fy = _financial_year(d)
            used = fy_equity_ltcg_used.get(fy, 0.0)
            room = max(EQUITY_LTCG_EXEMPTION - used, 0.0)
            harvested_this_event = 0.0
            if room > _TOL:
                for k in navs:
                    if not _is_equity_class(CLS.get(k)) or room - harvested_this_event <= _TOL:
                        continue
                    nav = DAILY[k].asof(d)
                    if not (nav == nav) or nav <= 0:
                        continue
                    new_lots = []
                    for lot in lots[k]:
                        remaining_room = room - harvested_this_event
                        is_lt = d > lot["date"] + pd.DateOffset(months=EQUITY_LT_MONTHS)
                        per_unit_gain = nav - lot["cost"]
                        if remaining_room <= _TOL or not is_lt or per_unit_gain <= 0:
                            new_lots.append(lot)
                            continue
                        lot_gain = lot["units"] * per_unit_gain
                        if lot_gain <= remaining_room + _TOL:
                            harvested_this_event += lot_gain
                            new_lots.append({"date": d, "units": lot["units"], "cost": nav})  # sold + rebought today
                        else:
                            harvest_units = remaining_room / per_unit_gain
                            harvested_this_event += harvest_units * per_unit_gain
                            new_lots.append({"date": d, "units": harvest_units, "cost": nav})
                            new_lots.append({"date": lot["date"], "units": lot["units"] - harvest_units, "cost": lot["cost"]})
                    lots[k] = new_lots
            if harvested_this_event > _TOL:
                fy_equity_ltcg_used[fy] = used + harvested_this_event
                harvested_gain_total += harvested_this_event
            while next_harvest <= d:
                next_harvest += pd.DateOffset(years=1)

        series_dates.append(str(d.date()))
        series_values.append(round(value, 2))

    current_value = 0.0
    for k in navs:
        nav = DAILY[k].asof(asof)
        if nav == nav:
            current_value += units[k] * nav

    # ---- final estimate: the tax due if EVERYTHING still held were sold
    # today, considering both short- and long-term lots, using whatever
    # exemption headroom and loss carryforward remain from the simulation
    # above. This is hypothetical -- it doesn't mutate any of that state,
    # since nothing actually happens after `asof`.
    equity_lt_gain = other_lt_gain = equity_st_gain = other_st_gain = 0.0
    for k in navs:
        nav = DAILY[k].asof(asof)
        if not (nav == nav) or not lots[k]:
            continue
        threshold_months = _lt_months_for_class(CLS.get(k))
        for lot in lots[k]:
            gain = lot["units"] * (nav - lot["cost"])
            is_lt = asof > lot["date"] + pd.DateOffset(months=threshold_months)
            if _is_equity_class(CLS.get(k)):
                equity_lt_gain += gain if is_lt else 0.0
                equity_st_gain += gain if not is_lt else 0.0
            else:
                other_lt_gain += gain if is_lt else 0.0
                other_st_gain += gain if not is_lt else 0.0

    if equity_lt_gain < 0 and other_lt_gain > 0:
        offset = min(-equity_lt_gain, other_lt_gain)
        other_lt_gain -= offset
        equity_lt_gain += offset
    elif other_lt_gain < 0 and equity_lt_gain > 0:
        offset = min(-other_lt_gain, equity_lt_gain)
        equity_lt_gain -= offset
        other_lt_gain += offset

    net_st_gain = equity_st_gain + other_st_gain
    if net_st_gain < 0:
        st_loss = -net_st_gain
        net_st_gain = 0.0
        reduce = min(st_loss, max(other_lt_gain, 0.0))
        other_lt_gain -= reduce
        st_loss -= reduce
        if st_loss > 0:
            reduce2 = min(st_loss, max(equity_lt_gain, 0.0))
            equity_lt_gain -= reduce2

    equity_lt_gain, other_lt_gain = max(equity_lt_gain, 0.0), max(other_lt_gain, 0.0)
    final_fy = _financial_year(asof)
    st_pool, lt_pool = [dict(e) for e in st_loss_cf], [dict(e) for e in lt_loss_cf]  # don't mutate the real pools
    net_st_gain = _apply_carryforward(st_pool, net_st_gain, final_fy)
    other_lt_gain = _apply_carryforward(st_pool, other_lt_gain, final_fy)
    equity_lt_gain = _apply_carryforward(st_pool, equity_lt_gain, final_fy)
    other_lt_gain = _apply_carryforward(lt_pool, other_lt_gain, final_fy)
    equity_lt_gain = _apply_carryforward(lt_pool, equity_lt_gain, final_fy)

    used = fy_equity_ltcg_used.get(final_fy, 0.0)
    remaining_exemption = max(EQUITY_LTCG_EXEMPTION - used, 0.0)
    taxable_equity_lt = max(equity_lt_gain - remaining_exemption, 0.0)
    liquidation_tax = taxable_equity_lt * LTCG_RATE + other_lt_gain * LTCG_RATE + net_st_gain * STCG_RATE

    return {
        "invested": round(invested, 2),
        "current_value": round(current_value, 2),
        "liquidation_tax": round(liquidation_tax, 2),
        "current_value_after_tax": round(current_value - liquidation_tax, 2),
        "rebalances": rebalances,
        "tax_paid": round(tax_paid, 2),
        "harvested_gain": round(harvested_gain_total, 2),
        "series": {"dates": series_dates, "values": series_values},
    }


def compute_sip(benches, plans, monthly_sip, stepup_pct, start_date, rebalance_years=None, harvest_ltcg=False, end_date=None):
    """
    Simulates a monthly SIP (with an optional yearly step-up) starting on
    `start_date`, for every plan (blended by its own target/weights, with
    unavailable-yet picks skipped and the rest re-weighted -- same logic as
    row_weights elsewhere) and every benchmark (100% into that one fund).

    rebalance_years: if set, each plan's portfolio is rebalanced back to its
    target weights every N years from `start_date` (sells only the overweight
    positions' excess at that month's contribution point, FIFO tax-lot by
    tax-lot, and rebuys the underweight ones with what's left after tax).
    None/0 means no rebalancing -- pure buy-and-hold that lets weights drift,
    same as before this option existed. Benchmarks are single-fund, so this
    is a no-op for them.

    Rebalance sales are taxed (12.5% long-term / 20% short-term on the GAIN
    portion only, per lot) using a long-term threshold of 12 months for an
    "equity" class and 24 months for everything else -- the tax leaves the
    portfolio and reduces what's reinvested, same as a real sale would.
    Unrealized (never-sold) gains are not taxed anywhere in this simulation.

    Real-rule refinements applied at each rebalance event, and again as one
    final hypothetical "sold everything today" estimate at `asof`:
    - The first Rs 1.25L of equity LTCG in a financial year (Apr-Mar) is
      exempt (Sec 112A) -- tracked per plan across all its rebalances (and
      the final estimate) in that FY, and only against equity-class LTCG
      (not equity STCG, not any non-equity gain, taxed from the first rupee).
    - A loss realized on one fund offsets a gain on another in the SAME
      event first: short-term losses offset short-term OR long-term gains
      of any class; long-term losses offset long-term gains of any class
      only. Whatever's left unabsorbed is carried forward (separately as a
      short-term pool and a long-term pool) to reduce gains at later
      rebalances/the final estimate, up to the real 8-assessment-year
      expiry -- it is NOT lost immediately as in an earlier version of this.
    - Each plan result includes "tax_paid" (tax actually deducted from the
      portfolio at each rebalance so far) plus "liquidation_tax" and
      "current_value_after_tax" -- the tax due, and the value left, if
      everything still held were sold today. Benchmarks get the latter two
      as well (treated as a single equity-class holding with its own,
      independent Rs 1.25L/FY exemption), but never "tax_paid"/"rebalances"
      since nothing is ever sold along the way for a single-fund benchmark.

    harvest_ltcg: if True, once a year (always yearly, independent of
    rebalance_years) each plan sells and immediately rebuys just enough of
    its equity long-term lots to use up whatever's left of that FY's
    Rs 1.25L exemption -- zero tax due (it's exactly inside the exemption),
    but it resets those units' cost basis AND holding-period clock to that
    date. Units held and weights are unchanged; this only matters for the
    later "sold everything" tax math. Shares the same per-FY exemption
    bucket a real rebalance sale draws from. Reported as "harvested_gain"
    (cumulative, tax-free) on each plan result; benchmarks and non-equity
    classes are untouched by this (no such exemption exists for them).

    end_date: optional -- if given, the simulation stops there instead of at
    the latest available NAV date (i.e. "what if I invested from X to Y"
    instead of "...to today"). Clamped down to whatever data is actually
    available if it's later than that; must not be before `start_date`.

    plans: [{"name": str, "picks": [...], "target": {...}}, ...]
    benches: [{"code", "label"}]
    returns {"asof": "YYYY-MM-DD", "plans": [...], "benches": [...]}
    """
    if monthly_sip is None or monthly_sip <= 0:
        raise EngineError("Monthly SIP amount must be a positive number.")
    if not plans:
        raise EngineError("Add at least one plan.")
    try:
        start = pd.Timestamp(start_date)
    except Exception:
        raise EngineError(f"Invalid start date: {start_date!r}")
    if rebalance_years is not None and rebalance_years <= 0:
        rebalance_years = None

    stepup = (stepup_pct or 0) / 100.0

    codes = {int(pk["code"]) for p in plans for pk in p.get("picks", [])}
    codes |= {int(b["code"]) for b in benches}
    if not codes:
        raise EngineError("No funds to simulate.")
    last_dates = []
    for code in codes:
        s, _ = fetch_nav(code)
        last_dates.append(s.index[-1])
    asof = min(last_dates)
    if end_date:
        try:
            end_ts = pd.Timestamp(end_date)
        except Exception:
            raise EngineError(f"Invalid end date: {end_date!r}")
        asof = min(asof, end_ts)
    if start > asof:
        raise EngineError(f"Start date {start.date()} is after the end date / latest available NAV date ({asof.date()}).")

    plan_results = []
    for i, p in enumerate(plans):
        name = p.get("name") or f"Plan {i + 1}"
        r = _simulate_portfolio(p.get("picks", []), p.get("target", {}), monthly_sip, stepup, start, asof, rebalance_years, harvest_ltcg)
        r["name"] = name
        plan_results.append(r)

    bench_results = []
    for b in benches:
        s, _ = fetch_nav(b["code"])
        r = _simulate_single_fund(s, monthly_sip, stepup, start, asof)
        r["label"] = b["label"]
        bench_results.append(r)

    return {"asof": str(asof.date()), "plans": plan_results, "benches": bench_results}


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
