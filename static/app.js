(function () {
  const D = window.__DEFAULTS__ || { benches: [], picks: [], target: {}, wins: [1, 2, 3, 5], years_back: 10 };

  let planSeq = 1;
  const state = {
    benches: D.benches.map(b => ({ ...b })),
    plans: [{
      id: planSeq++,
      name: "Plan 1",
      picks: D.picks.map(p => ({ ...p })),
      target: { ...D.target },
      investment: 100000,
    }],
    activePlanId: 1,
  };

  function activePlan() {
    return state.plans.find(p => p.id === state.activePlanId) || state.plans[0];
  }

  function fmtRupee(v) {
    return "₹" + Math.round(v).toLocaleString("en-IN");
  }

  const benchesBody = document.querySelector("#benches-table tbody");
  const picksBody = document.querySelector("#picks-table tbody");
  const targetBody = document.querySelector("#target-table tbody");
  const plansStrip = document.getElementById("plans-strip");

  // ---------------- plans strip ----------------
  function renderPlansStrip() {
    plansStrip.innerHTML = "";
    state.plans.forEach(plan => {
      const tab = document.createElement("div");
      tab.className = "plan-tab" + (plan.id === state.activePlanId ? " active" : "");
      tab.innerHTML = `
        <input type="text" data-plan-name="${plan.id}" value="${plan.name}">
        ${state.plans.length > 1 ? `<button type="button" class="plan-del" data-plan-del="${plan.id}" title="Delete plan">&times;</button>` : ""}`;
      tab.addEventListener("click", (e) => {
        if (e.target.closest("[data-plan-del]") || e.target.closest("[data-plan-name]")) return;
        selectPlan(plan.id);
      });
      plansStrip.appendChild(tab);
    });
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn-plan-add";
    addBtn.textContent = "+ Add plan";
    addBtn.addEventListener("click", addPlan);
    plansStrip.appendChild(addBtn);

    document.querySelectorAll("[data-plan-name]").forEach(inp => {
      const id = Number(inp.dataset.planName);
      inp.addEventListener("click", (e) => {
        e.stopPropagation();
        // clicking the name of a plan that isn't active switches to it first;
        // clicking the already-active plan's name just places the caret to rename it.
        if (id !== state.activePlanId) selectPlan(id);
      });
      inp.addEventListener("input", (e) => {
        const plan = state.plans.find(p => p.id === Number(e.target.dataset.planName));
        if (plan) { plan.name = e.target.value; updatePlanLabels(); }
      });
    });
    document.querySelectorAll("[data-plan-del]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        deletePlan(Number(e.target.dataset.planDel));
      });
    });
    updatePlanLabels();
  }

  function updatePlanLabels() {
    const name = activePlan().name;
    document.getElementById("active-plan-label").textContent = name;
    document.getElementById("active-plan-label2").textContent = name;
  }

  function addPlan() {
    const src = activePlan();
    const plan = {
      id: planSeq++,
      name: `Plan ${state.plans.length + 1}`,
      picks: src.picks.map(p => ({ ...p })),
      target: { ...src.target },
      investment: src.investment,
    };
    state.plans.push(plan);
    selectPlan(plan.id);
  }

  function deletePlan(id) {
    if (state.plans.length <= 1) return;
    state.plans = state.plans.filter(p => p.id !== id);
    if (state.activePlanId === id) state.activePlanId = state.plans[0].id;
    renderPlansStrip();
    renderPicks();
  }

  function selectPlan(id) {
    state.activePlanId = id;
    renderPlansStrip();
    renderPicks();
  }

  // ---------------- benches / picks / target rows ----------------
  function rowTemplateBench(row, idx) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="number" data-f="code" value="${row.code ?? ""}"></td>
      <td><input type="text" data-f="label" value="${row.label ?? ""}"></td>
      <td><button type="button" class="row-find" data-list="benches" data-idx="${idx}">Search</button></td>
      <td><button type="button" class="row-del" data-list="benches" data-idx="${idx}">&times;</button></td>`;
    return tr;
  }

  function rowTemplatePick(row, idx) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="text" data-f="cls" value="${row.cls ?? ""}"></td>
      <td><input type="number" data-f="code" value="${row.code ?? ""}"></td>
      <td><input type="text" data-f="label" value="${row.label ?? ""}"></td>
      <td><input type="number" step="0.1" min="0" placeholder="1" data-f="weight" value="${row.weight ?? ""}"></td>
      <td data-eff style="color:var(--text-dim)">—</td>
      <td><button type="button" class="row-find" data-list="picks" data-idx="${idx}">Search</button></td>
      <td><button type="button" class="row-del" data-list="picks" data-idx="${idx}">&times;</button></td>`;
    return tr;
  }

  function renderBenches() {
    benchesBody.innerHTML = "";
    state.benches.forEach((row, idx) => benchesBody.appendChild(rowTemplateBench(row, idx)));
  }

  function renderPicks() {
    picksBody.innerHTML = "";
    const plan = activePlan();
    activePlan().picks.forEach((row, idx) => picksBody.appendChild(rowTemplatePick(row, idx)));
    document.getElementById("plan-investment").value = plan.investment ?? 100000;
    syncTargetClasses();
    updateEffectivePercents();
  }

  function syncTargetClasses() {
    const plan = activePlan();
    const classes = [...new Set(plan.picks.map(p => (p.cls || "").trim()).filter(Boolean))];
    const next = {};
    classes.forEach(c => { next[c] = plan.target[c] !== undefined ? plan.target[c] : 0; });
    plan.target = next;
    renderTarget();
  }

  function renderTarget() {
    const plan = activePlan();
    targetBody.innerHTML = "";
    const totalRow = document.createElement("tr");
    totalRow.className = "total-row";
    totalRow.innerHTML = `<td><strong>Total</strong></td><td id="target-total-value"></td>`;
    targetBody.appendChild(totalRow);
    Object.keys(plan.target).forEach(cls => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${cls}</td>
        <td><input type="number" step="0.1" min="0" max="100" data-cls="${cls}" value="${(plan.target[cls] * 100).toFixed(1)}"></td>`;
      targetBody.appendChild(tr);
    });
    if (Object.keys(plan.target).length === 0) {
      const empty = document.createElement("tr");
      empty.innerHTML = `<td colspan="2" style="color:var(--text-dim)">Add a pick with a class to define targets.</td>`;
      targetBody.appendChild(empty);
    }
    updateTargetTotal();
  }

  function updateTargetTotal() {
    const plan = activePlan();
    const total = Object.values(plan.target).reduce((a, b) => a + Number(b || 0), 0) * 100;
    const el = document.getElementById("target-total-value");
    if (!el) return;
    el.textContent = total.toFixed(1) + "%";
    el.style.color = Math.abs(total - 100) < 0.05 ? "var(--pos)" : "var(--danger)";
  }

  // effective % of the WHOLE portfolio each pick ends up at, given its
  // class's target weight and how that class's weight is split among its picks.
  function effectivePercents(plan) {
    const classSum = {};
    plan.picks.forEach(p => {
      const cls = (p.cls || "").trim();
      if (!cls) return;
      const w = (p.weight === "" || p.weight == null || isNaN(Number(p.weight)) || Number(p.weight) <= 0) ? 1 : Number(p.weight);
      classSum[cls] = (classSum[cls] || 0) + w;
    });
    return plan.picks.map(p => {
      const cls = (p.cls || "").trim();
      if (!cls || !classSum[cls] || !plan.target[cls]) return null;
      const w = (p.weight === "" || p.weight == null || isNaN(Number(p.weight)) || Number(p.weight) <= 0) ? 1 : Number(p.weight);
      return plan.target[cls] * (w / classSum[cls]) * 100;
    });
  }

  function updateEffectivePercents() {
    const plan = activePlan();
    const investment = Number(plan.investment) || 0;
    const eff = effectivePercents(plan);
    document.querySelectorAll("#picks-table tbody tr").forEach((tr, idx) => {
      const cell = tr.querySelector("[data-eff]");
      if (!cell) return;
      if (eff[idx] == null) {
        cell.textContent = "—";
        cell.style.color = "var(--text-dim)";
      } else {
        cell.textContent = fmtRupee(eff[idx] / 100 * investment);
        cell.style.color = "var(--text)";
      }
    });
    const totalPct = eff.reduce((a, v) => a + (v || 0), 0);
    const el = document.getElementById("picks-total-value");
    if (el) {
      el.textContent = fmtRupee(totalPct / 100 * investment);
      el.style.color = Math.abs(totalPct - 100) < 0.05 ? "var(--pos)" : "var(--danger)";
    }
  }

  function listFor(tableId) {
    return tableId === "benches-table" ? state.benches : activePlan().picks;
  }

  document.addEventListener("input", (e) => {
    const f = e.target.dataset.f;
    if (f) {
      const tr = e.target.closest("tr");
      const table = e.target.closest("table");
      const idx = Array.from(table.tBodies[0].children).indexOf(tr);
      const list = listFor(table.id);
      let val = e.target.value;
      if (f === "code" || f === "weight") val = val ? Number(val) : "";
      list[idx][f] = val;
      if (table.id === "picks-table" && f === "cls") syncTargetClasses();
      if (table.id === "picks-table" && (f === "weight" || f === "cls")) updateEffectivePercents();
    }
    if (e.target.dataset.cls !== undefined) {
      activePlan().target[e.target.dataset.cls] = Number(e.target.value || 0) / 100;
      updateTargetTotal();
      updateEffectivePercents();
    }
    if (e.target.id === "plan-investment") {
      activePlan().investment = Number(e.target.value || 0);
      updateEffectivePercents();
    }
  });

  document.addEventListener("click", (e) => {
    if (e.target.dataset.add) {
      const list = e.target.dataset.add;
      if (list === "benches") { state.benches.push({ code: "", label: "" }); renderBenches(); }
      if (list === "picks") { activePlan().picks.push({ cls: "", code: "", label: "", weight: "" }); renderPicks(); }
    }
    if (e.target.classList.contains("row-del")) {
      const listName = e.target.dataset.list, idx = Number(e.target.dataset.idx);
      const list = listName === "benches" ? state.benches : activePlan().picks;
      list.splice(idx, 1);
      listName === "benches" ? renderBenches() : renderPicks();
    }
    if (e.target.classList.contains("row-find")) {
      openSearch(e.target.dataset.list, Number(e.target.dataset.idx));
    }
    if (e.target.classList.contains("top-tab")) {
      document.querySelectorAll(".top-tab").forEach(t => t.classList.remove("active"));
      e.target.classList.add("active");
      const view = e.target.dataset.view;
      document.getElementById("view-builder").classList.toggle("hidden", view !== "builder");
      document.getElementById("view-compare").classList.toggle("hidden", view !== "compare");
      document.getElementById("view-sip").classList.toggle("hidden", view !== "sip");
      if (view === "sip") refreshSipPlanSelect();
    }
  });

  // ---------------- search modal ----------------
  const modal = document.getElementById("search-modal");
  const searchInput = document.getElementById("search-input");
  const searchResults = document.getElementById("search-results");
  let searchTarget = null;
  let searchTimer = null;

  function openSearch(list, idx) {
    searchTarget = { list, idx };
    modal.classList.remove("hidden");
    searchInput.value = "";
    searchResults.innerHTML = "";
    searchInput.focus();
  }
  document.getElementById("search-close").addEventListener("click", () => modal.classList.add("hidden"));
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.add("hidden"); });

  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = searchInput.value.trim();
    if (!q) { searchResults.innerHTML = ""; return; }
    searchTimer = setTimeout(async () => {
      searchResults.innerHTML = `<div class="search-item">Searching…</div>`;
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await r.json();
        if (!Array.isArray(data) || data.length === 0) {
          searchResults.innerHTML = `<div class="search-item">No results</div>`;
          return;
        }
        searchResults.innerHTML = "";
        data.forEach(item => {
          const div = document.createElement("div");
          div.className = "search-item";
          div.innerHTML = `<span class="code">${item.schemeCode}</span>${item.schemeName}`;
          div.addEventListener("click", () => {
            const { list, idx } = searchTarget;
            const target = list === "benches" ? state.benches : activePlan().picks;
            target[idx].code = item.schemeCode;
            if (!target[idx].label) {
              target[idx].label = item.schemeName.split(" ").slice(0, 2).join(" ");
            }
            list === "benches" ? renderBenches() : renderPicks();
            modal.classList.add("hidden");
          });
          searchResults.appendChild(div);
        });
      } catch (err) {
        searchResults.innerHTML = `<div class="search-item">Search failed</div>`;
      }
    }, 350);
  });

  // ---------------- shared options ----------------
  function getWins() {
    return document.getElementById("wins").value.split(",").map(s => Number(s.trim())).filter(Boolean);
  }
  function getYearsBack() {
    return Number(document.getElementById("years-back").value || 10);
  }

  function buildPayload(plan) {
    return {
      benches: state.benches.filter(b => b.code && b.label),
      picks: plan.picks.filter(p => p.code && p.label && p.cls),
      target: plan.target,
      wins: getWins(),
      years_back: getYearsBack(),
    };
  }

  // ---------------- rendering matrices ----------------
  function fmtPct(v) {
    if (v === null || v === undefined) return `<td class="empty">—</td>`;
    const cls = v > 0 ? "pos" : (v < 0 ? "neg" : "");
    return `<td class="${cls}">${v.toFixed(2)}</td>`;
  }
  function fmtNum(v) {
    if (v === null || v === undefined) return `<td class="empty">—</td>`;
    return `<td>${v.toFixed(2)}</td>`;
  }

  function renderMatrix(container, title, tbl, fmt) {
    const wrap = document.createElement("div");
    wrap.className = "block";
    const head = `<tr><th>year</th>${tbl.columns.map(c => `<th>${c}</th>`).join("")}</tr>`;
    const rows = tbl.index.map((idx, r) => {
      const cells = tbl.data[r].map(v => fmt(v)).join("");
      return `<tr><td>${idx}</td>${cells}</tr>`;
    }).join("");
    wrap.innerHTML = `<h3>${title}</h3><div class="table-wrap"><table class="matrix"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
    container.appendChild(wrap);
  }

  function renderInfo(info) {
    const box = document.getElementById("info-box");
    const content = document.getElementById("info-content");
    box.classList.remove("hidden");
    content.innerHTML = info.map(f => `
      <div class="row">
        <span class="tag">${f.role}</span>
        <strong>${f.label}</strong>
        <span>${f.scheme_name}</span>
        <span>[${f.start} → ${f.end}]</span>
      </div>`).join("");
  }

  // ---------------- run single plan ----------------
  async function run() {
    const payload = buildPayload(activePlan());
    const status = document.getElementById("status");
    const errorBox = document.getElementById("error-box");
    const results = document.getElementById("results");
    errorBox.classList.add("hidden");
    results.innerHTML = "";
    status.textContent = "Fetching NAV history & computing…";
    document.getElementById("run-btn").disabled = true;
    try {
      const r = await fetch("/api/compute", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Request failed");
      renderInfo(data.info);
      Object.entries(data.blocks).forEach(([title, tbl]) => {
        const fmt = title.includes("VOLATILITY") || title.includes("CAGR") ? fmtPct : fmtNum;
        renderMatrix(results, title, tbl, fmt);
      });
      renderMatrix(results, "CORRELATION — full period", data.corr_full, fmtNum);
      renderMatrix(results, "CORRELATION — last 3 years", data.corr_last3, fmtNum);
      status.textContent = "Done.";
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.classList.remove("hidden");
      status.textContent = "";
    } finally {
      document.getElementById("run-btn").disabled = false;
    }
  }

  async function downloadFile(url, payload, filename, statusEl, errorEl, btn) {
    errorEl.classList.add("hidden");
    btn.disabled = true;
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const data = await r.json();
        throw new Error(data.error || "Export failed");
      }
      const blob = await r.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(objUrl);
      statusEl.textContent = "Downloaded.";
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove("hidden");
      statusEl.textContent = "";
    } finally {
      btn.disabled = false;
    }
  }

  async function exportXlsx() {
    const payload = buildPayload(activePlan());
    const btn = document.getElementById("export-btn");
    const filename = `${activePlan().name.replace(/\s+/g, "_")}_matrix.xlsx`;
    document.getElementById("status").textContent = "Building Excel file…";
    await downloadFile("/api/export", payload, filename,
      document.getElementById("status"), document.getElementById("error-box"), btn);
  }

  async function exportCompareXlsx() {
    const payload = {
      benches: state.benches.filter(b => b.code && b.label),
      plans: state.plans.map(p => ({
        name: p.name,
        picks: p.picks.filter(pk => pk.code && pk.label && pk.cls),
        target: p.target,
      })),
      wins: getWins(),
      years_back: getYearsBack(),
    };
    const btn = document.getElementById("compare-export-btn");
    document.getElementById("compare-status").textContent = "Building Excel file…";
    await downloadFile("/api/compare_export", payload, "mf_plans_compare.xlsx",
      document.getElementById("compare-status"), document.getElementById("compare-error"), btn);
  }

  document.getElementById("run-btn").addEventListener("click", run);
  document.getElementById("export-btn").addEventListener("click", exportXlsx);
  document.getElementById("compare-export-btn").addEventListener("click", exportCompareXlsx);
  document.getElementById("wins").value = (D.wins || [1, 2, 3, 5]).join(",");
  document.getElementById("years-back").value = D.years_back || 10;

  // ---------------- compare plans ----------------
  const PALETTE = ["#5b8cff", "#35c98f", "#ffb84d", "#ff6b6b", "#c792ea", "#4dd0e1", "#a3e635", "#f472b6"];
  const charts = [];

  function destroyCharts() {
    charts.forEach(c => c.destroy());
    charts.length = 0;
  }

  function renderLineChart(container, title, tbl, chartsArray = charts, yFormatter = null) {
    const wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    const canvas = document.createElement("canvas");
    wrap.appendChild(canvas);
    container.appendChild(wrap);
    const datasets = tbl.columns.map((col, i) => ({
      label: col,
      data: tbl.data.map(row => row[i]),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: PALETTE[i % PALETTE.length],
      spanGaps: true,
      tension: 0.25,
    }));
    const chart = new Chart(canvas, {
      type: "line",
      data: { labels: tbl.index, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: title, color: "#e7ebf5" },
          legend: { labels: { color: "#e7ebf5" } },
          tooltip: yFormatter ? { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${yFormatter(ctx.parsed.y)}` } } : {},
        },
        scales: {
          x: { ticks: { color: "#9aa6c4" }, grid: { color: "#2a3550" } },
          y: { ticks: { color: "#9aa6c4", callback: yFormatter ? (v) => yFormatter(v) : undefined }, grid: { color: "#2a3550" } },
        },
      },
    });
    chartsArray.push(chart);
  }

  function mergeColumn(results, blockTitle, planColumn, benchCols) {
    // results: [{plan, data}] ; builds a merged {index, columns, data} picking `planColumn`
    // from each plan's block, plus benchCols taken from the first successful result.
    const years = new Set();
    results.forEach(r => r.data.blocks[blockTitle]?.index.forEach(y => years.add(y)));
    const index = [...years].sort();
    const columns = [...results.map(r => r.plan.name), ...benchCols];
    const data = index.map(year => {
      const row = [];
      results.forEach(r => {
        const tbl = r.data.blocks[blockTitle];
        const yi = tbl ? tbl.index.indexOf(year) : -1;
        const ci = tbl ? tbl.columns.indexOf(planColumn) : -1;
        row.push(yi >= 0 && ci >= 0 ? tbl.data[yi][ci] : null);
      });
      const first = results.find(r => r.data.blocks[blockTitle]);
      benchCols.forEach(b => {
        const tbl = first?.data.blocks[blockTitle];
        const yi = tbl ? tbl.index.indexOf(year) : -1;
        const ci = tbl ? tbl.columns.indexOf(b) : -1;
        row.push(yi >= 0 && ci >= 0 ? tbl.data[yi][ci] : null);
      });
      return row;
    });
    return { index, columns, data };
  }

  async function runCompare() {
    const status = document.getElementById("compare-status");
    const errorBox = document.getElementById("compare-error");
    const container = document.getElementById("compare-results");
    errorBox.classList.add("hidden");
    container.innerHTML = "";
    destroyCharts();
    status.textContent = `Running ${state.plans.length} plan(s)…`;
    document.getElementById("compare-btn").disabled = true;
    try {
      const settled = await Promise.all(state.plans.map(async (plan) => {
        const payload = buildPayload(plan);
        const r = await fetch("/api/compute", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(`${plan.name}: ${data.error || "request failed"}`);
        return { plan, data };
      }));

      const benchLabels = state.benches.filter(b => b.code && b.label).map(b => b.label);
      const wins = getWins();

      wins.forEach(w => {
        const title = `${w} YR CAGR %`;
        const merged = mergeColumn(settled, title, "PORT_BH", benchLabels);
        const block = document.createElement("div");
        block.className = "compare-block";
        container.appendChild(block);
        renderLineChart(block, `${title} — PORT_BH (buy & hold)`, merged);
        renderMatrix(block, `${title} — PORT_BH (buy & hold) per plan vs benchmarks`, merged, fmtPct);
      });

      const volTitle = "CALENDAR-YEAR VOLATILITY %";
      const mergedVol = mergeColumn(settled, volTitle, "PORTFOLIO", benchLabels);
      const volBlock = document.createElement("div");
      volBlock.className = "compare-block";
      container.appendChild(volBlock);
      renderLineChart(volBlock, volTitle, mergedVol);
      renderMatrix(volBlock, `${volTitle} per plan vs benchmarks`, mergedVol, fmtPct);

      status.textContent = "Done.";
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.classList.remove("hidden");
      status.textContent = "";
    } finally {
      document.getElementById("compare-btn").disabled = false;
    }
  }

  document.getElementById("compare-btn").addEventListener("click", runCompare);

  // ---------------- SIP simulator ----------------
  const sipCharts = [];
  function destroySipCharts() {
    sipCharts.forEach(c => c.destroy());
    sipCharts.length = 0;
  }

  function refreshSipPlanSelect() {
    const sel = document.getElementById("sip-plan-select");
    const prev = sel.value;
    sel.innerHTML = state.plans.map(p => `<option value="${p.id}">${p.name}</option>`).join("");
    const stillExists = state.plans.some(p => String(p.id) === prev);
    sel.value = stillExists ? prev : String(state.activePlanId);
  }

  function mergeSipSeries(items) {
    // items: [{name, series: {dates, values}}]
    const dateSet = new Set();
    const maps = items.map(it => {
      const m = new Map();
      it.series.dates.forEach((d, i) => { m.set(d, it.series.values[i]); dateSet.add(d); });
      return m;
    });
    const index = [...dateSet].sort();
    const columns = items.map(it => it.name);
    const data = index.map(date => maps.map(m => (m.has(date) ? m.get(date) : null)));
    return { index, columns, data };
  }

  function renderSipSummary(container, items) {
    const rows = items.map(it => {
      const gain = it.current_value - it.invested;
      const gainPct = it.invested > 0 ? (gain / it.invested) * 100 : 0;
      const cls = gain > 0 ? "pos" : (gain < 0 ? "neg" : "");
      return `<tr>
        <td>${it.name}</td>
        <td>${fmtRupee(it.invested)}</td>
        <td>${fmtRupee(it.current_value)}</td>
        <td class="${cls}">${fmtRupee(gain)}</td>
        <td class="${cls}">${gainPct.toFixed(1)}%</td>
      </tr>`;
    }).join("");
    const wrap = document.createElement("div");
    wrap.className = "block";
    wrap.innerHTML = `<h3>SIP summary — all plans vs benchmarks</h3>
      <div class="table-wrap"><table class="matrix">
        <thead><tr><th>Name</th><th>Invested</th><th>Current value</th><th>Gain</th><th>Gain %</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
    container.appendChild(wrap);
  }

  async function runSip() {
    const status = document.getElementById("sip-status");
    const errorBox = document.getElementById("sip-error");
    const headline = document.getElementById("sip-headline");
    const results = document.getElementById("sip-results");
    errorBox.classList.add("hidden");
    headline.classList.add("hidden");
    results.innerHTML = "";
    destroySipCharts();

    const monthlySip = Number(document.getElementById("sip-amount").value || 0);
    const stepupPct = Number(document.getElementById("sip-stepup").value || 0);
    const startDate = document.getElementById("sip-start").value;
    const chosenPlanId = Number(document.getElementById("sip-plan-select").value);

    if (!startDate) { errorBox.textContent = "Pick a start date."; errorBox.classList.remove("hidden"); return; }

    const payload = {
      benches: state.benches.filter(b => b.code && b.label),
      plans: state.plans.map(p => ({
        name: p.name,
        picks: p.picks.filter(pk => pk.code && pk.label && pk.cls),
        target: p.target,
      })),
      monthly_sip: monthlySip,
      stepup_pct: stepupPct,
      start_date: startDate,
    };

    status.textContent = "Simulating…";
    document.getElementById("sip-btn").disabled = true;
    try {
      const r = await fetch("/api/sip", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Request failed");

      const chosenPlan = state.plans.find(p => p.id === chosenPlanId);
      const chosenResult = data.plans.find(p => p.name === (chosenPlan?.name));
      if (chosenResult) {
        const gain = chosenResult.current_value - chosenResult.invested;
        const gainPct = chosenResult.invested > 0 ? (gain / chosenResult.invested) * 100 : 0;
        const cls = gain > 0 ? "pos" : (gain < 0 ? "neg" : "");
        headline.classList.remove("hidden");
        headline.innerHTML = `
          <div class="card sip-headline-card">
            <h2>${chosenResult.name} — as of ${data.asof}</h2>
            <div class="sip-headline-grid">
              <div><span class="sip-stat-label">Invested</span><span class="sip-stat-value">${fmtRupee(chosenResult.invested)}</span></div>
              <div><span class="sip-stat-label">Current value</span><span class="sip-stat-value">${fmtRupee(chosenResult.current_value)}</span></div>
              <div><span class="sip-stat-label">Gain</span><span class="sip-stat-value ${cls}">${fmtRupee(gain)}</span></div>
              <div><span class="sip-stat-label">Gain %</span><span class="sip-stat-value ${cls}">${gainPct.toFixed(1)}%</span></div>
            </div>
          </div>`;
      }

      const allItems = [...data.plans, ...data.benches.map(b => ({ ...b, name: b.label }))];
      renderSipSummary(results, allItems);
      const merged = mergeSipSeries(allItems);
      const chartBlock = document.createElement("div");
      chartBlock.className = "block";
      results.appendChild(chartBlock);
      renderLineChart(chartBlock, "Portfolio value over time — all plans vs benchmarks", merged, sipCharts, fmtRupee);

      status.textContent = "Done.";
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.classList.remove("hidden");
      status.textContent = "";
    } finally {
      document.getElementById("sip-btn").disabled = false;
    }
  }

  document.getElementById("sip-btn").addEventListener("click", runSip);
  (function defaultSipStart() {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 3);
    document.getElementById("sip-start").value = d.toISOString().slice(0, 10);
  })();

  renderBenches();
  renderPlansStrip();
  renderPicks();
})();
