// Global Bicycle & e-Bike Sales Pivot + 2D/3D Regional Geo Map BI Module
// Loads docs/data/sales_market.json and renders interactive 3D stacked-column geo map (Three.js)
// & 2D choropleth map (D3 + TopoJSON), hierarchical slicers, charts, and dynamic Pivot Table.

import { SalesMap3D } from "./sales_map3d.js?v=2.4.0";

let salesData = null;
let d3Lib = null;
let topojsonLib = null;
let worldGeoFeatures = null;
let map3dInstance = null;
let lastMap3dView = null;
let initialized = false;
let mountEl = null;

const state = {
  region: "all",        // "all" | "europe" | "americas" | "apac"
  countryIso: null,     // null or iso2 e.g. "DE"
  year: "2025",         // "2023" | "2024" | "2025"
  category: "all",      // "all" | "ebike" | "mtb" | "road" | "city" | "other"
  mapMode: "3d",        // "3d" | "2d"
  barStyle: "stacked",  // "stacked" | "grouped"
  mapView: "all",       // "all" | "europe" | "americas" | "apac"
  mapMetric: "volume",  // "volume" | "ebike_share" | "yoy" | "asp"
  pivotRow: "region_country", // "region_country" | "country" | "category" | "year"
  pivotCol: "category",       // "category" | "year" | "region"
  pivotMetric: "volume",      // "volume" | "row_pct" | "revenue"
};

const CAT_COLORS = {
  ebike: "#c84b28",
  mtb: "#1d634f",
  road: "#2b5b84",
  city: "#b87a1e",
  other: "#7c7970",
};

const REGION_META = {
  all: { name_zh: "全球主要市場", short_zh: "全球" },
  europe: { name_zh: "歐洲（9 核心國）", short_zh: "歐洲" },
  americas: { name_zh: "美洲（美・加）", short_zh: "美洲" },
  apac: { name_zh: "亞太（中・日・澳・台）", short_zh: "亞太" },
};

// Map projection bounds [westLon, southLat, eastLon, northLat]
const MAP_VIEW_BOUNDS = {
  all: { lonLat: [[-140, -45], [160, 72]], label: "全球視角" },
  europe: { lonLat: [[-11, 35.5], [19.5, 59.5]], label: "歐洲各國" },
  americas: { lonLat: [[-142, 22], [-52, 68]], label: "美洲（美加）" },
  apac: { lonLat: [[74, -44], [156, 52]], label: "亞太區域" },
};

// Approximate label anchor [lon, lat] for crisp country badges on regional maps
const COUNTRY_CENTROIDS = {
  DE: [10.4, 51.2],
  FR: [2.2, 46.6],
  GB: [-2.2, 54.0],
  IT: [12.6, 42.6],
  ES: [-3.7, 40.3],
  NL: [5.3, 52.3],
  BE: [4.5, 50.6],
  AT: [14.2, 47.5],
  CH: [8.2, 46.8],
  US: [-98.5, 39.5],
  CA: [-104.0, 56.5],
  CN: [104.0, 35.5],
  JP: [138.2, 36.4],
  AU: [134.0, -25.5],
  TW: [121.0, 23.7],
};

