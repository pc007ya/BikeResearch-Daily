import { BikeStudioViewer } from "./viewer3d.js?v=2.2.0";

const SPEC_LABELS = [
  ["brand", "品牌"],
  ["model_name", "車款型號"],
  ["category_zh", "車款分類"],
  ["frame_material", "車架材質"],
  ["wheel_size", "輪徑配置"],
  ["travel_front", "前叉行程"],
  ["travel_rear", "後避震行程"],
  ["motor", "電輔馬達"],
  ["torque", "最大扭力"],
  ["battery", "電池容量"],
  ["display", "控制顯示器"],
  ["fork", "前叉規格"],
  ["rear_shock", "後避震器"],
  ["drivetrain", "傳動系統"],
  ["brakes", "煞車系統"],
  ["wheels", "輪組規格"],
  ["tires", "輪胎規格"],
  ["seatpost", "座管規格"],
  ["tire_clearance", "最大胎寬容納"],
  ["weight", "重量"],
  ["price", "參考售價"],
];

const SHARE_PALETTE = [
  "#c84b28",
  "#1d634f",
  "#2b5b84",
  "#b87a1e",
  "#6e4b8a",
  "#4c6a5a",
  "#8c5a3c",
];

const GEO_LABELS = {
  head_angle_deg: ["頭管角度 (HTA)", "°"],
  seat_angle_deg: ["立管角度 (STA)", "°"],
  reach_mm: ["前伸量 (Reach)", "mm"],
  stack_mm: ["堆疊高度 (Stack)", "mm"],
  wheelbase_mm: ["前後軸距 (Wheelbase)", "mm"],
  chainstay_mm: ["後下叉長度 (Chainstay)", "mm"],
  bb_drop_mm: ["五通下沉量 (BB Drop)", "mm"],
  head_tube_mm: ["頭管長度", "mm"],
  seat_tube_mm: ["立管長度", "mm"],
  travel_front_mm: ["前避震行程", "mm"],
  travel_rear_mm: ["後避震行程", "mm"],
  wheel_front_in: ["前輪徑", "吋"],
  wheel_rear_in: ["後輪徑", "吋"],
  tire_width_mm: ["建模胎寬", "mm"],
  rotor_front_mm: ["前碟盤直徑", "mm"],
  rotor_rear_mm: ["後碟盤直徑", "mm"],
};

const ALL_SOURCES_LINKS = [
  ["Bikerumor", "https://bikerumor.com/"],
  ["Pinkbike", "https://www.pinkbike.com/"],
  ["Cyclingnews", "https://www.cyclingnews.com/"],
  ["eMTB-News.de", "https://www.emtb-news.de/news/"],
  ["E-MOUNTAINBIKE", "https://ebike-mtb.com/en/"],
  ["road.cc", "https://road.cc/"],
  ["美騎網 Biketo", "https://www.biketo.com/"],
];

let currentReport = null;
let selectedBikeSlug = null;
let activeIntelTab = "articles";
let viewer = null;
let slidesData = [];
let currentSlideIdx = 0;

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
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return String(iso).slice(0, 10);
  }
}

function provenanceBadge(code) {
  if (code === "measured_table") return '<span class="badge badge-measured">實測／官方幾何表</span>';
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

function langTag(lang) {
  if (lang === "de") return "德文→繁中";
  if (String(lang || "").toLowerCase() === "zh-cn") return "簡中→繁中";
  return "英文→繁中";
}

function allSourcesFooterHtml() {
  return ALL_SOURCES_LINKS.map(
    ([name, url]) => `<a href="${url}" target="_blank" rel="noopener">${name}</a>`
  ).join("、");
}

function motorBadgeHtml(bike) {
  if (!bike.is_ebike) return "";
  const compMotor = bike.components?.motor?.brand;
  if (compMotor) {
    return `<span class="badge badge-motor" title="${esc(bike.components.motor.model || compMotor)}">⚡ 電機：${esc(compMotor)}</span>`;
  }
  return '<span class="badge badge-accent">⚡ 電輔車</span>';
}

function bikeCompChipsHtml(bike) {
  const comps = bike.components || {};
  const pairs = [
    ["fork", "前叉"],
    ["drivetrain", "變速"],
    ["tires", "輪胎"],
    ["wheels", "輪組"],
    ["brakes", "煞車"],
  ];
  const chips = pairs
    .filter(([k]) => comps[k]?.brand)
    .map(([k, lbl]) => `<span class="comp-chip" title="${esc(comps[k].model || comps[k].brand)}">${lbl} <strong>${esc(comps[k].brand)}</strong></span>`);
  if (!chips.length) return "";
  return `<div class="bike-comp-strip">${chips.join("")}</div>`;
}

let activeTopPage = "daily";

async function switchTopPage(page, { updateHash = true } = {}) {
  const next = page === "sales" ? "sales" : page === "seo" ? "seo" : "daily";
  activeTopPage = next;
  document.body.dataset.page = next;

  const salesMain = document.getElementById("page-sales");
  const seoMain = document.getElementById("page-seo");
  const statusEl = document.getElementById("top-page-status");
  const titleEl = document.getElementById("brand-title");
  const subEl = document.getElementById("brand-sub");
  const slideOverlay = document.getElementById("slide-deck-overlay");

  document.querySelectorAll("#top-page-tabs .top-page-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === next);
  });

  document.querySelectorAll(".daily-only").forEach((el) => {
    el.classList.toggle("hidden", next !== "daily");
  });
  document.querySelectorAll(".sales-only").forEach((el) => {
    el.classList.toggle("hidden", next !== "sales");
  });
  document.querySelectorAll(".seo-only").forEach((el) => {
    el.classList.toggle("hidden", next !== "seo");
  });

  if (next !== "daily" && slideOverlay) {
    slideOverlay.classList.add("hidden");
  }

  if (titleEl) {
    titleEl.textContent =
      next === "sales"
        ? "全球自行車銷售樞紐與地圖分析"
        : next === "seo"
          ? "全球自行車 SEO 關鍵字趨勢分析"
          : "全球自行車每日中文情報站";
  }
  if (subEl) {
    subEl.textContent =
      next === "sales"
        ? "歐洲各國・美洲（美加）・亞太區域｜電動車／登山車／公路車／城市車樞紐視覺化"
        : next === "seo"
          ? "每日更新各地區 Google 熱搜長尾詞｜7 日・30 日車種與賽事關鍵字趨勢表"
          : "追蹤品牌、焦點、趨勢及熱門話題";
  }
  if (statusEl) {
    statusEl.textContent =
      next === "sales"
        ? "模式：全球銷售樞紐與地圖分析（2023–2025）"
        : next === "seo"
          ? "模式：每日 SEO 關鍵字趨勢（7日／30日）"
          : "模式：每日產業情報與 3D 逆向實驗室";
  }

  if (updateHash) {
    const targetHash = next === "sales" ? "#sales" : next === "seo" ? "#seo" : "#daily";
    if (window.location.hash !== targetHash) {
      history.replaceState(null, "", targetHash);
    }
  }

  if (next === "sales" && salesMain) {
    const mod = await import("./sales_dashboard.js?v=2.4.1");
    await mod.mountSalesDashboard(salesMain);
  } else if (next === "seo" && seoMain) {
    const mod = await import("./seo_dashboard.js?v=2.5.0");
    await mod.mountSeoDashboard(seoMain);
  } else if (next === "daily") {
    requestAnimationFrame(() => viewer?._handleResize?.());
  }
}

