import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

/**
 * Parametric 3D Bicycle Studio Inspector (Three.js).
 * Features warm neutral cyclorama, studio PMREM reflections, 7 orthographic/perspective
 * inspection views, Clay/Wireframe/PBR modes, and live 3D CAD geometry dimension overlays.
 */
export class BikeStudioViewer {
  constructor(containerEl, loadingEl) {
    this.container = containerEl;
    this.loadingEl = loadingEl;
    this.scene = new THREE.Scene();
    this.scene.background = null; // CSS radial cyclorama backdrop shines cleanly

    this.width = containerEl.clientWidth || 720;
    this.height = containerEl.clientHeight || 490;
    this.aspect = this.width / Math.max(1, this.height);

    // Dual cameras (Perspective & Orthographic)
    this.perspCam = new THREE.PerspectiveCamera(34, this.aspect, 0.01, 60);
    this.orthoFrustum = 1.65;
    this.orthoCam = new THREE.OrthographicCamera(
      (-this.orthoFrustum * this.aspect) / 2,
      (this.orthoFrustum * this.aspect) / 2,
      this.orthoFrustum / 2,
      -this.orthoFrustum / 2,
      0.01,
      60
    );
    this.isOrtho = false;
    this.camera = this.perspCam;

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(this.width, this.height);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(this.renderer.domElement);

    // PMREM studio environment for crisp metallic reflections on rotors, Kashima & alloy
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();

    // 3-point soft studio lighting (Key, Fill, Rim)
    const hemi = new THREE.HemisphereLight(0xfaf8f2, 0xc9c3b8, 0.9);
    this.scene.add(hemi);

    const keyLight = new THREE.DirectionalLight(0xfffcf5, 1.85);
    keyLight.position.set(2.2, 4.0, 3.4);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(2048, 2048);
    keyLight.shadow.camera.near = 0.5;
    keyLight.shadow.camera.far = 14;
    keyLight.shadow.camera.left = -1.8;
    keyLight.shadow.camera.right = 1.8;
    keyLight.shadow.camera.top = 1.8;
    keyLight.shadow.camera.bottom = -1.8;
    keyLight.shadow.bias = -0.0004;
    keyLight.shadow.radius = 3;
    this.scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xeef2f7, 0.72);
    fillLight.position.set(-2.4, 2.4, -2.2);
    this.scene.add(fillLight);

    const rimLight = new THREE.DirectionalLight(0xffffff, 0.95);
    rimLight.position.set(0.4, 3.2, -3.5);
    this.scene.add(rimLight);

    // Subtle ground contact shadow receiver plane (Y=0)
    const groundGeo = new THREE.PlaneGeometry(12, 12);
    const groundMat = new THREE.ShadowMaterial({ opacity: 0.22 });
    this.ground = new THREE.Mesh(groundGeo, groundMat);
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.position.y = 0.0;
    this.ground.receiveShadow = true;
    this.scene.add(this.ground);

    // Subtle circular turntable hairline
    const ringGeo = new THREE.RingGeometry(1.06, 1.072, 96);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x171715,
      opacity: 0.09,
      transparent: true,
      side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.001;
    this.scene.add(ring);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minDistance = 0.35;
    this.controls.maxDistance = 8.0;

    this.loader = new GLTFLoader();
    this.modelRoot = null;
    this.cadOverlayGroup = new THREE.Group();
    this.scene.add(this.cadOverlayGroup);

    this.originalMaterials = new Map();
    this.clayMaterial = new THREE.MeshStandardMaterial({
      color: 0xd9d4ca,
      roughness: 0.78,
      metalness: 0.04,
    });
    this.wireMaterial = new THREE.MeshBasicMaterial({
      color: 0x262623,
      wireframe: true,
    });
    this.xrayMaterial = new THREE.MeshStandardMaterial({
      color: 0xd9481f,
      roughness: 0.45,
      metalness: 0.15,
      transparent: true,
      opacity: 0.52,
      depthWrite: false,
    });

