import { AlsoBikeViewer } from "./viewer3d.js";

const SPEC_LABELS = [
  ["brand", "品牌 (Brand)"],
  ["model_name", "車款型號 (Model)"],
  ["category_zh", "車款分類 (Category)"],
  ["frame_material", "車架材質 (Frame)"],
  ["wheel_size", "輪徑配置 (Wheels)"],
  ["travel_front", "前叉行程 (Front Travel)"],
  ["travel_rear", "後避震行程 (Rear Travel)"],
  ["motor", "電輔馬達 (Motor)"],
  ["torque", "最大扭力 (Torque)"],
  ["battery", "電池容量 (Battery)"],
  ["display", "控制顯示器 (Display)"],
  ["fork", "前叉規格 (Fork)"],
  ["rear_shock", "後避震器 (Rear Shock)"],
  ["drivetrain", "傳動系統 (Drivetrain)"],
  ["brakes", "煞車系統 (Brakes)"],
  ["seatpost", "座管 (Seatpost)"],
  ["tire_clearance", "最大胎寬 (Tire Clearance)"],
  ["weight", "重量 (Weight)"],
  ["price", "參考售價 (Price)"],
];

const GEO_LABELS = {
  head_angle_deg: ["頭管角度 (Head Angle)", "°"],
  seat_angle_deg: ["立管角度 (Seat Angle)", "°"],
  reach_mm: ["前伸量 (Reach)", "mm"],
  stack_mm: ["堆疊高度 (Stack)", "mm"],
  wheelbase_mm: ["前後軸距 (Wheelbase)", "mm"],
  chainstay_mm: ["後下叉長度 (Chainstay)", "mm"],
  bb_drop_mm: ["五通下沉量 (BB Drop)", "mm"],
  head_tube_mm: ["頭管長度 (Head Tube)", "mm"],
  seat_tube_mm: ["立管長度 (Seat Tube)", "mm"],
  travel_front_mm: ["前避震行程 (Front Travel)", "mm"],
  travel_rear_mm: ["後避震行程 (Rear Travel)", "mm"],
  wheel_front_in: ["前輪徑 (Front Wheel)", "in"],
  wheel_rear_in: ["後輪徑 (Rear Wheel)", "in"],
  tire_width_mm: ["建模胎寬 (Tire Width)", "mm"],
  rotor_front_mm: ["前碟盤直徑 (Front Rotor)", "mm"],
  rotor_rear_mm: ["後碟盤直徑 (Rear Rotor)", "mm"],
};

let currentReport = null;
let selectedBikeSlug = null;
let activeIntelTab = "articles";
let viewer = null;

function esc(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toISOString().slice(0, 10);
  } catch {
    return String(iso).slice(0, 10);
  }
}

function provenanceBadge(code) {
  if (code === "measured_table") return '<span class="badge badge-measured">實測/官方幾何表</span>';
  if (code === "measured_spec") return '<span class="badge badge-measured">官方規格數據</span>';
  if (code === "measured_text") return '<span class="badge badge-measured">報導原文數據</span>';
  return '<span class="badge badge-inferred">級距比例推估</span>';
}

function signalBadge(signal) {
  if (signal === "召回警示") return `<span class="badge badge-danger">${esc(signal)}</span>`;
  if (signal === "產品評測") return `<span class="badge badge-measured">${esc(signal)}</span>`;
  if (signal === "新品/動態") return `<span class="badge badge-accent">${esc(signal)}</span>`;
  return `<span class="badge badge-neutral">${esc(signal)}</span>`;
}

async function init() {
  viewer = new AlsoBikeViewer(
    document.getElementById("viewer-canvas-wrap"),
    document.getElementById("viewer-loading")
  );
  bindStaticControls();

  try {
    const idxResp = await fetch("data/index.json", { cache: "no-store" });
    if (idxResp.ok) {
      const idxData = await idxResp.json();
      const sel = document.getElementById("archive-select");
      sel.innerHTML = (idxData.archives || [])
        .map(
          (a) =>
            `<option value="${esc(a.file)}">${esc(a.date)} (${a.complete_bikes} 整車 / ${a.total_articles} 篇)</option>`
        )
        .join("");
      sel.addEventListener("change", () => loadReport(sel.value));
    }
  } catch (e) {
    console.warn("Archive index optional:", e);
  }

  await loadReport("data/latest.json");
}