async function init() {
  document.querySelectorAll("#top-page-tabs .top-page-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchTopPage(btn.dataset.page);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  window.addEventListener("hashchange", () => {
    if (window.location.hash === "#sales") {
      switchTopPage("sales", { updateHash: false });
    } else if (window.location.hash === "#seo") {
      switchTopPage("seo", { updateHash: false });
    } else if (window.location.hash === "#daily") {
      switchTopPage("daily", { updateHash: false });
    }
  });

  if (window.location.hash.startsWith("#sales")) {
    switchTopPage("sales", { updateHash: false });
  } else if (window.location.hash.startsWith("#seo")) {
    switchTopPage("seo", { updateHash: false });
  }

  viewer = new BikeStudioViewer(
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
            `<option value="${esc(a.file)}">${esc(a.date)}（${a.complete_bikes} 整車 / ${a.total_articles} 篇）</option>`
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

  // Update PPTX download link
  const pptxUrl = currentReport.pptx_file || "data/daily_briefing.pptx";
  document.getElementById("btn-download-pptx").href = pptxUrl;
  document.getElementById("btn-slide-pptx").href = pptxUrl;

  renderMastheadSources();
  renderConclusions();
  renderComponentShares();
  renderBikeSelector();
  if (currentReport.complete_bikes && currentReport.complete_bikes.length > 0) {
    const sorted = [...currentReport.complete_bikes].sort((a, b) => {
      const ca = a.model_3d?.photo_calibration ? 1 : 0;
      const cb = b.model_3d?.photo_calibration ? 1 : 0;
      if (cb !== ca) return cb - ca;
      return (b.measured_ratio || 0) - (a.measured_ratio || 0);
    });
    selectBike(sorted[0].slug);
  }
  renderIntelTables();
  buildWebSlides();
}

function newBadgeHtml(item) {
  if (!item?.is_new) return "";
  const prev = currentReport?.compared_with_date;
  const tip = prev ? `較前一日 (${prev}) 新增` : "當日新增";
  return `<span class="badge badge-new" title="${esc(tip)}">NEW</span>`;
}

function renderMastheadSources() {
  const chipsEl = document.getElementById("source-chips");
  chipsEl.innerHTML = (currentReport.sources || [])
    .map(
      (s) => `
      <a class="source-chip" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.focus)}">
        <span class="status-dot ${s.status === "ok" ? "" : "err"}"></span>
        <strong>${esc(s.name)}</strong>
        <span class="cnt">${s.item_count} 則 · ${langTag(s.lang)}</span>
      </a>`
    )
    .join("");
  const winStr =
    currentReport.window_start_cst && currentReport.window_end_cst
      ? ` · 僅保留近 ${currentReport.retention_days || 7} 日（${currentReport.window_start_cst}～${currentReport.window_end_cst}）`
      : " · 僅保留近 7 日新聞";
  const newCnt = currentReport.new_articles_count ?? (currentReport.articles || []).filter((a) => a.is_new).length;
  const newStr = newCnt > 0 ? ` · 較前日新增 ${newCnt} 則` : "";
  document.getElementById("generated-meta").textContent =
    `更新時間：${currentReport.generated_at_cst || currentReport.date}${winStr}${newStr}`;
}