    // 1:1 metric calibrated side-profile photo plane (world meters, X in [-1.25, +1.25], Y in [-0.12, +1.43])
    this.texLoader = new THREE.TextureLoader();
    this.photoPlaneMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    this.photoPlane = new THREE.Mesh(new THREE.PlaneGeometry(2.5, 1.55), this.photoPlaneMat);
    this.photoPlane.position.set(0.0, 0.655, -0.36);
    this.photoPlane.visible = false;
    this.photoPlane.renderOrder = -1;
    this.scene.add(this.photoPlane);

    this.renderMode = "pbr";
    this.cadVisible = true;
    this.currentPreset = "side_drive";

    this._onResize = this._handleResize.bind(this);
    window.addEventListener("resize", this._onResize);
    this._animate();
  }

  _handleResize() {
    const w = this.container.clientWidth || 720;
    const h = this.container.clientHeight || 490;
    this.width = w;
    this.height = h;
    this.aspect = w / Math.max(1, h);
    this.perspCam.aspect = this.aspect;
    this.perspCam.updateProjectionMatrix();
    this._updateOrthoFrustum();
    this.renderer.setSize(w, h);
  }

  _updateOrthoFrustum() {
    this.orthoCam.left = (-this.orthoFrustum * this.aspect) / 2;
    this.orthoCam.right = (this.orthoFrustum * this.aspect) / 2;
    this.orthoCam.top = this.orthoFrustum / 2;
    this.orthoCam.bottom = -this.orthoFrustum / 2;
    this.orthoCam.updateProjectionMatrix();
  }

  async loadBike(glbUrl, anchors3d, geo) {
    if (this.loadingEl) {
      this.loadingEl.textContent = "正在載入 3D GLB 模型...";
      this.loadingEl.classList.remove("hidden");
    }

    // Clear previous model
    if (this.modelRoot) {
      this.scene.remove(this.modelRoot);
      this.modelRoot.traverse((obj) => {
        if (obj.isMesh) {
          obj.geometry?.dispose();
        }
      });
      this.modelRoot = null;
      this.originalMaterials.clear();
    }

    try {
      const gltf = await this.loader.loadAsync(glbUrl);
      this.modelRoot = gltf.scene;
      this.modelRoot.traverse((obj) => {
        if (obj.isMesh) {
          obj.castShadow = true;
          obj.receiveShadow = true;
          this.originalMaterials.set(obj.uuid, obj.material);
        }
      });
      this.scene.add(this.modelRoot);
      this.setRenderMode(this.renderMode);
      this._buildCadOverlay(anchors3d, geo);
      this.setCameraPreset(this.currentPreset);
      if (this.loadingEl) this.loadingEl.classList.add("hidden");
    } catch (err) {
      console.error("GLB load failed:", err);
      if (this.loadingEl) {
        this.loadingEl.textContent = `3D 模型載入失敗 (${err.message || err})`;
      }
    }
  }

  _buildCadOverlay(anchors, geo) {
    while (this.cadOverlayGroup.children.length > 0) {
      const c = this.cadOverlayGroup.children.pop();
      c.geometry?.dispose();
      c.material?.dispose();
    }
    if (!anchors || !geo) return;

    // Place ALL CAD geometry strictly on the true bike centerline plane (Z = 0)
    // with depthTest=false so there is ZERO perspective parallax error from any camera angle!
    const v0 = (arr) => new THREE.Vector3(arr[0], arr[1], 0.0);
    const ra = v0(anchors.rear_axle);
    const fa = v0(anchors.front_axle);
    const bb = v0(anchors.bb);
    const htTop = v0(anchors.headtube_top);
    const htBot = v0(anchors.headtube_bottom);
    const stTop = v0(anchors.seattube_top);

    const addLine = (p0, p1, color = 0xc84b28, dashed = false, opacity = 0.92) => {
      const g = new THREE.BufferGeometry().setFromPoints([p0, p1]);
      const mat = dashed
        ? new THREE.LineDashedMaterial({
            color,
            dashSize: 0.024,
            gapSize: 0.014,
            transparent: true,
            opacity,
            depthTest: false,
            depthWrite: false,
          })
        : new THREE.LineBasicMaterial({
            color,
            transparent: true,
            opacity,
            depthTest: false,
            depthWrite: false,
          });
      const line = new THREE.Line(g, mat);
      if (dashed) line.computeLineDistances();
      line.renderOrder = 10;
      this.cadOverlayGroup.add(line);
    };

    const addNode = (p, color = 0xc84b28, radius = 0.010) => {
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(radius, 14, 14),
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.96,
          depthTest: false,
          depthWrite: false,
        })
      );
      dot.position.copy(p);
      dot.renderOrder = 11;
      this.cadOverlayGroup.add(dot);
    };

    const addCrosshair = (p, color = 0x171715, half = 0.022) => {
      addLine(new THREE.Vector3(p.x - half, p.y, 0), new THREE.Vector3(p.x + half, p.y, 0), color, false, 0.95);
      addLine(new THREE.Vector3(p.x, p.y - half, 0), new THREE.Vector3(p.x, p.y + half, 0), color, false, 0.95);
      addNode(p, color, 0.0085);
    };

    // 1. Wheelbase (WB): strictly locked to exact Rear Axle & Front Axle centers (Z=0)
    const wbY = 0.028;
    addLine(new THREE.Vector3(ra.x, wbY, 0), new THREE.Vector3(fa.x, wbY, 0), 0x171715, false, 0.95);
    // Crisp end ticks on Wheelbase dimension line
    addLine(new THREE.Vector3(ra.x, wbY - 0.016, 0), new THREE.Vector3(ra.x, wbY + 0.016, 0), 0x171715, false, 0.95);
    addLine(new THREE.Vector3(fa.x, wbY - 0.016, 0), new THREE.Vector3(fa.x, wbY + 0.016, 0), 0x171715, false, 0.95);
    // Vertical extension lines dropping directly from true rear & front hub centers
    addLine(new THREE.Vector3(ra.x, wbY, 0), ra, 0x171715, true, 0.72);
    addLine(new THREE.Vector3(fa.x, wbY, 0), fa, 0x171715, true, 0.72);
    addCrosshair(ra, 0x171715);
    addCrosshair(fa, 0x171715);

    // 2. Axle Datum Line & BB Drop reference
    addLine(ra, fa, 0x5c6773, true, 0.40);
    const axleMidY = 0.5 * (ra.y + fa.y);
    addLine(new THREE.Vector3(bb.x, axleMidY, 0), bb, 0x5c6773, false, 0.78);

    // 3. Stack (vertical BB -> HT top Y) & Reach (horizontal BB X -> HT top X)
    const corner = new THREE.Vector3(bb.x, htTop.y, 0);
    addLine(bb, corner, 0x1d634f, false, 0.95); // Stack
    addLine(corner, htTop, 0xc84b28, false, 0.95); // Reach
    // Small right-angle corner symbol at (bb.x, htTop.y)
    const sq = 0.022;
    addLine(new THREE.Vector3(bb.x + sq, htTop.y, 0), new THREE.Vector3(bb.x + sq, htTop.y - sq, 0), 0x55534c, false, 0.75);
    addLine(new THREE.Vector3(bb.x, htTop.y - sq, 0), new THREE.Vector3(bb.x + sq, htTop.y - sq, 0), 0x55534c, false, 0.75);
    addNode(bb, 0x1d634f, 0.010);
    addNode(htTop, 0xc84b28, 0.010);
    addNode(htBot, 0xc84b28, 0.0075);

    // 4. Chainstay (exact Rear Axle -> BB centerline)
    addLine(ra, bb, 0x996515, true, 0.92);

    // 5. Head Tube Angle (HTA) Steering Axis extending dead-center from steerer all the way to ground (Y=0)
    //    + perpendicular Fork Offset (Rake) tick directly to exact Front Axle center!
    const htDir = htBot.clone().sub(htTop).normalize();
    const tGround = htDir.y < -1e-4 ? htTop.y / -htDir.y : 1.0;
    const pHtGround = htTop.clone().addScaledVector(htDir, tGround);
    const pHtUpper = htTop.clone().addScaledVector(htDir, -0.10);
    addLine(pHtUpper, pHtGround, 0xc84b28, true, 0.92);
    // Horizontal ground angle baseline at HTA ground intersection
    addLine(pHtGround, new THREE.Vector3(pHtGround.x - 0.16, 0.0, 0), 0xc84b28, false, 0.65);
    // Exact perpendicular projection of Front Axle onto steering axis -> shows exact Fork Offset (Rake)!
    const sProj = fa.clone().sub(htTop).dot(htDir);
    const pSteerNearAxle = htTop.clone().addScaledVector(htDir, sProj);
    addLine(pSteerNearAxle, fa, 0xc84b28, false, 0.95);

    // 6. Seat Tube Angle (STA) Axis extending dead-center from BB through Seat Tube & Seatpost
    const stDir = stTop.clone().sub(bb).normalize();
    addLine(bb, stTop.clone().addScaledVector(stDir, 0.26), 0x1d634f, true, 0.92);
    // Short horizontal STA reference tick at BB
    addLine(bb, new THREE.Vector3(bb.x - 0.12, bb.y, 0), 0x1d634f, false, 0.65);

    this.cadOverlayGroup.visible = this.cadVisible;
  }

  setRenderMode(mode) {
    this.renderMode = mode;
    if (!this.modelRoot) return;
    this.modelRoot.traverse((obj) => {
      if (!obj.isMesh) return;
      if (mode === "clay") {
        obj.material = this.clayMaterial;
      } else if (mode === "wire") {
        obj.material = this.wireMaterial;
      } else if (mode === "xray") {
        obj.material = this.xrayMaterial;
      } else {
        const orig = this.originalMaterials.get(obj.uuid);
        if (orig) obj.material = orig;
      }
    });
  }

  setPhotoOverlay(visible, calibratedUrl, bounds) {
    if (!visible || !calibratedUrl) {
      this.photoPlane.visible = false;
      return;
    }
    if (bounds && bounds.width_m && bounds.height_m) {
      this.photoPlane.geometry?.dispose();
      this.photoPlane.geometry = new THREE.PlaneGeometry(bounds.width_m, bounds.height_m);
      this.photoPlane.position.set(bounds.center_x || 0.0, bounds.center_y || 0.655, -0.36);
    }
    this.texLoader.load(
      calibratedUrl,
      (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        if (this.photoPlaneMat.map) this.photoPlaneMat.map.dispose();
        this.photoPlaneMat.map = tex;
        this.photoPlaneMat.needsUpdate = true;
        this.photoPlane.visible = true;
      },
      undefined,
      () => {
        this.photoPlane.visible = false;
      }
    );
  }

  setCadOverlay(visible) {
    this.cadVisible = visible;
    this.cadOverlayGroup.visible = visible;
  }

  setProjection(useOrtho) {
    if (this.isOrtho === useOrtho) return;
    const pos = this.camera.position.clone();
    const target = this.controls.target.clone();
    this.isOrtho = useOrtho;
    this.camera = useOrtho ? this.orthoCam : this.perspCam;
    this.camera.position.copy(pos);
    this.controls.object = this.camera;
    this.controls.target.copy(target);
    this._updateOrthoFrustum();
    this.controls.update();
  }

  setCameraPreset(presetName) {
    this.currentPreset = presetName;
    // 7-view studio inspection rig mapped cleanly to glTF Y-up (+X forward, +Z drive side)
    const presets = {
      side_drive: { pos: [0.0, 0.60, 3.15], target: [0.0, 0.60, 0.0], ortho: 1.55 },
      side_brake: { pos: [0.0, 0.60, -3.15], target: [0.0, 0.60, 0.0], ortho: 1.55 },
      front: { pos: [2.85, 0.65, 0.0], target: [0.18, 0.58, 0.0], ortho: 1.35 },
      rear: { pos: [-2.85, 0.65, 0.0], target: [-0.18, 0.58, 0.0], ortho: 1.35 },
      front_45: { pos: [2.15, 1.05, 2.25], target: [0.02, 0.54, 0.0], ortho: 1.65 },
      rear_45: { pos: [-2.15, 1.05, -2.15], target: [-0.02, 0.54, 0.0], ortho: 1.65 },
      cockpit: { pos: [-0.05, 1.55, 0.72], target: [0.32, 0.96, 0.0], ortho: 0.95 },
    };
    const p = presets[presetName] || presets.side_drive;
    this.orthoFrustum = p.ortho;
    this._updateOrthoFrustum();
    this.camera.position.set(p.pos[0], p.pos[1], p.pos[2]);
    this.controls.target.set(p.target[0], p.target[1], p.target[2]);
    this.controls.update();
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
