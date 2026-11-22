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

    const v = (arr) => new THREE.Vector3(arr[0], arr[1], arr[2]);
    const ra = v(anchors.rear_axle);
    const fa = v(anchors.front_axle);
    const bb = v(anchors.bb);
    const htTop = v(anchors.headtube_top);
    const htBot = v(anchors.headtube_bottom);
    const stTop = v(anchors.seattube_top);

    const zPlane = 0.24; // Offset slightly in front of drive-side for crisp legibility
    const addLine = (p0, p1, color = 0xc84b28, dashed = false) => {
      const g = new THREE.BufferGeometry().setFromPoints([p0, p1]);
      const mat = dashed
        ? new THREE.LineDashedMaterial({ color, dashSize: 0.025, gapSize: 0.015 })
        : new THREE.LineBasicMaterial({ color });
      const line = new THREE.Line(g, mat);
      if (dashed) line.computeLineDistances();
      this.cadOverlayGroup.add(line);
    };

    const addNode = (p, color = 0xc84b28) => {
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.011, 12, 12),
        new THREE.MeshBasicMaterial({ color })
      );
      dot.position.copy(p);
      this.cadOverlayGroup.add(dot);
    };

    // Wheelbase dimension line near ground
    const wb0 = new THREE.Vector3(ra.x, 0.035, zPlane);
    const wb1 = new THREE.Vector3(fa.x, 0.035, zPlane);
    addLine(wb0, wb1, 0x171715);
    addLine(new THREE.Vector3(ra.x, 0.01, zPlane), new THREE.Vector3(ra.x, ra.y, zPlane), 0x171715, true);
    addLine(new THREE.Vector3(fa.x, 0.01, zPlane), new THREE.Vector3(fa.x, fa.y, zPlane), 0x171715, true);

    // Stack (vertical from BB to HT top Y) and Reach (horizontal from BB X to HT top X)
    const bbZ = new THREE.Vector3(bb.x, bb.y, zPlane);
    const cornerZ = new THREE.Vector3(bb.x, htTop.y, zPlane);
    const htTopZ = new THREE.Vector3(htTop.x, htTop.y, zPlane);
    addLine(bbZ, cornerZ, 0x1d634f); // Stack
    addLine(cornerZ, htTopZ, 0xc84b28); // Reach
    addNode(bbZ, 0x1d634f);
    addNode(htTopZ, 0xc84b28);

    // Chainstay line (RA -> BB)
    const raZ = new THREE.Vector3(ra.x, ra.y, zPlane);
    addLine(raZ, bbZ, 0x996515, true);
    addNode(raZ, 0x996515);

    // Head tube & Seat tube angle axes
    const htDir = htBot.clone().sub(htTop).normalize();
    addLine(
      htTop.clone().addScaledVector(htDir, -0.08).setZ(zPlane),
      htBot.clone().addScaledVector(htDir, 0.22).setZ(zPlane),
      0xc84b28,
      true
    );
    const stDir = stTop.clone().sub(bb).normalize();
    addLine(
      bbZ,
      stTop.clone().addScaledVector(stDir, 0.14).setZ(zPlane),
      0x1d634f,
      true
    );

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
      } else {
        const orig = this.originalMaterials.get(obj.uuid);
        if (orig) obj.material = orig;
      }
    });
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
      side_drive: { pos: [0.0, 0.60, 3.15], target: [0.0, 0.56, 0.0], ortho: 1.55 },
      side_brake: { pos: [0.0, 0.60, -3.15], target: [0.0, 0.56, 0.0], ortho: 1.55 },
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