function renderConclusions() {
  const c = currentReport.summary.counts;
  const newArt = currentReport.new_articles_count ?? c.new_articles ?? (currentReport.articles || []).filter((a) => a.is_new).length;
  const newBikes = currentReport.new_bikes_count ?? c.new_bikes ?? (currentReport.complete_bikes || []).filter((b) => b.is_new).length;
  document.getElementById("kpi-strip").innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">近 7 日新聞總篇數</div>
      <div class="kpi-value">${c.total_articles}${newArt > 0 ? ` <span class="badge badge-new">+${newArt} NEW</span>` : ""}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">整車 3D 逆向重建</div>
      <div class="kpi-value accent">${c.complete_bikes}${newBikes > 0 ? ` <span class="badge badge-new">+${newBikes} NEW</span>` : ""}</div>
    </div>
    <div class="kpi-card"><div class="kpi-label">活躍追蹤品牌數</div><div class="kpi-value">${c.brands_tracked}</div></div>
    <div class="kpi-card"><div class="kpi-label">賽事與展會動態</div><div class="kpi-value">${c.events_tracked}</div></div>
    <div class="kpi-card"><div class="kpi-label">產品評測／新品</div><div class="kpi-value">${c.reviews + c.launches}</div></div>
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

function renderComponentShares() {
  const grid = document.getElementById("component-shares-grid");
  if (!grid) return;
  const shares = currentReport?.summary?.component_shares || [];
  if (!shares.length) {
    grid.innerHTML = `<div class="conclusion-card">尚未產生配件品牌佔比統計。</div>`;
    return;
  }

  grid.innerHTML = shares
    .map((cat) => {
      const isMotor = cat.key === "motor";
      const brands = cat.brands || [];
      const stackedBar = brands.length
        ? `<div class="comp-stacked-bar">${brands
            .map(
              (b, idx) =>
                `<div class="comp-bar-seg" style="width:${b.share_pct}%;background:${SHARE_PALETTE[idx % SHARE_PALETTE.length]}" title="${esc(b.brand)}：${b.share_pct}% (${b.count}台)"></div>`
            )
            .join("")}</div>`
        : `<div class="comp-stacked-bar"></div>`;

      const rowsHtml = brands.length
        ? `<div class="comp-brand-list">${brands
            .map((b, idx) => {
              const color = SHARE_PALETTE[idx % SHARE_PALETTE.length];
              const chips = (b.bikes || [])
                .map(
                  (bk) =>
                    `<button type="button" class="comp-bike-link" data-jump-bike="${esc(bk.slug)}" title="${esc(bk.part_model || b.brand)}">${esc(bk.model_name)}</button>`
                )
                .join("");
              return `
                <div class="comp-brand-row">
                  <div class="comp-brand-top">
                    <span class="comp-brand-name"><span class="comp-swatch" style="background:${color}"></span>${esc(b.brand)}</span>
                    <span class="comp-brand-stat"><strong>${b.share_pct.toFixed(1)}%</strong>（${b.count} 台）</span>
                  </div>
                  <div class="comp-bike-chips">${chips}</div>
                </div>`;
            })
            .join("")}</div>`
        : `<div style="font-size:12.5px;color:var(--ink-muted);padding:12px 0;">本日報導未揭露此項配件品牌</div>`;

      const sampleUnit = cat.ebike_only ? "電輔車" : "整車";
      return `
        <div class="comp-share-card ${isMotor ? "is-motor" : ""}">
          <div class="comp-share-head">
            <h3 class="comp-share-title">${isMotor ? "⚡ " : ""}${esc(cat.label_zh)} <span class="comp-share-en">${esc(cat.en)}</span></h3>
            <span class="comp-share-sample">揭露 ${cat.sample_count}/${cat.eligible_count} 台${sampleUnit}</span>
          </div>
          ${stackedBar}
          ${rowsHtml}
        </div>`;
    })
    .join("");

  grid.querySelectorAll("[data-jump-bike]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slug = btn.dataset.jumpBike;
      selectBike(slug);
      document.getElementById("workbench-section")?.scrollIntoView({ behavior: "smooth" });
    });
  });
}

