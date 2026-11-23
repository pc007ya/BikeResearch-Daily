// Daily Multi-Region Cycling SEO Keyword Trends Dashboard (7-day & 30-day Analysis)
// Loads docs/data/seo_trends.json and renders interactive region/category slicers,
// 7d vs 30d comparison bars, Country × Category heatmap matrix, sortable 7d/30d table
// with 30-day inline SVG sparklines, live Google Suggest hot keywords, and CSV export.

let seoData = null;
let initialized = false;
let mountEl = null;

const state = {
  region: "all",       // "all" | "europe" | "americas" | "apac"
  countryIso: null,    // null or iso2 e.g. "DE"
  category: "all",     // "all" | category_id
  search: "",
  tableMode: "detail", // "detail" (country x category) | "summary" (category aggregate)
  sortBy: "score_7d",  // "score_7d" | "score_30d" | "wow_pct" | "momentum_7v30_pct" | "wiki_7d"
  sortDir: "desc",
};

const REGION_META = {
  all: { name_zh: "全球 9 大市場", short_zh: "全球" },
  europe: { name_zh: "歐洲（德・英・法・荷）", short_zh: "歐洲" },
  americas: { name_zh: "美洲（美・加）", short_zh: "美洲" },
  apac: { name_zh: "亞太（台・日・澳）", short_zh: "亞太" },
};

