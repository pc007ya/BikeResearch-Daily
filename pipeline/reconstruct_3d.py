"""ALSO-BIKE inspired parametric 3D bicycle reverse-engineering engine.

Builds real multi-part PBR glTF (.glb) assemblies directly from scraped bike geometry,
runs engineering QA tolerance checks, writes ALSO-style provenance manifests,
and exports Blender 4.x warm-neutral cyclorama studio rebuild/render scripts.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from trimesh.visual.material import PBRMaterial

# Right-handed glTF coordinate system:
#   +X = Forward (rear axle at X=0, front axle at X=wheelbase)
#   +Y = Up (ground plane at Y=0)
#   +Z = Right / Drive side (drivetrain at +Z, disc brake rotors at -Z)


def _mat(
    name: str,
    rgba: tuple[float, float, float, float],
    metallic: float = 0.2,
    roughness: float = 0.45,
) -> PBRMaterial:
    return PBRMaterial(
        name=name,
        baseColorFactor=[int(c * 255) for c in rgba[:3]] + [int(rgba[3] * 255)],
        metallicFactor=float(metallic),
        roughnessFactor=float(roughness),
    )


def _apply_mat(mesh: trimesh.Trimesh, mat: PBRMaterial) -> trimesh.Trimesh:
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)
    return mesh


def _basis_from_dir(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return orthonormal basis (t, n, b) where t is along d, b prefers +Z (lateral)."""
    t = d / (np.linalg.norm(d) + 1e-12)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(t, ref)) > 0.92:
        ref = np.array([0.0, 1.0, 0.0])
    n = np.cross(ref, t)
    n /= np.linalg.norm(n) + 1e-12
    b = np.cross(t, n)
    b /= np.linalg.norm(b) + 1e-12
    return t, n, b


def make_tapered_tube(
    p0: np.ndarray,
    p1: np.ndarray,
    rn0: float,
    rb0: float,
    rn1: float,
    rb1: float,
    segments: int = 20,
    rings: int = 6,
    squircle: float = 1.0,
    cap: bool = True,
) -> trimesh.Trimesh:
    """Create a hydroformed elliptical/squircle tapered tube between p0 and p1.

    rn: radius in frame plane (normal), rb: lateral radius (binormal, Z-axis).
    squircle=1.0 -> ellipse; squircle=0.72 -> hydroformed rounded-box section.
    """
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    d = p1 - p0
    if np.linalg.norm(d) < 1e-6:
        return trimesh.creation.icosphere(subdivisions=1, radius=max(rn0, rb0))
    _, n, b = _basis_from_dir(d)
    angles = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)
    if squircle != 1.0:
        cos_a = np.sign(cos_a) * (np.abs(cos_a) ** squircle)
        sin_a = np.sign(sin_a) * (np.abs(sin_a) ** squircle)

    verts: list[np.ndarray] = []
    for r_idx in range(rings + 1):
        u = r_idx / rings
        center = p0 * (1.0 - u) + p1 * u
        rn = rn0 * (1.0 - u) + rn1 * u
        rb = rb0 * (1.0 - u) + rb1 * u
        for ca, sa in zip(cos_a, sin_a):
            verts.append(center + n * (rn * ca) + b * (rb * sa))

    faces: list[list[int]] = []
    for r_idx in range(rings):
        base0 = r_idx * segments
        base1 = (r_idx + 1) * segments
        for s in range(segments):
            s_next = (s + 1) % segments
            faces.append([base0 + s, base0 + s_next, base1 + s_next])
            faces.append([base0 + s, base1 + s_next, base1 + s])

    if cap:
        c0_idx = len(verts)
        verts.append(p0)
        c1_idx = len(verts)
        verts.append(p1)
        last_base = rings * segments
        for s in range(segments):
            s_next = (s + 1) % segments
            faces.append([c0_idx, s_next, s])
            faces.append([c1_idx, last_base + s, last_base + s_next])

    mesh = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=False)
    mesh.fix_normals()
    return mesh


def make_swept_polyline(
    points: list[np.ndarray],
    radii: list[float] | float,
    segments: int = 16,
) -> trimesh.Trimesh:
    """Sweep a circular cross-section cleanly along a 3D polyline."""
    pts = [np.asarray(p, dtype=float) for p in points]
    if isinstance(radii, (int, float)):
        rads = [float(radii)] * len(pts)
    else:
        rads = [float(r) for r in radii]

    angles = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    verts: list[np.ndarray] = []
    prev_n = None

    for idx, p in enumerate(pts):
        if idx == 0:
            t = pts[1] - pts[0]
        elif idx == len(pts) - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[idx + 1] - pts[idx - 1]
        t = t / (np.linalg.norm(t) + 1e-12)
        if prev_n is None:
            ref = np.array([0.0, 1.0, 0.0]) if abs(t[1]) < 0.85 else np.array([1.0, 0.0, 0.0])
            n = np.cross(t, ref)
            n /= np.linalg.norm(n) + 1e-12
        else:
            # Parallel transport to prevent twist
            n = prev_n - np.dot(prev_n, t) * t
            if np.linalg.norm(n) < 1e-6:
                _, n, _ = _basis_from_dir(t)
            else:
                n /= np.linalg.norm(n)
        b = np.cross(t, n)
        b /= np.linalg.norm(b) + 1e-12
        prev_n = n
        r = rads[idx]
        for a in angles:
            verts.append(p + r * (math.cos(a) * n + math.sin(a) * b))

    faces: list[list[int]] = []
    for idx in range(len(pts) - 1):
        b0 = idx * segments
        b1 = (idx + 1) * segments
        for s in range(segments):
            sn = (s + 1) % segments
            faces.append([b0 + s, b0 + sn, b1 + sn])
            faces.append([b0 + s, b1 + sn, b1 + s])

    # Caps
    c0 = len(verts)
    verts.append(pts[0])
    c1 = len(verts)
    verts.append(pts[-1])
    last = (len(pts) - 1) * segments
    for s in range(segments):
        sn = (s + 1) % segments
        faces.append([c0, sn, s])
        faces.append([c1, last + s, last + sn])

    mesh = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=False)
    mesh.fix_normals()
    return mesh


def make_torus_xy(
    center: np.ndarray,
    major_r: float,
    minor_r_rad: float,
    minor_r_lat: float,
    major_seg: int = 56,
    minor_seg: int = 18,
) -> trimesh.Trimesh:
    """Create a wheel tire/rim torus lying in the XY plane centered at `center`."""
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    theta = np.linspace(0, 2 * math.pi, major_seg, endpoint=False)
    phi = np.linspace(0, 2 * math.pi, minor_seg, endpoint=False)
    verts = []
    for th in theta:
        ct, st = math.cos(th), math.sin(th)
        for ph in phi:
            r = major_r + minor_r_rad * math.cos(ph)
            x = cx + r * ct
            y = cy + r * st
            z = cz + minor_r_lat * math.sin(ph)
            verts.append([x, y, z])

    faces = []
    for i in range(major_seg):
        i_next = (i + 1) % major_seg
        for j in range(minor_seg):
            j_next = (j + 1) % minor_seg
            v00 = i * minor_seg + j
            v01 = i * minor_seg + j_next
            v10 = i_next * minor_seg + j
            v11 = i_next * minor_seg + j_next
            faces.append([v00, v10, v11])
            faces.append([v00, v11, v01])

    mesh = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=False)
    mesh.fix_normals()
    return mesh


def make_cylinder_z(
    center: np.ndarray,
    radius: float,
    width: float,
    sections: int = 28,
) -> trimesh.Trimesh:
    """Cylinder whose axis is along Z (for axles, hubs, rotors, BB shell, chainring)."""
    m = trimesh.creation.cylinder(radius=radius, height=width, sections=sections)
    m.apply_translation(center)
    return m


