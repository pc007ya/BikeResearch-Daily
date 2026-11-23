// Interactive Three.js 3D Architectural Relief World Map with Stacked 3D Bike Category Columns
// Uses existing Three.js 0.169.0 importmap + TopoJSON worldGeoFeatures from sales_dashboard.js.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const SCALE_X = 0.115; // lon [-180..180] -> [-20.7..20.7]
const SCALE_Z = 0.132; // lat [-60..78]   -> [7.9..-10.3]

const CAT_ORDER = ["ebike", "mtb", "road", "city", "other"];

const CAT_HEX = {
  ebike: 0xe2552d, // ⚡ 電動車
  mtb: 0x22936f,   // 🏔️ 登山車
  road: 0x357ec2,  // 🚴 公路／礫石車
  city: 0xe3a02b,  // 🏙️ 城市／通勤車
  other: 0x8f8c82, // 🧒 童車與其他
};

const COUNTRY_CENTROIDS = {
  DE: [10.4, 51.3],
  FR: [2.1, 46.6],
  GB: [-2.4, 54.0],
  IT: [12.7, 42.5],
  ES: [-3.8, 40.3],
  NL: [5.4, 52.7],
  BE: [4.3, 50.4],
  AT: [14.5, 47.6],
  CH: [8.1, 46.8],
  US: [-98.5, 39.5],
  CA: [-103.5, 56.0],
  CN: [104.0, 35.5],
  JP: [138.3, 36.4],
  AU: [134.0, -25.2],
  TW: [121.0, 23.7],
};

function lonLatToXZ(lon, lat) {
  const clampedLat = Math.max(-58, Math.min(76, lat));
  return [lon * SCALE_X, -clampedLat * SCALE_Z];
}

// Camera presets [camX, camY, camZ, targetX, targetY, targetZ]
function getCameraPreset(view) {
  if (view === "europe") {
    const [tx, tz] = lonLatToXZ(6.5, 48.2);
    return {
      pos: new THREE.Vector3(tx + 0.6, 5.1, tz + 5.9),
      target: new THREE.Vector3(tx, 0.55, tz),
    };
  }
  if (view === "americas") {
    const [tx, tz] = lonLatToXZ(-96.0, 43.0);
    return {
      pos: new THREE.Vector3(tx + 1.5, 10.2, tz + 11.4),
      target: new THREE.Vector3(tx, 0.7, tz),
    };
  }
  if (view === "apac") {
    const [tx, tz] = lonLatToXZ(118.0, 12.0);
    return {
      pos: new THREE.Vector3(tx + 2.2, 13.8, tz + 14.5),
      target: new THREE.Vector3(tx, 0.8, tz),
    };
  }
  // Global overview
  return {
    pos: new THREE.Vector3(1.4, 17.5, 22.8),
    target: new THREE.Vector3(1.2, 0.6, -2.1),
  };
}

function ringHasAntimeridianJump(ring) {
  for (let i = 1; i < ring.length; i++) {
    if (Math.abs(ring[i][0] - ring[i - 1][0]) > 170) return true;
  }
  return false;
}

function buildCountryShapes(geometry) {
  const shapes = [];
  const polys =
    geometry.type === "Polygon"
      ? [geometry.coordinates]
      : geometry.type === "MultiPolygon"
        ? geometry.coordinates
        : [];

  for (const poly of polys) {
    if (!poly || !poly.length) continue;
    const outer = poly[0];
    if (!outer || outer.length < 4 || ringHasAntimeridianJump(outer)) continue;

    // Shape lives in XY plane (we rotate mesh -PI/2 around X so shape Y maps to -Z, i.e., lat -> +Y in Shape)
    const shape = new THREE.Shape();
    let validPts = 0;
    for (let i = 0; i < outer.length; i++) {
      const [lon, lat] = outer[i];
      const x = lon * SCALE_X;
      const y = Math.max(-58, Math.min(76, lat)) * SCALE_Z;
      if (i === 0) shape.moveTo(x, y);
      else shape.lineTo(x, y);
      validPts++;
    }
    if (validPts < 4) continue;

    // Approximate area filter to skip microscopic islands
    const area = Math.abs(THREE.ShapeUtils.area(shape.getPoints()));
    if (area < 0.0025) continue;
    shapes.push(shape);
  }
  return shapes;
}