function esc(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtWan(k) {
  if (k == null || Number.isNaN(k)) return "—";
  const wan = k / 10;
  if (wan >= 100) return `${wan.toLocaleString("zh-TW", { maximumFractionDigits: 1 })} 萬`;
  return `${wan.toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} 萬`;
}

function fmtWanNum(k) {
  if (k == null || Number.isNaN(k)) return "—";
  return (k / 10).toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function fmtEurB(mEur) {
  if (mEur == null || Number.isNaN(mEur)) return "—";
  // 100 million EUR = 1 億歐元
  const yi = mEur / 100;
  return `€${yi.toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} 億`;
}

function fmtPct(v, signed = false) {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = signed && v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function catKey(catId) {
  return `${catId}_k`;
}

function getCountryVal(country, year, catId) {
  const row = country.yearly[year];
  if (!row) return 0;
  if (!catId || catId === "all") return row.total_k;
  return row[catKey(catId)] || 0;
}

function getFilteredCountries({ ignoreCountry = false } = {}) {
  if (!salesData) return [];
  return salesData.countries.filter((c) => {
    if (state.region !== "all" && c.region !== state.region) return false;
    if (!ignoreCountry && state.countryIso && c.iso2 !== state.countryIso) return false;
    return true;
  });
}

function getActiveCategoryMeta() {
  if (state.category === "all") {
    return { id: "all", name_zh: "全部車種", short_zh: "全車種", icon: "🚲", color: "#171715" };
  }
  return salesData.categories.find((c) => c.id === state.category) || salesData.categories[0];
}

function getCountryMapValue(country) {
  const yr = state.year;
  const row = country.yearly[yr];
  if (!row) return null;
  if (state.mapMetric === "volume") {
    return getCountryVal(country, yr, state.category) / 10; // 萬台
  }
  if (state.mapMetric === "ebike_share") {
    return row.ebike_share_pct;
  }
  if (state.mapMetric === "yoy") {
    return row.yoy_pct ?? 0;
  }
  if (state.mapMetric === "asp") {
    return row.asp_eur;
  }
  return row.total_k / 10;
}

async function ensureMapDeps() {
  if (worldGeoFeatures && d3Lib) return true;
  try {
    const [d3Mod, topoMod, worldRes] = await Promise.all([
      import("https://cdn.jsdelivr.net/npm/d3@7/+esm"),
      import("https://cdn.jsdelivr.net/npm/topojson-client@3/+esm"),
      fetch("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json"),
    ]);
    if (!worldRes.ok) throw new Error(`HTTP ${worldRes.status}`);
    const topo = await worldRes.json();
    d3Lib = d3Mod;
    topojsonLib = topoMod;
    const fc = topojsonLib.feature(topo, topo.objects.countries);
    // Exclude Antarctica (010) for cleaner framing
    worldGeoFeatures = {
      type: "FeatureCollection",
      features: fc.features.filter((f) => String(f.id).padStart(3, "0") !== "010"),
    };
    return true;
  } catch (err) {
    console.warn("Geo map CDN load failed, using fallback cartogram:", err);
    return false;
  }
}

function buildShellHtml() {
  return `
    <section class="section sales-section">
      <div class="section-header sales-header-row">
        <div>
          <div class="section-kicker">GLOBAL BICYCLE MARKET BI · 2023–2025 官方協會數據庫</div>
          <h2 class="section-title">全球自行車銷售樞紐分析與地理視覺化面板</h2>
          <p class="section-desc">整合歐洲（CONEBI/ZIV/USC/RAI/ANCMA/AMBE/Traxio/VSSÖ/Velosuisse/BA）、美洲（PeopleForBikes/StatCan）與亞太（JBPI/BIA/TBA/CBA）官方銷售數據，支援洲別→國家鑽取、車種交叉篩選、互動式熱力地圖與動態樞紐分析表。</p>
        </div>
        <div class="sales-meta-pill" id="sales-meta-pill">2023–2025 年度基準 · 15 核心市場</div>
      </div>

      <!-- Hierarchical Filter Slicer Panel -->
      <div class="sales-slicer-card" id="sales-slicers"></div>

      <!-- Executive KPI Strip -->
      <div class="kpi-strip sales-kpi-strip" id="sales-kpi-strip"></div>

      <!-- Map + Country/Region Deep Inspector -->
      <div class="sales-map-grid" id="sales-map-anchor">
        <div class="sales-card sales-map-card">
          <div class="sales-card-head">
            <div>
              <div class="sub-heading">地理區域 3D／2D 車種柱狀視覺化地圖</div>
              <div class="sales-card-sub" id="sales-map-subtitle">各國依車種堆疊柱狀呈現，點選立體柱或國家即可交叉篩選</div>
            </div>
            <div class="sales-map-controls">
              <div class="seg-group map-mode-seg" id="map-mode-btns" aria-label="2D 或 3D 地圖切換"></div>
              <div class="seg-group" id="map-barstyle-btns" aria-label="3D 柱狀排列模式"></div>
              <div class="seg-group" id="map-view-btns" aria-label="地圖視角縮放"></div>
              <select id="map-metric-select" class="filter-select" aria-label="底板著色指標">
                <option value="volume">底板色階：銷量規模（萬台）</option>
                <option value="ebike_share">底板色階：電輔車滲透率（%）</option>
                <option value="yoy">底板色階：年增率 YoY（%）</option>
                <option value="asp">底板色階：平均單價 ASP（€）</option>
              </select>
            </div>
          </div>
          <div class="sales-map-stage" id="sales-map-stage">
            <div class="sales-map-loading">載入世界與歐洲 3D 地理圖資中...</div>
          </div>
          <div class="sales-map-legend" id="sales-map-legend"></div>
          <div class="sales-map-tooltip hidden" id="sales-map-tooltip"></div>
        </div>

        <div class="sales-card sales-inspector-card" id="sales-inspector"></div>
      </div>

      <!-- Visual Analytics Charts Row -->
      <div class="sales-charts-grid" id="sales-charts-anchor">
        <div class="sales-card">
          <div class="sales-card-head">
            <div>
              <div class="sub-heading" id="stacked-chart-title">各國車種銷量堆疊比較</div>
              <div class="sales-card-sub">依目前篩選範圍與年度排序，點選國家列可連動地圖與鑽取詳情</div>
            </div>
            <div class="sales-cat-legend" id="sales-cat-legend"></div>
          </div>
          <div class="stacked-bars-wrap" id="sales-stacked-bars"></div>
        </div>

        <div class="sales-card">
          <div class="sales-card-head">
            <div>
              <div class="sub-heading" id="trend-chart-title">2023–2025 年度銷量與電輔滲透率趨勢</div>
              <div class="sales-card-sub">柱狀為篩選車種銷量（萬台），折線為該範圍電輔車滲透率（%）</div>
            </div>
          </div>
          <div class="trend-chart-wrap" id="sales-trend-chart"></div>
          <div class="cat-mix-bar-block" id="sales-cat-mix-block"></div>
        </div>
      </div>

      <!-- Dynamic Pivot Table -->
      <div class="sales-card sales-pivot-card" id="sales-pivot-anchor">
        <div class="sales-pivot-head">
          <div>
            <div class="sub-heading">動態樞紐分析表（Interactive Pivot Table）</div>
            <div class="sales-card-sub">自由切換列維度、欄維度與統計指標；表格支援即時熱力色階與 Excel 相容 CSV 匯出</div>
          </div>
          <div class="pivot-controls">
            <label class="pivot-ctrl">
              <span>列 (Rows)</span>
              <select id="pivot-row-select" class="filter-select">
                <option value="region_country">區域 → 國家（階層）</option>
                <option value="country">國家（依總量排序）</option>
                <option value="category">自行車車種</option>
                <option value="year">年份（2023–2025）</option>
              </select>
            </label>
            <label class="pivot-ctrl">
              <span>欄 (Columns)</span>
              <select id="pivot-col-select" class="filter-select">
                <option value="category">自行車車種</option>
                <option value="year">年份（2023–2025）</option>
                <option value="region">地理區域（歐／美／亞太）</option>
              </select>
            </label>
            <label class="pivot-ctrl">
              <span>指標 (Metric)</span>
              <select id="pivot-metric-select" class="filter-select">
                <option value="volume">銷量（萬台）</option>
                <option value="row_pct">列佔比（%）</option>
                <option value="revenue">估計產值（億€）</option>
              </select>
            </label>
            <button class="btn btn-accent" id="btn-export-pivot-csv">匯出樞紐 CSV</button>
          </div>
        </div>
        <div class="table-wrap" id="sales-pivot-wrap"></div>
      </div>

      <!-- Weekly Friday Auto-Crawled Sales Bulletins -->
      <div class="sales-card sales-bulletins-card" id="sales-weekly-bulletins"></div>

      <!-- Scope & Official Benchmarks Callouts -->
      <div class="sales-benchmarks-grid" id="sales-benchmarks"></div>

      <!-- Complete Sources & Methodology -->
      <div class="sales-card sales-sources-card" id="sales-sources-anchor">
        <div id="sales-sources-card"></div>
      </div>
    </section>
  `;
}

function renderSlicers() {
  const el = document.getElementById("sales-slicers");
  if (!el || !salesData) return;

  const regionTabs = [
    { id: "all", label: `🌐 全球總覽 (${salesData.countries.length}國)` },
    ...salesData.regions.map((r) => {
      const cnt = salesData.countries.filter((c) => c.region === r.id).length;
      return { id: r.id, label: `${r.id === "europe" ? "🇪🇺" : r.id === "americas" ? "🌎" : "🌏"} ${r.name_zh} (${cnt}國)` };
    }),
  ];

  const visibleCountries =
    state.region === "all"
      ? salesData.countries
      : salesData.countries.filter((c) => c.region === state.region);

  const catPills = [
    { id: "all", label: "🚲 全部車種", color: "#171715" },
    ...salesData.categories.map((c) => ({
      id: c.id,
      label: `${c.icon} ${c.name_zh}`,
      color: c.color,
    })),
  ];

  el.innerHTML = `
    <div class="slicer-row">
      <div class="slicer-label">地理區域</div>
      <div class="slicer-pills" id="slicer-region-pills">
        ${regionTabs
          .map(
            (t) =>
              `<button class="slicer-pill ${state.region === t.id ? "active" : ""}" data-region="${t.id}">${esc(t.label)}</button>`
          )
          .join("")}
      </div>
      <div class="slicer-year-wrap">
        <span class="slicer-label-inline">年度</span>
        <div class="seg-group" id="slicer-year-pills">
          ${salesData.years
            .slice()
            .reverse()
            .map(
              (yr) =>
                `<button class="tool-btn ${state.year === yr ? "active" : ""}" data-year="${yr}">${yr}${yr === "2025" ? " 最新" : ""}</button>`
            )
            .join("")}
        </div>
      </div>
    </div>

    <div class="slicer-row slicer-row-countries">
      <div class="slicer-label">${state.region === "all" ? "快速選國" : `${REGION_META[state.region].short_zh}各國`}</div>
      <div class="slicer-pills" id="slicer-country-pills">
        <button class="slicer-pill sub ${!state.countryIso ? "active" : ""}" data-iso="">全部${state.region === "all" ? " 15 國" : REGION_META[state.region].short_zh}</button>
        ${visibleCountries
          .map(
            (c) =>
              `<button class="slicer-pill sub ${state.countryIso === c.iso2 ? "active" : ""}" data-iso="${c.iso2}">${esc(c.name_zh)} <span class="pill-mini">${fmtWanNum(getCountryVal(c, state.year, state.category))}萬</span></button>`
          )
          .join("")}
      </div>
    </div>

    <div class="slicer-row">
      <div class="slicer-label">自行車種類</div>
      <div class="slicer-pills" id="slicer-cat-pills">
        ${catPills
          .map(
            (p) => `
          <button class="slicer-pill cat ${state.category === p.id ? "active" : ""}" data-cat="${p.id}" style="--pill-accent:${p.color}">
            <span class="cat-dot" style="background:${p.color}"></span>${esc(p.label)}
          </button>`
          )
          .join("")}
      </div>
    </div>
  `;

  el.querySelectorAll("#slicer-region-pills .slicer-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.region = btn.dataset.region;
      state.countryIso = null;
      state.mapView = state.region;
      renderAll();
    });
  });

  el.querySelectorAll("#slicer-country-pills .slicer-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      const iso = btn.dataset.iso || null;
      if (iso) {
        const found = salesData.countries.find((c) => c.iso2 === iso);
        if (found) {
          state.countryIso = state.countryIso === iso ? null : iso;
          if (state.countryIso) {
            state.mapView = found.region;
          }
        }
      } else {
        state.countryIso = null;
      }
      renderAll();
    });
  });

  el.querySelectorAll("#slicer-year-pills .tool-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.year = btn.dataset.year;
      renderAll();
    });
  });

  el.querySelectorAll("#slicer-cat-pills .slicer-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.category = btn.dataset.cat;
      renderAll();
    });
  });
}

