(function () {
  const D = window.__DEFAULTS__ || { benches: [], picks: [], target: {}, wins: [1, 2, 3, 5], years_back: 10 };

  const state = {
    benches: D.benches.map(b => ({ ...b })),
    picks: D.picks.map(p => ({ ...p })),
    target: { ...D.target },
  };

  const benchesBody = document.querySelector("#benches-table tbody");
  const picksBody = document.querySelector("#picks-table tbody");
  const targetBody = document.querySelector("#target-table tbody");

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
    state.picks.forEach((row, idx) => picksBody.appendChild(rowTemplatePick(row, idx)));
    syncTargetClasses();
  }

  function syncTargetClasses() {
    const classes = [...new Set(state.picks.map(p => (p.cls || "").trim()).filter(Boolean))];
    // drop targets for classes no longer present, keep existing weights for classes still present
    const next = {};
    classes.forEach(c => { next[c] = state.target[c] !== undefined ? state.target[c] : 0; });
    state.target = next;
    renderTarget();
  }

  function renderTarget() {
    targetBody.innerHTML = "";
    Object.keys(state.target).forEach(cls => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${cls}</td>
        <td><input type="number" step="0.1" min="0" max="100" data-cls="${cls}" value="${(state.target[cls] * 100).toFixed(1)}"></td>`;
      targetBody.appendChild(tr);
    });
    if (Object.keys(state.target).length === 0) {
      targetBody.innerHTML = `<tr><td colspan="2" style="color:var(--text-dim)">Add a pick with a class to define targets.</td></tr>`;
    }
  }

  document.addEventListener("input", (e) => {
    const f = e.target.dataset.f;
    if (f) {
      const tr = e.target.closest("tr");
      const table = e.target.closest("table");
      const idx = Array.from(table.tBodies[0].children).indexOf(tr);
      const list = table.id === "benches-table" ? "benches" : "picks";
      let val = e.target.value;
      if (f === "code") val = val ? Number(val) : "";
      state[list][idx][f] = val;
      if (list === "picks" && f === "cls") syncTargetClasses();
    }
    if (e.target.dataset.cls !== undefined) {
      state.target[e.target.dataset.cls] = Number(e.target.value || 0) / 100;
    }
  });

  document.addEventListener("click", (e) => {
    if (e.target.dataset.add) {
      const list = e.target.dataset.add;
      if (list === "benches") { state.benches.push({ code: "", label: "" }); renderBenches(); }
      if (list === "picks") { state.picks.push({ cls: "", code: "", label: "" }); renderPicks(); }
    }
    if (e.target.classList.contains("row-del")) {
      const list = e.target.dataset.list, idx = Number(e.target.dataset.idx);
      state[list].splice(idx, 1);
      list === "benches" ? renderBenches() : renderPicks();
    }
    if (e.target.classList.contains("row-find")) {
      openSearch(e.target.dataset.list, Number(e.target.dataset.idx));
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
            state[list][idx].code = item.schemeCode;
            if (!state[list][idx].label) {
              state[list][idx].label = item.schemeName.split(" ").slice(0, 2).join(" ");
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

  // ---------------- run / export ----------------
  function buildPayload() {
    const wins = document.getElementById("wins").value.split(",").map(s => Number(s.trim())).filter(Boolean);
    const years_back = Number(document.getElementById("years-back").value || 10);
    return {
      benches: state.benches.filter(b => b.code && b.label),
      picks: state.picks.filter(p => p.code && p.label && p.cls),
      target: state.target,
      wins,
      years_back,
    };
  }

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

  async function run() {
    const payload = buildPayload();
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

  async function exportXlsx() {
    const payload = buildPayload();
    const status = document.getElementById("status");
    const errorBox = document.getElementById("error-box");
    errorBox.classList.add("hidden");
    status.textContent = "Building Excel file…";
    document.getElementById("export-btn").disabled = true;
    try {
      const r = await fetch("/api/export", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const data = await r.json();
        throw new Error(data.error || "Export failed");
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "mf_matrix.xlsx";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      status.textContent = "Downloaded mf_matrix.xlsx";
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.classList.remove("hidden");
      status.textContent = "";
    } finally {
      document.getElementById("export-btn").disabled = false;
    }
  }

  document.getElementById("run-btn").addEventListener("click", run);
  document.getElementById("export-btn").addEventListener("click", exportXlsx);
  document.getElementById("wins").value = (D.wins || [1, 2, 3, 5]).join(",");
  document.getElementById("years-back").value = D.years_back || 10;

  renderBenches();
  renderPicks();
})();