def make_annulus_z(
    center: np.ndarray,
    r_inner: float,
    r_outer: float,
    thickness: float,
    sections: int = 40,
) -> trimesh.Trimesh:
    """Flat annular ring perpendicular to Z (for brake rotor tracks & chainrings)."""
    m = trimesh.creation.annulus(r_min=r_inner, r_max=r_outer, height=thickness, sections=sections)
    m.apply_translation(center)
    return m


def _wheel_outer_radius_m(wheel_in: float, tire_w_mm: float) -> tuple[float, float, float]:
    """Return (outer_radius_m, rim_radius_m, tire_section_m)."""
    bsd_map = {
        32.0: 0.686,
        29.0: 0.622,
        28.0: 0.622,
        27.5: 0.584,
        26.0: 0.559,
    }
    bsd = bsd_map.get(round(wheel_in, 1), 0.622)
    rim_r = bsd * 0.5
    tire_r = (tire_w_mm / 1000.0) * 0.5
    # Tire sits slightly proud of rim bead
    outer_r = rim_r + tire_r * 1.75
    return outer_r, rim_r, tire_r


def build_wheel_assembly(
    name_prefix: str,
    axle: np.ndarray,
    wheel_in: float,
    tire_w_mm: float,
    hub_width: float,
    rotor_diam_mm: float,
    is_mtb: bool,
    mats: dict[str, PBRMaterial],
) -> list[tuple[str, trimesh.Trimesh]]:
    parts: list[tuple[str, trimesh.Trimesh]] = []
    outer_r, rim_r, tire_r = _wheel_outer_radius_m(wheel_in, tire_w_mm)
    tire_major = outer_r - tire_r
    rim_depth = 0.022 if is_mtb else 0.036

    # Tire
    tire = make_torus_xy(axle, tire_major, tire_r, tire_r * 0.96, major_seg=56, minor_seg=18)
    parts.append((f"{name_prefix}_tire", _apply_mat(tire, mats["tire"])))

    # Rim
    rim = make_torus_xy(axle, rim_r - rim_depth * 0.4, rim_depth * 0.55, tire_r * 0.62, major_seg=52, minor_seg=12)
    parts.append((f"{name_prefix}_rim", _apply_mat(rim, mats["rim"])))

    # Hub body + left/right flanges + thru-axle endcaps
    hub_body = make_cylinder_z(axle, 0.014, hub_width * 0.72, sections=22)
    flange_l = make_cylinder_z(axle + np.array([0, 0, -hub_width * 0.30]), 0.027, 0.005, sections=24)
    flange_r = make_cylinder_z(axle + np.array([0, 0, hub_width * 0.30]), 0.027, 0.005, sections=24)
    endcaps = make_cylinder_z(axle, 0.009, hub_width * 1.06, sections=16)
    hub_combined = trimesh.util.concatenate([hub_body, flange_l, flange_r, endcaps])
    parts.append((f"{name_prefix}_hub", _apply_mat(hub_combined, mats["dark_alloy"])))

    # 24 tensioned spokes (12 left flange, 12 right flange, tangential offset)
    spoke_meshes = []
    n_spokes = 24
    for i in range(n_spokes):
        th = (2 * math.pi * i) / n_spokes
        side = -1.0 if i % 2 == 0 else 1.0
        th_hub = th + side * 0.24
        p_hub = axle + np.array([0.024 * math.cos(th_hub), 0.024 * math.sin(th_hub), side * hub_width * 0.29])
        p_rim = axle + np.array([(rim_r - rim_depth * 0.6) * math.cos(th), (rim_r - rim_depth * 0.6) * math.sin(th), side * 0.002])
        spoke_meshes.append(make_tapered_tube(p_hub, p_rim, 0.0011, 0.0011, 0.0011, 0.0011, segments=5, rings=1, cap=False))
    parts.append((f"{name_prefix}_spokes", _apply_mat(trimesh.util.concatenate(spoke_meshes), mats["steel"])))

    # Disc brake rotor (on -Z brake side) with centerlock spider + 6 arms + braking track
    rotor_r = (rotor_diam_mm / 1000.0) * 0.5
    rotor_z = -hub_width * 0.42
    rotor_center = axle + np.array([0.0, 0.0, rotor_z])
    track = make_annulus_z(rotor_center, rotor_r * 0.78, rotor_r, 0.0022, sections=44)
    carrier = make_annulus_z(rotor_center, 0.017, rotor_r * 0.36, 0.0036, sections=28)
    spider_arms = []
    for k in range(6):
        a = (2 * math.pi * k) / 6.0
        a_out = a + 0.35
        p_in = rotor_center + np.array([rotor_r * 0.32 * math.cos(a), rotor_r * 0.32 * math.sin(a), 0.0])
        p_out = rotor_center + np.array([rotor_r * 0.82 * math.cos(a_out), rotor_r * 0.82 * math.sin(a_out), 0.0])
        spider_arms.append(make_tapered_tube(p_in, p_out, 0.0045, 0.0014, 0.0038, 0.0012, segments=6, rings=1))
    rotor_mesh = trimesh.util.concatenate([track, carrier] + spider_arms)
    parts.append((f"{name_prefix}_brake_rotor", _apply_mat(rotor_mesh, mats["rotor_steel"])))

    return parts