function esc(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtSignedPct(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function fmtCompactNum(n) {
  if (!n) return "0";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}萬`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function deltaBadgeHtml(v, emphasize = false) {
  if (v == null || Number.isNaN(v)) return `<span class="seo-delta neutral">—</span>`;
  if (v >= 8) {
    return `<span class="seo-delta hot">${emphasize ? "🔥 " : "▲ "}${fmtSignedPct(v)}</span>`;
  }
  if (v > 1) {
    return `<span class="seo-delta pos">▲ ${fmtSignedPct(v)}</span>`;
  }
  if (v <= -8) {
    return `<span class="seo-delta neg">▼ ${fmtSignedPct(v)}</span>`;
  }
  if (v < -1) {
    return `<span class="seo-delta cool">▼ ${fmtSignedPct(v)}</span>`;
  }
  return `<span class="seo-delta neutral">${fmtSignedPct(v)}</span>`;
}

function sparklineSvg(daily30d, accentColor = "#c84b28") {
  const arr = Array.isArray(daily30d) && daily30d.length ? daily30d : Array(30).fill(0);
  const W = 112;
  const H = 28;
  const pad = 2;
  const maxV = Math.max(...arr, 1);
  const minV = Math.min(...arr, 0);
  const span = Math.max(maxV - minV, 1);

  const pt = (i, v) => {
    const x = pad + (i / Math.max(arr.length - 1, 1)) * (W - pad * 2);
    const y = H - pad - ((v - minV) / span) * (H - pad * 2);
    return [x, y];
  };

  // Split into days 0..23 (30d baseline) and days 23..29 (last 7 days highlighted!)
  const splitIdx = Math.max(0, arr.length - 7);
  const basePts = arr
    .slice(0, splitIdx + 1)
    .map((v, i) => pt(i, v).map((n) => n.toFixed(1)).join(","))
    .join(" ");
  const recentPts = arr
    .slice(splitIdx)
    .map((v, idx) => pt(splitIdx + idx, v).map((n) => n.toFixed(1)).join(","))
    .join(" ");

  const [lx, ly] = pt(arr.length - 1, arr[arr.length - 1]);
  const splitX = pt(splitIdx, arr[splitIdx])[0].toFixed(1);

  return `
    <svg viewBox="0 0 ${W} ${H}" class="seo-spark-svg" aria-hidden="true">
      <rect x="${splitX}" y="1" width="${(W - pad - Number(splitX)).toFixed(1)}" height="${H - 2}" fill="rgba(200,75,40,0.08)" rx="2" />
      <polyline points="${basePts}" fill="none" stroke="#8c897f" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
      <polyline points="${recentPts}" fill="none" stroke="${accentColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="2.3" fill="${accentColor}" />
    </svg>
  `;
}

function getFilteredRows({ ignoreCategory = false, ignoreCountry = false } = {}) {
  if (!seoData) return [];
  const q = state.search.trim().toLowerCase();
  return seoData.rows.filter((r) => {
    if (state.region !== "all" && r.region !== state.region) return false;
    if (!ignoreCountry && state.countryIso && r.country_iso2 !== state.countryIso) return false;
    if (!ignoreCategory && state.category !== "all" && r.category_id !== state.category) return false;
    if (q) {
      const kwBlob = (r.top_keywords || []).map((k) => `${k.query} ${k.query_zh}`).join(" ");
      const blob = `${r.country_zh} ${r.country_iso2} ${r.category_zh} ${r.seed_query} ${kwBlob}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
}

function getCategoryMeta(catId) {
  return seoData?.categories?.find((c) => c.id === catId) || {
    id: catId,
    name_zh: catId,
    short_zh: catId,
    icon: "🚲",
    color: "#171715",
  };
}

function buildShellHtml() {
  return `
    <section class="section sales-section seo-section">
      <div class="section-header sales-header-row">
        <div>
          <div class="section-kicker">DAILY CYCLING SEO &amp; SEARCH TRENDS · 7日 / 30日跨區關鍵字趨勢</div>
          <h2 class="section-title">全球不同地區自行車 SEO 關鍵字熱搜與 7 日／30 日趨勢分析</h2>
          <p class="section-desc">每日自動撈取歐洲（德・英・法・荷）、美洲（美・加）與亞太（台・日・澳）共 9 大市場、10 大自行車類別之即時 Google 熱搜關鍵字與 7 日／30 日搜尋聲量動能。</p>
        </div>
        <div class="sales-meta-pill" id="seo-meta-pill">每日 07:00 CST 自動更新</div>
      </div>

      <!-- Hierarchical Region + Category + Search Slicers -->
      <div class="sales-slicer-card" id="seo-slicers"></div>

      <!-- KPI Strip -->
      <div class="kpi-strip sales-kpi-strip" id="seo-kpi-strip"></div>

      <!-- Visual Overview: 7d vs 30d Category Bars + Country x Category Matrix -->
      <div class="sales-charts-grid" id="seo-overview-anchor">
        <div class="sales-card">
          <div class="sales-card-head">
            <div>
              <div class="sub-heading" id="seo-catbars-title">10 大自行車類別：7 日熱度 vs 30 日基準對比</div>
              <div class="sales-card-sub">深色條為近 7 日熱度、底條為 30 日基準；點擊任一類別可快速篩選下方表格</div>
            </div>
          </div>
          <div class="seo-cat-bars" id="seo-cat-bars"></div>
        </div>

        <div class="sales-card">
          <div class="sales-card-head">
            <div>
              <div class="sub-heading">跨地區 × 10 大車種 SEO 7 日熱度矩陣</div>
              <div class="sales-card-sub">顏色越深代表該國近 7 日搜尋熱度越高；點擊任一格可聚焦該國與類別</div>
            </div>
          </div>
          <div class="table-wrap" id="seo-matrix-wrap"></div>
        </div>
      </div>

      <!-- Main 7d / 30d SEO Trend Table -->
      <div class="sales-card sales-pivot-card" id="seo-table-anchor">
        <div class="sales-pivot-head">
          <div>
            <div class="sub-heading">7 日・30 日自行車 SEO 關鍵字趨勢總表</div>
            <div class="sales-card-sub" id="seo-table-subtitle">點選欄位標題可自由排序；折線右側橘色區間為近 7 日走勢</div>
          </div>
          <div class="pivot-controls">
            <div class="seg-group" id="seo-tablemode-btns">
              <button class="tool-btn active" data-tmode="detail">地區 × 類別明細</button>
              <button class="tool-btn" data-tmode="summary">10 大類別彙總</button>
            </div>
            <select id="seo-sort-select" class="filter-select" aria-label="排序方式">
              <option value="score_7d">排序：7 日熱度（高→低）</option>
              <option value="momentum_7v30_pct">排序：7日 vs 30日 飆升動能</option>
              <option value="wow_pct">排序：7日 vs 前7日 週變動</option>
              <option value="score_30d">排序：30 日基準熱度</option>
              <option value="wiki_7d">排序：7 日真實查詢量</option>
            </select>
            <button class="btn btn-accent" id="btn-export-seo-csv">匯出 SEO CSV</button>
          </div>
        </div>
        <div class="table-wrap" id="seo-table-wrap"></div>
      </div>

      <!-- Localized Google Hot Long-Tail Keywords Explorer -->
      <div class="sales-card sales-bulletins-card" id="seo-keywords-anchor">
        <div class="sales-card-head">
          <div>
            <div class="sub-heading" id="seo-kw-title">各地區即時 Google 熱搜長尾關鍵字（在地原文＋繁體中文）</div>
            <div class="sales-card-sub">點擊任一關鍵字可直接開啟 Google 搜尋結果頁（SERP）檢視排名與內容機會</div>
          </div>
        </div>
        <div class="seo-kw-grid" id="seo-kw-grid"></div>
      </div>

      <!-- Methodology Card -->
      <div class="sales-card sales-sources-card" id="seo-method-anchor">
        <div class="sub-heading">SEO 關鍵字趨勢資料來源與 7 日／30 日計算方法論</div>
        <p class="sales-method-text" id="seo-method-text"></p>
      </div>
    </section>
  `;
}

function renderSlicers() {
  const el = document.getElementById("seo-slicers");
  if (!el || !seoData) return;

  const regionTabs = [
    { id: "all", label: `🌐 全球 (${seoData.countries.length}國)` },
    ...seoData.regions.map((r) => {
      const cnt = seoData.countries.filter((c) => c.region === r.id).length;
      const flag = r.id === "europe" ? "🇪🇺" : r.id === "americas" ? "🌎" : "🌏";
      return { id: r.id, label: `${flag} ${r.name_zh} (${cnt}國)` };
    }),
  ];

  const visibleCountries =
    state.region === "all"
      ? seoData.countries
      : seoData.countries.filter((c) => c.region === state.region);

  const catPills = [
    { id: "all", label: "全部 10 類", icon: "📊", color: "#171715" },
    ...seoData.categories.map((c) => ({
      id: c.id,
      label: c.short_zh,
      icon: c.icon,
      color: c.color,
    })),
  ];

  el.innerHTML = `
    <div class="slicer-row">
      <div class="slicer-label">地理區域</div>
      <div class="slicer-pills" id="seo-region-pills">
        ${regionTabs
          .map(
            (t) =>
              `<button class="slicer-pill ${state.region === t.id ? "active" : ""}" data-region="${t.id}">${esc(t.label)}</button>`
          )
          .join("")}
      </div>
      <div class="slicer-year-wrap">
        <input type="search" id="seo-search-input" class="filter-input" value="${esc(state.search)}" placeholder="搜尋關鍵字、國家或類別（如 Lastenrad、電輔車）..." />
      </div>
    </div>

    <div class="slicer-row slicer-row-countries">
      <div class="slicer-label">${state.region === "all" ? "篩選國家" : `${REGION_META[state.region].short_zh}各國`}</div>
      <div class="slicer-pills" id="seo-country-pills">
        <button class="slicer-pill sub ${!state.countryIso ? "active" : ""}" data-iso="">全部${state.region === "all" ? " 9 國" : REGION_META[state.region].short_zh}</button>
        ${visibleCountries
          .map(
            (c) =>
              `<button class="slicer-pill sub ${state.countryIso === c.iso2 ? "active" : ""}" data-iso="${c.iso2}">${esc(c.name_zh)} <span class="pill-mini">${esc(c.lang_label)}</span></button>`
          )
          .join("")}
      </div>
    </div>

    <div class="slicer-row">
      <div class="slicer-label">SEO 主題</div>
      <div class="slicer-pills" id="seo-cat-pills">
        ${catPills
          .map(
            (p) => `
          <button class="slicer-pill cat ${state.category === p.id ? "active" : ""}" data-cat="${p.id}" style="--pill-accent:${p.color}">
            <span class="cat-dot" style="background:${p.color}"></span>${p.icon} ${esc(p.label)}
          </button>`
          )
          .join("")}
      </div>
    </div>
  `;

  el.querySelectorAll("#seo-region-pills .slicer-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.region = btn.dataset.region;
      state.countryIso = null;
      renderAll();
    });
  });

  el.querySelectorAll("#seo-country-pills .slicer-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      const iso = btn.dataset.iso || null;
      state.countryIso = state.countryIso === iso ? null : iso;
      renderAll();
    });
  });

  el.querySelectorAll("#seo-cat-pills .slicer-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.category = btn.dataset.cat;
      renderAll();
    });
  });

  const searchInput = document.getElementById("seo-search-input");
  searchInput?.addEventListener("input", (e) => {
    state.search = e.target.value;
    renderKpis();
    renderTable();
    renderKeywordGrid();
  });
}