function renderKpis() {
  const el = document.getElementById("sales-kpi-strip");
  if (!el || !salesData) return;

  const countries = getFilteredCountries();
  const yr = state.year;
  const prevYr = yr === "2025" ? "2024" : yr === "2024" ? "2023" : null;
  const catMeta = getActiveCategoryMeta();

  const totalK = countries.reduce((s, c) => s + getCountryVal(c, yr, state.category), 0);
  const allBikesTotalK = countries.reduce((s, c) => s + c.yearly[yr].total_k, 0);
  const ebikeK = countries.reduce((s, c) => s + c.yearly[yr].ebike_k, 0);
  const revenueMEur = countries.reduce((s, c) => s + c.yearly[yr].revenue_m_eur, 0);

  let yoy = null;
  if (prevYr) {
    const prevK = countries.reduce((s, c) => s + getCountryVal(c, prevYr, state.category), 0);
    if (prevK > 0) yoy = ((totalK - prevK) / prevK) * 100;
  }

  const ebikeShare = allBikesTotalK > 0 ? (ebikeK / allBikesTotalK) * 100 : 0;
  const weightedAsp = allBikesTotalK > 0 ? Math.round((revenueMEur * 1000) / allBikesTotalK) : 0;
  const catShareOfTotal = allBikesTotalK > 0 ? (totalK / allBikesTotalK) * 100 : 100;

  // Top country in scope
  const sortedByVal = [...countries].sort(
    (a, b) => getCountryVal(b, yr, state.category) - getCountryVal(a, yr, state.category)
  );
  const leader = sortedByVal[0];
  const topEbikeCountry = [...countries].sort(
    (a, b) => b.yearly[yr].ebike_share_pct - a.yearly[yr].ebike_share_pct
  )[0];

  const scopeLabel = state.countryIso
    ? `${countries[0]?.name_zh || ""}`
    : REGION_META[state.region].name_zh;

  const yoyBadge =
    yoy != null
      ? `<span class="kpi-yoy ${yoy >= 0 ? "pos" : "neg"}">${fmtPct(yoy, true)} YoY</span>`
      : `<span class="kpi-yoy neutral">基準年</span>`;

  el.innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">${esc(yr)} 年 ${esc(catMeta.short_zh)} 銷量 · ${esc(scopeLabel)}</div>
      <div class="kpi-value">${fmtWan(totalK)} ${yoyBadge}</div>
      <div class="kpi-sub">${state.category === "all" ? `涵蓋 ${countries.length} 個市場互斥加總` : `佔該範圍總銷量 ${catShareOfTotal.toFixed(1)}%`}</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">電輔車 (e-Bike) 銷量與滲透率</div>
      <div class="kpi-value">${fmtWan(ebikeK)} <span class="kpi-yoy accent">${ebikeShare.toFixed(1)}%</span></div>
      <div class="kpi-sub">${topEbikeCountry ? `滲透率最高：${esc(topEbikeCountry.name_zh)} (${topEbikeCountry.yearly[yr].ebike_share_pct}%)` : "—"}</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">全市場估計產值與加權均價</div>
      <div class="kpi-value">${fmtEurB(revenueMEur)}</div>
      <div class="kpi-sub">加權平均單價 ASP：€${weightedAsp.toLocaleString("zh-TW")} / 台</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">${state.countryIso ? "官方統計出處" : "範圍最大單一市場"}</div>
      <div class="kpi-value kpi-value-sm">${state.countryIso ? esc(leader?.name_zh || "—") : esc(leader ? `${leader.name_zh} · ${fmtWan(getCountryVal(leader, yr, state.category))}` : "—")}</div>
      <div class="kpi-sub">${leader ? esc(leader.source_name) : "—"}</div>
    </div>
  `;
}

function renderMapControls() {
  const modeEl = document.getElementById("map-mode-btns");
  if (modeEl) {
    modeEl.innerHTML = `
      <button class="tool-btn ${state.mapMode === "3d" ? "active" : ""}" data-mapmode="3d">🌐 3D 立體柱狀</button>
      <button class="tool-btn ${state.mapMode === "2d" ? "active" : ""}" data-mapmode="2d">🗺️ 2D 平面地圖</button>
    `;
    modeEl.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextMode = btn.dataset.mapmode;
        if (nextMode === state.mapMode) return;
        state.mapMode = nextMode;
        if (nextMode === "2d" && map3dInstance) {
          map3dInstance.dispose();
          map3dInstance = null;
          lastMap3dView = null;
        }
        renderMapControls();
        renderMap();
      });
    });
  }

  const styleEl = document.getElementById("map-barstyle-btns");
  if (styleEl) {
    styleEl.classList.toggle("hidden", state.mapMode !== "3d");
    styleEl.innerHTML = `
      <button class="tool-btn ${state.barStyle === "stacked" ? "active" : ""}" data-barstyle="stacked">堆疊柱</button>
      <button class="tool-btn ${state.barStyle === "grouped" ? "active" : ""}" data-barstyle="grouped">分群並列</button>
      <button class="tool-btn" id="btn-reset-3d-cam" title="重設 3D 相機角度">重設視角</button>
    `;
    styleEl.querySelectorAll("[data-barstyle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.barStyle = btn.dataset.barstyle;
        renderMapControls();
        renderMap();
      });
    });
    document.getElementById("btn-reset-3d-cam")?.addEventListener("click", () => {
      map3dInstance?.setView(state.mapView, false);
    });
  }

  const btnsEl = document.getElementById("map-view-btns");
  if (btnsEl) {
    btnsEl.innerHTML = Object.entries(MAP_VIEW_BOUNDS)
      .map(
        ([k, v]) =>
          `<button class="tool-btn ${state.mapView === k ? "active" : ""}" data-mapview="${k}">${esc(v.label)}</button>`
      )
      .join("");
    btnsEl.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.mapView = btn.dataset.mapview;
        renderMapControls();
        renderMap();
      });
    });
  }

  const metricSelect = document.getElementById("map-metric-select");
  if (metricSelect && !metricSelect.dataset.bound) {
    metricSelect.dataset.bound = "1";
    metricSelect.addEventListener("change", (e) => {
      state.mapMetric = e.target.value;
      renderMap();
    });
  }
  if (metricSelect) metricSelect.value = state.mapMetric;
}

function getMetricColorScale(values) {
  const valid = values.filter((v) => v != null && !Number.isNaN(v));
  const minVal = valid.length ? Math.min(...valid) : 0;
  const maxVal = valid.length ? Math.max(...valid) : 1;

  if (state.mapMetric === "yoy") {
    const absMax = Math.max(Math.abs(minVal), Math.abs(maxVal), 6);
    return {
      min: -absMax,
      max: absMax,
      unit: "%",
      palette: ["#a83228", "#c26a5b", "#394654", "#3c8c72", "#1f9c74"],
      color(v) {
        if (v == null) return "#2a3542";
        const t = Math.max(0, Math.min(1, (v + absMax) / (2 * absMax)));
        if (d3Lib) return d3Lib.interpolateRgbBasis(["#a83228", "#b95c4e", "#3c4b5c", "#2d8a6d", "#1fb083"])(t);
        return v >= 0 ? "#1f9c74" : "#b84335";
      },
    };
  }

  if (state.mapMetric === "ebike_share") {
    return {
      min: 0,
      max: Math.max(maxVal, 60),
      unit: "%",
      palette: ["#2c3a47", "#5c4a42", "#9e5138", "#cf5832", "#f06d42"],
      color(v) {
        if (v == null) return "#2a3542";
        const t = Math.max(0, Math.min(1, v / 60));
        return d3Lib
          ? d3Lib.interpolateRgbBasis(["#2b3947", "#5e4a41", "#a35036", "#d45830", "#f26e41"])(t)
          : "#d45830";
      },
    };
  }

  if (state.mapMetric === "asp") {
    return {
      min: 200,
      max: Math.max(maxVal, 2900),
      unit: "€",
      palette: ["#273645", "#2d4c68", "#346992", "#4389bd", "#6bb1e0"],
      color(v) {
        if (v == null) return "#2a3542";
        const t = Math.max(0, Math.min(1, (v - 200) / Math.max(maxVal - 200, 1)));
        return d3Lib
          ? d3Lib.interpolateRgbBasis(["#273645", "#2d4c68", "#346992", "#4389bd", "#6bb1e0"])(t)
          : "#346992";
      },
    };
  }

  // Volume (sqrt scale tuned for rich contrast on dark architectural map)
  const vmax = Math.max(maxVal, 10);
  return {
    min: 0,
    max: vmax,
    unit: "萬台",
    palette: ["#263b42", "#265558", "#227166", "#239175", "#35b38c"],
    color(v) {
      if (v == null) return "#2a3542";
      const t = Math.max(0, Math.min(1, Math.sqrt(Math.max(0, v)) / Math.sqrt(vmax)));
      return d3Lib
        ? d3Lib.interpolateRgbBasis(["#263b42", "#265558", "#227166", "#239175", "#35b38c"])(t)
        : "#227166";
    },
  };
}

function formatMapMetricVal(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (state.mapMetric === "volume") return `${v.toFixed(1)} 萬`;
  if (state.mapMetric === "ebike_share") return `${v.toFixed(1)}%`;
  if (state.mapMetric === "yoy") return fmtPct(v, true);
  if (state.mapMetric === "asp") return `€${Math.round(v).toLocaleString("zh-TW")}`;
  return String(v);
}

function showMapTooltip(evt, country) {
  const tip = document.getElementById("sales-map-tooltip");
  const card = tip?.parentElement;
  if (!tip || !card) return;
  const yr = state.year;
  const row = country.yearly[yr];
  const catMeta = getActiveCategoryMeta();
  const activeVal = getCountryVal(country, yr, state.category);

  const stackBarHtml = salesData.categories
    .map((cat) => {
      const v = row[catKey(cat.id)] || 0;
      const pct = row.total_k > 0 ? (v / row.total_k) * 100 : 0;
      return `<span style="width:${pct.toFixed(1)}%;background:${cat.color}"></span>`;
    })
    .join("");

  tip.innerHTML = `
    <div class="map-tip-head">
      <strong>${esc(country.name_zh)} (${esc(country.iso2)})</strong>
      <span class="map-tip-yr">${yr} 年 · 總量 ${fmtWan(row.total_k)}台</span>
    </div>
    <div class="map-tip-stackbar">${stackBarHtml}</div>
    <div class="map-tip-grid">
      <div><span>${esc(catMeta.short_zh)}銷量</span><strong>${fmtWan(activeVal)}台</strong></div>
      <div><span>⚡ 電輔車</span><strong>${fmtWan(row.ebike_k)} (${row.ebike_share_pct}%)</strong></div>
      <div><span>年增率 YoY</span><strong class="${(row.yoy_pct ?? 0) >= 0 ? "txt-pos" : "txt-neg"}">${fmtPct(row.yoy_pct, true)}</strong></div>
      <div><span>平均單價 ASP</span><strong>€${row.asp_eur.toLocaleString("zh-TW")}</strong></div>
    </div>
    <div class="map-tip-cats">
      <span><i style="background:${CAT_COLORS.mtb}"></i>登山 ${fmtWanNum(row.mtb_k)}萬</span>
      <span><i style="background:${CAT_COLORS.road}"></i>公路 ${fmtWanNum(row.road_k)}萬</span>
      <span><i style="background:${CAT_COLORS.city}"></i>城市 ${fmtWanNum(row.city_k)}萬</span>
      <span><i style="background:${CAT_COLORS.other}"></i>其他 ${fmtWanNum(row.other_k)}萬</span>
    </div>
    <div class="map-tip-src">來源：${esc(country.source_name)}（點擊鎖定篩選）</div>
  `;

  tip.classList.remove("hidden");
  const rect = card.getBoundingClientRect();
  let x = evt.clientX - rect.left + 16;
  let y = evt.clientY - rect.top - 14;
  const maxX = rect.width - 284;
  if (x > maxX) x = Math.max(12, evt.clientX - rect.left - 284);
  if (y + 210 > rect.height) y = Math.max(12, rect.height - 218);
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

function hideMapTooltip() {
  const tip = document.getElementById("sales-map-tooltip");
  if (tip) tip.classList.add("hidden");
}

function renderFallbackCartogram(stageEl, scale) {
  const byRegion = { europe: [], americas: [], apac: [] };
  salesData.countries.forEach((c) => byRegion[c.region]?.push(c));
  stageEl.innerHTML = `
    <div class="cartogram-grid">
      ${salesData.regions
        .map(
          (reg) => `
        <div class="cartogram-group">
          <div class="cartogram-group-title">${esc(reg.name_zh)}</div>
          <div class="cartogram-tiles">
            ${(byRegion[reg.id] || [])
              .map((c) => {
                const v = getCountryMapValue(c);
                const selected = state.countryIso === c.iso2;
                return `
                  <button class="cartogram-tile ${selected ? "selected" : ""}" data-iso="${c.iso2}" style="background:${scale.color(v)}">
                    <span class="tile-name">${esc(c.name_zh)}</span>
                    <span class="tile-val">${formatMapMetricVal(v)}</span>
                  </button>`;
              })
              .join("")}
          </div>
        </div>`
        )
        .join("")}
    </div>
  `;
  stageEl.querySelectorAll(".cartogram-tile").forEach((btn) => {
    btn.addEventListener("click", () => {
      const iso = btn.dataset.iso;
      state.countryIso = state.countryIso === iso ? null : iso;
      renderAll();
    });
  });
}

function handleMapCountrySelect(country) {
  state.countryIso = state.countryIso === country.iso2 ? null : country.iso2;
  if (state.countryIso && state.region !== "all" && state.region !== country.region) {
    state.region = country.region;
  }
  hideMapTooltip();
  renderAll();
}

async function renderMap() {
  const stageEl = document.getElementById("sales-map-stage");
  const legendEl = document.getElementById("sales-map-legend");
  const subEl = document.getElementById("sales-map-subtitle");
  if (!stageEl || !salesData) return;

  const catMeta = getActiveCategoryMeta();
  if (subEl) {
    const metricLabels = {
      volume: `${catMeta.name_zh}銷量（萬台）`,
      ebike_share: "電輔車滲透率（%）",
      yoy: "總銷量年增率 YoY（%）",
      asp: "平均單價 ASP（€）",
    };
    const modeTag =
      state.mapMode === "3d"
        ? `3D ${state.barStyle === "grouped" ? "並列分群柱" : "車種堆疊柱"}`
        : "2D 平面疊加柱";
    subEl.textContent = `${state.year} 年 · ${modeTag} · ${MAP_VIEW_BOUNDS[state.mapView].label} · 底板：${metricLabels[state.mapMetric]}`;
  }

  // Compute color scale across countries in active map view
  const scopeCountries =
    state.mapView === "all"
      ? salesData.countries
      : salesData.countries.filter((c) => c.region === state.mapView);
  const scale = getMetricColorScale(scopeCountries.map((c) => getCountryMapValue(c)));

  // Render unified legend: 5 Bike Category Bar Swatches + Plate Heat Ramp
  if (legendEl) {
    const grad = `linear-gradient(90deg, ${scale.palette.join(", ")})`;
    const minStr =
      state.mapMetric === "yoy"
        ? fmtPct(scale.min, true)
        : state.mapMetric === "asp"
          ? `€${Math.round(scale.min)}`
          : state.mapMetric === "ebike_share"
            ? "0%"
            : "0 萬";
    const maxStr =
      state.mapMetric === "yoy"
        ? fmtPct(scale.max, true)
        : state.mapMetric === "asp"
          ? `€${Math.round(scale.max).toLocaleString("zh-TW")}`
          : state.mapMetric === "ebike_share"
            ? `${Math.round(scale.max)}%`
            : `${scale.max.toFixed(0)} 萬`;

    const catSwatches = salesData.categories
      .map(
        (cat) => `
        <span class="map-leg-cat ${state.category !== "all" && state.category !== cat.id ? "dim" : ""}">
          <i style="background:${cat.color}"></i>${esc(cat.short_zh)}
        </span>`
      )
      .join("");

    legendEl.innerHTML = `
      <div class="map-legend-cats">
        <span class="map-leg-title">柱狀車種：</span>
        ${catSwatches}
      </div>
      <div class="map-legend-heat">
        <span class="map-leg-title">底板：</span>
        <span class="legend-cap">${minStr}</span>
        <span class="legend-ramp" style="background:${grad}"></span>
        <span class="legend-cap">${maxStr}</span>
      </div>
    `;
  }

  const ok = await ensureMapDeps();
  if (!ok || !d3Lib || !worldGeoFeatures) {
    renderFallbackCartogram(stageEl, scale);
    return;
  }

  // ==================== 3D ARCHITECTURAL RELIEF + STACKED COLUMNS ====================
  if (state.mapMode === "3d") {
    stageEl.classList.add("is-3d");
    if (!map3dInstance) {
      map3dInstance = new SalesMap3D(stageEl, {
        onHover: (evt, c) => showMapTooltip(evt, c),
        onLeave: hideMapTooltip,
        onSelect: handleMapCountrySelect,
      });
      map3dInstance.buildWorldGeometry(worldGeoFeatures, salesData.countries);
      lastMap3dView = null;
    }

    map3dInstance.updateData(salesData, state, {
      getMetricColor: (c) => scale.color(getCountryMapValue(c)),
      formatMetricVal: (c) => formatMapMetricVal(getCountryMapValue(c)),
      barStyle: state.barStyle,
    });

    if (lastMap3dView !== state.mapView) {
      map3dInstance.setView(state.mapView, lastMap3dView === null);
      lastMap3dView = state.mapView;
    }
    return;
  }

  // ==================== 2D ARCHITECTURAL PLANAR MAP + STACKED COLUMN PINS ====================
  stageEl.classList.remove("is-3d");
  const W = 780;
  const H = 450;
  const countryByIsoNum = new Map(salesData.countries.map((c) => [c.iso_num, c]));

  const bounds = MAP_VIEW_BOUNDS[state.mapView].lonLat;
  const bboxGeo = {
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: [bounds[0], [bounds[1][0], bounds[0][1]], bounds[1], [bounds[0][0], bounds[1][1]]],
    },
  };

  const projection =
    state.mapView === "all"
      ? d3Lib.geoNaturalEarth1().fitExtent([[14, 18], [W - 14, H - 18]], worldGeoFeatures)
      : d3Lib.geoMercator().fitExtent([[34, 34], [W - 34, H - 24]], bboxGeo);

  const pathGen = d3Lib.geoPath(projection);

  stageEl.innerHTML = "";
  const svg = d3Lib
    .select(stageEl)
    .append("svg")
    .attr("viewBox", `0 0 ${W} ${H}`)
    .attr("class", "geo-map-svg geo-map-2d-dark")
    .attr("role", "img")
    .attr("aria-label", "全球自行車銷售地理區域熱力與車種柱狀圖");

  // Dark slate ocean gradient + soft glow defs
  const defs = svg.append("defs");
  const oceanGrad = defs.append("linearGradient").attr("id", "oceanGrad2d").attr("x1", "0%").attr("y1", "0%").attr("x2", "0%").attr("y2", "100%");
  oceanGrad.append("stop").attr("offset", "0%").attr("stop-color", "#1a2330");
  oceanGrad.append("stop").attr("offset", "100%").attr("stop-color", "#121821");

  svg.append("rect").attr("width", W).attr("height", H).attr("fill", "url(#oceanGrad2d)").attr("rx", 8);

  const graticule = d3Lib.geoGraticule10();
  svg
    .append("path")
    .datum(graticule)
    .attr("d", pathGen)
    .attr("fill", "none")
    .attr("stroke", "rgba(148,176,204,0.11)")
    .attr("stroke-width", 0.7);

  // Countries layer
  const gCountries = svg.append("g");
  gCountries
    .selectAll("path")
    .data(worldGeoFeatures.features)
    .join("path")
    .attr("d", pathGen)
    .attr("class", (d) => {
      const c = countryByIsoNum.get(String(d.id).padStart(3, "0"));
      if (!c) return "geo-country untracked";
      const isSelected = state.countryIso === c.iso2;
      const inRegion = state.region === "all" || c.region === state.region;
      return `geo-country tracked ${isSelected ? "selected" : ""} ${inRegion ? "" : "dimmed"}`;
    })
    .attr("fill", (d) => {
      const c = countryByIsoNum.get(String(d.id).padStart(3, "0"));
      if (!c) return "#222c38";
      return scale.color(getCountryMapValue(c));
    })
    .on("mouseenter", (evt, d) => {
      const c = countryByIsoNum.get(String(d.id).padStart(3, "0"));
      if (c) showMapTooltip(evt, c);
    })
    .on("mousemove", (evt, d) => {
      const c = countryByIsoNum.get(String(d.id).padStart(3, "0"));
      if (c) showMapTooltip(evt, c);
    })
    .on("mouseleave", hideMapTooltip)
    .on("click", (_, d) => {
      const c = countryByIsoNum.get(String(d.id).padStart(3, "0"));
      if (c) handleMapCountrySelect(c);
    });

  // Overlaid 2D Stacked Bike Category Column Pins on tracked countries in current view
  const pinCountries =
    state.mapView === "all"
      ? salesData.countries
      : salesData.countries.filter((c) => c.region === state.mapView);

  const yr = state.year;
  const maxValK = Math.max(...pinCountries.map((c) => getCountryVal(c, yr, state.category)), 100);
  const maxBarPx = state.mapView === "europe" ? 64 : 74;
  const barW = state.mapView === "europe" ? 13 : 11;

  // Sort northernmost first so southern columns overlap naturally in front
  const sortedPins = [...pinCountries].sort(
    (a, b) => (COUNTRY_CENTROIDS[b.iso2]?.[1] || 0) - (COUNTRY_CENTROIDS[a.iso2]?.[1] || 0)
  );

  const gBars = svg.append("g").attr("class", "geo-2d-bars");
  const placedLabels = [];

  sortedPins.forEach((c) => {
    const coords = COUNTRY_CENTROIDS[c.iso2];
    if (!coords) return;
    const pt = projection(coords);
    if (!pt || pt[0] < 16 || pt[0] > W - 16 || pt[1] < 24 || pt[1] > H - 14) return;

    const row = c.yearly[yr];
    const totalK = getCountryVal(c, yr, state.category);
    const barH = Math.max(10, Math.pow(totalK / maxValK, 0.55) * maxBarPx);
    const isSelected = state.countryIso === c.iso2;
    const inRegion = state.region === "all" || c.region === state.region;

    const g = gBars
      .append("g")
      .attr("transform", `translate(${pt[0]}, ${pt[1]})`)
      .attr("class", `geo-2d-pin ${isSelected ? "selected" : ""} ${inRegion ? "" : "dimmed"}`)
      .style("cursor", "pointer")
      .on("mouseenter", (evt) => showMapTooltip(evt, c))
      .on("mousemove", (evt) => showMapTooltip(evt, c))
      .on("mouseleave", hideMapTooltip)
      .on("click", () => handleMapCountrySelect(c));

    // Subtle ground ellipse anchor
    g.append("ellipse")
      .attr("cx", 0)
      .attr("cy", 1)
      .attr("rx", barW * 0.72)
      .attr("ry", 3.2)
      .attr("fill", isSelected ? "rgba(242,110,65,0.85)" : "rgba(255,255,255,0.35)");

    // Stacked category column rising upward (-Y)
    if (state.category === "all") {
      let curY = 0;
      salesData.categories.forEach((cat) => {
        const v = row[catKey(cat.id)] || 0;
        if (v <= 0) return;
        const sh = Math.max(1.8, (v / totalK) * barH);
        g.append("rect")
          .attr("x", -barW / 2)
          .attr("y", -curY - sh)
          .attr("width", barW)
          .attr("height", sh)
          .attr("fill", cat.color)
          .attr("stroke", "rgba(18,24,33,0.7)")
          .attr("stroke-width", 0.6)
          .attr("rx", 1.2);
        curY += sh;
      });
    } else {
      g.append("rect")
        .attr("x", -barW / 2)
        .attr("y", -barH)
        .attr("width", barW)
        .attr("height", barH)
        .attr("fill", catMeta.color)
        .attr("stroke", "rgba(255,255,255,0.45)")
        .attr("stroke-width", 0.8)
        .attr("rx", 2);
    }

    // Crisp label above column top with simple anti-overlap check
    const labelText = `${c.name_zh} ${(totalK / 10).toFixed(1)}萬`;
    const pillW = Math.max(60, labelText.length * 7.2 + 12);
    const ly = -barH - 12;
    const box = {
      l: pt[0] - pillW / 2,
      r: pt[0] + pillW / 2,
      t: pt[1] + ly - 9,
      b: pt[1] + ly + 9,
    };
    const collides =
      !isSelected &&
      placedLabels.some((p) => !(box.r < p.l || box.l > p.r || box.b < p.t || box.t > p.b));

    if (!collides || state.mapView !== "all") {
      placedLabels.push(box);
      const gl = g.append("g").attr("class", `geo-badge ${isSelected ? "selected" : ""}`).attr("transform", `translate(0, ${ly})`);
      gl.append("rect").attr("x", -pillW / 2).attr("y", -9).attr("width", pillW).attr("height", 18).attr("rx", 4.5);
      gl.append("text").attr("text-anchor", "middle").attr("dy", "0.35em").text(labelText);
    }
  });
}

function renderInspector() {
  const el = document.getElementById("sales-inspector");
  if (!el || !salesData) return;

  const yr = state.year;
  const selected = state.countryIso
    ? salesData.countries.find((c) => c.iso2 === state.countryIso)
    : null;

  if (selected) {
    const row = selected.yearly[yr];
    const regName = salesData.regions.find((r) => r.id === selected.region)?.name_zh || "";
    const submixEntries = Object.entries(selected.ebike_submix || {});

    el.innerHTML = `
      <div class="inspector-head">
        <div>
          <div class="inspector-kicker">${esc(regName)} · ${esc(selected.name_en)} (${esc(selected.iso2)})</div>
          <h3 class="inspector-title">${esc(selected.name_zh)} ${yr} 市場剖析</h3>
        </div>
        <button class="tool-btn" id="btn-clear-country">返回區域總覽</button>
      </div>

      <div class="inspector-metrics">
        <div class="ins-metric">
          <span>總銷量</span>
          <strong>${fmtWan(row.total_k)}台</strong>
        </div>
        <div class="ins-metric">
          <span>電輔車滲透率</span>
          <strong class="txt-accent">${row.ebike_share_pct}%</strong>
        </div>
        <div class="ins-metric">
          <span>年增率 YoY</span>
          <strong class="${(row.yoy_pct ?? 0) >= 0 ? "txt-pos" : "txt-neg"}">${fmtPct(row.yoy_pct, true)}</strong>
        </div>
        <div class="ins-metric">
          <span>平均單價 ASP</span>
          <strong>€${row.asp_eur.toLocaleString("zh-TW")}</strong>
        </div>
      </div>

      <p class="inspector-note">${esc(selected.note_zh)}</p>

      <div class="inspector-subblock">
        <div class="sub-heading">${yr} 年各車種銷量明細</div>
        <div class="ins-cat-list">
          ${salesData.categories
            .map((cat) => {
              const v = row[catKey(cat.id)] || 0;
              const pct = row.total_k > 0 ? (v / row.total_k) * 100 : 0;
              return `
                <div class="ins-cat-row">
                  <div class="ins-cat-label"><span class="cat-dot" style="background:${cat.color}"></span>${cat.icon} ${esc(cat.short_zh)}</div>
                  <div class="ins-cat-bar-track"><div class="ins-cat-bar-fill" style="width:${pct.toFixed(1)}%;background:${cat.color}"></div></div>
                  <div class="ins-cat-val">${fmtWanNum(v)}萬 <small>(${pct.toFixed(1)}%)</small></div>
                </div>`;
            })
            .join("")}
        </div>
      </div>

      ${
        submixEntries.length
          ? `<div class="inspector-subblock">
              <div class="sub-heading">電輔車 (e-Bike) 內部細分結構</div>
              <div class="submix-chips">
                ${submixEntries
                  .map(
                    ([k, v]) => `<span class="submix-chip"><strong>${esc(k)}</strong> ${v}%</span>`
                  )
                  .join("")}
              </div>
            </div>`
          : ""
      }

      <div class="inspector-source">
        <span class="badge ${selected.confidence === "official" ? "badge-measured" : "badge-inferred"}">
          ${selected.confidence === "official" ? "官方協會年報" : "官方總量＋結構校準"}
        </span>
        <a href="${esc(selected.source_url)}" target="_blank" rel="noopener">${esc(selected.source_name)} ↗</a>
      </div>
    `;

    document.getElementById("btn-clear-country")?.addEventListener("click", () => {
      state.countryIso = null;
      renderAll();
    });
    return;
  }

  // Regional / Global Summary Inspector
  const countries = getFilteredCountries();
  const totalAll = countries.reduce((s, c) => s + c.yearly[yr].total_k, 0);

  // Breakdown by Region (when global) or top countries (when region)
  const regionSummaries = salesData.regions.map((r) => {
    const list = salesData.countries.filter((c) => c.region === r.id);
    const tot = list.reduce((s, c) => s + getCountryVal(c, yr, state.category), 0);
    const eb = list.reduce((s, c) => s + c.yearly[yr].ebike_k, 0);
    const allTot = list.reduce((s, c) => s + c.yearly[yr].total_k, 0);
    const rev = list.reduce((s, c) => s + c.yearly[yr].revenue_m_eur, 0);
    return {
      ...r,
      tot,
      ebShare: allTot > 0 ? (eb / allTot) * 100 : 0,
      rev,
      count: list.length,
    };
  });

  const catTotals = salesData.categories.map((cat) => {
    const v = countries.reduce((s, c) => s + (c.yearly[yr][catKey(cat.id)] || 0), 0);
    return { ...cat, val: v, pct: totalAll > 0 ? (v / totalAll) * 100 : 0 };
  });

  const scopeTitle = REGION_META[state.region].name_zh;

  el.innerHTML = `
    <div class="inspector-head">
      <div>
        <div class="inspector-kicker">REGIONAL SUMMARY · ${yr} 年結構總覽</div>
        <h3 class="inspector-title">${esc(scopeTitle)}</h3>
      </div>
    </div>

    <div class="inspector-subblock">
      <div class="sub-heading">三大區域比較（點擊快速鑽取）</div>
      <div class="region-compare-list">
        ${regionSummaries
          .map(
            (r) => `
          <button class="region-compare-row ${state.region === r.id ? "active" : ""}" data-jump-region="${r.id}">
            <div>
              <strong>${esc(r.name_zh)}</strong>
              <small>${r.count} 國 · 電輔 ${r.ebShare.toFixed(1)}% · ${fmtEurB(r.rev)}</small>
            </div>
            <div class="region-compare-val">${fmtWan(r.tot)}台</div>
          </button>`
          )
          .join("")}
      </div>
    </div>

    <div class="inspector-subblock">
      <div class="sub-heading">${esc(scopeTitle)} 車種結構佔比（${yr}）</div>
      <div class="ins-cat-list">
        ${catTotals
          .map(
            (c) => `
          <div class="ins-cat-row clickable ${state.category === c.id ? "active" : ""}" data-jump-cat="${c.id}">
            <div class="ins-cat-label"><span class="cat-dot" style="background:${c.color}"></span>${c.icon} ${esc(c.short_zh)}</div>
            <div class="ins-cat-bar-track"><div class="ins-cat-bar-fill" style="width:${c.pct.toFixed(1)}%;background:${c.color}"></div></div>
            <div class="ins-cat-val">${fmtWanNum(c.val)}萬 <small>(${c.pct.toFixed(1)}%)</small></div>
          </div>`
          )
          .join("")}
      </div>
    </div>

    <div class="inspector-hint">
      提示：點擊左側地圖上的任一國家（如德國、荷蘭、美國、日本），即可查看該國官方協會來源、電輔細分結構（e-MTB／e-City）與三年走勢。
    </div>
  `;

  el.querySelectorAll("[data-jump-region]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const r = btn.dataset.jumpRegion;
      state.region = state.region === r ? "all" : r;
      state.countryIso = null;
      state.mapView = state.region;
      renderAll();
    });
  });

  el.querySelectorAll("[data-jump-cat]").forEach((row) => {
    row.addEventListener("click", () => {
      const cid = row.dataset.jumpCat;
      state.category = state.category === cid ? "all" : cid;
      renderAll();
    });
  });
}

function renderStackedBars() {
  const wrap = document.getElementById("sales-stacked-bars");
  const legend = document.getElementById("sales-cat-legend");
  const titleEl = document.getElementById("stacked-chart-title");
  if (!wrap || !salesData) return;

  const yr = state.year;
  const catMeta = getActiveCategoryMeta();
  const countries = getFilteredCountries({ ignoreCountry: true });

  if (titleEl) {
    titleEl.textContent = `${REGION_META[state.region].name_zh} · 各國${state.category === "all" ? "車種堆疊" : ` ${catMeta.short_zh} `}銷量排行（${yr}）`;
  }

  if (legend) {
    legend.innerHTML = salesData.categories
      .map(
        (c) =>
          `<span class="legend-item ${state.category !== "all" && state.category !== c.id ? "dim" : ""}"><span class="cat-dot" style="background:${c.color}"></span>${esc(c.short_zh)}</span>`
      )
      .join("");
  }

  const sorted = [...countries].sort(
    (a, b) => getCountryVal(b, yr, state.category) - getCountryVal(a, yr, state.category)
  );
  const maxVal = Math.max(...sorted.map((c) => getCountryVal(c, yr, state.category)), 1);

  wrap.innerHTML = sorted
    .map((c) => {
      const row = c.yearly[yr];
      const activeVal = getCountryVal(c, yr, state.category);
      const barPct = (activeVal / maxVal) * 100;
      const isSelected = state.countryIso === c.iso2;

      let segsHtml = "";
      if (state.category === "all") {
        segsHtml = salesData.categories
          .map((cat) => {
            const v = row[catKey(cat.id)] || 0;
            const w = activeVal > 0 ? (v / activeVal) * 100 : 0;
            return `<span class="sbar-seg" style="width:${w.toFixed(2)}%;background:${cat.color}" title="${cat.name_zh}: ${fmtWan(v)}台"></span>`;
          })
          .join("");
      } else {
        segsHtml = `<span class="sbar-seg" style="width:100%;background:${catMeta.color}"></span>`;
      }

      return `
        <button class="sbar-row ${isSelected ? "selected" : ""}" data-iso="${c.iso2}">
          <div class="sbar-country">
            <strong>${esc(c.name_zh)}</strong>
            <span class="sbar-ebike-tag">⚡ ${row.ebike_share_pct}%</span>
          </div>
          <div class="sbar-track">
            <div class="sbar-fill" style="width:${Math.max(barPct, 2).toFixed(1)}%">${segsHtml}</div>
          </div>
          <div class="sbar-num">${fmtWan(activeVal)}</div>
        </button>
      `;
    })
    .join("");

  wrap.querySelectorAll(".sbar-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      const iso = btn.dataset.iso;
      state.countryIso = state.countryIso === iso ? null : iso;
      if (state.countryIso) {
        const found = salesData.countries.find((c) => c.iso2 === iso);
        if (found) state.mapView = found.region;
      }
      renderAll();
    });
  });
}

function renderTrendChart() {
  const wrap = document.getElementById("sales-trend-chart");
  const mixWrap = document.getElementById("sales-cat-mix-block");
  const titleEl = document.getElementById("trend-chart-title");
  if (!wrap || !salesData) return;

  const countries = getFilteredCountries();
  const catMeta = getActiveCategoryMeta();
  const scopeLabel = state.countryIso
    ? countries[0]?.name_zh || ""
    : REGION_META[state.region].name_zh;

  if (titleEl) {
    titleEl.textContent = `${scopeLabel} · 2023–2025 ${catMeta.short_zh}銷量與電輔滲透率`;
  }

  const series = salesData.years.map((yr) => {
    const valK = countries.reduce((s, c) => s + getCountryVal(c, yr, state.category), 0);
    const totK = countries.reduce((s, c) => s + c.yearly[yr].total_k, 0);
    const ebK = countries.reduce((s, c) => s + c.yearly[yr].ebike_k, 0);
    return {
      yr,
      valWan: valK / 10,
      ebikePct: totK > 0 ? (ebK / totK) * 100 : 0,
    };
  });

  const W = 460;
  const H = 220;
  const padL = 48;
  const padR = 46;
  const padT = 26;
  const padB = 34;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const maxWan = Math.max(...series.map((s) => s.valWan), 1) * 1.18;
  const maxPct = Math.max(...series.map((s) => s.ebikePct), 20) * 1.25;

  const xs = series.map((_, i) => padL + (chartW / series.length) * (i + 0.5));
  const barW = 54;

  const linePts = series
    .map((s, i) => {
      const y = padT + chartH - (s.ebikePct / maxPct) * chartH;
      return `${xs[i].toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" class="trend-svg" role="img" aria-label="2023到2025年銷售與電輔滲透率趨勢圖">
      <!-- Horizontal gridlines -->
      ${[0, 0.33, 0.66, 1]
        .map((t) => {
          const y = padT + chartH * (1 - t);
          const lbl = (maxWan * t).toFixed(maxWan >= 100 ? 0 : 1);
          return `
            <line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="rgba(23,23,21,0.08)" stroke-dasharray="3,3" />
            <text x="${padL - 8}" y="${y + 4}" text-anchor="end" class="svg-axis-txt">${lbl}</text>`;
        })
        .join("")}
      <text x="${padL - 8}" y="14" text-anchor="end" class="svg-axis-unit">萬台</text>
      <text x="${W - padR + 8}" y="14" text-anchor="start" class="svg-axis-unit" fill="#c84b28">電輔%</text>

      <!-- Bars -->
      ${series
        .map((s, i) => {
          const bh = (s.valWan / maxWan) * chartH;
          const by = padT + chartH - bh;
          const isCur = s.yr === state.year;
          return `
            <g>
              <rect x="${xs[i] - barW / 2}" y="${by}" width="${barW}" height="${bh}" rx="5"
                fill="${isCur ? "#1d634f" : "#9dbcb1"}" />
              <text x="${xs[i]}" y="${by - 6}" text-anchor="middle" class="svg-val-txt">${s.valWan.toFixed(1)}萬</text>
              <text x="${xs[i]}" y="${H - 12}" text-anchor="middle" class="svg-yr-txt ${isCur ? "active" : ""}">${s.yr}</text>
            </g>`;
        })
        .join("")}

      <!-- e-Bike % line -->
      <polyline points="${linePts}" fill="none" stroke="#c84b28" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
      ${series
        .map((s, i) => {
          const y = padT + chartH - (s.ebikePct / maxPct) * chartH;
          return `
            <circle cx="${xs[i]}" cy="${y}" r="4.5" fill="#fff" stroke="#c84b28" stroke-width="2.4" />
            <text x="${xs[i] + 10}" y="${y - 8}" text-anchor="start" class="svg-line-txt">⚡${s.ebikePct.toFixed(1)}%</text>`;
        })
        .join("")}
    </svg>
  `;

  // Stacked horizontal 100% category strip for active year
  if (mixWrap) {
    const yr = state.year;
    const tot = countries.reduce((s, c) => s + c.yearly[yr].total_k, 0);
    const items = salesData.categories.map((cat) => {
      const v = countries.reduce((s, c) => s + (c.yearly[yr][catKey(cat.id)] || 0), 0);
      return { ...cat, v, pct: tot > 0 ? (v / tot) * 100 : 0 };
    });

    mixWrap.innerHTML = `
      <div class="mix-strip-head">
        <span>${yr} 年車種佔比組成條（100%）</span>
        <span>總計 ${fmtWan(tot)}台</span>
      </div>
      <div class="mix-strip-bar">
        ${items
          .map(
            (it) =>
              `<div class="mix-strip-seg" style="width:${it.pct.toFixed(2)}%;background:${it.color}" title="${it.name_zh}: ${fmtWan(it.v)}台 (${it.pct.toFixed(1)}%)"></div>`
          )
          .join("")}
      </div>
      <div class="mix-strip-labels">
        ${items
          .map(
            (it) =>
              `<span><i style="background:${it.color}"></i>${esc(it.short_zh)} <strong>${it.pct.toFixed(1)}%</strong></span>`
          )
          .join("")}
      </div>
    `;
  }
}

function buildPivotModel() {
  const countries = getFilteredCountries();
  const rowDim = state.pivotRow;
  const colDim = state.pivotCol;
  const metric = state.pivotMetric; // "volume" | "row_pct" | "revenue"

  // Determine columns
  let cols = [];
  if (colDim === "category") {
    cols = salesData.categories.map((c) => ({ id: c.id, label: `${c.icon} ${c.short_zh}` }));
  } else if (colDim === "year") {
    cols = salesData.years.map((y) => ({ id: y, label: `${y} 年` }));
  } else if (colDim === "region") {
    cols = salesData.regions.map((r) => ({ id: r.id, label: r.name_zh }));
  }

  // Value helper for a country × year × category
  function cellValueFor(countryList, yr, catId) {
    if (metric === "revenue") {
      // Proportional revenue attribution if filtered by category, else exact country revenue
      return countryList.reduce((s, c) => {
        const row = c.yearly[yr];
        if (!row) return s;
        if (!catId || catId === "all") return s + row.revenue_m_eur / 100; // 億€
        const share = row.total_k > 0 ? (row[catKey(catId)] || 0) / row.total_k : 0;
        // Weight e-bike ASP higher (~2.2x) vs traditional (~0.75x) is complex; keep transparent volume-proportional € attribution with note
        return s + (row.revenue_m_eur / 100) * share;
      }, 0);
    }
    return countryList.reduce((s, c) => s + getCountryVal(c, yr, catId) / 10, 0); // 萬台
  }

  const rows = [];

  function computeRowCells(rowSpec) {
    const rawVals = cols.map((col) => {
      const targetCountries =
        colDim === "region"
          ? rowSpec.countries.filter((c) => c.region === col.id)
          : rowSpec.countries;
      const targetYear = colDim === "year" ? col.id : rowSpec.year || state.year;
      const targetCat = colDim === "category" ? col.id : rowSpec.cat || state.category;
      return cellValueFor(targetCountries, targetYear, targetCat);
    });
    const total = rawVals.reduce((a, b) => a + b, 0);
    return { ...rowSpec, rawVals, total };
  }

  if (rowDim === "region_country") {
    const activeRegions = salesData.regions.filter((r) =>
      countries.some((c) => c.region === r.id)
    );
    activeRegions.forEach((reg) => {
      const regCountries = countries
        .filter((c) => c.region === reg.id)
        .sort((a, b) => getCountryVal(b, state.year, state.category) - getCountryVal(a, state.year, state.category));

      rows.push(
        computeRowCells({
          key: `reg-${reg.id}`,
          label: `${reg.name_zh}（區域小計）`,
          isGroup: true,
          countries: regCountries,
        })
      );
      regCountries.forEach((c) => {
        rows.push(
          computeRowCells({
            key: `c-${c.iso2}`,
            iso2: c.iso2,
            label: `${c.name_zh} (${c.iso2})`,
            sublabel: c.source_name,
            isChild: true,
            countries: [c],
          })
        );
      });
    });
  } else if (rowDim === "country") {
    const sorted = [...countries].sort(
      (a, b) => getCountryVal(b, state.year, state.category) - getCountryVal(a, state.year, state.category)
    );
    sorted.forEach((c) => {
      rows.push(
        computeRowCells({
          key: `c-${c.iso2}`,
          iso2: c.iso2,
          label: `${c.name_zh} (${c.iso2})`,
          sublabel: c.source_name,
          countries: [c],
        })
      );
    });
  } else if (rowDim === "category") {
    salesData.categories.forEach((cat) => {
      rows.push(
        computeRowCells({
          key: `cat-${cat.id}`,
          label: `${cat.icon} ${cat.name_zh}`,
          cat: cat.id,
          countries,
        })
      );
    });
  } else if (rowDim === "year") {
    salesData.years.forEach((yr) => {
      rows.push(
        computeRowCells({
          key: `yr-${yr}`,
          label: `${yr} 年度`,
          year: yr,
          countries,
        })
      );
    });
  }

  // Grand total across leaf rows (avoid double-counting group subtotal rows)
  const leafRows = rows.filter((r) => !r.isGroup);
  const grandCols = cols.map((_, idx) => leafRows.reduce((s, r) => s + r.rawVals[idx], 0));
  const grandTotal = grandCols.reduce((a, b) => a + b, 0);

  return { cols, rows, grandCols, grandTotal, metric };
}

function renderPivotTable() {
  const wrap = document.getElementById("sales-pivot-wrap");
  if (!wrap || !salesData) return;

  const model = buildPivotModel();
  const { cols, rows, grandCols, grandTotal, metric } = model;

  // Max leaf cell value for subtle heatmap tint
  const leafVals = rows.filter((r) => !r.isGroup).flatMap((r) => r.rawVals);
  const maxCell = Math.max(...leafVals, 0.001);

  const fmtCell = (val, rowTotal) => {
    if (metric === "row_pct") {
      const pct = rowTotal > 0 ? (val / rowTotal) * 100 : 0;
      return `${pct.toFixed(1)}%`;
    }
    if (metric === "revenue") {
      return `€${val.toFixed(1)}億`;
    }
    return `${val.toFixed(1)}`;
  };

  const unitBadge =
    metric === "row_pct"
      ? "單位：列佔比 %"
      : metric === "revenue"
        ? "單位：億歐元（依銷量佔比分攤）"
        : "單位：萬台";

  const colHeaderTitle =
    state.pivotRow === "region_country"
      ? "區域 / 國家"
      : state.pivotRow === "country"
        ? "國家"
        : state.pivotRow === "category"
          ? "自行車車種"
          : "年份";

  wrap.innerHTML = `
    <div class="pivot-meta-strip">
      <span>目前篩選：<strong>${esc(state.countryIso ? salesData.countries.find((c) => c.iso2 === state.countryIso)?.name_zh : REGION_META[state.region].name_zh)}</strong> · ${state.pivotCol === "year" || state.pivotRow === "year" ? "2023–2025 全年" : `${state.year} 年`} · ${esc(getActiveCategoryMeta().name_zh)}</span>
      <span class="pivot-unit-tag">${unitBadge}</span>
    </div>
    <table class="data-table pivot-table">
      <thead>
        <tr>
          <th>${colHeaderTitle}</th>
          ${cols.map((c) => `<th class="num-col">${esc(c.label)}</th>`).join("")}
          <th class="num-col pivot-total-col">${metric === "row_pct" ? "列合計" : "總計"}</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map((r) => {
            const trCls = [
              r.isGroup ? "pivot-group-row" : "",
              r.isChild ? "pivot-child-row" : "",
              r.iso2 && state.countryIso === r.iso2 ? "pivot-selected-row" : "",
              r.iso2 ? "clickable" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return `
              <tr class="${trCls}" ${r.iso2 ? `data-pivot-iso="${r.iso2}"` : ""}>
                <td>
                  <div class="pivot-row-lbl">${r.isChild ? '<span class="pivot-indent">└</span>' : ""}${esc(r.label)}</div>
                  ${r.sublabel ? `<div class="pivot-row-sub">${esc(r.sublabel)}</div>` : ""}
                </td>
                ${r.rawVals
                  .map((v) => {
                    const ratio =
                      metric === "row_pct"
                        ? r.total > 0
                          ? v / r.total
                          : 0
                        : Math.sqrt(Math.max(0, v)) / Math.sqrt(maxCell);
                    const alpha = r.isGroup ? 0 : Math.min(0.28, ratio * 0.26);
                    const bg = alpha > 0.01 ? `background:rgba(29,99,79,${alpha.toFixed(3)})` : "";
                    return `<td class="num-col mono-cell" style="${bg}">${fmtCell(v, r.total)}</td>`;
                  })
                  .join("")}
                <td class="num-col mono-cell pivot-total-col">${metric === "row_pct" ? "100.0%" : fmtCell(r.total, r.total)}</td>
              </tr>`;
          })
          .join("")}
      </tbody>
      <tfoot>
        <tr class="pivot-grand-row">
          <td><strong>全部總計（${state.pivotCol === "year" || state.pivotRow === "year" ? "跨年合計" : `${state.year} 年`}）</strong></td>
          ${grandCols.map((v) => `<td class="num-col mono-cell"><strong>${fmtCell(v, grandTotal)}</strong></td>`).join("")}
          <td class="num-col mono-cell pivot-total-col"><strong>${metric === "row_pct" ? "100.0%" : fmtCell(grandTotal, grandTotal)}</strong></td>
        </tr>
      </tfoot>
    </table>
  `;

  wrap.querySelectorAll("tr[data-pivot-iso]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const iso = tr.dataset.pivotIso;
      state.countryIso = state.countryIso === iso ? null : iso;
      if (state.countryIso) {
        const found = salesData.countries.find((c) => c.iso2 === iso);
        if (found) state.mapView = found.region;
      }
      renderAll();
    });
  });
}

function exportPivotCsv() {
  const model = buildPivotModel();
  const { cols, rows, grandCols, grandTotal, metric } = model;

  const fmtRaw = (v, tot) => {
    if (metric === "row_pct") return tot > 0 ? `${((v / tot) * 100).toFixed(1)}%` : "0.0%";
    return v.toFixed(2);
  };

  const header = ["維度", ...cols.map((c) => c.label.replace(/\s+/g, " ")), "總計"];
  const lines = [header.map((s) => `"${String(s).replaceAll('"', '""')}"`).join(",")];

  rows.forEach((r) => {
    const vals = [r.label, ...r.rawVals.map((v) => fmtRaw(v, r.total)), metric === "row_pct" ? "100.0%" : fmtRaw(r.total, r.total)];
    lines.push(vals.map((s) => `"${String(s).replaceAll('"', '""')}"`).join(","));
  });

  lines.push(
    ["總計", ...grandCols.map((v) => fmtRaw(v, grandTotal)), metric === "row_pct" ? "100.0%" : fmtRaw(grandTotal, grandTotal)]
      .map((s) => `"${String(s).replaceAll('"', '""')}"`)
      .join(",")
  );

  // UTF-8 BOM for clean Chinese display in Excel
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `global_bike_sales_pivot_${state.year}_${state.region}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderBenchmarksAndSources() {
  const bEl = document.getElementById("sales-benchmarks");
  const sEl = document.getElementById("sales-sources-card");
  if (!salesData) return;

  const { europe_total_benchmark: eu, taiwan_export_benchmark: tw, china_scope_note: cn } = salesData.meta;

  if (bEl) {
    bEl.innerHTML = `
      <div class="benchmark-card">
        <div class="benchmark-kicker">🇪🇺 歐洲全區基準 · ${esc(eu.source)}</div>
        <div class="benchmark-val">${(eu.eu27_uk_2025_total_k / 10).toLocaleString("zh-TW")} 萬台 <small>(2025 EU27+UK, ${eu.eu27_uk_2025_yoy_pct}%)</small></div>
        <p>${esc(eu.note_zh)}</p>
      </div>
      <div class="benchmark-card">
        <div class="benchmark-kicker">🇹🇼 台灣高階整車出口基準 · ${esc(tw.source)}</div>
        <div class="benchmark-val">傳統車 ${(tw.traditional_export_2024_k / 10).toFixed(1)} 萬 + 電輔 ${(tw.ebike_export_2024_k / 10).toFixed(1)} 萬 <small>(2024 出口)</small></div>
        <p>${esc(tw.note_zh)}</p>
      </div>
      <div class="benchmark-card">
        <div class="benchmark-kicker">🇨🇳 中國統計口徑透明聲明 · ${esc(cn.source)}</div>
        <div class="benchmark-val">排除國標電動機車 ${cn.gb17761_2024_domestic_m} 百萬台 <small>(GB 17761)</small></div>
        <p>${esc(cn.note_zh)}</p>
      </div>
    `;
  }

  if (sEl) {
    sEl.innerHTML = `
      <div class="sub-heading">官方統計資料來源與方法論說明</div>
      <p class="sales-method-text">${esc(salesData.meta.methodology_zh)}</p>
      <div class="sales-source-grid">
        ${salesData.countries
          .map(
            (c) => `
          <a class="sales-source-item" href="${esc(c.source_url)}" target="_blank" rel="noopener">
            <span class="src-country">${esc(c.name_zh)}</span>
            <span class="src-org">${esc(c.source_name)}</span>
            <span class="badge ${c.confidence === "official" ? "badge-measured" : "badge-inferred"}">
              ${c.confidence === "official" ? "官方年報" : "官方＋校準"}
            </span>
          </a>`
          )
          .join("")}
      </div>
    `;
  }
}

function bindPivotControls() {
  const rSel = document.getElementById("pivot-row-select");
  const cSel = document.getElementById("pivot-col-select");
  const mSel = document.getElementById("pivot-metric-select");
  const expBtn = document.getElementById("btn-export-pivot-csv");

  if (rSel) {
    rSel.value = state.pivotRow;
    rSel.addEventListener("change", (e) => {
      state.pivotRow = e.target.value;
      // Avoid identical row & col dimensions
      if (state.pivotRow === state.pivotCol) {
        state.pivotCol = state.pivotRow === "category" ? "year" : "category";
        if (cSel) cSel.value = state.pivotCol;
      }
      renderPivotTable();
    });
  }
  if (cSel) {
    cSel.value = state.pivotCol;
    cSel.addEventListener("change", (e) => {
      state.pivotCol = e.target.value;
      if (state.pivotRow === state.pivotCol) {
        state.pivotRow = state.pivotCol === "category" ? "region_country" : "category";
        if (rSel) rSel.value = state.pivotRow;
      }
      renderPivotTable();
    });
  }
  if (mSel) {
    mSel.value = state.pivotMetric;
    mSel.addEventListener("change", (e) => {
      state.pivotMetric = e.target.value;
      renderPivotTable();
    });
  }
  if (expBtn) {
    expBtn.addEventListener("click", exportPivotCsv);
  }
}

function renderWeeklyBulletins() {
  const pillEl = document.getElementById("sales-meta-pill");
  const cardEl = document.getElementById("sales-weekly-bulletins");
  const ws = salesData?.meta?.weekly_sync;

  if (pillEl && ws) {
    pillEl.textContent = `每週五 08:00 CST 自動撈取 · 上次更新 ${ws.last_synced_at_cst || salesData.meta.updated_at}`;
  }
  if (!cardEl) return;

  const allItems = ws?.latest_bulletins || [];
  const filtered =
    state.region === "all"
      ? allItems
      : allItems.filter((b) => b.region === state.region || (state.countryIso && b.country_iso2 === state.countryIso));
  const shown = filtered.length ? filtered : allItems;
  const regLabel = state.region === "all" ? "全球" : REGION_META[state.region].short_zh;
  const regNameMap = { europe: "歐洲", americas: "美洲", apac: "亞太", global: "全球" };

  cardEl.innerHTML = `
    <div class="sales-card-head">
      <div>
        <div class="sub-heading">每週五自動撈取：最新官方銷售與市場快訊（${esc(regLabel)}）</div>
        <div class="sales-card-sub">
          排程：<strong>${esc(ws?.schedule_zh || "每週五 08:00 CST 自動撈取更新")}</strong>
          ${ws?.last_synced_at_cst ? ` · 上次撈取：${esc(ws.last_synced_at_cst)}` : ""}
          ${ws?.next_friday_cst ? ` · 下次排程：${esc(ws.next_friday_cst)}` : ""}
        </div>
      </div>
      <span class="badge badge-measured">自動追蹤 ${ws?.sources_status?.length || 5} 大產業來源</span>
    </div>
    ${
      shown.length
        ? `<div class="bulletins-list">
            ${shown
              .slice(0, 10)
              .map(
                (b) => `
              <a class="bulletin-row" href="${esc(b.url)}" target="_blank" rel="noopener">
                <span class="bul-date">${esc(b.date || "—")}</span>
                <span class="bul-tag ${esc(b.region || "global")}">${esc(b.country_zh || regNameMap[b.region] || "全球")}</span>
                <span class="bul-title">${esc(b.title_zh || b.title)}</span>
                <span class="bul-metrics">${(b.metrics || []).map((m) => `<em>${esc(m)}</em>`).join("")}</span>
                <span class="bul-src">${esc(b.source_name || "")} ↗</span>
              </a>`
              )
              .join("")}
          </div>`
        : `<p class="sales-method-text">本週尚無新增市場快訊，系統將於每週五 08:00 CST 自動撈取更新。</p>`
    }
  `;
}

function renderAll() {
  renderSlicers();
  renderKpis();
  renderMapControls();
  renderMap();
  renderInspector();
  renderStackedBars();
  renderTrendChart();
  renderPivotTable();
  renderWeeklyBulletins();
}

export async function mountSalesDashboard(containerEl) {
  mountEl = containerEl;
  if (initialized) {
    renderMap();
    requestAnimationFrame(() => map3dInstance?.resize());
    return;
  }
  initialized = true;
  mountEl.innerHTML = buildShellHtml();

  try {
    const res = await fetch(`data/sales_market.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    salesData = await res.json();
  } catch (err) {
    mountEl.innerHTML = `<div class="section"><div class="sales-card">載入全球銷售資料庫失敗：${esc(err.message)}</div></div>`;
    initialized = false;
    return;
  }

  bindPivotControls();
  renderBenchmarksAndSources();
  renderAll();
}