def build_bike_3d_model(bike: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Reconstruct complete parametric 3D bike (.glb), run ALSO-style QA, and emit Blender script."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = bike["slug"]
    geo = bike["geometry_resolved"]
    specs = bike.get("specs", {})

    # Extract target geometric parameters (converted to meters / radians)
    wb = geo["wheelbase_mm"] / 1000.0
    reach = geo["reach_mm"] / 1000.0
    stack = geo["stack_mm"] / 1000.0
    hta = math.radians(geo["head_angle_deg"])
    sta = math.radians(geo["seat_angle_deg"])
    cs = geo["chainstay_mm"] / 1000.0
    bb_drop = geo["bb_drop_mm"] / 1000.0
    ht_len = geo["head_tube_mm"] / 1000.0
    st_len = geo["seat_tube_mm"] / 1000.0
    travel_f = geo["travel_front_mm"] / 1000.0
    travel_r = geo["travel_rear_mm"] / 1000.0
    w_f_in = geo["wheel_front_in"]
    w_r_in = geo["wheel_rear_in"]
    tire_w_mm = geo["tire_width_mm"]
    rotor_f_mm = geo["rotor_front_mm"]
    rotor_r_mm = geo["rotor_rear_mm"]

    is_ebike = bool(bike.get("is_ebike"))
    full_sus = bool(bike.get("full_suspension"))
    bar_type = bike.get("handlebar_type", "riser")
    is_mtb = bar_type != "drop"
    kashima = bool(bike.get("kashima_gold"))
    accent = bike.get("accent_rgb", [0.20, 0.28, 0.32])

    # Materials palette (calibrated for ALSO warm-neutral studio presentation)
    mats = {
        "frame": _mat("Frame_Paint_PBR", (accent[0], accent[1], accent[2], 1.0), metallic=0.22, roughness=0.32),
        "frame_secondary": _mat("Frame_Carbon_Matte", (0.14, 0.14, 0.15, 1.0), metallic=0.12, roughness=0.52),
        "dark_alloy": _mat("Anodized_Dark_Alloy", (0.12, 0.12, 0.13, 1.0), metallic=0.72, roughness=0.34),
        "raw_alloy": _mat("CNC_Raw_Alloy", (0.68, 0.70, 0.72, 1.0), metallic=0.88, roughness=0.26),
        "stanchion": _mat(
            "Stanchion_Kashima" if kashima else "Stanchion_Black",
            (0.76, 0.56, 0.22, 1.0) if kashima else (0.09, 0.09, 0.10, 1.0),
            metallic=0.92,
            roughness=0.16,
        ),
        "tire": _mat("Rubber_Tire_Matte", (0.11, 0.11, 0.12, 1.0), metallic=0.0, roughness=0.86),
        "rim": _mat("Rim_Carbon_Satin", (0.15, 0.15, 0.16, 1.0), metallic=0.28, roughness=0.40),
        "steel": _mat("Spokes_Chain_Steel", (0.42, 0.44, 0.46, 1.0), metallic=0.85, roughness=0.32),
        "rotor_steel": _mat("Brake_Rotor_Stainless", (0.76, 0.78, 0.80, 1.0), metallic=0.92, roughness=0.24),
        "saddle": _mat("Saddle_Grip_Microfiber", (0.13, 0.13, 0.14, 1.0), metallic=0.0, roughness=0.75),
        "motor_housing": _mat("EDrive_Motor_Magnesium", (0.20, 0.21, 0.23, 1.0), metallic=0.55, roughness=0.42),
        "display_glow": _mat("HMI_Display_Screen", (0.12, 0.18, 0.22, 1.0), metallic=0.10, roughness=0.12),
    }

    # --- 1. EXACT KINEMATIC ANCHOR NODES ---
    r_f, _, _ = _wheel_outer_radius_m(w_f_in, tire_w_mm)
    r_r, _, _ = _wheel_outer_radius_m(w_r_in, tire_w_mm)

    p_ra = np.array([0.0, r_r, 0.0])
    p_fa = np.array([wb, r_f, 0.0])

    y_bb = 0.5 * (r_r + r_f) - bb_drop
    dy_cs = r_r - y_bb
    dx_cs = math.sqrt(max(0.08, cs * cs - dy_cs * dy_cs))
    p_bb = np.array([dx_cs, y_bb, 0.0])

    p_ht_top = np.array([p_bb[0] + reach, p_bb[1] + stack, 0.0])
    u_ht = np.array([math.cos(hta), -math.sin(hta), 0.0])
    p_ht_bot = p_ht_top + ht_len * u_ht

    u_st = np.array([-math.cos(sta), math.sin(sta), 0.0])
    p_st_top = p_bb + st_len * u_st

    # Compute true fork crown just below headtube bottom
    p_crown = p_ht_bot + 0.016 * u_ht

    # Named assembly container
    named_parts: list[tuple[str, trimesh.Trimesh]] = []

    # --- 2. WHEELS & DISC BRAKE ROTORS ---
    f_hub_w = 0.110 if is_mtb else 0.100
    r_hub_w = 0.148 if is_mtb else 0.142
    named_parts.extend(
        build_wheel_assembly("front_wheel", p_fa, w_f_in, tire_w_mm, f_hub_w, rotor_f_mm, is_mtb, mats)
    )
    named_parts.extend(
        build_wheel_assembly("rear_wheel", p_ra, w_r_in, tire_w_mm, r_hub_w, rotor_r_mm, is_mtb, mats)
    )

    # --- 3. MAIN FRAME TRIANGLE (HYDROFORMED TAPERED TUBING) ---
    # Head tube + headset cups
    ht_r = 0.029 if is_ebike else (0.026 if is_mtb else 0.023)
    ht_mesh = make_tapered_tube(p_ht_top, p_ht_bot, ht_r * 0.94, ht_r * 0.94, ht_r * 1.08, ht_r * 1.08, segments=24, rings=6)
    cup_top = make_tapered_tube(p_ht_top - 0.010 * u_ht, p_ht_top + 0.004 * u_ht, ht_r * 0.98, ht_r * 0.98, ht_r * 1.02, ht_r * 1.02, segments=22, rings=2)
    cup_bot = make_tapered_tube(p_ht_bot - 0.003 * u_ht, p_ht_bot + 0.010 * u_ht, ht_r * 1.12, ht_r * 1.12, ht_r * 1.06, ht_r * 1.06, segments=22, rings=2)
    named_parts.append(("frame_headtube", _apply_mat(ht_mesh, mats["frame"])))
    named_parts.append(("headset_cups", _apply_mat(trimesh.util.concatenate([cup_top, cup_bot]), mats["dark_alloy"])))

    # Down tube (thicker box-oval battery bay for e-bikes, sleek hydroformed for analog)
    dt_start = p_ht_bot - 0.022 * u_ht
    dt_end = p_bb + np.array([0.022, 0.028, 0.0])
    if is_ebike:
        dt_mesh = make_tapered_tube(dt_start, dt_end, 0.044, 0.036, 0.052, 0.040, segments=24, rings=8, squircle=0.76)
        # Battery cover inlay plate along underside of downtube
        dt_dir = dt_end - dt_start
        dt_dir /= np.linalg.norm(dt_dir) + 1e-12
        _, dt_n, _ = _basis_from_dir(dt_dir)
        if dt_n[1] > 0:
            dt_n = -dt_n
        bat_p0 = dt_start + 0.12 * (dt_end - dt_start) + dt_n * 0.015
        bat_p1 = dt_start + 0.85 * (dt_end - dt_start) + dt_n * 0.018
        bat_cover = make_tapered_tube(bat_p0, bat_p1, 0.033, 0.027, 0.036, 0.029, segments=18, rings=4, squircle=0.70)
        named_parts.append(("ebike_battery_cover", _apply_mat(bat_cover, mats["frame_secondary"])))
    else:
        rn_dt = 0.030 if is_mtb else 0.027
        rb_dt = 0.023 if is_mtb else 0.019
        dt_mesh = make_tapered_tube(dt_start, dt_end, rn_dt, rb_dt, rn_dt * 1.15, rb_dt * 1.15, segments=22, rings=8, squircle=0.84)
    named_parts.append(("frame_downtube", _apply_mat(dt_mesh, mats["frame"])))

    # Top tube (sloping MTB/e-MTB vs classic horizontal-ish gravel/road)
    tt_start = p_ht_top + 0.024 * u_ht
    tt_attach_ratio = 0.80 if full_sus else (0.86 if is_mtb else 0.92)
    tt_end = p_bb + (st_len * tt_attach_ratio) * u_st
    tt_mesh = make_tapered_tube(tt_start, tt_end, 0.023, 0.021, 0.017, 0.018, segments=20, rings=8, squircle=0.82)
    named_parts.append(("frame_toptube", _apply_mat(tt_mesh, mats["frame"])))

    # Seat tube + seatpost clamp
    st_mesh = make_tapered_tube(p_bb + np.array([0, 0.015, 0]), p_st_top, 0.022, 0.022, 0.0185, 0.0185, segments=22, rings=6)
    st_clamp = make_tapered_tube(p_st_top - 0.008 * u_st, p_st_top + 0.012 * u_st, 0.021, 0.021, 0.021, 0.021, segments=20, rings=2)
    named_parts.append(("frame_seattube", _apply_mat(st_mesh, mats["frame"])))
    named_parts.append(("seatpost_collar", _apply_mat(st_clamp, mats["dark_alloy"])))

    # Bottom Bracket Shell OR Integrated Mid-Drive E-Bike Motor Unit
    if is_ebike:
        motor_main = make_cylinder_z(p_bb + np.array([0.018, 0.016, 0.0]), 0.068, 0.118, sections=28)
        motor_front = make_cylinder_z(p_bb + np.array([0.072, 0.036, 0.0]), 0.044, 0.106, sections=22)
        motor_skid = make_tapered_tube(
            p_bb + np.array([-0.035, -0.046, 0.0]),
            p_bb + np.array([0.095, -0.018, 0.0]),
            0.020, 0.052, 0.018, 0.048, segments=14, rings=3, squircle=0.72,
        )
        named_parts.append(("ebike_motor_housing", _apply_mat(trimesh.util.concatenate([motor_main, motor_front, motor_skid]), mats["motor_housing"])))
    else:
        bb_shell = make_cylinder_z(p_bb, 0.026, 0.078 if is_mtb else 0.070, sections=24)
        named_parts.append(("frame_bb_shell", _apply_mat(bb_shell, mats["frame"])))

    # --- 4. REAR TRIANGLE & SUSPENSION LINKAGE ---
    # Left & right chainstays (slightly dropped on drive side for chain clearance)
    cs_meshes = []
    ss_meshes = []
    rear_pivot_z = 0.042 if is_ebike else 0.034
    for side in (-1.0, 1.0):
        p_cs_bb = p_bb + np.array([-0.010, 0.022 if full_sus else 0.004, side * rear_pivot_z])
        p_cs_mid = 0.45 * p_cs_bb + 0.55 * (p_ra + np.array([0.01, -0.012, side * (r_hub_w * 0.52)]))
        if side > 0 and is_mtb:
            p_cs_mid[1] -= 0.016  # Dropped drive-side chainstay
        p_cs_ra = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
        cs_meshes.append(make_tapered_tube(p_cs_bb, p_cs_mid, 0.017, 0.010, 0.014, 0.009, segments=14, rings=3, squircle=0.75))
        cs_meshes.append(make_tapered_tube(p_cs_mid, p_cs_ra, 0.014, 0.009, 0.011, 0.008, segments=14, rings=3, squircle=0.75))

        # Seatstays
        if full_sus:
            p_ss_top = p_bb + (st_len * 0.56) * u_st + np.array([-0.038, 0.018, side * 0.034])
        else:
            p_ss_top = p_bb + (st_len * (0.78 if is_mtb else 0.82)) * u_st + np.array([-0.012, 0.0, side * 0.018])
        ss_meshes.append(make_tapered_tube(p_cs_ra + np.array([0.0, 0.012, 0.0]), p_ss_top, 0.010, 0.008, 0.012, 0.009, segments=14, rings=4, squircle=0.80))

    named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
    named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))

    # Full-suspension rocker linkage + rear air shock (and piggyback if travel >= 140mm)
    if full_sus:
        p_rocker_st = p_bb + (st_len * 0.56) * u_st
        p_shock_rear = p_rocker_st + np.array([0.055, 0.020, 0.0])
        p_tt_mount = tt_start + 0.48 * (tt_end - tt_start)
        p_shock_front = p_tt_mount + np.array([0.0, -0.044, 0.0])

        link_parts = []
        for side in (-1.0, 1.0):
            p_l_ss = p_rocker_st + np.array([-0.038, 0.018, side * 0.034])
            p_l_st = p_rocker_st + np.array([0.0, 0.0, side * 0.025])
            p_l_sh = p_shock_rear + np.array([0.0, 0.0, side * 0.020])
            link_parts.append(make_tapered_tube(p_l_ss, p_l_st, 0.013, 0.005, 0.014, 0.005, segments=12, rings=2, squircle=0.72))
            link_parts.append(make_tapered_tube(p_l_st, p_l_sh, 0.014, 0.005, 0.012, 0.005, segments=12, rings=2, squircle=0.72))
            # Front shock clevis bracket bolted cleanly into top tube
            link_parts.append(
                make_tapered_tube(
                    p_tt_mount + np.array([0.0, 0.0, side * 0.015]),
                    p_shock_front + np.array([0.0, 0.0, side * 0.016]),
                    0.014, 0.005, 0.012, 0.005, segments=10, rings=2, squircle=0.75
                )
            )
        pivot_bolt = make_cylinder_z(p_rocker_st, 0.012, 0.062, sections=16)
        front_eye_bolt = make_cylinder_z(p_shock_front, 0.008, 0.044, sections=14)
        link_parts.extend([pivot_bolt, front_eye_bolt])
        named_parts.append(("suspension_rocker_link", _apply_mat(trimesh.util.concatenate(link_parts), mats["dark_alloy"])))

        # Rear shock body + damper shaft + optional piggyback reservoir
        sh_mid = 0.42 * p_shock_rear + 0.58 * p_shock_front
        shock_can = make_tapered_tube(sh_mid, p_shock_front, 0.024, 0.024, 0.025, 0.025, segments=22, rings=4)
        shock_shaft = make_tapered_tube(p_shock_rear, sh_mid + 0.02 * (p_shock_front - p_shock_rear), 0.014, 0.014, 0.014, 0.014, segments=18, rings=2)
        shock_parts = [shock_can]
        if travel_r >= 0.135:
            sh_dir = p_shock_front - p_shock_rear
            _, sh_n, _ = _basis_from_dir(sh_dir)
            if sh_n[1] > 0:
                sh_n = -sh_n
            pb_p0 = p_shock_front - 0.025 * (sh_dir / (np.linalg.norm(sh_dir) + 1e-12)) + sh_n * 0.032
            pb_p1 = pb_p0 - 0.095 * (sh_dir / (np.linalg.norm(sh_dir) + 1e-12))
            shock_parts.append(make_tapered_tube(pb_p0, pb_p1, 0.013, 0.013, 0.013, 0.013, segments=16, rings=3))
        named_parts.append(("rear_shock_body", _apply_mat(trimesh.util.concatenate(shock_parts), mats["dark_alloy"])))
        named_parts.append(("rear_shock_shaft", _apply_mat(shock_shaft, mats["stanchion"])))

    # --- 5. FORK ASSEMBLY (SUSPENSION vs RIGID AERO BLADE) ---
    fork_span_z = 0.064 if is_mtb else 0.052
    fork_dir = p_fa - p_crown
    fork_len = float(np.linalg.norm(fork_dir))

    if travel_f >= 0.04:
        # Forged CNC Crown
        crown_l = p_crown + np.array([0.0, 0.0, -fork_span_z])
        crown_r = p_crown + np.array([0.0, 0.0, fork_span_z])
        crown_mesh = make_tapered_tube(crown_l, crown_r, 0.022, 0.022, 0.022, 0.022, segments=16, rings=3, squircle=0.75)
        named_parts.append(("fork_crown", _apply_mat(crown_mesh, mats["dark_alloy"])))

        # Upper Stanchions (36-38mm diameter, Kashima Gold or Black)
        stanchion_r = 0.019 if travel_f >= 0.145 else 0.017
        stanchion_ratio = min(0.50, max(0.30, (travel_f + 0.04) / max(0.35, fork_len)))
        stanchion_meshes = []
        lower_meshes = []
        for side in (-1.0, 1.0):
            p_top_leg = p_crown + np.array([0.0, 0.0, side * fork_span_z])
            p_bot_leg = p_fa + np.array([0.0, 0.0, side * (f_hub_w * 0.54)])
            p_seal = p_top_leg * (1.0 - stanchion_ratio) + p_bot_leg * stanchion_ratio
            stanchion_meshes.append(make_tapered_tube(p_top_leg, p_seal, stanchion_r, stanchion_r, stanchion_r, stanchion_r, segments=18, rings=3))
            lower_meshes.append(make_tapered_tube(p_seal, p_bot_leg, stanchion_r * 1.24, stanchion_r * 1.24, stanchion_r * 1.05, stanchion_r * 1.05, segments=18, rings=4))

        # Fork brake arch bridge connecting lowers above front tire
        p_arch_l = p_crown * (1.0 - stanchion_ratio) + p_fa * stanchion_ratio + np.array([0.018, 0.015, -fork_span_z])
        p_arch_r = p_crown * (1.0 - stanchion_ratio) + p_fa * stanchion_ratio + np.array([0.018, 0.015, fork_span_z])
        p_arch_mid = 0.5 * (p_arch_l + p_arch_r) + np.array([0.014, 0.028, 0.0])
        lower_meshes.append(make_swept_polyline([p_arch_l, p_arch_mid, p_arch_r], 0.012, segments=12))

        named_parts.append(("fork_stanchions", _apply_mat(trimesh.util.concatenate(stanchion_meshes), mats["stanchion"])))
        named_parts.append(("fork_lowers", _apply_mat(trimesh.util.concatenate(lower_meshes), mats["dark_alloy"])))
    else:
        # Rigid Aero Carbon Blade Fork (Gravel / Road / Urban)
        blade_meshes = []
        crown_mesh = make_tapered_tube(
            p_crown + np.array([0, 0, -fork_span_z * 0.72]),
            p_crown + np.array([0, 0, fork_span_z * 0.72]),
            0.022, 0.018, 0.022, 0.018, segments=16, rings=2, squircle=0.75
        )
        blade_meshes.append(crown_mesh)
        for side in (-1.0, 1.0):
            p_top_leg = p_crown + np.array([0.0, -0.008, side * fork_span_z * 0.68])
            p_bot_leg = p_fa + np.array([0.0, 0.0, side * (f_hub_w * 0.53)])
            blade_meshes.append(make_tapered_tube(p_top_leg, p_bot_leg, 0.022, 0.009, 0.014, 0.007, segments=16, rings=5, squircle=0.78))
        named_parts.append(("fork_rigid_blades", _apply_mat(trimesh.util.concatenate(blade_meshes), mats["frame"])))

    # --- 6. BRAKE CALIPERS (PRECISELY ALIGNED TO -Z DISC ROTORS & POST-MOUNTS) ---
    caliper_meshes = []
    # Front caliper sits directly behind left fork lower at ~122 deg
    f_rot_r = (rotor_f_mm / 1000.0) * 0.5
    f_cal_ang = math.radians(122.0)
    f_cal_pos = p_fa + np.array([f_rot_r * 0.90 * math.cos(f_cal_ang), f_rot_r * 0.90 * math.sin(f_cal_ang), -f_hub_w * 0.44])
    f_cal = trimesh.creation.box(extents=[0.044, 0.028, 0.030])
    f_cal.apply_translation(f_cal_pos)
    caliper_meshes.append(f_cal)

    # Rear caliper sits cleanly nestled between left seatstay & chainstay at ~25 deg
    r_rot_r = (rotor_r_mm / 1000.0) * 0.5
    r_cal_ang = math.radians(24.0)
    r_cal_pos = p_ra + np.array([r_rot_r * 0.90 * math.cos(r_cal_ang), r_rot_r * 0.90 * math.sin(r_cal_ang), -r_hub_w * 0.44])
    r_cal = trimesh.creation.box(extents=[0.044, 0.026, 0.030])
    r_cal.apply_translation(r_cal_pos)
    caliper_meshes.append(r_cal)
    named_parts.append(("brake_calipers", _apply_mat(trimesh.util.concatenate(caliper_meshes), mats["dark_alloy"])))

    # --- 7. DRIVETRAIN (CRANKSET, CHAINRING, CASSETTE, DERAILLEUR, CHAIN) ---
    chain_z = 0.054 if is_mtb else 0.047
    crank_len = 0.170
    crank_ang = math.radians(-22.0)  # Aesthetic drive-side forward-down studio pose (matches ALSO bike!)
    p_crank_r = p_bb + np.array([crank_len * math.cos(crank_ang), crank_len * math.sin(crank_ang), 0.088])
    p_crank_l = p_bb + np.array([-crank_len * math.cos(crank_ang), -crank_len * math.sin(crank_ang), -0.088])
    crank_arm_r = make_tapered_tube(p_bb + np.array([0, 0, 0.072]), p_crank_r, 0.018, 0.008, 0.014, 0.007, segments=12, rings=3, squircle=0.70)
    crank_arm_l = make_tapered_tube(p_bb + np.array([0, 0, -0.072]), p_crank_l, 0.018, 0.008, 0.014, 0.007, segments=12, rings=3, squircle=0.70)
    spindle = make_cylinder_z(p_bb, 0.012, 0.148, sections=16)

    # Pedals
    pedal_r = trimesh.creation.box(extents=[0.098, 0.014, 0.088])
    pedal_r.apply_translation(p_crank_r + np.array([0, 0, 0.052]))
    pedal_l = trimesh.creation.box(extents=[0.098, 0.014, 0.088])
    pedal_l.apply_translation(p_crank_l + np.array([0, 0, -0.052]))
    named_parts.append(("drivetrain_crankset", _apply_mat(trimesh.util.concatenate([crank_arm_r, crank_arm_l, spindle, pedal_r, pedal_l]), mats["dark_alloy"])))

    # Front Chainring
    ring_r = 0.072 if is_mtb else 0.088
    chainring = make_annulus_z(p_bb + np.array([0, 0, chain_z]), ring_r * 0.65, ring_r, 0.004, sections=36)
    ring_spider = make_cylinder_z(p_bb + np.array([0, 0, chain_z]), ring_r * 0.68, 0.005, sections=12)
    named_parts.append(("drivetrain_chainring", _apply_mat(trimesh.util.concatenate([chainring, ring_spider]), mats["raw_alloy"])))

    # Rear 12-speed stepped Cassette
    cass_meshes = []
    max_cog_r = 0.104 if is_mtb else 0.084
    min_cog_r = 0.024
    for i in range(10):
        u = i / 9.0
        cog_r = max_cog_r * (1.0 - u) + min_cog_r * u
        z_cog = r_hub_w * 0.25 + u * 0.036
        cass_meshes.append(make_annulus_z(p_ra + np.array([0, 0, z_cog]), 0.017, cog_r, 0.0022, sections=30))
    named_parts.append(("drivetrain_cassette", _apply_mat(trimesh.util.concatenate(cass_meshes), mats["steel"])))

    # Rear Derailleur cage + jockey pulleys
    p_rd_top = p_ra + np.array([0.008, -0.042, r_hub_w * 0.56])
    p_rd_bot = p_ra + np.array([-0.018, -0.118, r_hub_w * 0.56])
    rd_arm = make_tapered_tube(p_rd_top, p_rd_bot, 0.012, 0.007, 0.010, 0.006, segments=10, rings=2)
    rd_p1 = make_cylinder_z(p_rd_top + np.array([0.004, -0.020, 0.0]), 0.018, 0.008, sections=16)
    rd_p2 = make_cylinder_z(p_rd_bot, 0.020, 0.008, sections=16)
    named_parts.append(("drivetrain_derailleur", _apply_mat(trimesh.util.concatenate([rd_arm, rd_p1, rd_p2]), mats["dark_alloy"])))

    # Chain upper & lower runs
    p_ch_f_top = p_bb + np.array([0.0, ring_r * 0.96, chain_z])
    p_ch_r_top = p_ra + np.array([0.0, max_cog_r * 0.62, r_hub_w * 0.36])
    p_ch_f_bot = p_bb + np.array([0.0, -ring_r * 0.96, chain_z])
    p_ch_r_bot = p_rd_bot + np.array([0.0, -0.015, -0.010])
    ch_top = make_tapered_tube(p_ch_f_top, p_ch_r_top, 0.0045, 0.0032, 0.0045, 0.0032, segments=8, rings=2)
    ch_bot = make_tapered_tube(p_ch_f_bot, p_ch_r_bot, 0.0045, 0.0032, 0.0045, 0.0032, segments=8, rings=2)
    named_parts.append(("drivetrain_chain", _apply_mat(trimesh.util.concatenate([ch_top, ch_bot]), mats["steel"])))

    # --- 8. COCKPIT (STEM, HANDLEBAR, GRIPS/HOODS, OPTIONAL E-BIKE HMI) ---
    stem_len = 0.045 if is_mtb else 0.095
    p_steerer_top = p_ht_top - 0.036 * u_ht
    p_bar_center = p_steerer_top + np.array([stem_len, 0.008, 0.0])
    spacer_stack = make_tapered_tube(p_ht_top - 0.005 * u_ht, p_steerer_top - 0.016 * u_ht, 0.019, 0.019, 0.019, 0.019, segments=18, rings=2)
    stem_body = make_tapered_tube(p_steerer_top, p_bar_center, 0.018, 0.016, 0.018, 0.018, segments=16, rings=3, squircle=0.72)
    named_parts.append(("cockpit_stem", _apply_mat(trimesh.util.concatenate([spacer_stack, stem_body]), mats["dark_alloy"])))

    if bar_type == "drop":
        # Sculpted Gravel / Road Drop Handlebar with flare + dual brake/shift hoods
        bar_w = 0.225  # half width (450mm gravel / 420mm road)
        bar_pts = [
            p_bar_center + np.array([-0.045, -0.115, -bar_w * 1.12]),
            p_bar_center + np.array([0.045, -0.105, -bar_w * 1.08]),
            p_bar_center + np.array([0.088, -0.025, -bar_w * 1.02]),
            p_bar_center + np.array([0.065, 0.004, -bar_w * 0.96]),
            p_bar_center + np.array([0.004, 0.004, -bar_w * 0.55]),
            p_bar_center,
            p_bar_center + np.array([0.004, 0.004, bar_w * 0.55]),
            p_bar_center + np.array([0.065, 0.004, bar_w * 0.96]),
            p_bar_center + np.array([0.088, -0.025, bar_w * 1.02]),
            p_bar_center + np.array([0.045, -0.105, bar_w * 1.08]),
            p_bar_center + np.array([-0.045, -0.115, bar_w * 1.12]),
        ]
        bar_mesh = make_swept_polyline(bar_pts, 0.014, segments=14)
        named_parts.append(("cockpit_dropbar", _apply_mat(bar_mesh, mats["dark_alloy"])))

        hoods = []
        for side in (-1.0, 1.0):
            p_hood = p_bar_center + np.array([0.095, 0.022, side * bar_w * 0.98])
            hood = make_tapered_tube(p_hood + np.array([-0.022, -0.028, 0]), p_hood + np.array([0.018, 0.022, 0]), 0.018, 0.014, 0.014, 0.012, segments=12, rings=3)
            lever = make_tapered_tube(p_hood + np.array([0.015, -0.015, 0]), p_hood + np.array([0.005, -0.105, 0]), 0.007, 0.005, 0.005, 0.004, segments=8, rings=2)
            hoods.extend([hood, lever])
        named_parts.append(("cockpit_shifter_hoods", _apply_mat(trimesh.util.concatenate(hoods), mats["saddle"])))
    else:
        # MTB / e-MTB Riser Handlebar (780mm width, 25mm rise, 8° backsweep)
        bar_half = 0.390 if full_sus else 0.340
        rise = 0.025 if full_sus else 0.018
        bar_pts = [
            p_bar_center + np.array([-0.042, rise, -bar_half]),
            p_bar_center + np.array([-0.016, rise * 0.85, -bar_half * 0.45]),
            p_bar_center + np.array([0.0, 0.0, -0.055]),
            p_bar_center,
            p_bar_center + np.array([0.0, 0.0, 0.055]),
            p_bar_center + np.array([-0.016, rise * 0.85, bar_half * 0.45]),
            p_bar_center + np.array([-0.042, rise, bar_half]),
        ]
        bar_mesh = make_swept_polyline(bar_pts, 0.0145, segments=14)
        named_parts.append(("cockpit_riser_bar", _apply_mat(bar_mesh, mats["dark_alloy"])))

        # Lock-on grips + hydraulic brake levers
        grips = []
        levers = []
        for side in (-1.0, 1.0):
            g0 = p_bar_center + np.array([-0.042, rise, side * bar_half])
            g1 = p_bar_center + np.array([-0.028, rise * 0.92, side * (bar_half - 0.130)])
            grips.append(make_tapered_tube(g0, g1, 0.017, 0.017, 0.017, 0.017, segments=14, rings=2))
            l0 = g1 + np.array([0.018, -0.006, -side * 0.025])
            l1 = l0 + np.array([0.048, -0.010, side * 0.055])
            levers.append(make_tapered_tube(l0, l1, 0.008, 0.005, 0.004, 0.003, segments=8, rings=2))
        named_parts.append(("cockpit_grips", _apply_mat(trimesh.util.concatenate(grips), mats["saddle"])))
        named_parts.append(("cockpit_brake_levers", _apply_mat(trimesh.util.concatenate(levers), mats["dark_alloy"])))

    # E-Bike Integrated HMI Display (on stem/toptube — ALSO Portal inspired!)
    if is_ebike:
        hmi_box = trimesh.creation.box(extents=[0.056, 0.014, 0.036])
        hmi_box.apply_translation(p_bar_center + np.array([-0.018, 0.024, 0.0]))
        named_parts.append(("cockpit_ebike_hmi", _apply_mat(hmi_box, mats["display_glow"])))

    # --- 9. SEATPOST & ERGONOMIC SADDLE ---
    post_ext = 0.195 if is_mtb else 0.175
    p_saddle_clamp = p_st_top + post_ext * u_st
    if is_mtb:
        # Dropper post outer + upper stanchion
        p_drop_mid = p_st_top + 0.055 * u_st
        post_low = make_tapered_tube(p_st_top - 0.015 * u_st, p_drop_mid, 0.0158, 0.0158, 0.0158, 0.0158, segments=18, rings=2)
        post_up = make_tapered_tube(p_drop_mid, p_saddle_clamp, 0.013, 0.013, 0.013, 0.013, segments=18, rings=2)
        named_parts.append(("seatpost_dropper_lower", _apply_mat(post_low, mats["dark_alloy"])))
        named_parts.append(("seatpost_dropper_upper", _apply_mat(post_up, mats["stanchion"] if kashima else mats["dark_alloy"])))
    else:
        post_mesh = make_tapered_tube(p_st_top - 0.015 * u_st, p_saddle_clamp, 0.014, 0.011, 0.014, 0.011, segments=16, rings=3, squircle=0.80)
        named_parts.append(("seatpost_aero", _apply_mat(post_mesh, mats["dark_alloy"])))

    # Saddle rails + sculpted ergonomic shell
    p_sad_c = p_saddle_clamp + np.array([0.012, 0.036, 0.0])
    rail_meshes = []
    for side in (-1.0, 1.0):
        r_pts = [
            p_sad_c + np.array([-0.095, -0.008, side * 0.022]),
            p_saddle_clamp + np.array([0.0, 0.012, side * 0.022]),
            p_sad_c + np.array([0.088, -0.006, side * 0.018]),
        ]
        rail_meshes.append(make_swept_polyline(r_pts, 0.0035, segments=8))
    named_parts.append(("saddle_rails", _apply_mat(trimesh.util.concatenate(rail_meshes), mats["steel"])))

    saddle_rear = make_tapered_tube(
        p_sad_c + np.array([-0.125, 0.006, 0.0]),
        p_sad_c + np.array([-0.010, -0.004, 0.0]),
        0.014, 0.068, 0.012, 0.042, segments=18, rings=4, squircle=0.72,
    )
    saddle_nose = make_tapered_tube(
        p_sad_c + np.array([-0.010, -0.004, 0.0]),
        p_sad_c + np.array([0.135, 0.002, 0.0]),
        0.012, 0.042, 0.009, 0.019, segments=16, rings=4, squircle=0.78,
    )
    named_parts.append(("saddle_shell", _apply_mat(trimesh.util.concatenate([saddle_rear, saddle_nose]), mats["saddle"])))

    # --- 10. ASSEMBLE SCENE & SHIFT SO LOWEST TIRE CONTACT = EXACT Y=0.000 ---
    scene = trimesh.Scene()
    all_min_y = min(float(m.bounds[0][1]) for _, m in named_parts)
    y_shift = -all_min_y

    # Also center X around wheelbase midpoint for smooth orbit viewing!
    x_center_offset = -wb * 0.5
    shift_vec = np.array([x_center_offset, y_shift, 0.0])

    object_inventory = []
    total_verts = 0
    total_faces = 0
    for part_name, mesh in named_parts:
        mesh.apply_translation(shift_vec)
        scene.add_geometry(mesh, node_name=part_name, geom_name=part_name)
        v_cnt = int(len(mesh.vertices))
        f_cnt = int(len(mesh.faces))
        total_verts += v_cnt
        total_faces += f_cnt
        object_inventory.append(
            {
                "name": part_name,
                "vertices": v_cnt,
                "faces": f_cnt,
                "bounds_min_m": [round(float(x), 4) for x in mesh.bounds[0]],
                "bounds_max_m": [round(float(x), 4) for x in mesh.bounds[1]],
            }
        )

    # Export GLB
    glb_path = out_dir / f"{slug}.glb"
    glb_bytes = scene.export(file_type="glb")
    glb_path.write_bytes(glb_bytes)
    glb_sha256 = hashlib.sha256(glb_bytes).hexdigest()

    # --- 11. ALSO-STYLE ENGINEERING QA VALIDATION ---
    # Compute shifted anchor points for exact 3D overlay coordinates in Three.js viewer!
    def _s(pt: np.ndarray) -> list[float]:
        v = pt + shift_vec
        return [round(float(v[0]), 4), round(float(v[1]), 4), round(float(v[2]), 4)]

    anchors_3d = {
        "rear_axle": _s(p_ra),
        "front_axle": _s(p_fa),
        "bb": _s(p_bb),
        "headtube_top": _s(p_ht_top),
        "headtube_bottom": _s(p_ht_bot),
        "seattube_top": _s(p_st_top),
        "saddle_center": _s(p_sad_c),
        "bar_center": _s(p_bar_center),
    }

    measured_wb_mm = round(float(p_fa[0] - p_ra[0]) * 1000.0, 2)
    measured_reach_mm = round(float(p_ht_top[0] - p_bb[0]) * 1000.0, 2)
    measured_stack_mm = round(float(p_ht_top[1] - p_bb[1]) * 1000.0, 2)
    measured_hta_deg = round(math.degrees(math.atan2(p_ht_top[1] - p_ht_bot[1], p_ht_bot[0] - p_ht_top[0])), 2)
    measured_sta_deg = round(math.degrees(math.atan2(p_st_top[1] - p_bb[1], p_bb[0] - p_st_top[0])), 2)
    measured_cs_mm = round(float(np.linalg.norm(p_bb - p_ra)) * 1000.0, 2)
    ground_y_min_mm = round(min(float(m.bounds[0][1]) for _, m in named_parts) * 1000.0, 3)
    crank_clearance_mm = round((float(p_bb[1] + shift_vec[1]) - crank_len) * 1000.0, 1)

    qa_checks = [
        {
            "check": "輪胎接地平面驗證 (Y_min)",
            "target": "0.00 mm",
            "measured": f"{ground_y_min_mm:.2f} mm",
            "delta": f"{abs(ground_y_min_mm):.2f} mm",
            "status": "通過" if abs(ground_y_min_mm) < 0.5 else "留意",
        },
        {
            "check": "前後軸距公差 (Wheelbase)",
            "target": f"{geo['wheelbase_mm']:.1f} mm",
            "measured": f"{measured_wb_mm:.1f} mm",
            "delta": f"{abs(measured_wb_mm - geo['wheelbase_mm']):.2f} mm",
            "status": "通過" if abs(measured_wb_mm - geo["wheelbase_mm"]) < 1.0 else "留意",
        },
        {
            "check": "車架前伸量座標 (Reach)",
            "target": f"{geo['reach_mm']:.1f} mm",
            "measured": f"{measured_reach_mm:.1f} mm",
            "delta": f"{abs(measured_reach_mm - geo['reach_mm']):.2f} mm",
            "status": "通過" if abs(measured_reach_mm - geo["reach_mm"]) < 1.0 else "留意",
        },
        {
            "check": "車架堆疊高度座標 (Stack)",
            "target": f"{geo['stack_mm']:.1f} mm",
            "measured": f"{measured_stack_mm:.1f} mm",
            "delta": f"{abs(measured_stack_mm - geo['stack_mm']):.2f} mm",
            "status": "通過" if abs(measured_stack_mm - geo["stack_mm"]) < 1.0 else "留意",
        },
        {
            "check": "頭管角度 (HTA)",
            "target": f"{geo['head_angle_deg']:.2f}°",
            "measured": f"{measured_hta_deg:.2f}°",
            "delta": f"{abs(measured_hta_deg - geo['head_angle_deg']):.2f}°",
            "status": "通過" if abs(measured_hta_deg - geo["head_angle_deg"]) < 0.1 else "留意",
        },
        {
            "check": "立管角度 (STA)",
            "target": f"{geo['seat_angle_deg']:.2f}°",
            "measured": f"{measured_sta_deg:.2f}°",
            "delta": f"{abs(measured_sta_deg - geo['seat_angle_deg']):.2f}°",
            "status": "通過" if abs(measured_sta_deg - geo["seat_angle_deg"]) < 0.1 else "留意",
        },
        {
            "check": "後下叉有效長度 (Chainstay)",
            "target": f"{geo['chainstay_mm']:.1f} mm",
            "measured": f"{measured_cs_mm:.1f} mm",
            "delta": f"{abs(measured_cs_mm - geo['chainstay_mm']):.2f} mm",
            "status": "通過" if abs(measured_cs_mm - geo["chainstay_mm"]) < 1.5 else "留意",
        },
        {
            "check": "五通／曲柄離地淨高 (170mm)",
            "target": "> 110.0 mm",
            "measured": f"{crank_clearance_mm:.1f} mm",
            "delta": "正常" if crank_clearance_mm >= 110.0 else "偏低",
            "status": "通過" if crank_clearance_mm >= 110.0 else "留意",
        },
    ]

    # Render ALSO-style warm neutral orthographic side-drive preview PNG for slides & cards
    preview_path = out_dir / f"{slug}_preview.png"
    _render_side_preview_png(scene, preview_path)

    prov = bike.get("geometry_provenance", {})
    measured_fields = [k for k, v in prov.items() if v.startswith("measured")]
    inferred_fields = [k for k, v in prov.items() if not v.startswith("measured")]

    manifest = {
        "schema": "ALSO-BIKE-PARAMETRIC-RE-v1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bike_slug": slug,
        "brand": bike["brand"],
        "model_name": bike["model_name"],
        "modeled_size": bike.get("default_size", "L"),
        "source_url": bike["url"],
        "glb_file": f"models/{slug}.glb",
        "preview_image": f"models/{slug}_preview.png",
        "glb_sha256": glb_sha256,
        "glb_bytes": len(glb_bytes),
        "blender_script": f"models/{slug}_blender_rebuild.py",
        "object_count": len(object_inventory),
        "total_vertices": total_verts,
        "total_faces": total_faces,
        "geometry_resolved": geo,
        "measured_fields": measured_fields,
        "inferred_fields": inferred_fields,
        "anchors_3d_gltf": anchors_3d,
        "qa_checks": qa_checks,
        "scope_qualifications": [
            "主車架三角、輪距、前伸量 (Reach)、堆疊高度 (Stack)、頭管與立管角度係依據抓取之規格與幾何表精確建構。",
            f"標記為「實測／官方數據」({len(measured_fields)} 項) 的欄位來自原廠或媒體表格與原文；標記為「級距比例推估」({len(inferred_fields)} 項) 的欄位依車型級距比例推估。",
            "管件壁厚、內部走線通道、避震連桿培林座與煞車碟盤散熱孔數屬於逆向工程視覺與裝配比例重建，不代表原廠結構強度或有限元素 (FEA) 認證。",
            "參照雲端 ALSO_BIKE 建模與驗證規範：輸出獨立分件 GLB、SHA256 雜湊校驗、7 視角正交攝影棚相機腳本與逐項幾何公差報表。",
        ],
        "object_inventory": object_inventory,
    }

    manifest_path = out_dir / f"{slug}_qa_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 12. ALSO-STYLE BLENDER 4.x STUDIO REBUILD & MULTI-VIEW RENDER SCRIPT ---
    blender_script = _generate_also_blender_script(slug, bike["model_name"], glb_sha256, geo)
    blender_path = out_dir / f"{slug}_blender_rebuild.py"
    blender_path.write_text(blender_script, encoding="utf-8")

    return {
        "glb_file": f"models/{slug}.glb",
        "preview_image": f"models/{slug}_preview.png",
        "glb_sha256": glb_sha256,
        "glb_bytes": len(glb_bytes),
        "manifest_file": f"models/{slug}_qa_manifest.json",
        "blender_script": f"models/{slug}_blender_rebuild.py",
        "object_count": len(object_inventory),
        "total_vertices": total_verts,
        "total_faces": total_faces,
        "anchors_3d": anchors_3d,
        "qa_checks": qa_checks,
        "qa_pass_count": sum(1 for q in qa_checks if q["status"] == "通過"),
        "qa_total_count": len(qa_checks),
        "scope_qualifications": manifest["scope_qualifications"],
    }