async function loadReport(url) {
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    document.getElementById("generated-meta").textContent = "載入資料失敗，請確認 pipeline 已產生 data/latest.json";
    return;
  }
  currentReport = await resp.json();
  renderMastheadSources();
  renderConclusions();
  renderBikeSelector();
  if (currentReport.complete_bikes && currentReport.complete_bikes.length > 0) {
    // Prefer bike with highest measured geometry ratio as default showcase
    const sorted = [...currentReport.complete_bikes].sort((a, b) => (b.measured_ratio || 0) - (a.measured_ratio || 0));
    selectBike(sorted[0].slug);
  }
  renderIntelTables();
}

function renderMastheadSources() {
  const chipsEl = document.getElementById("source-chips");
  chipsEl.innerHTML = (currentReport.sources || [])
    .map(
      (s) => `
      <a class="source-chip" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.focus)}">
        <span class="status-dot ${s.status === "ok" ? "" : "err"}"></span>
        <strong>${esc(s.name)}</strong>
        <span class="cnt">${s.item_count} 則</span>
      </a>`
    )
    .join("");
  document.getElementById("generated-meta").textContent =
    `更新時間：${currentReport.generated_at_cst || currentReport.date} · 每日自動排程 (07:00 CST)`;
}

function renderConclusions() {
  const c = currentReport.summary.counts;
  document.getElementById("kpi-strip").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">五站抓取總篇數</div><div class="kpi-value">${c.total_articles}</div></div>
    <div class="kpi-card"><div class="kpi-label">整車 3D 逆向重建</div><div class="kpi-value accent">${c.complete_bikes}</div></div>
    <div class="kpi-card"><div class="kpi-label">活躍追蹤品牌數</div><div class="kpi-value">${c.brands_tracked}</div></div>
    <div class="kpi-card"><div class="kpi-label">賽事與展會動態</div><div class="kpi-value">${c.events_tracked}</div></div>
    <div class="kpi-card"><div class="kpi-label">產品評測 / 新品</div><div class="kpi-value">${c.reviews + c.launches}</div></div>
  `;

  document.getElementById("conclusions-grid").innerHTML = (currentReport.summary.conclusions || [])
    .map(
      (item) => `
      <div class="conclusion-card">
        <span class="conclusion-tag">${esc(item.tag)}</span>
        <h3>${esc(item.title)}</h3>
        <p>${esc(item.detail)}</p>
      </div>`
    )
    .join("");
}

function renderBikeSelector() {
  const strip = document.getElementById("bike-selector-strip");
  const bikes = currentReport.complete_bikes || [];
  if (!bikes.length) {
    strip.innerHTML = `<div class="conclusion-card">本日 5 站報導中尚無新增整車評測或發布。</div>`;
    return;
  }
  strip.innerHTML = bikes
    .map((b) => {
      const m = b.model_3d || {};
      const pct = Math.round((b.measured_ratio || 0) * 100);
      return `
        <button class="bike-pick-card ${b.slug === selectedBikeSlug ? "active" : ""}" data-slug="${esc(b.slug)}">
          <img class="bike-pick-thumb" src="${esc(b.hero_image || "")}" alt="${esc(b.model_name)}" loading="lazy" />
          <div class="bike-pick-body">
            <div class="bike-pick-meta">
              <span>${esc(b.source_name)}</span>
              <span>QA ${m.qa_pass_count || 0}/${m.qa_total_count || 8}</span>
            </div>
            <div class="bike-pick-title">${esc(b.model_name)}</div>
            <div class="bike-pick-cat">${esc(b.category_zh)}</div>
            <div class="bike-pick-badges">
              <span class="badge ${pct >= 50 ? "badge-measured" : "badge-inferred"}">實測幾何 ${pct}%</span>
              ${b.is_ebike ? '<span class="badge badge-accent">e-Bike</span>' : ""}
              ${b.full_suspension ? '<span class="badge badge-neutral">Full-Sus</span>' : '<span class="badge badge-neutral">Rigid/HT</span>'}
            </div>
          </div>
        </button>`;
    })
    .join("");

  strip.querySelectorAll(".bike-pick-card").forEach((btn) => {
    btn.addEventListener("click", () => selectBike(btn.dataset.slug));
  });
}

function selectBike(slug) {
  const bike = (currentReport.complete_bikes || []).find((b) => b.slug === slug);
  if (!bike) return;
  selectedBikeSlug = slug;

  // Update active card highlight
  document.querySelectorAll(".bike-pick-card").forEach((el) => {
    el.classList.toggle("active", el.dataset.slug === slug);
  });

  const m = bike.model_3d || {};
  const geo = bike.geometry_resolved || {};
  const specs = bike.specs || {};

  // Header
  document.getElementById("wb-badges").innerHTML = `
    <span class="badge badge-accent">${esc(bike.brand)}</span>
    <span class="badge badge-neutral">${esc(bike.category_zh)}</span>
    <span class="badge badge-neutral">來源：${esc(bike.source_name)}</span>
    <span class="badge badge-measured">建模尺碼：Size ${esc(bike.default_size || "L")}</span>
  `;
  document.getElementById("wb-title").textContent = bike.model_name;
  document.getElementById("wb-actions").innerHTML = `
    <a class="btn btn-primary" href="${esc(m.glb_file)}" download>下載 3D 模型 (.glb)</a>
    <a class="btn btn-accent" href="${esc(m.blender_script)}" download>ALSO Blender 腳本 (.py)</a>
    <a class="btn" href="${esc(m.manifest_file)}" target="_blank" rel="noopener">QA Manifest (.json)</a>
    <a class="btn" href="${esc(bike.url)}" target="_blank" rel="noopener">原始報導 ↗</a>
  `;

  // HUD
  document.getElementById("hud-model-info").textContent =
    `${bike.model_name} · ${m.object_count || 0} 分件 · ${(m.total_faces || 0).toLocaleString()} 三角面`;
  document.getElementById("hud-qa-badge").textContent =
    `ALSO QA: ${m.qa_pass_count || 0}/${m.qa_total_count || 8} PASS`;
  document.getElementById("hud-geo-legend").innerHTML = `
    <span>WB ${geo.wheelbase_mm}mm</span>
    <span>Reach ${geo.reach_mm}mm</span>
    <span>Stack ${geo.stack_mm}mm</span>
    <span>HTA ${geo.head_angle_deg}°</span>
    <span>STA ${geo.seat_angle_deg}°</span>
  `;
  document.getElementById("hud-sha").textContent =
    `SHA256: ${(m.glb_sha256 || "").slice(0, 14)}… (${Math.round((m.glb_bytes || 0) / 1024)} KB)`;

  // Load 3D GLB into Three.js ALSO Studio Viewer
  if (viewer && m.glb_file) {
    viewer.loadBike(m.glb_file, m.anchors_3d, geo);
  }

  // Reference Photo Gallery
  const gallery = bike.gallery && bike.gallery.length ? bike.gallery : [{ url: bike.hero_image, alt: bike.model_name }];
  const mainImg = document.getElementById("ref-photo-main");
  mainImg.src = gallery[0]?.url || "";
  mainImg.alt = gallery[0]?.alt || bike.model_name;

  const thumbsEl = document.getElementById("ref-photo-thumbs");
  thumbsEl.innerHTML = gallery
    .map(
      (g, i) =>
        `<img class="photo-thumb ${i === 0 ? "active" : ""}" src="${esc(g.url)}" alt="${esc(g.alt || bike.model_name)}" data-idx="${i}" loading="lazy" />`
    )
    .join("");
  thumbsEl.querySelectorAll(".photo-thumb").forEach((img) => {
    img.addEventListener("click", () => {
      const idx = Number(img.dataset.idx);
      mainImg.src = gallery[idx].url;
      thumbsEl.querySelectorAll(".photo-thumb").forEach((t, ti) => t.classList.toggle("active", ti === idx));
    });
  });

  // Spec KV Table
  const mergedSpecObj = {
    brand: bike.brand,
    model_name: bike.model_name,
    category_zh: bike.category_zh,
    ...specs,
  };
  document.getElementById("wb-spec-tbody").innerHTML = SPEC_LABELS.filter(([k]) => mergedSpecObj[k])
    .map(([k, label]) => `<tr><th>${esc(label)}</th><td>${esc(mergedSpecObj[k])}</td></tr>`)
    .join("");

  // Bottom Tab 1: Geometry & Provenance
  renderGeometryTab(bike);
  // Bottom Tab 2: ALSO QA Manifest
  renderQaTab(bike);
}

function renderGeometryTab(bike) {
  const container = document.getElementById("wbtab-geometry");
  const gt = bike.geometry_table || {};
  let multiSizeHtml = "";

  if (gt.sizes && gt.sizes.length && gt.raw_rows && gt.raw_rows.length) {
    multiSizeHtml = `
      <h4 class="sub-heading">來源原廠多尺碼幾何表 (Scraped Multi-Size Geometry Table)</h4>
      <div class="table-wrap" style="margin-bottom: 22px;">
        <table class="data-table">
          <thead>
            <tr>
              <th>幾何項目</th>
              ${gt.sizes.map((s) => `<th>Size ${esc(s)}${s === gt.default_size ? " ★" : ""}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${gt.raw_rows
              .map(
                (r) => `
                <tr>
                  <td><strong>${esc(r.label)}</strong></td>
                  ${gt.sizes.map((s) => `<td class="mono">${esc(r.values[s] || "—")}</td>`).join("")}
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  const geo = bike.geometry_resolved || {};
  const prov = bike.geometry_provenance || {};
  const rowsHtml = Object.entries(GEO_LABELS)
    .map(([key, [label, unit]]) => {
      const val = geo[key];
      const provKey = key.startsWith("wheel_") ? "wheel_size" : key.startsWith("rotor_") ? "rotors_mm" : key;
      return `
        <tr>
          <td><strong>${esc(label)}</strong></td>
          <td class="mono">${val !== undefined ? `${val} ${unit}` : "—"}</td>
          <td>${provenanceBadge(prov[provKey])}</td>
        </tr>`;
    })
    .join("");

  container.innerHTML = `
    ${multiSizeHtml}
    <h4 class="sub-heading">3D 逆向工程輸入參數與資料溯源 (Resolved 3D Input Parameters — Size ${esc(bike.default_size || "L")})</h4>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>幾何參數</th><th>3D 建模數值</th><th>數據溯源等級</th></tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;
}

function renderQaTab(bike) {
  const container = document.getElementById("wbtab-qa");
  const m = bike.model_3d || {};
  const checks = m.qa_checks || [];
  const quals = m.scope_qualifications || [];

  container.innerHTML = `
    <h4 class="sub-heading">ALSO_BIKE 規範幾何公差檢核表 (Automated Geometric QA Checks)</h4>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>檢核項目</th><th>目標規格 (Target)</th><th>3D 實測值 (Measured)</th><th>公差 (Delta)</th><th>狀態</th></tr>
        </thead>
        <tbody>
          ${checks
            .map(
              (q) => `
              <tr>
                <td><strong>${esc(q.check)}</strong></td>
                <td class="mono">${esc(q.target)}</td>
                <td class="mono">${esc(q.measured)}</td>
                <td class="mono">${esc(q.delta)}</td>
                <td><span class="badge ${q.status === "PASS" ? "badge-measured" : "badge-inferred"}">${esc(q.status)}</span></td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>
    <div class="scope-box">
      <h4>Scope Qualifications · 逆向工程範圍與精度聲明（對齊 ALSO_BIKE FINAL_INTEGRATED_REVIEW 規範）</h4>
      <ul>
        ${quals.map((q) => `<li>${esc(q)}</li>`).join("")}
      </ul>
    </div>
  `;
}

function renderIntelTables() {
  renderArticlesTable();
  renderBrandsTable();
  renderEventsTable();
}

function renderArticlesTable() {
  const q = (document.getElementById("filter-search").value || "").trim().toLowerCase();
  const src = document.getElementById("filter-source").value;
  const bucket = document.getElementById("filter-bucket").value;

  const list = (currentReport.articles || []).filter((a) => {
    if (src !== "all" && a.source_id !== src) return false;
    if (bucket !== "all" && a.classification.bucket !== bucket) return false;
    if (q) {
      const blob = `${a.title} ${a.takeaway_zh} ${a.source_name} ${(a.brands || []).map((b) => b.name).join(" ")} ${(a.events || []).map((e) => e.name).join(" ")}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });

  const panel = document.getElementById("intel-panel-articles");
  if (!list.length) {
    panel.innerHTML = `<div style="padding: 28px; color: var(--ink-muted); text-align: center;">查無符合篩選條件的情報資料。</div>`;
    return;
  }

  panel.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:92px;">日期</th>
          <th style="width:128px;">來源 / 訊號</th>
          <th style="width:160px;">涉及品牌與賽事</th>
          <th>中文情報結論與原文標題</th>
          <th style="width:96px;">操作</th>
        </tr>
      </thead>
      <tbody>
        ${list
          .map((a) => {
            const brandTags = (a.brands || [])
              .slice(0, 3)
              .map((b) => `<span class="badge badge-neutral">${esc(b.name)}</span>`)
              .join("");
            const eventTags = (a.events || [])
              .slice(0, 2)
              .map((e) => `<span class="badge badge-accent">${esc(e.kind)}</span>`)
              .join("");
            const bikeBtn = a.bike_slug
              ? `<button class="btn btn-accent jump-bike-btn" data-slug="${esc(a.bike_slug)}" style="padding:4px 9px;font-size:11px;">檢視 3D</button>`
              : `<a class="btn" href="${esc(a.url)}" target="_blank" rel="noopener" style="padding:4px 9px;font-size:11px;">原文 ↗</a>`;
            return `
              <tr>
                <td class="mono">${fmtDate(a.published_at)}</td>
                <td>
                  <div style="font-weight:600;margin-bottom:4px;">${esc(a.source_name)}</div>
                  ${signalBadge(a.classification.signal)}
                </td>
                <td>
                  <div class="tag-list">${brandTags}${eventTags || (brandTags ? "" : '<span class="badge badge-neutral">綜合</span>')}</div>
                </td>
                <td>
                  <a class="article-title-link" href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>
                  <div class="takeaway-line">${esc(a.takeaway_zh)}</div>
                </td>
                <td>${bikeBtn}</td>
              </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  `;

  panel.querySelectorAll(".jump-bike-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectBike(btn.dataset.slug);
      document.getElementById("workbench-section").scrollIntoView({ behavior: "smooth" });
    });
  });
}

function renderBrandsTable() {
  const brands = currentReport.summary.top_brands || [];
  document.getElementById("intel-panel-brands").innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:60px;">#</th>
          <th style="width:170px;">品牌名稱</th>
          <th style="width:130px;">定位分類</th>
          <th style="width:90px;">提及次數</th>
          <th style="width:180px;">今日動態訊號</th>
          <th>相關代表報導</th>
        </tr>
      </thead>
      <tbody>
        ${brands
          .map(
            (b, i) => `
            <tr>
              <td class="mono">${String(i + 1).padStart(2, "0")}</td>
              <td><strong>${esc(b.name)}</strong></td>
              <td><span class="badge badge-neutral">${esc(b.type)}</span></td>
              <td class="mono"><strong>${b.mentions}</strong></td>
              <td><div class="tag-list">${(b.signals || []).map((s) => signalBadge(s)).join("")}</div></td>
              <td>
                ${(b.articles || [])
                  .slice(0, 2)
                  .map(
                    (a) =>
                      `<div style="margin-bottom:4px;"><a class="article-title-link" style="font-size:12.5px;margin:0;" href="${esc(a.url)}" target="_blank" rel="noopener">[${esc(a.source)}] ${esc(a.title)}</a></div>`
                  )
                  .join("")}
              </td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderEventsTable() {
  const events = currentReport.summary.events || [];
  document.getElementById("intel-panel-events").innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:240px;">賽事／展會／活動名稱</th>
          <th style="width:130px;">活動類別</th>
          <th style="width:140px;">報導媒體</th>
          <th style="width:80px;">篇數</th>
          <th>重點報導摘要</th>
        </tr>
      </thead>
      <tbody>
        ${events
          .map(
            (e) => `
            <tr>
              <td><strong>${esc(e.name)}</strong></td>
              <td><span class="badge badge-accent">${esc(e.kind)}</span></td>
              <td><div class="tag-list">${(e.sources || []).map((s) => `<span class="badge badge-neutral">${esc(s)}</span>`).join("")}</div></td>
              <td class="mono"><strong>${e.mentions}</strong></td>
              <td>
                ${(e.headlines || [])
                  .map(
                    (h) =>
                      `<div style="margin-bottom:4px;"><a class="article-title-link" style="font-size:12.5px;margin:0;" href="${esc(h.url)}" target="_blank" rel="noopener">[${esc(h.source)}] ${esc(h.title)}</a></div>`
                  )
                  .join("")}
              </td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function bindStaticControls() {
  // Camera preset buttons
  document.querySelectorAll("#cam-presets .tool-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#cam-presets .tool-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      viewer?.setCameraPreset(btn.dataset.cam);
    });
  });

  // Render modes (PBR / Clay / Wireframe)
  const modeBtns = [
    ["btn-mode-pbr", "pbr"],
    ["btn-mode-clay", "clay"],
    ["btn-mode-wire", "wire"],
  ];
  modeBtns.forEach(([id, mode]) => {
    document.getElementById(id).addEventListener("click", () => {
      modeBtns.forEach(([bid]) => document.getElementById(bid).classList.remove("active"));
      document.getElementById(id).classList.add("active");
      viewer?.setRenderMode(mode);
    });
  });

  // CAD overlay toggle
  const cadBtn = document.getElementById("btn-toggle-cad");
  cadBtn.addEventListener("click", () => {
    const next = !cadBtn.classList.contains("active");
    cadBtn.classList.toggle("active", next);
    viewer?.setCadOverlay(next);
  });

  // Ortho / Persp toggle
  const projBtn = document.getElementById("btn-toggle-proj");
  projBtn.addEventListener("click", () => {
    const next = !projBtn.classList.contains("active");
    projBtn.classList.toggle("active", next);
    projBtn.textContent = next ? "Ortho ✓" : "Ortho";
    viewer?.setProjection(next);
  });

  // Workbench bottom tabs
  document.querySelectorAll(".wb-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".wb-tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.wbtab;
      document.getElementById("wbtab-geometry").classList.toggle("hidden", target !== "geometry");
      document.getElementById("wbtab-qa").classList.toggle("hidden", target !== "qa");
    });
  });

  // Intelligence tabs
  document.querySelectorAll(".intel-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".intel-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeIntelTab = btn.dataset.tab;
      document.getElementById("intel-panel-articles").classList.toggle("hidden", activeIntelTab !== "articles");
      document.getElementById("intel-panel-brands").classList.toggle("hidden", activeIntelTab !== "brands");
      document.getElementById("intel-panel-events").classList.toggle("hidden", activeIntelTab !== "events");
      document.getElementById("article-filters").style.display = activeIntelTab === "articles" ? "flex" : "none";
    });
  });

  // Filters
  ["filter-search", "filter-source", "filter-bucket"].forEach((id) => {
    document.getElementById(id).addEventListener("input", renderArticlesTable);
    document.getElementById(id).addEventListener("change", renderArticlesTable);
  });
}

init();