export class SalesMap3D {
  constructor(containerEl, callbacks = {}) {
    this.container = containerEl;
    this.callbacks = callbacks;
    this.disposed = false;
    this.animating = false;
    this.rafId = null;

    this.countryMeshes = new Map(); // iso_num -> { group, meshes, borderMat, baseMat, country }
    this.barRoot = new THREE.Group();
    this.barEntries = []; // { country, group, meshes, topWorld: Vector3, labelEl, targetScaleY, curScaleY }
    this.hoveredIso = null;
    this.selectedIso = null;
    this.currentView = "all";
    this.barStyle = "stacked"; // "stacked" | "grouped"

    // Camera fly-to interpolation state
    this.camLerp = null;

    this._initScene();
    this._bindEvents();
  }

  _initScene() {
    this.container.innerHTML = "";
    this.container.classList.add("map3d-host");

    const w = Math.max(this.container.clientWidth || 720, 320);
    const h = Math.max(this.container.clientHeight || 440, 360);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x131922);
    this.scene.fog = new THREE.FogExp2(0x131922, 0.0115);

    this.camera = new THREE.PerspectiveCamera(36, w / h, 0.2, 180);
    const preset = getCameraPreset("all");
    this.camera.position.copy(preset.pos);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.12;
    this.container.appendChild(this.renderer.domElement);

    // Floating 2D label layer
    this.labelsLayer = document.createElement("div");
    this.labelsLayer.className = "map3d-labels-layer";
    this.container.appendChild(this.labelsLayer);

    // Subtle 3D HUD overlay hint
    this.hudHint = document.createElement("div");
    this.hudHint.className = "map3d-hud-hint";
    this.hudHint.textContent = "左鍵旋轉 3D 視角 · 滾輪縮放 · 右鍵平移 · 點選立體柱或國家篩選";
    this.container.appendChild(this.hudHint);

    // OrbitControls
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.copy(preset.target);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.maxPolarAngle = Math.PI * 0.46;
    this.controls.minPolarAngle = 0.16;
    this.controls.minDistance = 3.2;
    this.controls.maxDistance = 44;
    this.controls.update();

    // Stop camera fly-to if user drags manually
    this.controls.addEventListener("start", () => {
      this.camLerp = null;
    });

    // Studio Lighting (Architectural Rim + Soft Overhead Key + Cool Fill)
    const hemi = new THREE.HemisphereLight(0xdce8f8, 0x1a2028, 0.95);
    this.scene.add(hemi);

    const keyLight = new THREE.DirectionalLight(0xfff7ec, 1.85);
    keyLight.position.set(14, 24, 16);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(2048, 2048);
    keyLight.shadow.camera.near = 2;
    keyLight.shadow.camera.far = 75;
    keyLight.shadow.camera.left = -26;
    keyLight.shadow.camera.right = 26;
    keyLight.shadow.camera.top = 18;
    keyLight.shadow.camera.bottom = -18;
    keyLight.shadow.bias = -0.0005;
    this.scene.add(keyLight);

    const rimLight = new THREE.DirectionalLight(0x78b2e8, 0.85);
    rimLight.position.set(-18, 12, -16);
    this.scene.add(rimLight);

    // Architectural Ocean Tabletop Base + Lat/Lon Graticule Grid
    const baseGeo = new THREE.PlaneGeometry(54, 30);
    const baseMat = new THREE.MeshStandardMaterial({
      color: 0x161f2b,
      roughness: 0.72,
      metalness: 0.18,
    });
    const baseMesh = new THREE.Mesh(baseGeo, baseMat);
    baseMesh.rotation.x = -Math.PI / 2;
    baseMesh.position.set(0, -0.02, -1.2);
    baseMesh.receiveShadow = true;
    this.scene.add(baseMesh);