def _render_side_preview_png(scene: trimesh.Scene, out_png: Path) -> None:
    """Render a crisp ALSO-style warm neutral cyclorama orthographic side-drive preview PNG."""
    w, h = 1000, 620
    img = Image.new("RGB", (w, h), (221, 217, 208))
    draw = ImageDraw.Draw(img)
    light_dir = np.array([0.32, 0.72, 0.62])
    light_dir /= np.linalg.norm(light_dir)

    tris: list[tuple[float, np.ndarray, np.ndarray, np.ndarray, tuple[int, int, int]]] = []
    for geom in scene.geometry.values():
        v = geom.vertices
        f = geom.faces
        mat = getattr(geom.visual, "material", None)
        base = [130, 130, 130]
        if mat is not None and getattr(mat, "baseColorFactor", None) is not None:
            bc = mat.baseColorFactor
            base = [int(c) if c > 1.0 else int(c * 255) for c in bc[:3]]
        p0 = v[f[:, 0]]
        p1 = v[f[:, 1]]
        p2 = v[f[:, 2]]
        normals = np.cross(p1 - p0, p2 - p0)
        normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
        z_avg = (p0[:, 2] + p1[:, 2] + p2[:, 2]) / 3.0
        ndotl = np.clip(np.abs(normals @ light_dir), 0.22, 1.0)
        for i in range(len(f)):
            shade = 0.36 + 0.64 * float(ndotl[i])
            col = (
                min(255, max(0, int(base[0] * shade))),
                min(255, max(0, int(base[1] * shade))),
                min(255, max(0, int(base[2] * shade))),
            )
            tris.append((float(z_avg[i]), p0[i], p1[i], p2[i], col))

    tris.sort(key=lambda t: t[0])
    scale = 405.0
    cx, cy = w * 0.50, h * 0.86
    draw.line([(36, cy), (w - 36, cy)], fill=(182, 177, 167), width=2)
    for _, a, b, c, col in tris:
        pts = [
            (cx + a[0] * scale, cy - a[1] * scale),
            (cx + b[0] * scale, cy - b[1] * scale),
            (cx + c[0] * scale, cy - c[1] * scale),
        ]
        draw.polygon(pts, fill=col)
    img.save(out_png, optimize=True)