function renderBikeSelector() {
  const strip = document.getElementById("bike-selector-strip");
  const bikes = currentReport.complete_bikes || [];
  if (!bikes.length) {
    strip.innerHTML = `<div class="conclusion-card">本日 7 站報導中尚無新增整車評測或發布。</div>`;
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
              <span>QA ${m.qa_pass_count || 0}/${m.qa_total_count || 8} 通過</span>
            </div>
            <div class="bike-pick-title">${esc(b.model_name)}</div>
            <div class="bike-pick-cat">${esc(b.category_zh)}</div>
            <div class="bike-pick-badges">
              ${newBadgeHtml(b)}
              ${motorBadgeHtml(b)}
              <span class="badge ${pct >= 50 ? "badge-measured" : "badge-inferred"}">實測幾何 ${pct}%</span>
              ${b.full_suspension ? '<span class="badge badge-neutral">全避震</span>' : '<span class="badge badge-neutral">硬尾／硬叉</span>'}
            </div>
            ${bikeCompChipsHtml(b)}
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

  document.querySelectorAll(".bike-pick-card").forEach((el) => {
    el.classList.toggle("active", el.dataset.slug === slug);
  });

  const m = bike.model_3d || {};
  const geo = bike.geometry_resolved || {};
  const specs = bike.specs || {};
  const comps = bike.components || {};
  const wbCompBadges = [
    ["fork", "前叉"],
    ["drivetrain", "變速"],
    ["tires", "輪胎"],
    ["wheels", "輪組"],
    ["brakes", "煞車"],
  ]
    .filter(([k]) => comps[k]?.brand)
    .map(([k, lbl]) => `<span class="badge badge-comp" title="${esc(comps[k].model || comps[k].brand)}">${lbl}：${esc(comps[k].brand)}</span>`)
    .join("");

  document.getElementById("wb-badges").innerHTML = `
    ${newBadgeHtml(bike)}
    <span class="badge badge-accent">${esc(bike.brand)}</span>
    ${motorBadgeHtml(bike)}
    <span class="badge badge-neutral">${esc(bike.category_zh)}</span>
    ${m.frame_arch_zh ? `<span class="badge badge-measured">${esc(m.frame_arch_zh)}</span>` : ""}
    ${m.suspension_type_zh ? `<span class="badge badge-comp">避震：${esc(m.suspension_type_zh)}</span>` : ""}
    ${wbCompBadges}
    <span class="badge badge-neutral">來源：${esc(bike.source_name)}</span>
    <span class="badge badge-measured">建模尺碼：${esc(bike.default_size || "L")}</span>
  `;

  // Sync 1:1 calibrated photo overlay button state with OpenCV wheel-registration availability
  const ovBtn = document.getElementById("btn-toggle-overlay");
  const cal = m.photo_calibration || null;
  if (ovBtn) {
    if (cal && cal.calibrated_photo) {
      ovBtn.disabled = false;
      ovBtn.style.opacity = "1";
      ovBtn.title = `已以 OpenCV 雙輪軸心自動校準（圓輪邊緣吻合度 ${Math.round((cal.edge_support || 0) * 100)}%）`;
      ovBtn.textContent = ovBtn.classList.contains("active") ? "1:1 照片疊圖 ✓" : "1:1 照片疊圖校正";
      if (ovBtn.classList.contains("active")) {
        viewer?.setPhotoOverlay(true, cal.calibrated_photo, cal.plane_world_bounds);
      } else {
        viewer?.setPhotoOverlay(false);
      }
    } else {
      ovBtn.classList.remove("active");
      ovBtn.disabled = true;
      ovBtn.style.opacity = "0.45";
      ovBtn.textContent = "無正側視原圖";
      ovBtn.title = "此篇報導無正側面實車照，避免硬疊不同視角造成誤導";
      viewer?.setPhotoOverlay(false);
    }
  }
  document.getElementById("wb-title").textContent = bike.title_zh
    ? `${bike.model_name} — ${bike.title_zh}`
    : bike.model_name;

  document.getElementById("wb-actions").innerHTML = `
    <a class="btn btn-primary" href="${esc(m.glb_file)}" download>下載 3D 模型 (.glb)</a>
    <a class="btn btn-accent" href="${esc(m.blender_script)}" download>Blender 棚拍腳本 (.py)</a>
    <a class="btn" href="${esc(m.manifest_file)}" target="_blank" rel="noopener">QA 驗證清單 (.json)</a>
    <a class="btn" href="${esc(bike.url)}" target="_blank" rel="noopener">原始報導 ↗</a>
  `;

  document.getElementById("hud-model-info").textContent =
    `${bike.model_name} · ${m.object_count || 0} 分件 · ${(m.total_faces || 0).toLocaleString()} 三角面`;
  document.getElementById("hud-qa-badge").textContent =
    `幾何公差驗證：${m.qa_pass_count || 0}/${m.qa_total_count || 8} 通過`;
  document.getElementById("hud-geo-legend").innerHTML = `
    <span>軸距 ${geo.wheelbase_mm}mm</span>
    <span>前伸 ${geo.reach_mm}mm</span>
    <span>堆疊 ${geo.stack_mm}mm</span>
    <span>頭管 ${geo.head_angle_deg}°</span>
    <span>立管 ${geo.seat_angle_deg}°</span>
  `;
  document.getElementById("hud-sha").textContent =
    `SHA256: ${(m.glb_sha256 || "").slice(0, 14)}…（${Math.round((m.glb_bytes || 0) / 1024)} KB）`;

  if (viewer && m.glb_file) {
    viewer.loadBike(m.glb_file, m.anchors_3d, geo);
  }

  const gallery = bike.gallery && bike.gallery.length ? bike.gallery : [{ url: bike.hero_image, alt: bike.model_name }];
  const mainImg = document.getElementById("ref-photo-main");
  mainImg.src = gallery[0]?.url || "";
  mainImg.alt = bike.model_name;

  const thumbsEl = document.getElementById("ref-photo-thumbs");
  thumbsEl.innerHTML = gallery
    .map(
      (g, i) =>
        `<img class="photo-thumb ${i === 0 ? "active" : ""}" src="${esc(g.url)}" alt="${esc(bike.model_name)}" data-idx="${i}" loading="lazy" />`
    )
    .join("");
  thumbsEl.querySelectorAll(".photo-thumb").forEach((img) => {
    img.addEventListener("click", () => {
      const idx = Number(img.dataset.idx);
      mainImg.src = gallery[idx].url;
      thumbsEl.querySelectorAll(".photo-thumb").forEach((t, ti) => t.classList.toggle("active", ti === idx));
    });
  });

  const mergedSpecObj = {
    brand: bike.brand,
    model_name: bike.model_name,
    category_zh: bike.category_zh,
    ...specs,
  };
  document.getElementById("wb-spec-tbody").innerHTML = SPEC_LABELS.filter(([k]) => mergedSpecObj[k])
    .map(([k, label]) => `<tr><th>${esc(label)}</th><td>${esc(mergedSpecObj[k])}</td></tr>`)
    .join("");

  document.getElementById("wb-source-footer").innerHTML = `
    <span>資料來源：<strong>${esc(bike.source_name)}</strong> ｜ <a href="${esc(bike.url)}" target="_blank" rel="noopener">${esc(bike.url)}</a></span>
    <span>擷取日期：${esc(currentReport.date)} ｜ 檢核標準：參數化幾何公差 QA</span>
  `;

  renderGeometryTab(bike);
  renderQaTab(bike);
}

function renderGeometryTab(bike) {
  const container = document.getElementById("wbtab-geometry");
  const gt = bike.geometry_table || {};
  let multiSizeHtml = "";

  if (gt.sizes && gt.sizes.length && gt.raw_rows && gt.raw_rows.length) {
    multiSizeHtml = `
      <h4 class="sub-heading">來源原廠多尺碼幾何表（已統一中文化）</h4>
      <div class="table-wrap" style="margin-bottom: 22px;">
        <table class="data-table">
          <thead>
            <tr>
              <th>幾何項目</th>
              ${gt.sizes.map((s) => `<th>尺碼 ${esc(s)}${s === gt.default_size ? " ★" : ""}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${gt.raw_rows
              .map(
                (r) => `
                <tr>
                  <td><strong>${esc(r.label_zh || r.label)}</strong></td>
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
    <h4 class="sub-heading">3D 逆向工程輸入參數與資料溯源（建模尺碼 ${esc(bike.default_size || "L")}）</h4>
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
  const cal = m.photo_calibration || null;

  const overlayProofHtml =
    cal && cal.overlay_qa_image
      ? `
    <div class="scope-box" style="margin-top:0;margin-bottom:18px;">
      <h4>1:1 雙輪軸心自動校準疊圖驗證（OpenCV 圓輪邊緣吻合度 ${Math.round((cal.edge_support || 0) * 100)}% · 實車輪距比 ${cal.detected_wb_ratio} vs 規格 ${cal.target_wb_ratio}）</h4>
      <img src="${esc(cal.overlay_qa_image)}" alt="1:1 實車照片與 3D 輪廓疊圖驗證" style="width:100%;max-width:860px;border-radius:8px;border:1px solid var(--border-hairline);display:block;margin-top:8px;" loading="lazy" />
    </div>`
      : "";

  container.innerHTML = `
    ${overlayProofHtml}
    <h4 class="sub-heading">3D 幾何公差檢核表</h4>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>檢核項目</th><th>目標規格</th><th>3D 實測值</th><th>誤差值</th><th>判定狀態</th></tr>
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
                <td><span class="badge ${q.status === "通過" || q.status === "PASS" ? "badge-measured" : "badge-inferred"}">${esc(q.status)}</span></td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>
    <div class="scope-box">
      <h4>逆向工程範圍與精度聲明（參數化逆向工程驗證聲明）</h4>
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
  const newOnly = Boolean(document.getElementById("filter-new-only")?.checked);

  const list = (currentReport.articles || []).filter((a) => {
    if (newOnly && !a.is_new) return false;
    if (src !== "all" && a.source_id !== src) return false;
    if (bucket !== "all" && a.classification.bucket !== bucket) return false;
    if (q) {
      const blob = `${a.title_zh || ""} ${a.title} ${a.summary_zh || ""} ${a.takeaway_zh} ${a.source_name} ${(a.brands || []).map((b) => b.name).join(" ")} ${(a.events || []).map((e) => e.name).join(" ")}`.toLowerCase();
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
          <th style="width:142px;">媒體來源／訊號</th>
          <th style="width:160px;">涉及品牌與賽事</th>
          <th>中文翻譯標題與情報摘要（游標移至標題可查看原文）</th>
          <th style="width:98px;">操作</th>
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
            const displayTitle = a.title_zh || a.title;
            return `
              <tr class="${a.is_new ? "row-is-new" : ""}">
                <td class="mono">${fmtDate(a.published_at)}</td>
                <td>
                  <div style="font-weight:600;margin-bottom:4px;">${esc(a.source_name)}</div>
                  <div class="tag-list">
                    ${signalBadge(a.classification.signal)}
                    <span class="badge badge-neutral">${langTag(a.source_lang)}</span>
                  </div>
                </td>
                <td>
                  <div class="tag-list">${brandTags}${eventTags || (brandTags ? "" : '<span class="badge badge-neutral">綜合</span>')}</div>
                </td>
                <td>
                  <div class="article-title-row">
                    ${newBadgeHtml(a)}
                    <a class="article-title-link" style="margin:0;" href="${esc(a.url)}" target="_blank" rel="noopener" title="原文：${esc(a.title)}">${esc(displayTitle)}</a>
                  </div>
                  <div class="takeaway-line">${esc(a.takeaway_zh)}</div>
                  ${a.summary_zh ? `<div class="takeaway-line" style="font-size:11.5px;color:var(--ink-muted);margin-top:3px;">${esc(a.summary_zh.slice(0, 140))}</div>` : ""}
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
          <th style="width:60px;">排名</th>
          <th style="width:170px;">品牌名稱</th>
          <th style="width:130px;">定位分類</th>
          <th style="width:90px;">提及次數</th>
          <th style="width:180px;">今日動態訊號</th>
          <th>代表報導（全中文翻譯）</th>
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
                      `<div style="margin-bottom:4px;"><a class="article-title-link" style="font-size:12.5px;margin:0;" href="${esc(a.url)}" target="_blank" rel="noopener" title="原文：${esc(a.title)}">[${esc(a.source)}] ${esc(a.title_zh || a.title)}</a></div>`
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
          <th>重點報導摘要（全中文翻譯）</th>
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
                      `<div style="margin-bottom:4px;"><a class="article-title-link" style="font-size:12.5px;margin:0;" href="${esc(h.url)}" target="_blank" rel="noopener" title="原文：${esc(h.title)}">[${esc(h.source)}] ${esc(h.title_zh || h.title)}</a></div>`
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

/* ============================================================================
 * INTERACTIVE 16:9 SLIDE DECK MODE (100% Traditional Chinese + Source Footer)
 * ========================================================================== */
function buildWebSlides() {
  if (!currentReport) return;
  const dateStr = currentReport.date || "";
  const c = currentReport.summary.counts;
  const conclusions = currentReport.summary.conclusions || [];
  const topBrands = (currentReport.summary.top_brands || []).slice(0, 8);
  const events = (currentReport.summary.events || []).slice(0, 8);
  const bikes = [...(currentReport.complete_bikes || [])].sort((a, b) => (b.measured_ratio || 0) - (a.measured_ratio || 0));
  const highlights = (currentReport.articles || [])
    .filter((a) => ["召回警示", "產品評測", "新品/動態"].includes(a.classification.signal))
    .slice(0, 8);

  const slides = [];

  // Slide 1: Cover
  slides.push({
    navLabel: "01 封面總覽",
    sourceHtml: `資料來源：${allSourcesFooterHtml()} ｜ 擷取日期：${esc(dateStr)}`,
    bodyHtml: `
      <div class="slide-kicker">每日全球自行車產業情報簡報（七站統一翻譯繁體中文）</div>
      <h2 class="slide-h2" style="font-size:30px;margin-top:8px;">全球自行車每日中文情報站</h2>
      <p style="color:var(--ink-secondary);margin:0 0 22px;font-size:14px;">
        追蹤品牌、焦點、趨勢及熱門話題 ｜ 更新時間：${esc(currentReport.generated_at_cst || dateStr)}
      </p>
      <div class="kpi-strip" style="margin-bottom:18px;">
        <div class="kpi-card"><div class="kpi-label">七站抓取篇數</div><div class="kpi-value">${c.total_articles}</div></div>
        <div class="kpi-card"><div class="kpi-label">整車 3D 建模</div><div class="kpi-value accent">${c.complete_bikes}</div></div>
        <div class="kpi-card"><div class="kpi-label">活躍品牌數</div><div class="kpi-value">${c.brands_tracked}</div></div>
        <div class="kpi-card"><div class="kpi-label">賽事與展會</div><div class="kpi-value">${c.events_tracked}</div></div>
        <div class="kpi-card"><div class="kpi-label">評測／新品</div><div class="kpi-value">${c.reviews + c.launches}</div></div>
      </div>
      <div class="conclusion-card">
        <span class="conclusion-tag">七大監測媒體與語系轉換</span>
        <p>${(currentReport.sources || []).map((s) => `<strong>${esc(s.name)}</strong>（${s.item_count} 篇 · ${langTag(s.lang)}）`).join(" ｜ ")}</p>
      </div>
    `,
  });

  // Slide 2: Conclusions
  slides.push({
    navLabel: "02 今日核心結論",
    sourceHtml: `資料來源：${allSourcesFooterHtml()} ｜ 擷取日期：${esc(dateStr)}`,
    bodyHtml: `
      <div class="slide-kicker">01 / DAILY EXECUTIVE CONCLUSIONS</div>
      <h2 class="slide-h2">今日全球自行車產業核心結論</h2>
      <div class="slide-grid-2">
        ${conclusions
          .map(
            (item) => `
            <div class="conclusion-card">
              <span class="conclusion-tag">${esc(item.tag)}</span>
              <h3>${esc(item.title)}</h3>
              <p>${esc(item.detail)}</p>
            </div>`
          )
          .join("")}
      </div>
    `,
  });

  // Slide 3: Component & Motor Brand Share Statistics
  const compShares = currentReport.summary.component_shares || [];
  if (compShares.length) {
    slides.push({
      navLabel: "03 電機與配件品牌佔比",
      sourceHtml: `資料來源：${allSourcesFooterHtml()} ｜ 擷取日期：${esc(dateStr)}`,
      bodyHtml: `
        <div class="slide-kicker">02 / COMPONENT &amp; MOTOR BRAND SHARE</div>
        <h2 class="slide-h2">本日整車電機、前叉、變速器、輪胎、輪組與煞車品牌佔比</h2>
        <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;">
          ${compShares
            .slice(0, 6)
            .map((cat) => {
              const brs = (cat.brands || []).slice(0, 5);
              return `
                <div class="conclusion-card" style="padding:11px 13px;">
                  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
                    <strong style="font-size:13px;">${cat.key === "motor" ? "⚡ " : ""}${esc(cat.label_zh)}</strong>
                    <span class="mono" style="font-size:10.5px;color:var(--ink-muted);">${cat.sample_count}/${cat.eligible_count}台</span>
                  </div>
                  <div class="comp-stacked-bar" style="height:8px;margin-bottom:7px;">
                    ${brs
                      .map(
                        (b, i) =>
                          `<div class="comp-bar-seg" style="width:${b.share_pct}%;background:${SHARE_PALETTE[i % SHARE_PALETTE.length]}"></div>`
                      )
                      .join("")}
                  </div>
                  ${
                    brs.length
                      ? brs
                          .map(
                            (b, i) => `
                            <div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:3px;">
                              <span style="display:inline-flex;align-items:center;gap:5px;font-weight:600;">
                                <span class="comp-swatch" style="background:${SHARE_PALETTE[i % SHARE_PALETTE.length]}"></span>${esc(b.brand)}
                              </span>
                              <span class="mono"><strong>${b.share_pct.toFixed(1)}%</strong> (${b.count})</span>
                            </div>`
                          )
                          .join("")
                      : '<div style="font-size:11px;color:var(--ink-muted);">未揭露</div>'
                  }
                </div>`;
            })
            .join("")}
        </div>
      `,
    });
  }

  // Slide 4: Top Brands
  slides.push({
    navLabel: "04 熱門品牌動態",
    sourceHtml: `資料來源：${allSourcesFooterHtml()} ｜ 擷取日期：${esc(dateStr)}`,
    bodyHtml: `
      <div class="slide-kicker">02 / BRAND MOMENTUM</div>
      <h2 class="slide-h2">本日高聲量品牌與動態排行（全中文）</h2>
      <table class="data-table" style="font-size:12px;">
        <thead><tr><th>排名</th><th>品牌</th><th>定位</th><th>動態訊號</th><th>代表報導（中文翻譯）</th></tr></thead>
        <tbody>
          ${topBrands
            .map((b, i) => {
              const rep = (b.articles || [])[0] || {};
              return `
                <tr>
                  <td class="mono">${String(i + 1).padStart(2, "0")} (${b.mentions}則)</td>
                  <td><strong>${esc(b.name)}</strong></td>
                  <td>${esc(b.type)}</td>
                  <td>${(b.signals || []).slice(0, 2).map((s) => signalBadge(s)).join(" ")}</td>
                  <td>[${esc(rep.source || "")}] ${esc(rep.title_zh || rep.title || "")}</td>
                </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    `,
  });

  // Slide 4: Races & Events
  slides.push({
    navLabel: "04 賽事與展會活動",
    sourceHtml: `資料來源：${allSourcesFooterHtml()} ｜ 擷取日期：${esc(dateStr)}`,
    bodyHtml: `
      <div class="slide-kicker">03 / RACES &amp; INDUSTRY EVENTS</div>
      <h2 class="slide-h2">全球賽事戰報、車隊陣容與產業展會追蹤</h2>
      <table class="data-table" style="font-size:12px;">
        <thead><tr><th>賽事／活動名稱</th><th>類型</th><th>媒體來源</th><th>焦點報導（中文翻譯）</th></tr></thead>
        <tbody>
          ${events
            .map((ev) => {
              const hl = (ev.headlines || [])[0] || {};
              return `
                <tr>
                  <td><strong>${esc(ev.name)}</strong></td>
                  <td><span class="badge badge-accent">${esc(ev.kind)}</span></td>
                  <td>${esc((ev.sources || []).join("、"))}</td>
                  <td>${esc(hl.title_zh || hl.title || "")}</td>
                </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    `,
  });

  // Slides 5..N: Each Complete Bike
  bikes.forEach((b, idx) => {
    const geo = b.geometry_resolved || {};
    const prov = b.geometry_provenance || {};
    const specs = b.specs || {};
    const m = b.model_3d || {};
    const pct = Math.round((b.measured_ratio || 0) * 100);
    const pTag = (k) => (String(prov[k] || "").startsWith("measured") ? '<span class="badge badge-measured">實測</span>' : '<span class="badge badge-inferred">推估</span>');

    slides.push({
      navLabel: `${String(idx + 5).padStart(2, "0")} 整車：${b.model_name}`,
      sourceHtml: `資料來源：<strong>${esc(b.source_name)}</strong> ｜ <a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.url)}</a> ｜ 擷取日期：${esc(dateStr)}`,
      bodyHtml: `
        <div class="slide-kicker">04 / 整車逆向建模 · 實測幾何 ${pct}% · 幾何驗證 ${m.qa_pass_count || 0}/${m.qa_total_count || 8} 通過</div>
        <h2 class="slide-h2">${esc(b.brand)} — ${esc(b.model_name)}（${esc(b.category_zh)}）</h2>
        <div class="slide-bike-grid">
          <div class="slide-photo-stack">
            <div class="slide-img-card">
              <div class="cap">來源實車照片（${esc(b.source_name)}）</div>
              <img src="${esc(b.hero_image || "")}" alt="${esc(b.model_name)}" />
            </div>
            <div class="slide-img-card">
              <div class="cap">3D 逆向工程正交側視圖（${m.object_count || 0} 分件 · 尺碼 ${esc(b.default_size || "L")}）</div>
              <img class="contain" src="${esc(m.preview_image || "")}" alt="${esc(b.model_name)} 3D 側視圖" />
            </div>
          </div>
          <div style="display:flex;flex-direction:column;gap:10px;">
            <table class="data-table" style="font-size:11.5px;">
              <thead><tr><th colspan="2">產品規格參數表（全中文）</th></tr></thead>
              <tbody>
                <tr><td style="width:32%;color:var(--ink-secondary);">車架／輪徑</td><td>${esc(specs.frame_material || "依車型規格")} ｜ ${esc(specs.wheel_size || `${geo.wheel_front_in} 吋`)}（胎寬 ${geo.tire_width_mm}mm）</td></tr>
                <tr><td style="color:var(--ink-secondary);">避震行程</td><td>前 ${geo.travel_front_mm} mm ／ 後 ${geo.travel_rear_mm} mm</td></tr>
                <tr><td style="color:var(--ink-secondary);">電輔系統</td><td>${esc(specs.motor || "純人力車款")} ｜ 電池 ${esc(specs.battery || "—")}</td></tr>
                <tr><td style="color:var(--ink-secondary);">傳動／煞車</td><td>${esc(specs.drivetrain || "—")} ｜ ${esc(specs.brakes || "—")}</td></tr>
                <tr><td style="color:var(--ink-secondary);">重量／售價</td><td>${esc(specs.weight || "—")} ｜ ${esc(specs.price || "—")}</td></tr>
              </tbody>
            </table>
            <table class="data-table" style="font-size:11.5px;">
              <thead><tr><th>幾何參數（尺碼 ${esc(b.default_size || "L")}）</th><th>建模數值</th><th>溯源</th></tr></thead>
              <tbody>
                <tr><td>前後軸距 / 後下叉</td><td class="mono">${geo.wheelbase_mm} mm / ${geo.chainstay_mm} mm</td><td>${pTag("wheelbase_mm")}</td></tr>
                <tr><td>前伸量 (Reach) / 堆疊 (Stack)</td><td class="mono">${geo.reach_mm} mm / ${geo.stack_mm} mm</td><td>${pTag("reach_mm")}</td></tr>
                <tr><td>頭管角度 / 立管角度</td><td class="mono">${geo.head_angle_deg}° / ${geo.seat_angle_deg}°</td><td>${pTag("head_angle_deg")}</td></tr>
                <tr><td>五通下沉量 (BB Drop)</td><td class="mono">${geo.bb_drop_mm} mm</td><td>${pTag("bb_drop_mm")}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      `,
    });
  });

  // Final Slide: Reviews, Launches & Recalls Highlights
  slides.push({
    navLabel: `${String(bikes.length + 5).padStart(2, "0")} 評測新品與召回精選`,
    sourceHtml: `資料來源：${allSourcesFooterHtml()} ｜ 擷取日期：${esc(dateStr)}`,
    bodyHtml: `
      <div class="slide-kicker">05 / PRODUCT REVIEWS, LAUNCHES &amp; RECALLS</div>
      <h2 class="slide-h2">本日重點產品評測、新品發布與安全召回（全中文翻譯）</h2>
      <table class="data-table" style="font-size:12px;">
        <thead><tr><th>來源</th><th>標籤</th><th>中文翻譯標題</th><th>重點結論</th></tr></thead>
        <tbody>
          ${highlights
            .map(
              (a) => `
              <tr>
                <td><strong>${esc(a.source_name)}</strong></td>
                <td>${signalBadge(a.classification.signal)}</td>
                <td><a class="article-title-link" style="margin:0;font-size:12px;" href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title_zh || a.title)}</a></td>
                <td style="font-size:11.5px;color:var(--ink-secondary);">${esc(a.takeaway_zh)}</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>
    `,
  });

  slidesData = slides;
  const sel = document.getElementById("slide-jump-select");
  sel.innerHTML = slidesData
    .map((s, i) => `<option value="${i}">${esc(s.navLabel)}</option>`)
    .join("");
  renderActiveSlide(0);
}

function renderActiveSlide(idx) {
  if (!slidesData.length) return;
  currentSlideIdx = Math.max(0, Math.min(slidesData.length - 1, idx));
  const slide = slidesData[currentSlideIdx];
  const total = slidesData.length;
  const pageText = `頁次 ${String(currentSlideIdx + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;

  document.getElementById("slide-counter-badge").textContent = `${String(currentSlideIdx + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
  document.getElementById("slide-jump-select").value = String(currentSlideIdx);

  document.getElementById("slide-frame").innerHTML = `
    <div class="slide-body">${slide.bodyHtml}</div>
    <footer class="slide-footer">
      <div class="slide-footer-src">${slide.sourceHtml}</div>
      <div class="slide-footer-page">${pageText}</div>
    </footer>
  `;
}

function bindStaticControls() {
  document.querySelectorAll("#cam-presets .tool-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#cam-presets .tool-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      viewer?.setCameraPreset(btn.dataset.cam);
    });
  });

  const modeBtns = [
    ["btn-mode-pbr", "pbr"],
    ["btn-mode-clay", "clay"],
    ["btn-mode-wire", "wire"],
    ["btn-mode-xray", "xray"],
  ];
  const activateMode = (mode) => {
    modeBtns.forEach(([bid, m]) => document.getElementById(bid).classList.toggle("active", m === mode));
    viewer?.setRenderMode(mode);
  };
  modeBtns.forEach(([id, mode]) => {
    document.getElementById(id).addEventListener("click", () => activateMode(mode));
  });

  const cadBtn = document.getElementById("btn-toggle-cad");
  cadBtn.addEventListener("click", () => {
    const next = !cadBtn.classList.contains("active");
    cadBtn.classList.toggle("active", next);
    viewer?.setCadOverlay(next);
  });

  const projBtn = document.getElementById("btn-toggle-proj");
  projBtn.addEventListener("click", () => {
    const next = !projBtn.classList.contains("active");
    projBtn.classList.toggle("active", next);
    projBtn.textContent = next ? "正交視角 ✓" : "正交視角";
    viewer?.setProjection(next);
  });

  const ovBtn = document.getElementById("btn-toggle-overlay");
  ovBtn.addEventListener("click", () => {
    const bike = (currentReport?.complete_bikes || []).find((b) => b.slug === selectedBikeSlug);
    const cal = bike?.model_3d?.photo_calibration;
    if (!cal || !cal.calibrated_photo) return;
    const next = !ovBtn.classList.contains("active");
    ovBtn.classList.toggle("active", next);
    ovBtn.textContent = next ? "1:1 照片疊圖 ✓" : "1:1 照片疊圖校正";
    if (next) {
      projBtn.classList.add("active");
      projBtn.textContent = "正交視角 ✓";
      viewer?.setProjection(true);
      viewer?.setCameraPreset("side_drive");
      document.querySelectorAll("#cam-presets .tool-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.cam === "side_drive");
      });
      viewer?.setPhotoOverlay(true, cal.calibrated_photo, cal.plane_world_bounds);
      activateMode("xray");
    } else {
      viewer?.setPhotoOverlay(false);
      activateMode("pbr");
    }
  });

  document.querySelectorAll(".wb-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".wb-tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.wbtab;
      document.getElementById("wbtab-geometry").classList.toggle("hidden", target !== "geometry");
      document.getElementById("wbtab-qa").classList.toggle("hidden", target !== "qa");
    });
  });

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

  ["filter-search", "filter-source", "filter-bucket", "filter-new-only"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", renderArticlesTable);
    el.addEventListener("change", renderArticlesTable);
  });

  // Slide deck controls
  const overlay = document.getElementById("slide-deck-overlay");
  document.getElementById("btn-open-slides").addEventListener("click", () => {
    overlay.classList.remove("hidden");
    renderActiveSlide(currentSlideIdx);
  });
  document.getElementById("btn-close-slides").addEventListener("click", () => {
    overlay.classList.add("hidden");
  });
  document.getElementById("btn-slide-prev").addEventListener("click", () => renderActiveSlide(currentSlideIdx - 1));
  document.getElementById("btn-slide-next").addEventListener("click", () => renderActiveSlide(currentSlideIdx + 1));
  document.getElementById("slide-jump-select").addEventListener("change", (e) => {
    renderActiveSlide(Number(e.target.value));
  });

  window.addEventListener("keydown", (e) => {
    if (overlay.classList.contains("hidden")) return;
    if (e.key === "Escape") overlay.classList.add("hidden");
    if (e.key === "ArrowRight" || e.key === "PageDown") renderActiveSlide(currentSlideIdx + 1);
    if (e.key === "ArrowLeft" || e.key === "PageUp") renderActiveSlide(currentSlideIdx - 1);
  });
}

init();