    // Crisp lat/lon architectural gridlines
    const gridPts = [];
    for (let lon = -180; lon <= 180; lon += 20) {
      const [x, z1] = lonLatToXZ(lon, -56);
      const [, z2] = lonLatToXZ(lon, 74);
      gridPts.push(x, 0.005, z1, x, 0.005, z2);
    }
    for (let lat = -40; lat <= 70; lat += 20) {
      const [x1, z] = lonLatToXZ(-180, lat);
      const [x2] = lonLatToXZ(180, lat);
      gridPts.push(x1, 0.005, z, x2, 0.005, z);
    }
    const gridGeo = new THREE.BufferGeometry();
    gridGeo.setAttribute("position", new THREE.Float32BufferAttribute(gridPts, 3));
    const gridMat = new THREE.LineBasicMaterial({
      color: 0x3b4d63,
      transparent: true,
      opacity: 0.34,
    });
    this.scene.add(new THREE.LineSegments(gridGeo, gridMat));

    this.landRoot = new THREE.Group();
    this.scene.add(this.landRoot);
    this.scene.add(this.barRoot);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2(-99, -99);
    this._pointerDownPos = null;

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
  }

  _bindEvents() {
    const dom = this.renderer.domElement;

    this._onPointerMove = (evt) => {
      const rect = dom.getBoundingClientRect();
      this.pointer.x = ((evt.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((evt.clientY - rect.top) / rect.height) * 2 + 1;
      this._pick(evt, false);
    };

    this._onPointerDown = (evt) => {
      this._pointerDownPos = { x: evt.clientX, y: evt.clientY };
    };

    this._onPointerUp = (evt) => {
      if (!this._pointerDownPos) return;
      const dx = evt.clientX - this._pointerDownPos.x;
      const dy = evt.clientY - this._pointerDownPos.y;
      this._pointerDownPos = null;
      if (Math.hypot(dx, dy) > 5) return; // Ignore orbit drags
      const rect = dom.getBoundingClientRect();
      this.pointer.x = ((evt.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((evt.clientY - rect.top) / rect.height) * 2 + 1;
      this._pick(evt, true);
    };

    this._onPointerLeave = () => {
      if (this.hoveredIso) {
        this.hoveredIso = null;
        this._refreshHighlights();
      }
      this.callbacks.onLeave?.();
    };

    dom.addEventListener("pointermove", this._onPointerMove);
    dom.addEventListener("pointerdown", this._onPointerDown);
    dom.addEventListener("pointerup", this._onPointerUp);
    dom.addEventListener("pointerleave", this._onPointerLeave);
  }

  _pick(evt, isClick) {
    if (!this._pickables || !this._pickables.length) return;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this._pickables, false);
    const hitCountry = hits.length ? hits[0].object.userData?.country : null;

    if (isClick) {
      if (hitCountry) {
        this.callbacks.onSelect?.(hitCountry);
      }
      return;
    }

    const nextIso = hitCountry?.iso2 || null;
    if (nextIso !== this.hoveredIso) {
      this.hoveredIso = nextIso;
      this._refreshHighlights();
      this.renderer.domElement.style.cursor = hitCountry ? "pointer" : "grab";
    }
    if (hitCountry) {
      this.callbacks.onHover?.(evt, hitCountry);
    } else {
      this.callbacks.onLeave?.();
    }
  }

  buildWorldGeometry(worldGeoFeatures, salesCountries) {
    if (this._worldBuilt) return;
    this._worldBuilt = true;

    const trackedByIsoNum = new Map(salesCountries.map((c) => [c.iso_num, c]));
    const untrackedMat = new THREE.MeshStandardMaterial({
      color: 0x222c38,
      roughness: 0.85,
      metalness: 0.08,
    });
    const untrackedEdgeMat = new THREE.LineBasicMaterial({
      color: 0x39495c,
      transparent: true,
      opacity: 0.48,
    });

    for (const feat of worldGeoFeatures.features) {
      const isoNum = String(feat.id).padStart(3, "0");
      const country = trackedByIsoNum.get(isoNum) || null;
      const shapes = buildCountryShapes(feat.geometry);
      if (!shapes.length) continue;

      const depth = country ? 0.24 : 0.11;
      const extrudeGeo = new THREE.ExtrudeGeometry(shapes, {
        depth,
        bevelEnabled: !!country,
        bevelThickness: country ? 0.025 : 0,
        bevelSize: country ? 0.02 : 0,
        bevelSegments: 2,
        curveSegments: 1,
      });
      // Rotate so Shape X -> World X, Shape Y -> World -Z, Extrude Z -> World +Y
      extrudeGeo.rotateX(-Math.PI / 2);

      if (!country) {
        const mesh = new THREE.Mesh(extrudeGeo, untrackedMat);
        mesh.receiveShadow = true;
        this.landRoot.add(mesh);

        const edges = new THREE.EdgesGeometry(extrudeGeo, 28);
        const line = new THREE.LineSegments(edges, untrackedEdgeMat);
        line.position.y = 0.002;
        this.landRoot.add(line);
      } else {
        const mat = new THREE.MeshStandardMaterial({
          color: 0x2f4b56,
          roughness: 0.56,
          metalness: 0.16,
          emissive: 0x000000,
          emissiveIntensity: 0.22,
        });
        const mesh = new THREE.Mesh(extrudeGeo, mat);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.userData = { country };

        const edgeMat = new THREE.LineBasicMaterial({
          color: 0x8ea9c2,
          transparent: true,
          opacity: 0.72,
        });
        const edges = new THREE.EdgesGeometry(extrudeGeo, 26);
        const line = new THREE.LineSegments(edges, edgeMat);
        line.position.y = 0.004;

        const grp = new THREE.Group();
        grp.add(mesh);
        grp.add(line);
        this.landRoot.add(grp);

        this.countryMeshes.set(country.iso2, {
          country,
          group: grp,
          mesh,
          mat,
          edgeMat,
        });
      }
    }
  }

  _clearBars() {
    while (this.barRoot.children.length) {
      const child = this.barRoot.children[0];
      child.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
          else obj.material.dispose();
        }
      });
      this.barRoot.remove(child);
    }
    this.barEntries.forEach((b) => b.labelEl?.remove());
    this.barEntries = [];
  }

  updateData(salesData, state, { getMetricColor, formatMetricVal, barStyle = "stacked" }) {
    this.selectedIso = state.countryIso;
    this.barStyle = barStyle;
    this._clearBars();

    const yr = state.year;
    const activeCat = state.category;
    const scopeCountries =
      state.mapView === "all"
        ? salesData.countries
        : salesData.countries.filter((c) => c.region === state.mapView);

    // Compute max height reference in active map view so Europe/Americas/APAC fill nicely
    const getVal = (c) => {
      const r = c.yearly[yr];
      return activeCat === "all" ? r.total_k : r[`${activeCat}_k`] || 0;
    };
    const maxK = Math.max(...scopeCountries.map(getVal), 100);
    const isZoomedRegion = state.mapView !== "all";
    const maxBarH = state.mapView === "europe" ? 2.55 : isZoomedRegion ? 3.8 : 5.4;
    const colWidth = state.mapView === "europe" ? 0.24 : isZoomedRegion ? 0.44 : 0.52;

    const pickables = [];

    // Update tracked country plates + build 3D stacked / grouped bars
    salesData.countries.forEach((c) => {
      const plate = this.countryMeshes.get(c.iso2);
      const inRegion = state.region === "all" || c.region === state.region;
      const isSelected = state.countryIso === c.iso2;

      if (plate) {
        const fillHex = getMetricColor(c);
        plate.mat.color.set(fillHex);
        plate.mat.opacity = inRegion ? 1.0 : 0.45;
        plate.mat.transparent = !inRegion;
        plate.group.position.y = isSelected ? 0.08 : 0;
        pickables.push(plate.mesh);
      }

      const coords = COUNTRY_CENTROIDS[c.iso2];
      if (!coords) return;
      const [cx, cz] = lonLatToXZ(coords[0], coords[1]);
      const baseY = isSelected ? 0.35 : 0.27;
      const row = c.yearly[yr];
      const totalValK = getVal(c);
      if (totalValK <= 0) return;

      // Power-law compression so smaller European & APAC countries still render tall, distinct category stacks
      const totalH = Math.max(0.28, Math.pow(Math.min(totalValK, maxK * 1.4) / maxK, 0.56) * maxBarH);

      const barGrp = new THREE.Group();
      barGrp.position.set(cx, baseY, cz);

      // Luminous base pedestal ring on country surface
      const ringGeo = new THREE.RingGeometry(colWidth * 0.62, colWidth * 0.88, 28);
      ringGeo.rotateX(-Math.PI / 2);
      const ringMat = new THREE.MeshBasicMaterial({
        color: isSelected ? 0xff784f : 0xf4f2ec,
        transparent: true,
        opacity: isSelected ? 0.92 : inRegion ? 0.42 : 0.14,
        side: THREE.DoubleSide,
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.position.y = 0.008;
      barGrp.add(ringMesh);

      const stackWrap = new THREE.Group();
      stackWrap.scale.y = 0.05; // Smooth rise-in animation
      barGrp.add(stackWrap);

      const segMeshes = [];
      let topLocalY = totalH;

      if (activeCat !== "all") {
        // Focused single bike category prism
        const geo = new THREE.BoxGeometry(colWidth, totalH, colWidth);
        const mat = new THREE.MeshStandardMaterial({
          color: CAT_HEX[activeCat] || 0xe2552d,
          roughness: 0.26,
          metalness: 0.18,
          emissive: CAT_HEX[activeCat] || 0xe2552d,
          emissiveIntensity: isSelected ? 0.36 : 0.18,
          transparent: !inRegion,
          opacity: inRegion ? 0.96 : 0.34,
        });
        const m = new THREE.Mesh(geo, mat);
        m.position.y = totalH / 2;
        m.castShadow = true;
        m.receiveShadow = true;
        m.userData = { country: c };
        stackWrap.add(m);
        segMeshes.push(m);
        pickables.push(m);
      } else if (barStyle === "grouped") {
        // Grouped 4+1 side-by-side mini category columns (ebike, mtb, road, city, other)
        const cats = CAT_ORDER;
        const maxCatK = Math.max(...cats.map((cid) => row[`${cid}_k`] || 0), 1);
        const miniW = colWidth * 0.34;
        const gap = miniW * 0.24;
        const offsets = [
          [-miniW - gap / 2, -miniW * 0.65],
          [0, -miniW * 0.65],
          [miniW + gap / 2, -miniW * 0.65],
          [-miniW * 0.55, miniW * 0.65],
          [miniW * 0.55, miniW * 0.65],
        ];
        let tallest = 0.25;
        cats.forEach((cid, idx) => {
          const v = row[`${cid}_k`] || 0;
          const h = Math.max(0.08, (v / maxCatK) * totalH);
          if (h > tallest) tallest = h;
          const geo = new THREE.BoxGeometry(miniW, h, miniW);
          const mat = new THREE.MeshStandardMaterial({
            color: CAT_HEX[cid],
            roughness: 0.28,
            metalness: 0.16,
            emissive: CAT_HEX[cid],
            emissiveIntensity: isSelected ? 0.32 : 0.15,
            transparent: !inRegion,
            opacity: inRegion ? 0.96 : 0.32,
          });
          const m = new THREE.Mesh(geo, mat);
          m.position.set(offsets[idx][0], h / 2, offsets[idx][1]);
          m.castShadow = true;
          m.receiveShadow = true;
          m.userData = { country: c };
          stackWrap.add(m);
          segMeshes.push(m);
          pickables.push(m);
        });
        topLocalY = tallest;
      } else {
        // Stacked 5-tier 3D Category Prism Column (default — ultra-crisp, zero cross-country collision!)
        let curY = 0;
        const gapY = Math.min(0.025, totalH * 0.015);
        CAT_ORDER.forEach((cid) => {
          const v = row[`${cid}_k`] || 0;
          if (v <= 0) return;
          const segH = Math.max(0.035, (v / totalValK) * totalH - gapY);
          const geo = new THREE.BoxGeometry(colWidth, segH, colWidth);
          const mat = new THREE.MeshStandardMaterial({
            color: CAT_HEX[cid],
            roughness: 0.26,
            metalness: 0.16,
            emissive: CAT_HEX[cid],
            emissiveIntensity: isSelected ? 0.32 : 0.16,
            transparent: !inRegion,
            opacity: inRegion ? 0.97 : 0.32,
          });
          const m = new THREE.Mesh(geo, mat);
          m.position.y = curY + segH / 2;
          m.castShadow = true;
          m.receiveShadow = true;
          m.userData = { country: c };
          stackWrap.add(m);

          // Crisp hairline top bezel on e-Bike & top segments for architectural sharpness
          const edgeGeo = new THREE.EdgesGeometry(geo);
          const edgeMat = new THREE.LineBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: isSelected ? 0.38 : 0.16,
          });
          const wire = new THREE.LineSegments(edgeGeo, edgeMat);
          wire.position.copy(m.position);
          stackWrap.add(wire);

          segMeshes.push(m);
          pickables.push(m);
          curY += segH + gapY;
        });
        topLocalY = curY;
      }

      this.barRoot.add(barGrp);

      // Create floating 2D DOM label above column top
      const labelEl = document.createElement("button");
      labelEl.type = "button";
      labelEl.className = `map3d-label ${isSelected ? "selected" : ""} ${inRegion ? "" : "dimmed"}`;
      const wanStr = `${(totalValK / 10).toFixed(1)}萬`;
      const subStr =
        state.mapMetric === "volume"
          ? `⚡${row.ebike_share_pct}%`
          : formatMetricVal(c);
      labelEl.innerHTML = `<span class="m3d-lbl-name">${c.name_zh}</span><span class="m3d-lbl-val">${wanStr}</span><span class="m3d-lbl-sub">${subStr}</span>`;
      labelEl.addEventListener("mouseenter", (evt) => this.callbacks.onHover?.(evt, c));
      labelEl.addEventListener("mousemove", (evt) => this.callbacks.onHover?.(evt, c));
      labelEl.addEventListener("mouseleave", () => this.callbacks.onLeave?.());
      labelEl.addEventListener("click", (evt) => {
        evt.stopPropagation();
        this.callbacks.onSelect?.(c);
      });
      this.labelsLayer.appendChild(labelEl);

      this.barEntries.push({
        country: c,
        barGrp,
        stackWrap,
        segMeshes,
        ringMat,
        topWorld: new THREE.Vector3(cx, baseY + topLocalY + 0.16, cz),
        labelEl,
        priority: isSelected ? 1e9 : totalValK,
        inViewRegion: state.mapView === "all" || c.region === state.mapView,
      });
    });

    this._pickables = pickables;
    this._refreshHighlights();
    this.start();
  }

  _refreshHighlights() {
    this.countryMeshes.forEach((entry, iso2) => {
      const isSel = iso2 === this.selectedIso;
      const isHov = iso2 === this.hoveredIso;
      entry.mat.emissive.setHex(isSel ? 0xc84b28 : isHov ? 0x4b7ea6 : 0x000000);
      entry.mat.emissiveIntensity = isSel ? 0.42 : isHov ? 0.34 : 0;
      entry.edgeMat.color.setHex(isSel ? 0xffa685 : isHov ? 0xffffff : 0x8ea9c2);
      entry.edgeMat.opacity = isSel || isHov ? 0.98 : 0.65;
    });
    this.barEntries.forEach((b) => {
      const isHov = b.country.iso2 === this.hoveredIso;
      const isSel = b.country.iso2 === this.selectedIso;
      b.labelEl.classList.toggle("hovered", isHov);
      b.labelEl.classList.toggle("selected", isSel);
      b.ringMat.opacity = isSel ? 0.95 : isHov ? 0.85 : 0.38;
    });
  }

  setView(mapView, instant = false) {
    this.currentView = mapView;
    const preset = getCameraPreset(mapView);
    if (instant) {
      this.camera.position.copy(preset.pos);
      this.controls.target.copy(preset.target);
      this.controls.update();
      this.camLerp = null;
      return;
    }
    this.camLerp = {
      startPos: this.camera.position.clone(),
      endPos: preset.pos.clone(),
      startTarget: this.controls.target.clone(),
      endTarget: preset.target.clone(),
      t: 0,
    };
  }

  resize() {
    if (this.disposed) return;
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  _updateLabels() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (!w || !h) return;

    const proj = new THREE.Vector3();
    const placedBoxes = [];

    // Sort so selected & larger countries win label visibility if crowded
    const ordered = [...this.barEntries].sort((a, b) => b.priority - a.priority);

    for (const b of ordered) {
      if (!b.inViewRegion) {
        b.labelEl.style.display = "none";
        continue;
      }
      proj.copy(b.topWorld).project(this.camera);
      if (proj.z > 1 || proj.z < -1) {
        b.labelEl.style.display = "none";
        continue;
      }
      const sx = (proj.x * 0.5 + 0.5) * w;
      const sy = (-proj.y * 0.5 + 0.5) * h;
      if (sx < 24 || sx > w - 24 || sy < 18 || sy > h - 26) {
        b.labelEl.style.display = "none";
        continue;
      }

      // Simple collision check to keep Europe & global view crisp
      const boxW = 92;
      const boxH = 24;
      const box = { l: sx - boxW / 2, r: sx + boxW / 2, t: sy - boxH, b: sy };
      const collides =
        b.country.iso2 !== this.selectedIso &&
        b.country.iso2 !== this.hoveredIso &&
        placedBoxes.some(
          (p) => !(box.r < p.l || box.l > p.r || box.b < p.t || box.t > p.b)
        );

      if (collides) {
        b.labelEl.style.display = "none";
      } else {
        placedBoxes.push(box);
        b.labelEl.style.display = "inline-flex";
        b.labelEl.style.transform = `translate(-50%, -100%) translate(${sx.toFixed(1)}px, ${sy.toFixed(1)}px)`;
      }
    }
  }

  start() {
    if (this.animating || this.disposed) return;
    this.animating = true;
    const tick = () => {
      if (this.disposed || !this.animating) return;
      this.rafId = requestAnimationFrame(tick);

      // Skip GPU work when container is hidden
      if (this.container.offsetParent === null) return;

      // Smooth rise-in animation for 3D columns
      for (const b of this.barEntries) {
        if (b.stackWrap.scale.y < 0.999) {
          b.stackWrap.scale.y += (1 - b.stackWrap.scale.y) * 0.14;
          if (1 - b.stackWrap.scale.y < 0.002) b.stackWrap.scale.y = 1;
        }
      }

      // Smooth cubic camera fly-to
      if (this.camLerp) {
        this.camLerp.t = Math.min(1, this.camLerp.t + 0.045);
        const ease = 1 - Math.pow(1 - this.camLerp.t, 3);
        this.camera.position.lerpVectors(this.camLerp.startPos, this.camLerp.endPos, ease);
        this.controls.target.lerpVectors(this.camLerp.startTarget, this.camLerp.endTarget, ease);
        if (this.camLerp.t >= 1) this.camLerp = null;
      }

      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      this._updateLabels();
    };
    tick();
  }

  stop() {
    this.animating = false;
    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
  }

  dispose() {
    this.disposed = true;
    this.stop();
    this.resizeObserver?.disconnect();
    const dom = this.renderer?.domElement;
    if (dom) {
      dom.removeEventListener("pointermove", this._onPointerMove);
      dom.removeEventListener("pointerdown", this._onPointerDown);
      dom.removeEventListener("pointerup", this._onPointerUp);
      dom.removeEventListener("pointerleave", this._onPointerLeave);
    }
    this._clearBars();
    this.controls?.dispose();
    this.renderer?.dispose();
    this.container.innerHTML = "";
  }
}