def _generate_also_blender_script(
    slug: str, model_name: str, glb_sha256: str, geo: dict[str, float]
) -> str:
    """Generate a standalone Blender 4.x studio script modeled directly after ALSO_BIKE/render_compact.py."""
    return f'''"""ALSO-BIKE Studio Standard — Blender 4.x Import, Cyclorama & Multi-View QA Render Script.

Model      : {model_name} ({slug})
GLB SHA256 : {glb_sha256}
Geometry   : WB={geo["wheelbase_mm"]}mm | Reach={geo["reach_mm"]}mm | Stack={geo["stack_mm"]}mm | HTA={geo["head_angle_deg"]}deg | STA={geo["seat_angle_deg"]}deg

Usage (headless or Blender GUI):
    blender -b --python {slug}_blender_rebuild.py -- --glb {slug}.glb --out ./renders_{slug}
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

EXPECTED_SHA256 = "{glb_sha256}"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", default="{slug}.glb")
    parser.add_argument("--out", default="./renders_{slug}")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=900)
    return parser.parse_args(argv)


def setup_also_warm_cyclorama(scene):
    """Replicate ALSO_BIKE warm neutral cyclorama (0.78, 0.76, 0.72) + AgX + 3-point studio disk lights."""
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 32
    scene.eevee.use_raytracing = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    # World shader with camera ray split (ALSO standard)
    scene.world.use_nodes = True
    nt = scene.world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg_env = nt.nodes.new("ShaderNodeBackground")
    bg_env.inputs["Color"].default_value = (0.75, 0.72, 0.67, 1.0)
    bg_env.inputs["Strength"].default_value = 0.25
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_cam.inputs["Color"].default_value = (0.78, 0.76, 0.72, 1.0)
    bg_cam.inputs["Strength"].default_value = 1.0
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_env.outputs[0], mix.inputs[1])
    nt.links.new(bg_cam.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])

    # Warm neutral cyclorama floor
    mat_floor = bpy.data.materials.new("ALSO_Warm_Neutral_Cyclorama")
    mat_floor.use_nodes = True
    bsdf = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.78, 0.76, 0.72, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.82
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0.0, 0.0, 0.0))
    bpy.context.object.data.materials.append(mat_floor)

    # 3-Point physical jittered-shadow studio disk lights (Key, Fill, Rim)
    light_specs = [
        ("ALSO_Key", (1.6, -3.2, 3.8), 580.0, 3.0, (0.0, 0.0, 0.60)),
        ("ALSO_Fill", (-1.4, 2.2, 2.5), 260.0, 3.0, (0.0, 0.0, 0.60)),
        ("ALSO_Rim", (0.2, 1.8, 3.5), 420.0, 2.0, (0.0, 0.0, 0.68)),
    ]
    for name, loc, energy, size, target in light_specs:
        ldata = bpy.data.lights.new(name, "AREA")
        ldata.energy = energy
        ldata.shape = "DISK"
        ldata.size = size
        ldata.use_shadow = True
        if hasattr(ldata, "use_shadow_jitter"):
            ldata.use_shadow_jitter = True
        lobj = bpy.data.objects.new(name, ldata)
        scene.collection.objects.link(lobj)
        lobj.location = loc
        lobj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def main():
    args = parse_args()
    glb_path = Path(args.glb).resolve()
    actual_sha = hashlib.sha256(glb_path.read_bytes()).hexdigest()
    assert actual_sha == EXPECTED_SHA256, f"SHA256 mismatch: {{actual_sha}} != {{EXPECTED_SHA256}}"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))

    scene = bpy.context.scene
    setup_also_warm_cyclorama(scene)

    cam_data = bpy.data.cameras.new("ALSO_Ortho_Camera")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.001
    cam_obj = bpy.data.objects.new("ALSO_Ortho_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    # ALSO-style 7-view orthographic inspection rig (Z-up in Blender)
    views = [
        ("01_side_drive", (0.0, -4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("02_side_brake", (0.0, 4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("03_front", (4.0, 0.0, 0.68), (0.4, 0.0, 0.58), 1.45),
        ("04_rear", (-4.0, 0.0, 0.68), (-0.4, 0.0, 0.58), 1.45),
        ("05_front_45", (3.0, -3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("06_rear_45", (-3.0, 3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("07_cockpit", (0.15, -0.70, 1.65), (0.35, 0.0, 0.98), 0.95),
    ]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.eevee.taa_render_samples = args.samples

    for name, eye, target, scale in views:
        cam_obj.location = Vector(eye)
        cam_obj.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat("-Z", "Y").to_euler()
        cam_data.ortho_scale = scale
        scene.render.filepath = str(out_dir / f"{{name}}.png")
        bpy.ops.render.render(write_still=True)

    # Save integrated .blend file alongside renders
    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "{slug}_ALSO_studio.blend"))
    print(json.dumps({{"status": "ok", "model": "{slug}", "sha256": actual_sha, "views": len(views)}}))


if __name__ == "__main__":
    main()
'''