function renderKpis() {
  const pill = document.getElementById("seo-meta-pill");
  if (pill && seoData) {
    pill.textContent = `每日 07:00 CST 自動更新 · 7日(${seoData.window_7d}) / 30日(${seoData.window_30d})`;
  }

  const el = document.getElementById("seo-kpi-strip");
  if (!el || !seoData) return;

  const rows = getFilteredRows();
  if (!rows.length) {
    el.innerHTML = `<div class="kpi-card"><div class="kpi-label">篩選結果</div><div class="kpi-value">0</div><div class="kpi-sub">請調整搜尋關鍵字或地區條件</div></div>`;
    return;
  }

  const top7d = [...rows].sort((a, b) => b.score_7d - a.score_7d)[0];
  const topRise = [...rows].sort((a, b) => b.momentum_7v30_pct - a.momentum_7v30_pct)[0];
  const top30d = [...rows].sort((a, b) => b.score_30d - a.score_30d)[0];
  const totalKws = rows.reduce((s, r) => s + (r.top_keywords?.length || 0), 0);
  const newKws = rows.reduce((s, r) => s + (r.new_keywords_count || 0), 0);

  el.innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">近 7 日熱度最高主題</div>
      <div class="kpi-value kpi-value-sm">${esc(top7d.country_zh)} · ${esc(top7d.category_short)} <span class="kpi-yoy accent">${top7d.score_7d}</span></div>
      <div class="kpi-sub">種子詞「${esc(top7d.seed_query)}」· 7日新聞 ${top7d.news_7d} 則 / 查詢 ${fmtCompactNum(top7d.wiki_7d)}</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">7日 vs 30日 飆升最快（動能冠軍）</div>
      <div class="kpi-value kpi-value-sm">${esc(topRise.country_zh)} · ${esc(topRise.category_short)} ${deltaBadgeHtml(topRise.momentum_7v30_pct, true)}</div>
      <div class="kpi-sub">7日對比前7日週變動：${fmtSignedPct(topRise.wow_pct)}</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">30 日基準熱度冠軍</div>
      <div class="kpi-value kpi-value-sm">${esc(top30d.country_zh)} · ${esc(top30d.category_short)} <span class="kpi-yoy neutral">${top30d.score_30d}</span></div>
      <div class="kpi-sub">30 日累計查詢 ${fmtCompactNum(top30d.wiki_30d)} · 新聞提及 ${top30d.news_30d} 則</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">即時 Google 熱搜關鍵字數</div>
      <div class="kpi-value">${totalKws}${newKws > 0 ? ` <span class="badge badge-new">+${newKws} NEW</span>` : ""}</div>
      <div class="kpi-sub">涵蓋 ${rows.length} 組「國家 × 車種」在地化長尾熱搜詞</div>
    </div>
  `;
}

function renderCategoryBars() {
  const el = document.getElementById("seo-cat-bars");
  const titleEl = document.getElementById("seo-catbars-title");
  if (!el || !seoData) return;

  const baseRows = getFilteredRows({ ignoreCategory: true });
  const scopeLabel = state.countryIso
    ? seoData.countries.find((c) => c.iso2 === state.countryIso)?.name_zh || ""
    : REGION_META[state.region].name_zh;
  if (titleEl) titleEl.textContent = `${scopeLabel} · 10 大自行車類別「7 日 vs 30 日」熱度對比`;

  const agg = seoData.categories.map((cat) => {
    const sub = baseRows.filter((r) => r.category_id === cat.id);
    const n = Math.max(sub.length, 1);
    const avg7 = sub.reduce((s, r) => s + r.score_7d, 0) / n;
    const avg30 = sub.reduce((s, r) => s + r.score_30d, 0) / n;
    const avgMom = sub.reduce((s, r) => s + r.momentum_7v30_pct, 0) / n;
    return { ...cat, avg7, avg30, avgMom };
  });

  agg.sort((a, b) => b.avg7 - a.avg7);

  el.innerHTML = agg
    .map(
      (c) => `
      <button class="seo-cbar-row ${state.category === c.id ? "selected" : ""}" data-cat="${c.id}">
        <div class="seo-cbar-lbl">${c.icon} <strong>${esc(c.short_zh)}</strong></div>
        <div class="seo-cbar-tracks">
          <div class="seo-cbar-track30" title="30日基準：${c.avg30.toFixed(1)}">
            <div class="seo-cbar-fill30" style="width:${c.avg30.toFixed(1)}%"></div>
          </div>
          <div class="seo-cbar-track7" title="7日熱度：${c.avg7.toFixed(1)}">
            <div class="seo-cbar-fill7" style="width:${c.avg7.toFixed(1)}%;background:${c.color}"></div>
          </div>
        </div>
        <div class="seo-cbar-nums">
          <span class="mono-7d">${c.avg7.toFixed(1)}</span>
          <span class="mono-30d">/${c.avg30.toFixed(0)}</span>
          ${deltaBadgeHtml(c.avgMom)}
        </div>
      </button>`
    )
    .join("");

  el.querySelectorAll(".seo-cbar-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cid = btn.dataset.cat;
      state.category = state.category === cid ? "all" : cid;
      renderAll();
    });
  });
}

function renderMatrix() {
  const wrap = document.getElementById("seo-matrix-wrap");
  if (!wrap || !seoData) return;

  const countries =
    state.region === "all"
      ? seoData.countries
      : seoData.countries.filter((c) => c.region === state.region);

  const rowMap = new Map(seoData.rows.map((r) => [`${r.country_iso2}:${r.category_id}`, r]));

  wrap.innerHTML = `
    <table class="data-table seo-matrix-table">
      <thead>
        <tr>
          <th>地區</th>
          ${seoData.categories.map((c) => `<th title="${esc(c.name_zh)}">${c.icon}<br/><small>${esc(c.short_zh.slice(0, 3))}</small></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${countries
          .map(
            (c) => `
          <tr class="${state.countryIso === c.iso2 ? "pivot-selected-row" : ""}">
            <td class="seo-mx-country"><strong>${esc(c.name_zh)}</strong></td>
            ${seoData.categories
              .map((cat) => {
                const r = rowMap.get(`${c.iso2}:${cat.id}`);
                const s7 = r ? r.score_7d : 0;
                const alpha = Math.max(0.06, ((s7 - 15) / 85) * 0.55);
                const isActive = state.countryIso === c.iso2 && state.category === cat.id;
                return `
                  <td class="seo-mx-cell ${isActive ? "active" : ""}" data-mx-iso="${c.iso2}" data-mx-cat="${cat.id}"
                    style="background:rgba(200,75,40,${alpha.toFixed(2)})"
                    title="${esc(c.name_zh)} × ${esc(cat.name_zh)}：7日 ${s7} / 30日 ${r?.score_30d || 0} (${fmtSignedPct(r?.momentum_7v30_pct)})">
                    ${Math.round(s7)}
                  </td>`;
              })
              .join("")}
          </tr>`
          )
          .join("")}
      </tbody>
    </table>
  `;

  wrap.querySelectorAll(".seo-mx-cell").forEach((td) => {
    td.addEventListener("click", () => {
      const iso = td.dataset.mxIso;
      const cid = td.dataset.mxCat;
      if (state.countryIso === iso && state.category === cid) {
        state.countryIso = null;
        state.category = "all";
      } else {
        state.countryIso = iso;
        state.category = cid;
      }
      renderAll();
    });
  });
}

function getSortedTableData() {
  const rows = getFilteredRows();
  const dir = state.sortDir === "asc" ? 1 : -1;

  if (state.tableMode === "summary") {
    const byCat = new Map();
    rows.forEach((r) => {
      if (!byCat.has(r.category_id)) byCat.set(r.category_id, []);
      byCat.get(r.category_id).push(r);
    });
    const list = Array.from(byCat.entries()).map(([catId, group]) => {
      const n = group.length;
      const daily30d = Array.from({ length: 30 }, (_, i) =>
        Math.round(group.reduce((s, r) => s + (r.daily_30d?.[i] || 0), 0) / n)
      );
      const topKws = [];
      const seen = new Set();
      group.forEach((r) => {
        (r.top_keywords || []).slice(0, 2).forEach((k) => {
          const key = k.query.toLowerCase();
          if (!seen.has(key) && topKws.length < 5) {
            seen.add(key);
            topKws.push({ ...k, country_zh: r.country_zh });
          }
        });
      });
      return {
        isSummary: true,
        category_id: catId,
        category_zh: group[0].category_zh,
        category_short: group[0].category_short,
        countries_count: n,
        score_7d: Number((group.reduce((s, r) => s + r.score_7d, 0) / n).toFixed(1)),
        score_30d: Number((group.reduce((s, r) => s + r.score_30d, 0) / n).toFixed(1)),
        wow_pct: Number((group.reduce((s, r) => s + r.wow_pct, 0) / n).toFixed(1)),
        momentum_7v30_pct: Number((group.reduce((s, r) => s + r.momentum_7v30_pct, 0) / n).toFixed(1)),
        wiki_7d: group.reduce((s, r) => s + r.wiki_7d, 0),
        wiki_30d: group.reduce((s, r) => s + r.wiki_30d, 0),
        news_7d: group.reduce((s, r) => s + r.news_7d, 0),
        news_30d: group.reduce((s, r) => s + r.news_30d, 0),
        daily_30d: daily30d,
        top_keywords: topKws,
      };
    });
    list.sort((a, b) => ((a[state.sortBy] || 0) - (b[state.sortBy] || 0)) * dir);
    return list;
  }

  const copy = [...rows];
  copy.sort((a, b) => ((a[state.sortBy] || 0) - (b[state.sortBy] || 0)) * dir);
  return copy;
}

function renderTable() {
  const wrap = document.getElementById("seo-table-wrap");
  const subEl = document.getElementById("seo-table-subtitle");
  if (!wrap || !seoData) return;

  const list = getSortedTableData();
  if (subEl) {
    subEl.textContent = `7 日區間：${seoData.window_7d} ｜ 30 日區間：${seoData.window_30d} ｜ 顯示 ${list.length} 列（折線右側橘色區為近 7 日）`;
  }

  if (!list.length) {
    wrap.innerHTML = `<div style="padding:26px;text-align:center;color:var(--ink-muted);">查無符合篩選條件的 SEO 關鍵字資料。</div>`;
    return;
  }

  const sortArrow = (col) =>
    state.sortBy === col ? (state.sortDir === "desc" ? " ↓" : " ↑") : "";

  wrap.innerHTML = `
    <table class="data-table seo-table">
      <thead>
        <tr>
          ${state.tableMode === "detail" ? `<th style="width:94px;">地區／國家</th>` : ""}
          <th style="width:148px;">自行車 SEO 類別</th>
          <th class="num-col sortable" data-sort="score_7d" style="width:94px;">7日熱度${sortArrow("score_7d")}</th>
          <th class="num-col sortable" data-sort="score_30d" style="width:94px;">30日基準${sortArrow("score_30d")}</th>
          <th class="num-col sortable" data-sort="wow_pct" style="width:98px;">7日週變動${sortArrow("wow_pct")}</th>
          <th class="num-col sortable" data-sort="momentum_7v30_pct" style="width:108px;">7日 vs 30日${sortArrow("momentum_7v30_pct")}</th>
          <th class="num-col sortable" data-sort="wiki_7d" style="width:116px;">7日 / 30日聲量${sortArrow("wiki_7d")}</th>
          <th style="width:124px;">30日每日走勢</th>
          <th>即時 Google 熱搜關鍵字（在地詞 → 中文）</th>
        </tr>
      </thead>
      <tbody>
        ${list
          .map((r) => {
            const cat = getCategoryMeta(r.category_id);
            const kwHtml = (r.top_keywords || [])
              .slice(0, 4)
              .map((k) => {
                const showZh = k.query_zh && k.query_zh.toLowerCase() !== k.query.toLowerCase();
                const gUrl = `https://www.google.com/search?q=${encodeURIComponent(k.query)}`;
                return `
                  <a class="seo-kw-pill" href="${gUrl}" target="_blank" rel="noopener" title="點擊開啟 Google 搜尋「${esc(k.query)}」">
                    ${k.is_new ? '<span class="badge badge-new">NEW</span>' : ""}
                    <strong>${esc(k.query)}</strong>
                    ${showZh ? `<small>${esc(k.query_zh)}</small>` : ""}
                  </a>`;
              })
              .join("");

            return `
              <tr>
                ${
                  state.tableMode === "detail"
                    ? `<td>
                        <div class="seo-tbl-country"><strong>${esc(r.country_zh)}</strong> <span class="bul-tag ${esc(r.region)}">${esc(r.country_iso2)}</span></div>
                        <div class="seo-tbl-sub">${esc(r.lang_label)}</div>
                      </td>`
                    : ""
                }
                <td>
                  <div class="seo-tbl-cat"><span class="cat-dot" style="background:${cat.color}"></span>${cat.icon} <strong>${esc(r.category_short)}</strong></div>
                  <div class="seo-tbl-sub">${r.isSummary ? `涵蓋 ${r.countries_count} 國平均` : `種子詞：${esc(r.seed_query)}`}</div>
                </td>
                <td class="num-col">
                  <div class="seo-score-cell">
                    <strong class="mono">${r.score_7d.toFixed(1)}</strong>
                    <div class="seo-mini-bar"><span style="width:${r.score_7d}%;background:${cat.color}"></span></div>
                  </div>
                </td>
                <td class="num-col mono">${r.score_30d.toFixed(1)}</td>
                <td class="num-col">${deltaBadgeHtml(r.wow_pct)}</td>
                <td class="num-col">${deltaBadgeHtml(r.momentum_7v30_pct, true)}</td>
                <td class="num-col">
                  <div class="mono" style="font-size:12px;">${fmtCompactNum(r.wiki_7d)} / ${fmtCompactNum(r.wiki_30d)}</div>
                  <div class="seo-tbl-sub">新聞 ${r.news_7d} / ${r.news_30d} 則</div>
                </td>
                <td>${sparklineSvg(r.daily_30d, cat.color)}</td>
                <td><div class="seo-kw-pills-wrap">${kwHtml || '<span style="color:var(--ink-muted);font-size:11.5px;">—</span>'}</div></td>
              </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  `;

  wrap.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (state.sortBy === col) {
        state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
      } else {
        state.sortBy = col;
        state.sortDir = "desc";
      }
      const sel = document.getElementById("seo-sort-select");
      if (sel) sel.value = state.sortBy;
      renderTable();
    });
  });
}

function renderKeywordGrid() {
  const grid = document.getElementById("seo-kw-grid");
  const titleEl = document.getElementById("seo-kw-title");
  if (!grid || !seoData) return;

  const rows = getFilteredRows()
    .filter((r) => (r.top_keywords || []).length > 0)
    .sort((a, b) => b.score_7d - a.score_7d)
    .slice(0, 18);

  if (titleEl) {
    const scope = state.countryIso
      ? seoData.countries.find((c) => c.iso2 === state.countryIso)?.name_zh
      : REGION_META[state.region].name_zh;
    titleEl.textContent = `${scope} · 即時 Google 熱搜長尾關鍵字矩陣（在地詞＋中文翻譯）`;
  }

  grid.innerHTML = rows
    .map((r) => {
      const cat = getCategoryMeta(r.category_id);
      return `
        <div class="seo-kw-card">
          <div class="seo-kw-card-head">
            <span><span class="bul-tag ${esc(r.region)}">${esc(r.country_zh)}</span> ${cat.icon} <strong>${esc(r.category_short)}</strong></span>
            <span class="mono" style="font-size:11.5px;color:var(--ink-secondary);">7日 ${r.score_7d.toFixed(1)}</span>
          </div>
          <div class="seo-kw-card-list">
            ${(r.top_keywords || [])
              .map((k, idx) => {
                const showZh = k.query_zh && k.query_zh.toLowerCase() !== k.query.toLowerCase();
                const gUrl = `https://www.google.com/search?q=${encodeURIComponent(k.query)}`;
                return `
                  <a class="seo-kw-item" href="${gUrl}" target="_blank" rel="noopener">
                    <span class="kw-rank">${idx + 1}</span>
                    <span class="kw-text">
                      <strong>${esc(k.query)}</strong>
                      ${showZh ? `<small>${esc(k.query_zh)}</small>` : ""}
                    </span>
                    ${k.is_new ? '<span class="badge badge-new">NEW</span>' : '<span class="kw-ext">↗</span>'}
                  </a>`;
              })
              .join("")}
          </div>
        </div>`;
    })
    .join("");
}

function exportSeoCsv() {
  const list = getSortedTableData();
  const headers = [
    "國家",
    "區域",
    "自行車SEO類別",
    "在地種子詞",
    "7日熱度指數",
    "30日基準指數",
    "7日週變動(%)",
    "7日vs30日動能(%)",
    "7日真實查詢量",
    "30日真實查詢量",
    "7日新聞提及",
    "30日新聞提及",
    "即時Google熱搜詞",
  ];
  const lines = [headers.map((h) => `"${h}"`).join(",")];
  list.forEach((r) => {
    const kws = (r.top_keywords || []).map((k) => k.query).join(" | ");
    const row = [
      r.isSummary ? "跨國彙總" : r.country_zh,
      r.isSummary ? REGION_META[state.region].short_zh : r.region,
      r.category_zh,
      r.seed_query || "",
      r.score_7d,
      r.score_30d,
      r.wow_pct,
      r.momentum_7v30_pct,
      r.wiki_7d,
      r.wiki_30d,
      r.news_7d,
      r.news_30d,
      kws,
    ];
    lines.push(row.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(","));
  });

  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cycling_seo_trends_7d_30d_${seoData?.date || "latest"}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function bindStaticSeoControls() {
  document.querySelectorAll("#seo-tablemode-btns .tool-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.tableMode = btn.dataset.tmode;
      document.querySelectorAll("#seo-tablemode-btns .tool-btn").forEach((b) =>
        b.classList.toggle("active", b.dataset.tmode === state.tableMode)
      );
      renderTable();
    });
  });

  document.getElementById("seo-sort-select")?.addEventListener("change", (e) => {
    state.sortBy = e.target.value;
    state.sortDir = "desc";
    renderTable();
  });

  document.getElementById("btn-export-seo-csv")?.addEventListener("click", exportSeoCsv);
}

function renderAll() {
  renderSlicers();
  renderKpis();
  renderCategoryBars();
  renderMatrix();
  renderTable();
  renderKeywordGrid();
}

export async function mountSeoDashboard(containerEl) {
  mountEl = containerEl;
  if (initialized) return;
  initialized = true;
  mountEl.innerHTML = buildShellHtml();

  try {
    const res = await fetch(`data/seo_trends.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    seoData = await res.json();
  } catch (err) {
    mountEl.innerHTML = `<div class="section"><div class="sales-card">載入全球 SEO 關鍵字趨勢資料失敗：${esc(err.message)}</div></div>`;
    initialized = false;
    return;
  }

  const mEl = document.getElementById("seo-method-text");
  if (mEl) mEl.textContent = seoData.meta?.methodology_zh || "";

  bindStaticSeoControls();
  renderAll();
}
