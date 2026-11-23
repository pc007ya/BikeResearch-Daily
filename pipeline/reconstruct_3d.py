"""Parametric 3D bicycle reverse-engineering engine.

Supports 4 distinct real-world frame architectures (Single-Pivot Gullarm e-MTB,
Step-Through Commuter e-Bike, Low-Slung Trail/e-MTB/SUV Full-Suspension, and
Aero Dropped-Stay Gravel/Road), true HTA-coaxial offset fork kinematics,
belt-drive & rack/fender assemblies, photo-sampled PBR colors, automated
engineering QA validation, orthographic preview rendering, and Blender 4.x studio scripts.
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

from pipeline.photo_calibration import (
    calibrate_bike_reference_photo,
    inspect_calibrated_photo_frame,
    render_overlay_qa_image,
)

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
        baseColorFactor=[int(np.clip(c, 0, 1) * 255) for c in rgba[:3]] + [int(np.clip(rgba[3], 0, 1) * 255)],
        metallicFactor=float(metallic),
        roughnessFactor=float(roughness),
    )


def _apply_mat(mesh: trimesh.Trimesh, mat: PBRMaterial) -> trimesh.Trimesh:
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)
    return mesh


def _basis_from_dir(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    d = p1 - p0
    if np.linalg.norm(d) < 1e-6:
        return trimesh.creation.icosphere(subdivisions=1, radius=max(rn0, rb0, 0.005))
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


def make_curved_hydroformed_tube(
    ctrl_pts: list[np.ndarray],
    rn_list: list[float],
    rb_list: list[float],
    segments: int = 20,
    samples: int = 16,
    squircle: float = 0.80,
) -> trimesh.Trimesh:
    """Loft a smooth hydroformed squircle tube along a quadratic/cubic Bezier spline."""
    pts = [np.asarray(p, dtype=float) for p in ctrl_pts]
    n_ctrl = len(pts)

    def _eval_bezier(arr: list[Any], u: float) -> Any:
        work = [np.array(v, dtype=float) for v in arr]
        while len(work) > 1:
            work = [(1.0 - u) * work[i] + u * work[i + 1] for i in range(len(work) - 1)]
        return work[0]

    us = np.linspace(0.0, 1.0, samples)
    centers = [_eval_bezier(pts, float(u)) for u in us]
    rns = [float(_eval_bezier(rn_list, float(u))) for u in us]
    rbs = [float(_eval_bezier(rb_list, float(u))) for u in us]

    angles = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    cos_a = np.sign(np.cos(angles)) * (np.abs(np.cos(angles)) ** squircle)
    sin_a = np.sign(np.sin(angles)) * (np.abs(np.sin(angles)) ** squircle)

    verts: list[np.ndarray] = []
    for idx, c in enumerate(centers):
        if idx == 0:
            t = centers[1] - centers[0]
        elif idx == len(centers) - 1:
            t = centers[-1] - centers[-2]
        else:
            t = centers[idx + 1] - centers[idx - 1]
        _, n, b = _basis_from_dir(t)
        rn, rb = rns[idx], rbs[idx]
        for ca, sa in zip(cos_a, sin_a):
            verts.append(c + n * (rn * ca) + b * (rb * sa))

    faces: list[list[int]] = []
    for idx in range(len(centers) - 1):
        b0 = idx * segments
        b1 = (idx + 1) * segments
        for s in range(segments):
            sn = (s + 1) % segments
            faces.append([b0 + s, b0 + sn, b1 + sn])
            faces.append([b0 + s, b1 + sn, b1 + s])

    c0 = len(verts)
    verts.append(centers[0])
    c1 = len(verts)
    verts.append(centers[-1])
    last = (len(centers) - 1) * segments
    for s in range(segments):
        sn = (s + 1) % segments
        faces.append([c0, sn, s])
        faces.append([c1, last + s, last + sn])

    mesh = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=False)
    mesh.fix_normals()
    return mesh


def make_swept_polyline(
    points: list[np.ndarray],
    radii: list[float] | float,
    segments: int = 16,
) -> trimesh.Trimesh:
    pts = [np.asarray(p, dtype=float) for p in points]
    rads = [float(radii)] * len(pts) if isinstance(radii, (int, float)) else [float(r) for r in radii]
    angles = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    verts: list[np.ndarray] = []
    prev_n = None

    for idx, p in enumerate(pts):
        t = pts[1] - pts[0] if idx == 0 else (pts[-1] - pts[-2] if idx == len(pts) - 1 else pts[idx + 1] - pts[idx - 1])
        t = t / (np.linalg.norm(t) + 1e-12)
        if prev_n is None:
            ref = np.array([0.0, 1.0, 0.0]) if abs(t[1]) < 0.85 else np.array([1.0, 0.0, 0.0])
            n = np.cross(t, ref)
            n /= np.linalg.norm(n) + 1e-12
        else:
            n = prev_n - np.dot(prev_n, t) * t
            n = _basis_from_dir(t)[1] if np.linalg.norm(n) < 1e-6 else n / np.linalg.norm(n)
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


def make_fender_arc(
    axle: np.ndarray,
    radius: float,
    width: float,
    start_deg: float,
    end_deg: float,
    steps: int = 24,
) -> trimesh.Trimesh:
    """Create a curved wrap-around mudguard fender hugging a wheel in the XY plane."""
    angs = np.linspace(math.radians(start_deg), math.radians(end_deg), steps)
    pts = [axle + np.array([radius * math.cos(a), radius * math.sin(a), 0.0]) for a in angs]
    return make_curved_hydroformed_tube(
        pts[:1] + [pts[len(pts) // 2]] + pts[-1:] if len(pts) > 3 else pts,
        [0.005, 0.005, 0.005],
        [width * 0.5, width * 0.5, width * 0.5],
        segments=10,
        samples=steps,
        squircle=0.65,
    )


def make_fender_polyline_arc(
    axle: np.ndarray,
    radius: float,
    width: float,
    start_deg: float,
    end_deg: float,
    steps: int = 28,
) -> trimesh.Trimesh:
    """Exact circular-arc mudguard shell around `axle` at `radius`."""
    angs = np.linspace(math.radians(start_deg), math.radians(end_deg), steps)
    profile = np.linspace(-math.pi * 0.42, math.pi * 0.42, 7)
    verts = []
    half_w = width * 0.52
    thick = 0.004
    for a in angs:
        ca, sa = math.cos(a), math.sin(a)
        for p in profile:
            r_cur = radius + 0.008 * math.cos(p)
            z_cur = half_w * math.sin(p)
            verts.append([axle[0] + r_cur * ca, axle[1] + r_cur * sa, axle[2] + z_cur])
        for p in reversed(profile):
            r_cur = radius + 0.008 * math.cos(p) - thick
            z_cur = half_w * math.sin(p)
            verts.append([axle[0] + r_cur * ca, axle[1] + r_cur * sa, axle[2] + z_cur])
    ring_n = len(profile) * 2
    faces = []
    for i in range(steps - 1):
        b0 = i * ring_n
        b1 = (i + 1) * ring_n
        for j in range(ring_n):
            jn = (j + 1) % ring_n
            faces.append([b0 + j, b0 + jn, b1 + jn])
            faces.append([b0 + j, b1 + jn, b1 + j])
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
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    theta = np.linspace(0, 2 * math.pi, major_seg, endpoint=False)
    phi = np.linspace(0, 2 * math.pi, minor_seg, endpoint=False)
    verts = []
    for th in theta:
        ct, st = math.cos(th), math.sin(th)
        for ph in phi:
            r = major_r + minor_r_rad * math.cos(ph)
            verts.append([cx + r * ct, cy + r * st, cz + minor_r_lat * math.sin(ph)])

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


def make_cylinder_z(center: np.ndarray, radius: float, width: float, sections: int = 28) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=radius, height=width, sections=sections)
    m.apply_translation(center)
    return m


def make_annulus_z(center: np.ndarray, r_inner: float, r_outer: float, thickness: float, sections: int = 40) -> trimesh.Trimesh:
    m = trimesh.creation.annulus(r_min=r_inner, r_max=r_outer, height=thickness, sections=sections)
    m.apply_translation(center)
    return m


def _wheel_outer_radius_m(wheel_in: float, tire_w_mm: float) -> tuple[float, float, float]:
    bsd_map = {
        32.0: 0.686,
        29.0: 0.622,
        28.0: 0.622,
        27.5: 0.584,
        26.0: 0.559,
        24.0: 0.507,
    }
    bsd = bsd_map.get(round(wheel_in, 1), 0.622)
    rim_r = bsd * 0.5
    tire_r = (tire_w_mm / 1000.0) * 0.5
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

    tire = make_torus_xy(axle, tire_major, tire_r, tire_r * 0.96, major_seg=56, minor_seg=18)
    parts.append((f"{name_prefix}_tire", _apply_mat(tire, mats["tire"])))

    rim = make_torus_xy(axle, rim_r - rim_depth * 0.4, rim_depth * 0.55, tire_r * 0.62, major_seg=52, minor_seg=12)
    parts.append((f"{name_prefix}_rim", _apply_mat(rim, mats["rim"])))

    hub_body = make_cylinder_z(axle, 0.014, hub_width * 0.72, sections=22)
    flange_l = make_cylinder_z(axle + np.array([0, 0, -hub_width * 0.30]), 0.027, 0.005, sections=24)
    flange_r = make_cylinder_z(axle + np.array([0, 0, hub_width * 0.30]), 0.027, 0.005, sections=24)
    endcaps = make_cylinder_z(axle, 0.009, hub_width * 1.06, sections=16)
    parts.append((f"{name_prefix}_hub", _apply_mat(trimesh.util.concatenate([hub_body, flange_l, flange_r, endcaps]), mats["dark_alloy"])))

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
    parts.append((f"{name_prefix}_brake_rotor", _apply_mat(trimesh.util.concatenate([track, carrier] + spider_arms), mats["rotor_steel"])))

    return parts


def build_bike_3d_model(
    bike: dict[str, Any],
    out_dir: Path,
    _override_arch: str | None = None,
    _override_rgb: list[float] | None = None,
    _existing_photo_cal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct architecture-accurate parametric 3D bike (.glb), run geometric tolerance QA, and emit Blender script."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = bike["slug"]
    geo = bike["geometry_resolved"]

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

    frame_arch = _override_arch or bike.get("frame_arch", "low_slung_emtb")
    is_ebike = bool(bike.get("is_ebike"))
    full_sus = bool(bike.get("full_suspension")) and travel_r >= 0.04
    is_tall_urban = bike.get("category_key") == "urban_ebike"
    suspension_type = bike.get("suspension_type") or (
        "single_pivot_gullarm"
        if frame_arch == "single_pivot_gullarm"
        else (
            "hardtail_rigid"
            if not full_sus
            else ("vertical_behind_st" if frame_arch in ("lowstep_monotube", "stagger_midstep") else "horst_horizontal_toptube")
        )
    )
    if frame_arch in ("lowstep_monotube", "stagger_midstep") and full_sus:
        suspension_type = "vertical_behind_st"
    elif not full_sus:
        suspension_type = "hardtail_rigid"
    bar_type = bike.get("handlebar_type", "riser")
    is_mtb = bar_type != "drop"
    kashima = bool(bike.get("kashima_gold"))
    has_belt = bool(bike.get("has_belt_drive"))
    has_fenders = bool(bike.get("has_fenders"))
    has_rear_rack = bool(bike.get("has_rear_rack"))
    has_front_rack = bool(bike.get("has_front_rack"))
    has_headlight = bool(bike.get("has_headlight"))
    two_tone_lower = bool(bike.get("two_tone_lower"))

    accent = _override_rgb if _override_rgb is not None else bike.get("accent_rgb", [0.80, 0.82, 0.85])
    sec_rgb = bike.get("secondary_rgb", [0.15, 0.16, 0.18])

    mats = {
        "frame": _mat("Frame_Primary_Paint", (accent[0], accent[1], accent[2], 1.0), metallic=0.18, roughness=0.30),
        "frame_secondary": _mat("Frame_Secondary_Carbon", (sec_rgb[0], sec_rgb[1], sec_rgb[2], 1.0), metallic=0.15, roughness=0.48),
        "dark_alloy": _mat("Anodized_Dark_Alloy", (0.12, 0.12, 0.13, 1.0), metallic=0.70, roughness=0.34),
        "raw_alloy": _mat("CNC_Raw_Alloy", (0.72, 0.74, 0.76, 1.0), metallic=0.88, roughness=0.25),
        "stanchion": _mat(
            "Stanchion_Kashima" if kashima else "Stanchion_Black",
            (0.78, 0.58, 0.22, 1.0) if kashima else (0.09, 0.09, 0.10, 1.0),
            metallic=0.92,
            roughness=0.15,
        ),
        "tire": _mat("Rubber_Tire_Matte", (0.10, 0.10, 0.11, 1.0), metallic=0.0, roughness=0.86),
        "rim": _mat("Rim_Carbon_Satin", (0.14, 0.14, 0.15, 1.0), metallic=0.28, roughness=0.38),
        "steel": _mat("Spokes_Chain_Steel", (0.44, 0.46, 0.48, 1.0), metallic=0.85, roughness=0.30),
        "rotor_steel": _mat("Brake_Rotor_Stainless", (0.78, 0.80, 0.82, 1.0), metallic=0.92, roughness=0.22),
        "saddle": _mat("Saddle_Grip_Microfiber", (0.13, 0.13, 0.14, 1.0), metallic=0.0, roughness=0.76),
        "motor_housing": _mat("EDrive_Motor_Magnesium", (0.18, 0.19, 0.21, 1.0), metallic=0.55, roughness=0.40),
        "display_glow": _mat("HMI_Display_Screen", (0.12, 0.19, 0.24, 1.0), metallic=0.10, roughness=0.12),
        "lens": _mat("LED_Headlight_Lens", (0.94, 0.96, 0.98, 1.0), metallic=0.05, roughness=0.08),
    }

    # --- 1. EXACT KINEMATIC ANCHOR NODES ---
    r_f, _, _ = _wheel_outer_radius_m(w_f_in, tire_w_mm)
    r_r, _, _ = _wheel_outer_radius_m(w_r_in, tire_w_mm)

    p_ra = np.array([0.0, r_r, 0.0])
    p_fa = np.array([wb, r_f, 0.0])

    y_bb = 0.5 * (r_r + r_f) - bb_drop
    dy_cs = r_r - y_bb
    dx_cs = math.sqrt(max(0.06, cs * cs - dy_cs * dy_cs))
    p_bb = np.array([dx_cs, y_bb, 0.0])

    p_ht_top = np.array([p_bb[0] + reach, p_bb[1] + stack, 0.0])
    u_ht = np.array([math.cos(hta), -math.sin(hta), 0.0])  # Down-forward along steering axis
    n_ht = np.array([math.sin(hta), math.cos(hta), 0.0])   # Perpendicular forward to steering axis
    p_ht_bot = p_ht_top + ht_len * u_ht

    u_st = np.array([-math.cos(sta), math.sin(sta), 0.0])  # Up-backward along seat tube
    p_st_top = p_bb + st_len * u_st

    # Exact HTA-coaxial fork crown kinematics!
    # Real suspension forks keep the crown flush & coaxial under the lower headset cup (~10-14mm forward),
    # with stanchions & lowers running strictly parallel to the head tube axis, and forward thru-axle dropouts
    # at the bottom of the lowers providing the remaining ~30-35mm of fork offset.
    p_crown_axis = p_ht_bot + 0.012 * u_ht
    v_cf = p_fa - p_crown_axis
    s_fork_along = float(np.dot(v_cf, u_ht))
    d_fork_offset = float(np.dot(v_cf, n_ht))
    crown_offset = float(np.clip(d_fork_offset * 0.24, 0.008, 0.014)) if travel_f >= 0.04 else 0.004
    p_crown_offset = p_crown_axis + crown_offset * n_ht

    named_parts: list[tuple[str, trimesh.Trimesh]] = []

    # --- 2. WHEELS & DISC BRAKE ROTORS ---
    f_hub_w = 0.110 if is_mtb else 0.100
    r_hub_w = 0.148 if is_mtb else 0.142
    named_parts.extend(build_wheel_assembly("front_wheel", p_fa, w_f_in, tire_w_mm, f_hub_w, rotor_f_mm, is_mtb, mats))
    named_parts.extend(build_wheel_assembly("rear_wheel", p_ra, w_r_in, tire_w_mm, r_hub_w, rotor_r_mm, is_mtb, mats))

    # --- 3. HEAD TUBE & HEADSET ---
    ht_r = 0.031 if is_ebike else (0.026 if is_mtb else 0.023)
    ht_mesh = make_tapered_tube(p_ht_top, p_ht_bot, ht_r * 0.95, ht_r * 0.95, ht_r * 1.08, ht_r * 1.08, segments=24, rings=6)
    cup_top = make_tapered_tube(p_ht_top - 0.010 * u_ht, p_ht_top + 0.004 * u_ht, ht_r * 0.98, ht_r * 0.98, ht_r * 1.02, ht_r * 1.02, segments=22, rings=2)
    cup_bot = make_tapered_tube(p_ht_bot - 0.003 * u_ht, p_ht_bot + 0.012 * u_ht, ht_r * 1.12, ht_r * 1.12, ht_r * 1.06, ht_r * 1.06, segments=22, rings=2)
    named_parts.append(("frame_headtube", _apply_mat(ht_mesh, mats["frame"])))
    named_parts.append(("headset_cups", _apply_mat(trimesh.util.concatenate([cup_top, cup_bot]), mats["dark_alloy"])))

    # --- 4. ARCHITECTURE-SPECIFIC MAIN FRAME & REAR TRIANGLE ---
    if frame_arch == "single_pivot_gullarm":
        # HONDA RN0: Monocoque two-tone Y-truss front frame + massive black Gullarm single-pivot swingarm!
        p_dt_mid = 0.48 * p_ht_bot + 0.52 * (p_bb + np.array([0.04, 0.04, 0.0]))
        # Upper silver-grey swept main boom (headtube top -> seat tube collar)
        p_y_st = p_bb + (st_len * 0.78) * u_st
        p_y_mid = 0.45 * p_ht_top + 0.55 * p_y_st + np.array([0.035, -0.055, 0.0])
        upper_boom = make_curved_hydroformed_tube(
            [p_ht_top + 0.02 * u_ht, p_y_mid, p_y_st],
            [0.044, 0.036, 0.028],
            [0.032, 0.028, 0.024],
            segments=22, samples=16, squircle=0.72,
        )
        # Upper silver-grey Y-diagonal strut enclosing shock tunnel (overlaps seamlessly into lower dark spine)
        p_pivot = p_bb + np.array([-0.045, 0.145, 0.0])
        p_y_truss_top = p_ht_bot - 0.015 * u_ht
        y_upper = make_tapered_tube(p_y_truss_top, p_dt_mid + np.array([-0.015, -0.012, 0.0]), 0.052, 0.038, 0.055, 0.040, segments=22, rings=6, squircle=0.70)
        y_bridge = make_tapered_tube(p_y_st + np.array([0.005, -0.065, 0.0]), p_dt_mid + np.array([-0.005, 0.015, 0.0]), 0.028, 0.026, 0.038, 0.033, segments=20, rings=5, squircle=0.72)
        named_parts.append(("frame_monocoque_upper", _apply_mat(trimesh.util.concatenate([upper_boom, y_upper, y_bridge]), mats["frame"])))

        # Dark graphite lower battery downtube & motor belly spine (seamless overlap)
        dt_lower = make_tapered_tube(p_dt_mid + np.array([0.012, 0.012, 0.0]), p_bb + np.array([0.025, 0.025, 0.0]), 0.055, 0.040, 0.058, 0.044, segments=22, rings=6, squircle=0.68)
        st_lower = make_tapered_tube(p_bb + np.array([0.0, 0.02, 0.0]), p_pivot + np.array([0.01, 0.04, 0.0]), 0.036, 0.040, 0.034, 0.038, segments=18, rings=4, squircle=0.72)
        named_parts.append(("frame_downtube_lower_dark", _apply_mat(trimesh.util.concatenate([dt_lower, st_lower]), mats["frame_secondary"])))

        # Upper seat tube + signature rear mudguard fin
        st_up = make_tapered_tube(p_pivot + np.array([0.01, 0.02, 0.0]), p_st_top, 0.024, 0.024, 0.020, 0.020, segments=20, rings=5)
        fin_p0 = p_y_st + np.array([0.0, -0.05, 0.0])
        fin_p1 = p_y_st + np.array([-0.095, 0.065, 0.0])
        rear_fin = make_tapered_tube(fin_p0, fin_p1, 0.014, 0.018, 0.004, 0.008, segments=12, rings=3, squircle=0.70)
        named_parts.append(("frame_seattube", _apply_mat(st_up, mats["frame"])))
        named_parts.append(("frame_rear_fin", _apply_mat(rear_fin, mats["frame_secondary"])))

        # Tucked shock nestled cleanly inside the Y-frame cavity (connecting pivot linkage to Y-pocket)
        p_sh_front = p_y_mid + np.array([0.03, -0.058, 0.0])
        p_sh_rear = p_pivot + np.array([0.025, 0.050, 0.0])
        sh_mid = 0.45 * p_sh_rear + 0.55 * p_sh_front
        sh_body = make_tapered_tube(sh_mid, p_sh_front, 0.022, 0.022, 0.023, 0.023, segments=20, rings=4)
        sh_shaft = make_tapered_tube(p_sh_rear, sh_mid + 0.02 * (p_sh_front - p_sh_rear), 0.014, 0.014, 0.014, 0.014, segments=16, rings=2)
        named_parts.append(("rear_shock_body", _apply_mat(sh_body, mats["dark_alloy"])))
        named_parts.append(("rear_shock_shaft", _apply_mat(sh_shaft, mats["stanchion"])))

        # Massive black single-pivot GULLARM swingarm (NO upper seatstays!)
        gull_parts = []
        for side in (-1.0, 1.0):
            p_g0 = p_pivot + np.array([0.0, 0.0, side * 0.052])
            p_g_arch = 0.55 * p_g0 + 0.45 * (p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.55)])) + np.array([-0.01, 0.068, side * 0.018])
            p_g2 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.54)])
            gull_parts.append(
                make_curved_hydroformed_tube(
                    [p_g0, p_g_arch, p_g2],
                    [0.044, 0.036, 0.020],
                    [0.016, 0.014, 0.011],
                    segments=18, samples=14, squircle=0.68,
                )
            )
        pivot_axle = make_cylinder_z(p_pivot, 0.026, 0.130, sections=22)
        gull_parts.append(pivot_axle)
        named_parts.append(("rear_gullarm_swingarm", _apply_mat(trimesh.util.concatenate(gull_parts), mats["frame_secondary"])))

    elif frame_arch == "lowstep_monotube":
        # TRUE LOW-STEP SINGLE-DOWNTUBE / MONOTUBE (FOCUS AVENTURA² FS, CONWAY CAIRON WAVE, AMFLOW UE CARBON PRO)
        # ZERO top tube, ZERO second parallel stagger tube — ONE massive hydroformed battery monotube!
        p_ht_mid = 0.50 * p_ht_top + 0.50 * p_ht_bot
        dt_start = p_ht_mid - 0.008 * n_ht
        dt_end = p_bb + np.array([0.036, 0.032, 0.0])
        dt_ctrl = 0.50 * dt_start + 0.50 * dt_end + np.array([0.012, -0.010, 0.0])
        # Oversized boxy-squircle monotube spanning full headtube height into BB motor cradle
        dt_mesh = make_curved_hydroformed_tube(
            [dt_start, dt_ctrl, dt_end],
            [0.056, 0.058, 0.064],
            [0.036, 0.038, 0.042],
            segments=26, samples=16, squircle=0.72,
        )
        named_parts.append(("frame_lowstep_monotube", _apply_mat(dt_mesh, mats["frame"])))

        # Lower step-through gusset bridge tying monotube smoothly into base of seat tube
        gusset = make_tapered_tube(
            p_bb + np.array([0.055, 0.062, 0.0]),
            p_bb + (st_len * 0.16) * u_st,
            0.038, 0.034, 0.028, 0.026,
            segments=20, rings=4, squircle=0.76,
        )
        named_parts.append(("frame_lowstep_gusset", _apply_mat(gusset, mats["frame"])))

        # Sculpted seat tube (slightly beefier lower tower on FS low-step SUV bikes)
        st_mesh = make_tapered_tube(
            p_bb + np.array([0.0, 0.018, 0.0]),
            p_st_top,
            0.030 if full_sus else 0.028,
            0.028 if full_sus else 0.026,
            0.021, 0.021,
            segments=22, rings=6, squircle=0.80,
        )
        named_parts.append(("frame_seattube", _apply_mat(st_mesh, mats["frame"])))

        if full_sus:
            # FULL-SUSPENSION LOW-STEP SUV (FOCUS AVENTURA² FS & CONWAY CAIRON SUV FS):
            # Vertical/semi-vertical rear shock tucked cleanly BEHIND the seat tube + compact rocker link!
            p_rocker_st = p_bb + (st_len * 0.44) * u_st
            p_shock_top = p_rocker_st + np.array([-0.056, -0.008, 0.0])
            p_shock_bot = p_bb + np.array([-0.052, 0.042, 0.0])

            cs_meshes, ss_meshes, link_parts = [], [], []
            for side in (-1.0, 1.0):
                p_cs0 = p_bb + np.array([-0.014, 0.024, side * 0.044])
                p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
                cs_meshes.append(make_tapered_tube(p_cs0, p_cs1, 0.018, 0.011, 0.013, 0.009, segments=14, rings=4, squircle=0.74))
                p_ss_piv = p_rocker_st + np.array([-0.058, 0.014, side * 0.036])
                ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0.0, 0.014, 0.0]), p_ss_piv, 0.012, 0.009, 0.014, 0.010, segments=14, rings=4, squircle=0.78))
                # Compact rocker link bridging seat tube -> seatstay pivot -> shock top eyelet
                p_l_st = p_rocker_st + np.array([0.0, 0.0, side * 0.026])
                p_l_sh = p_shock_top + np.array([0.0, 0.0, side * 0.020])
                link_parts.append(make_tapered_tube(p_l_st, p_ss_piv, 0.014, 0.006, 0.013, 0.006, segments=12, rings=2, squircle=0.72))
                link_parts.append(make_tapered_tube(p_ss_piv, p_l_sh, 0.013, 0.006, 0.012, 0.006, segments=12, rings=2, squircle=0.72))
            link_parts.append(make_cylinder_z(p_rocker_st, 0.012, 0.064, sections=16))
            link_parts.append(make_cylinder_z(p_shock_top, 0.009, 0.048, sections=14))
            link_parts.append(make_cylinder_z(p_shock_bot, 0.010, 0.048, sections=14))
            named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
            named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))
            named_parts.append(("suspension_rocker_link", _apply_mat(trimesh.util.concatenate(link_parts), mats["dark_alloy"])))

            sh_mid = 0.45 * p_shock_bot + 0.55 * p_shock_top
            sh_can = make_tapered_tube(sh_mid, p_shock_top, 0.022, 0.022, 0.023, 0.023, segments=22, rings=4)
            sh_shaft = make_tapered_tube(p_shock_bot, sh_mid + 0.02 * (p_shock_top - p_shock_bot), 0.013, 0.013, 0.013, 0.013, segments=18, rings=2)
            named_parts.append(("rear_shock_body", _apply_mat(sh_can, mats["dark_alloy"])))
            named_parts.append(("rear_shock_shaft", _apply_mat(sh_shaft, mats["stanchion"])))
        else:
            # Clean stiff triangular commuter rear stays (rigid / hardtail low-step like Amflow UE Carbon Pro)
            cs_meshes, ss_meshes = [], []
            for side in (-1.0, 1.0):
                p_cs0 = p_bb + np.array([-0.010, 0.008, side * 0.040])
                p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
                cs_meshes.append(make_tapered_tube(p_cs0, p_cs1, 0.016, 0.010, 0.012, 0.009, segments=14, rings=4, squircle=0.76))
                p_ss_top = p_bb + (st_len * 0.27) * u_st + np.array([-0.014, 0.0, side * 0.024])
                ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0.0, 0.014, 0.0]), p_ss_top, 0.012, 0.009, 0.014, 0.010, segments=14, rings=4, squircle=0.80))
            named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
            named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))

    elif frame_arch == "stagger_midstep":
        # EXPLICIT STAGGER / TRAPEZ / MID-STEP DOUBLE-TUBE FRAME (separate downtube + dropped top tube)
        dt_start = p_ht_bot - 0.012 * u_ht
        dt_end = p_bb + np.array([0.030, 0.022, 0.0])
        dt_mesh = make_tapered_tube(dt_start, dt_end, 0.040, 0.032, 0.046, 0.035, segments=24, rings=8, squircle=0.76)
        named_parts.append(("frame_downtube", _apply_mat(dt_mesh, mats["frame"])))

        tt_start = p_ht_top + 0.028 * u_ht
        tt_end = p_bb + (st_len * 0.36) * u_st
        tt_ctrl = 0.5 * (tt_start + tt_end) + np.array([0.01, -0.020, 0.0])
        tt_mesh = make_curved_hydroformed_tube([tt_start, tt_ctrl, tt_end], [0.024, 0.022, 0.026], [0.019, 0.019, 0.022], segments=20, samples=14, squircle=0.78)
        named_parts.append(("frame_stagger_toptube", _apply_mat(tt_mesh, mats["frame"])))

        st_mesh = make_tapered_tube(p_bb + np.array([0, 0.018, 0]), p_st_top, 0.026, 0.024, 0.021, 0.021, segments=22, rings=6, squircle=0.82)
        named_parts.append(("frame_seattube", _apply_mat(st_mesh, mats["frame"])))

        cs_meshes, ss_meshes = [], []
        for side in (-1.0, 1.0):
            p_cs0 = p_bb + np.array([-0.010, 0.008, side * 0.040])
            p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
            cs_meshes.append(make_tapered_tube(p_cs0, p_cs1, 0.016, 0.010, 0.012, 0.009, segments=14, rings=4, squircle=0.76))
            p_ss_top = p_bb + (st_len * 0.38) * u_st + np.array([-0.014, 0.0, side * 0.024])
            ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0.0, 0.014, 0.0]), p_ss_top, 0.012, 0.009, 0.014, 0.010, segments=14, rings=4, squircle=0.80))
        named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
        named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))

    elif frame_arch == "aero_gravel_road":
        # MODERN AERO GRAVEL / ROAD: Dropped aero seatstays + sleek hydroformed triangle!
        dt_start = p_ht_bot - 0.018 * u_ht
        dt_end = p_bb + np.array([0.018, 0.018, 0.0])
        dt_mesh = make_tapered_tube(dt_start, dt_end, 0.029, 0.020, 0.033, 0.023, segments=22, rings=8, squircle=0.78)
        named_parts.append(("frame_downtube", _apply_mat(dt_mesh, mats["frame"])))

        tt_start = p_ht_top + 0.022 * u_ht
        tt_end = p_bb + (st_len * 0.90) * u_st
        tt_mesh = make_tapered_tube(tt_start, tt_end, 0.022, 0.020, 0.015, 0.017, segments=20, rings=8, squircle=0.78)
        named_parts.append(("frame_toptube", _apply_mat(tt_mesh, mats["frame"])))

        st_mesh = make_tapered_tube(p_bb + np.array([0, 0.012, 0]), p_st_top, 0.020, 0.018, 0.017, 0.015, segments=20, rings=6, squircle=0.82)
        named_parts.append(("frame_seattube", _apply_mat(st_mesh, mats["frame"])))

        cs_meshes, ss_meshes = [], []
        for side in (-1.0, 1.0):
            p_cs0 = p_bb + np.array([-0.010, 0.002, side * 0.032])
            p_cs_mid = 0.45 * p_cs0 + 0.55 * (p_ra + np.array([0, -0.010, side * (r_hub_w * 0.52)]))
            p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
            cs_meshes.append(make_tapered_tube(p_cs0, p_cs_mid, 0.016, 0.009, 0.013, 0.008, segments=14, rings=3, squircle=0.74))
            cs_meshes.append(make_tapered_tube(p_cs_mid, p_cs1, 0.013, 0.008, 0.010, 0.007, segments=14, rings=3, squircle=0.74))
            # Dropped aero seatstays joining ~70% up seat tube!
            p_ss_top = p_bb + (st_len * 0.70) * u_st + np.array([-0.010, 0.0, side * 0.016])
            ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0, 0.010, 0]), p_ss_top, 0.009, 0.006, 0.011, 0.007, segments=14, rings=4, squircle=0.82))
        named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
        named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))

    else:
        # DIAMOND / SLOPING TOP-TUBE MTB & SUV FULL-SUSPENSION
        # Dispatches true mechanical linkage type: horst_vertical_front, horst_horizontal_toptube, or vpp_lower_tunnel!
        dt_start = p_ht_bot - 0.018 * u_ht
        dt_end = p_bb + np.array([0.026, 0.026, 0.0])
        dt_mid = 0.52 * dt_start + 0.48 * dt_end + np.array([0.015, -0.018, 0.0])
        dt_r_y = 0.050 if is_ebike else 0.033
        if is_ebike:
            dt_mesh = make_curved_hydroformed_tube([dt_start, dt_mid, dt_end], [0.044, 0.048, 0.052], [0.034, 0.036, 0.038], segments=24, samples=16, squircle=0.74)
        else:
            dt_mesh = make_curved_hydroformed_tube([dt_start, dt_mid, dt_end], [0.030, 0.032, 0.034], [0.023, 0.025, 0.027], segments=22, samples=16, squircle=0.80)
        named_parts.append(("frame_downtube", _apply_mat(dt_mesh, mats["frame"])))

        # Sculpted sloping top tube aligned closely to real e-MTB / Trail / SUV frames
        tt_start = p_ht_top + 0.022 * u_ht
        tt_end = p_bb + (st_len * 0.72) * u_st
        tt_ctrl = 0.45 * tt_start + 0.55 * tt_end + np.array([-0.01, 0.008, 0.0])
        tt_mesh = make_curved_hydroformed_tube([tt_start, tt_ctrl, tt_end], [0.026, 0.021, 0.018], [0.023, 0.020, 0.019], segments=20, samples=16, squircle=0.78)
        named_parts.append(("frame_toptube", _apply_mat(tt_mesh, mats["frame"])))

        st_mesh = make_tapered_tube(p_bb + np.array([0, 0.016, 0]), p_st_top, 0.024, 0.024, 0.019, 0.019, segments=22, rings=6)
        named_parts.append(("frame_seattube", _apply_mat(st_mesh, mats["frame"])))

        rear_pivot_z = 0.042 if is_ebike else 0.034
        cs_meshes, ss_meshes, link_parts, boss_parts = [], [], [], []

        if not full_sus:
            # Clean hardtail rear triangle
            for side in (-1.0, 1.0):
                p_cs0 = p_bb + np.array([-0.012, 0.004, side * rear_pivot_z])
                p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
                cs_meshes.append(make_tapered_tube(p_cs0, p_cs1, 0.016, 0.010, 0.011, 0.008, segments=14, rings=4, squircle=0.74))
                p_ss_top = p_bb + (st_len * 0.72) * u_st + np.array([-0.012, 0.0, side * 0.018])
                ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0.0, 0.012, 0.0]), p_ss_top, 0.011, 0.008, 0.013, 0.009, segments=14, rings=4, squircle=0.78))
            named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
            named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))

        elif suspension_type == "horst_vertical_front":
            # TYPE A: 4-BAR HORST LINK / BEAMER WITH VERTICAL SHOCK IN FRONT OF SEAT TUBE
            # (2026 Santa Cruz Tallboy, Kona Remote 160 CR, Trek Fuel EX, Giant Trance, Pivot, Transition)
            p_main_piv = p_bb + np.array([-0.010, 0.044, 0.0])
            p_horst = p_ra + np.array([0.036, -0.020, 0.0])
            p_rocker_st = p_bb + (st_len * 0.50) * u_st
            p_rocker_ss = p_rocker_st + np.array([-0.056, 0.006, 0.0])
            p_shock_top = p_rocker_st + np.array([0.084, 0.026, 0.0])

            # Evaluate downtube Bezier at u=0.84 so lower shock clevis seats FLUSH on the downtube top surface!
            u_dt = 0.84
            p_dt_anchor = (1 - u_dt) ** 2 * dt_start + 2 * (1 - u_dt) * u_dt * dt_mid + u_dt**2 * dt_end
            p_dt_tan = 2 * (1 - u_dt) * (dt_mid - dt_start) + 2 * u_dt * (dt_end - dt_mid)
            p_dt_tan = p_dt_tan / (np.linalg.norm(p_dt_tan) + 1e-12)
            p_dt_up = np.array([-p_dt_tan[1], p_dt_tan[0], 0.0])
            if p_dt_up[1] < 0:
                p_dt_up = -p_dt_up
            p_shock_bot = p_dt_anchor + p_dt_up * (dt_r_y + 0.014)

            for side in (-1.0, 1.0):
                p_cs0 = p_main_piv + np.array([0.0, 0.0, side * rear_pivot_z])
                p_h = p_horst + np.array([0.0, 0.0, side * (r_hub_w * 0.50)])
                p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
                p_cs_mid = 0.50 * p_cs0 + 0.50 * p_h + np.array([0.0, -0.012 if side > 0 else -0.004, 0.0])
                cs_meshes.append(make_tapered_tube(p_cs0, p_cs_mid, 0.017, 0.010, 0.014, 0.009, segments=14, rings=3, squircle=0.74))
                cs_meshes.append(make_tapered_tube(p_cs_mid, p_h, 0.014, 0.009, 0.013, 0.009, segments=14, rings=3, squircle=0.74))
                # Rear dropout extension from Horst pivot to rear axle
                ss_meshes.append(make_tapered_tube(p_h, p_cs1, 0.013, 0.009, 0.013, 0.009, segments=12, rings=2, squircle=0.75))
                # Seatstay from Horst pivot / dropout up to rear arm of rocker link
                p_ss_top = p_rocker_ss + np.array([0.0, 0.0, side * 0.032])
                ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0.0, 0.010, 0.0]), p_ss_top, 0.012, 0.008, 0.013, 0.009, segments=14, rings=4, squircle=0.78))

                # Closed triangular CNC bell-crank rocker link (seat-tube pivot <-> seatstay <-> shock top)
                p_l_st = p_rocker_st + np.array([0.0, 0.0, side * 0.028])
                p_l_sh = p_shock_top + np.array([0.0, 0.0, side * 0.022])
                link_parts.append(make_tapered_tube(p_ss_top, p_l_st, 0.013, 0.006, 0.015, 0.006, segments=12, rings=2, squircle=0.72))
                link_parts.append(make_tapered_tube(p_l_st, p_l_sh, 0.015, 0.006, 0.013, 0.006, segments=12, rings=2, squircle=0.72))
                link_parts.append(make_tapered_tube(p_ss_top, p_l_sh, 0.010, 0.005, 0.010, 0.005, segments=10, rings=2, squircle=0.72))
                # Machined Horst pivot cap
                link_parts.append(make_cylinder_z(p_h, 0.011, 0.016, sections=14))
                # Downtube lower shock clevis ears
                boss_parts.append(
                    make_tapered_tube(
                        p_dt_anchor + np.array([0.0, 0.0, side * 0.018]),
                        p_shock_bot + np.array([0.0, 0.0, side * 0.018]),
                        0.020, 0.007, 0.015, 0.006, segments=10, rings=2, squircle=0.72,
                    )
                )

            # Pivot axle hardware caps (Main Pivot, Seat-Tube Rocker Pivot, Shock Top/Bot Eyelets)
            link_parts.append(make_cylinder_z(p_main_piv, 0.014, rear_pivot_z * 2.15, sections=16))
            link_parts.append(make_cylinder_z(p_rocker_st, 0.013, 0.068, sections=16))
            link_parts.append(make_cylinder_z(p_shock_top, 0.010, 0.052, sections=14))
            link_parts.append(make_cylinder_z(p_shock_bot, 0.010, 0.048, sections=14))
            named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
            named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))
            named_parts.append(("frame_shock_clevis_boss", _apply_mat(trimesh.util.concatenate(boss_parts), mats["frame"])))
            named_parts.append(("suspension_rocker_link", _apply_mat(trimesh.util.concatenate(link_parts), mats["dark_alloy"])))

            # Vertical rear shock standing cleanly in front of seat tube (can at top, shaft to downtube!)
            sh_mid = 0.42 * p_shock_bot + 0.58 * p_shock_top
            sh_can = make_tapered_tube(sh_mid, p_shock_top, 0.023, 0.023, 0.025, 0.025, segments=22, rings=4)
            sh_shaft = make_tapered_tube(p_shock_bot, sh_mid + 0.02 * (p_shock_top - p_shock_bot), 0.014, 0.014, 0.014, 0.014, segments=18, rings=2)
            sh_parts = [sh_can]
            if travel_r >= 0.135:
                sh_dir = p_shock_top - p_shock_bot
                sh_u = sh_dir / (np.linalg.norm(sh_dir) + 1e-12)
                sh_fwd = np.array([sh_u[1], -sh_u[0], 0.0])
                if sh_fwd[0] < 0:
                    sh_fwd = -sh_fwd
                pb_p0 = p_shock_top - 0.020 * sh_u + sh_fwd * 0.032
                pb_p1 = pb_p0 - 0.088 * sh_u
                sh_parts.append(make_tapered_tube(pb_p0, pb_p1, 0.012, 0.012, 0.012, 0.012, segments=16, rings=3))
            named_parts.append(("rear_shock_body", _apply_mat(trimesh.util.concatenate(sh_parts), mats["dark_alloy"])))
            named_parts.append(("rear_shock_shaft", _apply_mat(sh_shaft, mats["stanchion"])))

        elif suspension_type == "vpp_lower_tunnel":
            # TYPE B: LOWER-LINK VPP / TUNNEL-DRIVEN LOW HORIZONTAL SHOCK
            # (Classic Santa Cruz Hightower/Megatower/Bronson/Nomad, Intense)
            p_upper_st = p_bb + (st_len * 0.44) * u_st
            p_lower_bb = p_bb + np.array([0.008, 0.032, 0.0])
            p_rt_top = p_upper_st + np.array([-0.056, 0.012, 0.0])
            p_rt_bot = p_lower_bb + np.array([-0.048, 0.006, 0.0])

            u_dt = 0.68
            p_dt_anchor = (1 - u_dt) ** 2 * dt_start + 2 * (1 - u_dt) * u_dt * dt_mid + u_dt**2 * dt_end
            p_shock_front = p_dt_anchor + np.array([-0.014, 0.032, 0.0])
            p_shock_rear = p_lower_bb + np.array([0.016, 0.012, 0.0])

            for side in (-1.0, 1.0):
                p_cs0 = p_rt_bot + np.array([0.0, 0.0, side * rear_pivot_z])
                p_ss0 = p_rt_top + np.array([0.0, 0.0, side * 0.034])
                p_ra_s = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
                # Rigid 1-piece VPP rear triangle (chainstay + seatstay + front vertical brace, NO Horst pivot)
                cs_meshes.append(make_tapered_tube(p_cs0, p_ra_s, 0.016, 0.010, 0.012, 0.009, segments=14, rings=4, squircle=0.74))
                ss_meshes.append(make_tapered_tube(p_ra_s + np.array([0.0, 0.012, 0.0]), p_ss0, 0.012, 0.008, 0.014, 0.009, segments=14, rings=4, squircle=0.78))
                ss_meshes.append(make_tapered_tube(p_cs0, p_ss0, 0.014, 0.009, 0.013, 0.009, segments=12, rings=2, squircle=0.74))
                # Counter-rotating Upper & Lower VPP short links
                link_parts.append(make_tapered_tube(p_upper_st + np.array([0, 0, side * 0.026]), p_ss0, 0.013, 0.006, 0.012, 0.006, segments=12, rings=2, squircle=0.72))
                link_parts.append(make_tapered_tube(p_lower_bb + np.array([0, 0, side * 0.028]), p_cs0, 0.015, 0.007, 0.014, 0.007, segments=12, rings=2, squircle=0.72))
                boss_parts.append(make_tapered_tube(p_dt_anchor + np.array([0, 0, side * 0.018]), p_shock_front + np.array([0, 0, side * 0.018]), 0.018, 0.007, 0.014, 0.006, segments=10, rings=2, squircle=0.72))

            link_parts.append(make_cylinder_z(p_upper_st, 0.012, 0.062, sections=16))
            link_parts.append(make_cylinder_z(p_lower_bb, 0.014, 0.072, sections=16))
            link_parts.append(make_cylinder_z(p_shock_front, 0.009, 0.044, sections=14))
            named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
            named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))
            named_parts.append(("frame_shock_clevis_boss", _apply_mat(trimesh.util.concatenate(boss_parts), mats["frame"])))
            named_parts.append(("suspension_vpp_links", _apply_mat(trimesh.util.concatenate(link_parts), mats["dark_alloy"])))

            sh_mid = 0.45 * p_shock_rear + 0.55 * p_shock_front
            sh_can = make_tapered_tube(sh_mid, p_shock_front, 0.022, 0.022, 0.024, 0.024, segments=22, rings=4)
            sh_shaft = make_tapered_tube(p_shock_rear, sh_mid + 0.02 * (p_shock_front - p_shock_rear), 0.013, 0.013, 0.013, 0.013, segments=18, rings=2)
            named_parts.append(("rear_shock_body", _apply_mat(sh_can, mats["dark_alloy"])))
            named_parts.append(("rear_shock_shaft", _apply_mat(sh_shaft, mats["stanchion"])))

        else:
            # TYPE C: HORIZONTAL / SLOPED UNDER-TOP-TUBE INLINE-YOKE 4-BAR / CONCENTRIC PIVOT
            # (2027 Orbea Rise LT, Specialized Turbo Vado 3 X 6.0, Aventon Current REC, Canyon Spectral, Cube Stereo)
            # Seatstay -> Rocker Upper Pivot -> Coaxial Twin-Arm CNC Shock Yoke -> Shock -> Tight Top-Tube Clevis!
            p_main_piv = p_bb + np.array([0.004, 0.042, 0.0])
            is_concentric = "orbea" in bike.get("brand", "").lower() or "rise" in bike.get("model_name", "").lower()
            p_horst = p_ra if is_concentric else (p_ra + np.array([0.032, -0.018, 0.0]))
            p_rocker_st = p_bb + (st_len * 0.49) * u_st
            p_rocker_upper = p_rocker_st + np.array([-0.026, 0.038, 0.0])

            # Compact integrated top-tube clevis pocket (only 24mm below top-tube centerline — ZERO dangling stick!)
            u_tt = 0.44
            p_tt_anchor = (1 - u_tt) ** 2 * tt_start + 2 * (1 - u_tt) * u_tt * tt_ctrl + u_tt**2 * tt_end
            p_shock_front = p_tt_anchor + np.array([0.0, -0.024, 0.0])

            # Strictly COAXIAL straight diagonal line from under-top-tube clevis -> shock -> CNC Yoke -> rocker upper pivot!
            v_line = p_rocker_upper - p_shock_front
            dist_line = float(np.linalg.norm(v_line))
            u_line = v_line / (dist_line + 1e-12)
            shock_len = min(0.205, dist_line * 0.68)
            p_shock_rear = p_shock_front + shock_len * u_line

            for side in (-1.0, 1.0):
                p_cs0 = p_main_piv + np.array([0.0, 0.0, side * rear_pivot_z])
                p_h = p_horst + np.array([0.0, 0.0, side * (r_hub_w * 0.50)])
                p_cs1 = p_ra + np.array([0.0, 0.0, side * (r_hub_w * 0.52)])
                p_cs_mid = 0.50 * p_cs0 + 0.50 * p_h + np.array([0.0, -0.012 if side > 0 else -0.004, 0.0])
                cs_meshes.append(make_tapered_tube(p_cs0, p_cs_mid, 0.017, 0.010, 0.014, 0.009, segments=14, rings=3, squircle=0.74))
                cs_meshes.append(make_tapered_tube(p_cs_mid, p_h, 0.014, 0.009, 0.012, 0.008, segments=14, rings=3, squircle=0.74))
                if not is_concentric:
                    ss_meshes.append(make_tapered_tube(p_h, p_cs1, 0.012, 0.008, 0.012, 0.008, segments=12, rings=2, squircle=0.75))
                    link_parts.append(make_cylinder_z(p_h, 0.010, 0.015, sections=14))

                # Seatstay runs straight into rocker upper pivot — visually continuous with shock & yoke!
                p_l_up = p_rocker_upper + np.array([0.0, 0.0, side * 0.030])
                p_l_st = p_rocker_st + np.array([0.0, 0.0, side * 0.026])
                ss_meshes.append(make_tapered_tube(p_cs1 + np.array([0.0, 0.010, 0.0]), p_l_up, 0.012, 0.008, 0.014, 0.009, segments=14, rings=4, squircle=0.78))

                # Compact vertical rocker link pivoting on seat tube + straight coaxial twin-arm CNC Shock Yoke straddling seat tube!
                link_parts.append(make_tapered_tube(p_l_st, p_l_up, 0.014, 0.006, 0.014, 0.006, segments=12, rings=2, squircle=0.74))
                p_yoke_front = p_shock_rear + np.array([0.0, 0.0, side * 0.014])
                p_yoke_mid = 0.55 * p_l_up + 0.45 * p_yoke_front + np.array([0.0, 0.0, side * 0.008])
                link_parts.append(make_tapered_tube(p_l_up, p_yoke_mid, 0.012, 0.006, 0.011, 0.006, segments=12, rings=2, squircle=0.74))
                link_parts.append(make_tapered_tube(p_yoke_mid, p_yoke_front, 0.011, 0.006, 0.010, 0.006, segments=12, rings=2, squircle=0.74))

                # Tight integrated top-tube shock clevis pocket
                boss_parts.append(
                    make_tapered_tube(
                        p_tt_anchor + np.array([0.004, 0.0, side * 0.016]),
                        p_shock_front + np.array([0.0, 0.0, side * 0.016]),
                        0.018, 0.007, 0.014, 0.006, segments=10, rings=2, squircle=0.72,
                    )
                )

            link_parts.append(make_cylinder_z(p_main_piv, 0.014, rear_pivot_z * 2.15, sections=16))
            link_parts.append(make_cylinder_z(p_rocker_st, 0.012, 0.062, sections=16))
            link_parts.append(make_cylinder_z(p_rocker_upper, 0.011, 0.068, sections=16))
            link_parts.append(make_cylinder_z(p_shock_rear, 0.010, 0.036, sections=14))
            link_parts.append(make_cylinder_z(p_shock_front, 0.009, 0.042, sections=14))
            named_parts.append(("rear_chainstays", _apply_mat(trimesh.util.concatenate(cs_meshes), mats["frame"])))
            named_parts.append(("rear_seatstays", _apply_mat(trimesh.util.concatenate(ss_meshes), mats["frame"])))
            named_parts.append(("frame_shock_clevis_boss", _apply_mat(trimesh.util.concatenate(boss_parts), mats["frame"])))
            named_parts.append(("suspension_rocker_yoke", _apply_mat(trimesh.util.concatenate(link_parts), mats["dark_alloy"])))

            sh_mid = 0.44 * p_shock_rear + 0.56 * p_shock_front
            sh_can = make_tapered_tube(sh_mid, p_shock_front, 0.023, 0.023, 0.024, 0.024, segments=22, rings=4)
            sh_shaft = make_tapered_tube(p_shock_rear, sh_mid + 0.02 * (p_shock_front - p_shock_rear), 0.014, 0.014, 0.014, 0.014, segments=18, rings=2)
            sh_parts = [sh_can]
            if travel_r >= 0.135:
                sh_dir = p_shock_front - p_shock_rear
                _, sh_n, _ = _basis_from_dir(sh_dir)
                if sh_n[1] > 0:
                    sh_n = -sh_n
                pb_p0 = p_shock_front - 0.022 * (sh_dir / (np.linalg.norm(sh_dir) + 1e-12)) + sh_n * 0.030
                pb_p1 = pb_p0 - 0.084 * (sh_dir / (np.linalg.norm(sh_dir) + 1e-12))
                sh_parts.append(make_tapered_tube(pb_p0, pb_p1, 0.012, 0.012, 0.012, 0.012, segments=16, rings=3))
            named_parts.append(("rear_shock_body", _apply_mat(trimesh.util.concatenate(sh_parts), mats["dark_alloy"])))
            named_parts.append(("rear_shock_shaft", _apply_mat(sh_shaft, mats["stanchion"])))

    # Seatpost collar
    st_clamp = make_tapered_tube(p_st_top - 0.008 * u_st, p_st_top + 0.012 * u_st, 0.022, 0.022, 0.022, 0.022, segments=20, rings=2)
    named_parts.append(("seatpost_collar", _apply_mat(st_clamp, mats["dark_alloy"])))

    # BB Shell OR Integrated E-Bike Motor Unit
    if is_ebike:
        motor_main = make_cylinder_z(p_bb + np.array([0.016, 0.014, 0.0]), 0.064, 0.114, sections=28)
        motor_front = make_cylinder_z(p_bb + np.array([0.068, 0.032, 0.0]), 0.042, 0.102, sections=22)
        motor_skid = make_tapered_tube(
            p_bb + np.array([-0.032, -0.044, 0.0]),
            p_bb + np.array([0.090, -0.018, 0.0]),
            0.019, 0.048, 0.017, 0.044, segments=14, rings=3, squircle=0.72,
        )
        named_parts.append(("ebike_motor_housing", _apply_mat(trimesh.util.concatenate([motor_main, motor_front, motor_skid]), mats["motor_housing"])))
    else:
        bb_shell = make_cylinder_z(p_bb, 0.026, 0.078 if is_mtb else 0.070, sections=24)
        named_parts.append(("frame_bb_shell", _apply_mat(bb_shell, mats["frame"])))

    # --- 5. TRUE HTA-COAXIAL FORK ASSEMBLY (SUSPENSION vs RIGID AERO BLADE) ---
    fork_span_z = 0.064 if is_mtb else 0.052
    if travel_f >= 0.04:
        stanchion_r = 0.019 if travel_f >= 0.145 else (0.017 if travel_f >= 0.10 else 0.0155)
        # Sculpted forged fork crown seated flush under lower headset cup (zero detached dog-leg!)
        crown_parts = [
            make_tapered_tube(
                p_ht_bot + 0.002 * u_ht,
                p_crown_axis + 0.018 * u_ht,
                ht_r * 1.00, ht_r * 1.00, ht_r * 0.88, ht_r * 0.88,
                segments=22, rings=2,
            )
        ]
        for side in (-1.0, 1.0):
            p_shoulder = p_crown_offset + np.array([0.0, 0.0, side * fork_span_z]) + 0.008 * u_ht
            crown_parts.append(
                make_tapered_tube(
                    p_crown_axis + 0.008 * u_ht,
                    p_shoulder,
                    0.022, 0.024, stanchion_r * 1.24, stanchion_r * 1.24,
                    segments=16, rings=3, squircle=0.78,
                )
            )
            # Top cap / rebound adjuster knob at top of each crown bore
            crown_parts.append(
                make_tapered_tube(
                    p_shoulder - 0.016 * u_ht,
                    p_shoulder + 0.016 * u_ht,
                    stanchion_r * 1.22, stanchion_r * 1.22, stanchion_r * 1.22, stanchion_r * 1.22,
                    segments=18, rings=2,
                )
            )
        named_parts.append(("fork_crown", _apply_mat(trimesh.util.concatenate(crown_parts), mats["dark_alloy"])))

        stanchion_ratio = min(0.46, max(0.24, (travel_f + 0.032) / max(0.35, s_fork_along)))
        stanchion_meshes, lower_meshes = [], []
        for side in (-1.0, 1.0):
            p_top_leg = p_crown_offset + np.array([0.0, 0.0, side * fork_span_z]) + 0.014 * u_ht
            # Stanchions AND lowers stay strictly parallel to head tube axis (u_ht)!
            p_seal = p_top_leg + (s_fork_along * stanchion_ratio) * u_ht
            p_lower_bot = p_crown_offset + s_fork_along * u_ht + np.array([0.0, 0.0, side * (f_hub_w * 0.56)])
            p_axle_lug = p_fa + np.array([0.0, 0.0, side * (f_hub_w * 0.54)])

            stanchion_meshes.append(
                make_tapered_tube(p_top_leg, p_seal, stanchion_r, stanchion_r, stanchion_r, stanchion_r, segments=18, rings=3)
            )
            # Seal wiper collar + parallel tapered lower leg casting
            lower_meshes.append(
                make_tapered_tube(
                    p_seal - 0.008 * u_ht, p_seal + 0.012 * u_ht,
                    stanchion_r * 1.28, stanchion_r * 1.28, stanchion_r * 1.28, stanchion_r * 1.28,
                    segments=18, rings=2,
                )
            )
            lower_meshes.append(
                make_tapered_tube(
                    p_seal, p_lower_bot,
                    stanchion_r * 1.24, stanchion_r * 1.24, stanchion_r * 1.06, stanchion_r * 1.06,
                    segments=18, rings=4,
                )
            )
            # Forward thru-axle dropout lug projecting cleanly from lower leg onto front axle p_fa!
            lower_meshes.append(
                make_tapered_tube(
                    p_lower_bot - 0.014 * u_ht, p_axle_lug,
                    stanchion_r * 1.04, stanchion_r * 0.92, 0.016, 0.014,
                    segments=14, rings=2, squircle=0.75,
                )
            )
            lower_meshes.append(make_cylinder_z(p_axle_lug, 0.015, 0.014, sections=16))

        p_arch_c = p_crown_offset + (s_fork_along * stanchion_ratio + 0.014) * u_ht + 0.018 * n_ht
        p_arch_l = p_arch_c + np.array([0, 0, -fork_span_z])
        p_arch_r = p_arch_c + np.array([0, 0, fork_span_z])
        p_arch_mid = p_arch_c + 0.020 * n_ht - 0.024 * u_ht
        lower_meshes.append(make_swept_polyline([p_arch_l, p_arch_mid, p_arch_r], 0.012, segments=12))

        named_parts.append(("fork_stanchions", _apply_mat(trimesh.util.concatenate(stanchion_meshes), mats["stanchion"])))
        named_parts.append(("fork_lowers", _apply_mat(trimesh.util.concatenate(lower_meshes), mats["dark_alloy"])))
    else:
        # Coaxial integrated rigid fork crown + smooth tangent-entry carbon aero blades
        blade_meshes = [
            make_tapered_tube(
                p_ht_bot + 0.002 * u_ht,
                p_crown_axis + 0.024 * u_ht,
                ht_r * 1.02, ht_r * 1.02, ht_r * 0.90, ht_r * 0.90,
                segments=22, rings=2,
            ),
            make_tapered_tube(
                p_crown_offset + 0.014 * u_ht + np.array([0, 0, -fork_span_z * 0.72]),
                p_crown_offset + 0.014 * u_ht + np.array([0, 0, fork_span_z * 0.72]),
                0.022, 0.018, 0.022, 0.018, segments=16, rings=2, squircle=0.75,
            ),
        ]
        for side in (-1.0, 1.0):
            p_top_leg = p_crown_offset + 0.014 * u_ht + np.array([0.0, 0.0, side * fork_span_z * 0.68])
            p_ctrl_leg = p_top_leg + (s_fork_along * 0.56) * u_ht + np.array([0.0, 0.0, side * (f_hub_w * 0.53 - fork_span_z * 0.68) * 0.5])
            p_bot_leg = p_fa + np.array([0.0, 0.0, side * (f_hub_w * 0.53)])
            blade_meshes.append(
                make_curved_hydroformed_tube(
                    [p_top_leg, p_ctrl_leg, p_bot_leg],
                    [0.022, 0.018, 0.013],
                    [0.009, 0.008, 0.007],
                    segments=16, samples=12, squircle=0.78,
                )
            )
        named_parts.append(("fork_rigid_blades", _apply_mat(trimesh.util.concatenate(blade_meshes), mats["frame"])))

    # --- 6. BRAKE CALIPERS ---
    caliper_meshes = []
    f_rot_r = (rotor_f_mm / 1000.0) * 0.5
    f_cal_pos = p_fa + np.array([f_rot_r * 0.90 * math.cos(math.radians(122.0)), f_rot_r * 0.90 * math.sin(math.radians(122.0)), -f_hub_w * 0.44])
    f_cal = trimesh.creation.box(extents=[0.044, 0.028, 0.030])
    f_cal.apply_translation(f_cal_pos)
    caliper_meshes.append(f_cal)

    r_rot_r = (rotor_r_mm / 1000.0) * 0.5
    r_cal_pos = p_ra + np.array([r_rot_r * 0.90 * math.cos(math.radians(24.0)), r_rot_r * 0.90 * math.sin(math.radians(24.0)), -r_hub_w * 0.44])
    r_cal = trimesh.creation.box(extents=[0.044, 0.026, 0.030])
    r_cal.apply_translation(r_cal_pos)
    caliper_meshes.append(r_cal)
    named_parts.append(("brake_calipers", _apply_mat(trimesh.util.concatenate(caliper_meshes), mats["dark_alloy"])))

    # --- 7. DRIVETRAIN (CHAIN + CASSETTE vs GATES CARBON BELT DRIVE!) ---
    chain_z = 0.054 if is_mtb else 0.047
    crank_len = 0.170
    crank_ang = math.radians(-14.0 if is_tall_urban else -20.0)
    p_crank_r = p_bb + np.array([crank_len * math.cos(crank_ang), crank_len * math.sin(crank_ang), 0.088])
    p_crank_l = p_bb + np.array([-crank_len * math.cos(crank_ang), -crank_len * math.sin(crank_ang), -0.088])
    crank_arm_r = make_tapered_tube(p_bb + np.array([0, 0, 0.072]), p_crank_r, 0.018, 0.008, 0.014, 0.007, segments=12, rings=3, squircle=0.70)
    crank_arm_l = make_tapered_tube(p_bb + np.array([0, 0, -0.072]), p_crank_l, 0.018, 0.008, 0.014, 0.007, segments=12, rings=3, squircle=0.70)
    spindle = make_cylinder_z(p_bb, 0.012, 0.148, sections=16)
    pedal_r = trimesh.creation.box(extents=[0.098, 0.014, 0.088])
    pedal_r.apply_translation(p_crank_r + np.array([0, 0, 0.052]))
    pedal_l = trimesh.creation.box(extents=[0.098, 0.014, 0.088])
    pedal_l.apply_translation(p_crank_l + np.array([0, 0, -0.052]))
    named_parts.append(("drivetrain_crankset", _apply_mat(trimesh.util.concatenate([crank_arm_r, crank_arm_l, spindle, pedal_r, pedal_l]), mats["dark_alloy"])))

    ring_r = 0.078 if has_belt else (0.072 if is_mtb else 0.088)
    chainring = make_annulus_z(p_bb + np.array([0, 0, chain_z]), ring_r * 0.65, ring_r, 0.005, sections=36)
    ring_spider = make_cylinder_z(p_bb + np.array([0, 0, chain_z]), ring_r * 0.68, 0.005, sections=12)
    named_parts.append(("drivetrain_chainring", _apply_mat(trimesh.util.concatenate([chainring, ring_spider]), mats["dark_alloy"] if has_belt else mats["raw_alloy"])))

    if has_belt:
        # Clean Gates Carbon Belt Drive (single rear belt sprocket + tensioner + toothed black belt)
        rear_cog_r = 0.044
        rear_cog = make_annulus_z(p_ra + np.array([0, 0, r_hub_w * 0.36]), 0.018, rear_cog_r, 0.009, sections=32)
        named_parts.append(("drivetrain_belt_sprocket", _apply_mat(rear_cog, mats["dark_alloy"])))
        belt_top = make_tapered_tube(p_bb + np.array([0, ring_r * 0.96, chain_z]), p_ra + np.array([0, rear_cog_r * 0.96, r_hub_w * 0.36]), 0.0055, 0.0055, 0.0055, 0.0055, segments=8, rings=2)
        belt_bot = make_tapered_tube(p_bb + np.array([0, -ring_r * 0.96, chain_z]), p_ra + np.array([0, -rear_cog_r * 0.96, r_hub_w * 0.36]), 0.0055, 0.0055, 0.0055, 0.0055, segments=8, rings=2)
        named_parts.append(("drivetrain_carbon_belt", _apply_mat(trimesh.util.concatenate([belt_top, belt_bot]), mats["tire"])))
    else:
        cass_meshes = []
        max_cog_r = 0.104 if is_mtb else 0.084
        for i in range(10):
            u = i / 9.0
            cog_r = max_cog_r * (1.0 - u) + 0.024 * u
            z_cog = r_hub_w * 0.25 + u * 0.036
            cass_meshes.append(make_annulus_z(p_ra + np.array([0, 0, z_cog]), 0.017, cog_r, 0.0022, sections=30))
        named_parts.append(("drivetrain_cassette", _apply_mat(trimesh.util.concatenate(cass_meshes), mats["steel"])))

        p_rd_top = p_ra + np.array([0.008, -0.042, r_hub_w * 0.56])
        p_rd_bot = p_ra + np.array([-0.018, -0.118, r_hub_w * 0.56])
        rd_arm = make_tapered_tube(p_rd_top, p_rd_bot, 0.012, 0.007, 0.010, 0.006, segments=10, rings=2)
        rd_p1 = make_cylinder_z(p_rd_top + np.array([0.004, -0.020, 0.0]), 0.018, 0.008, sections=16)
        rd_p2 = make_cylinder_z(p_rd_bot, 0.020, 0.008, sections=16)
        named_parts.append(("drivetrain_derailleur", _apply_mat(trimesh.util.concatenate([rd_arm, rd_p1, rd_p2]), mats["dark_alloy"])))

        ch_top = make_tapered_tube(p_bb + np.array([0, ring_r * 0.96, chain_z]), p_ra + np.array([0, max_cog_r * 0.62, r_hub_w * 0.36]), 0.0045, 0.0032, 0.0045, 0.0032, segments=8, rings=2)
        ch_bot = make_tapered_tube(p_bb + np.array([0, -ring_r * 0.96, chain_z]), p_rd_bot + np.array([0, -0.015, -0.010]), 0.0045, 0.0032, 0.0045, 0.0032, segments=8, rings=2)
        named_parts.append(("drivetrain_chain", _apply_mat(trimesh.util.concatenate([ch_top, ch_bot]), mats["steel"])))

    # --- 8. COCKPIT (TALL INTEGRATED COMMUTER MAST vs SUV vs MTB RISER vs DROP BAR) ---
    steerer_ext = 0.135 if is_tall_urban else (0.056 if frame_arch in ("lowstep_monotube", "stagger_midstep") else 0.038)
    stem_len = 0.048 if is_mtb else 0.095
    p_steerer_top = p_ht_top - steerer_ext * u_ht
    p_bar_center = p_steerer_top + np.array([0.025 if is_tall_urban else stem_len, 0.010, 0.0])
    spacer_r = 0.024 if is_tall_urban else 0.019
    spacer_stack = make_tapered_tube(p_ht_top - 0.005 * u_ht, p_steerer_top - 0.014 * u_ht, spacer_r, spacer_r * 0.9, spacer_r * 0.92, spacer_r * 0.85, segments=18, rings=3, squircle=0.78)
    stem_body = make_tapered_tube(p_steerer_top, p_bar_center, 0.019, 0.017, 0.018, 0.018, segments=16, rings=3, squircle=0.72)
    named_parts.append(("cockpit_stem", _apply_mat(trimesh.util.concatenate([spacer_stack, stem_body]), mats["dark_alloy"])))

    if bar_type == "drop":
        bar_w = 0.225
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
        named_parts.append(("cockpit_dropbar", _apply_mat(make_swept_polyline(bar_pts, 0.014, segments=14), mats["dark_alloy"])))
        hoods = []
        for side in (-1.0, 1.0):
            p_hood = p_bar_center + np.array([0.095, 0.022, side * bar_w * 0.98])
            hoods.append(make_tapered_tube(p_hood + np.array([-0.022, -0.028, 0]), p_hood + np.array([0.018, 0.022, 0]), 0.018, 0.014, 0.014, 0.012, segments=12, rings=3))
            hoods.append(make_tapered_tube(p_hood + np.array([0.015, -0.015, 0]), p_hood + np.array([0.005, -0.105, 0]), 0.007, 0.005, 0.005, 0.004, segments=8, rings=2))
        named_parts.append(("cockpit_shifter_hoods", _apply_mat(trimesh.util.concatenate(hoods), mats["saddle"])))
    else:
        bar_half = 0.390 if full_sus else 0.335
        rise = 0.024 if full_sus else 0.022
        sweep = -0.085 if is_tall_urban else (-0.060 if frame_arch in ("lowstep_monotube", "stagger_midstep") else -0.042)
        bar_pts = [
            p_bar_center + np.array([sweep, rise, -bar_half]),
            p_bar_center + np.array([sweep * 0.42, rise * 0.85, -bar_half * 0.45]),
            p_bar_center + np.array([0.0, 0.0, -0.055]),
            p_bar_center,
            p_bar_center + np.array([0.0, 0.0, 0.055]),
            p_bar_center + np.array([sweep * 0.42, rise * 0.85, bar_half * 0.45]),
            p_bar_center + np.array([sweep, rise, bar_half]),
        ]
        named_parts.append(("cockpit_riser_bar", _apply_mat(make_swept_polyline(bar_pts, 0.0145, segments=14), mats["dark_alloy"])))
        grips, levers = [], []
        for side in (-1.0, 1.0):
            g0 = p_bar_center + np.array([sweep, rise, side * bar_half])
            g1 = p_bar_center + np.array([sweep * 0.72, rise * 0.92, side * (bar_half - 0.130)])
            grips.append(make_tapered_tube(g0, g1, 0.017, 0.017, 0.017, 0.017, segments=14, rings=2))
            l0 = g1 + np.array([0.018, -0.006, -side * 0.025])
            levers.append(make_tapered_tube(l0, l0 + np.array([0.048, -0.010, side * 0.055]), 0.008, 0.005, 0.004, 0.003, segments=8, rings=2))
        named_parts.append(("cockpit_grips", _apply_mat(trimesh.util.concatenate(grips), mats["saddle"])))
        named_parts.append(("cockpit_brake_levers", _apply_mat(trimesh.util.concatenate(levers), mats["dark_alloy"])))

    if is_ebike:
        hmi_box = trimesh.creation.box(extents=[0.056, 0.014, 0.036])
        hmi_box.apply_translation(p_bar_center + np.array([-0.016, 0.024, 0.0]))
        named_parts.append(("cockpit_ebike_hmi", _apply_mat(hmi_box, mats["display_glow"])))

    # --- 9. SEATPOST & SADDLE ---
    post_ext = 0.210 if is_mtb else 0.175
    p_saddle_clamp = p_st_top + post_ext * u_st
    if is_mtb:
        p_drop_mid = p_st_top + 0.055 * u_st
        post_low = make_tapered_tube(p_st_top - 0.015 * u_st, p_drop_mid, 0.0158, 0.0158, 0.0158, 0.0158, segments=18, rings=2)
        post_up = make_tapered_tube(p_drop_mid, p_saddle_clamp, 0.013, 0.013, 0.013, 0.013, segments=18, rings=2)
        named_parts.append(("seatpost_dropper_lower", _apply_mat(post_low, mats["dark_alloy"])))
        named_parts.append(("seatpost_dropper_upper", _apply_mat(post_up, mats["stanchion"] if (kashima and frame_arch != "single_pivot_gullarm") else mats["dark_alloy"])))
    else:
        post_mesh = make_tapered_tube(p_st_top - 0.015 * u_st, p_saddle_clamp, 0.014, 0.011, 0.014, 0.011, segments=16, rings=3, squircle=0.80)
        named_parts.append(("seatpost_aero", _apply_mat(post_mesh, mats["dark_alloy"])))

    p_sad_c = p_saddle_clamp + np.array([0.012, 0.036, 0.0])
    rail_meshes = []
    for side in (-1.0, 1.0):
        rail_meshes.append(
            make_swept_polyline(
                [p_sad_c + np.array([-0.095, -0.008, side * 0.022]), p_saddle_clamp + np.array([0.0, 0.012, side * 0.022]), p_sad_c + np.array([0.088, -0.006, side * 0.018])],
                0.0035, segments=8,
            )
        )
    named_parts.append(("saddle_rails", _apply_mat(trimesh.util.concatenate(rail_meshes), mats["steel"])))
    saddle_rear = make_tapered_tube(p_sad_c + np.array([-0.125, 0.006, 0.0]), p_sad_c + np.array([-0.010, -0.004, 0.0]), 0.014, 0.068, 0.012, 0.042, segments=18, rings=4, squircle=0.72)
    saddle_nose = make_tapered_tube(p_sad_c + np.array([-0.010, -0.004, 0.0]), p_sad_c + np.array([0.135, 0.002, 0.0]), 0.012, 0.042, 0.009, 0.019, segments=16, rings=4, squircle=0.78)
    named_parts.append(("saddle_shell", _apply_mat(trimesh.util.concatenate([saddle_rear, saddle_nose]), mats["saddle"])))

    # --- 10. COMMUTER / SUV EQUIPMENT (FENDERS, REAR RACK, FRONT CARGO RACK, HEADLIGHT) ---
    if has_fenders:
        f_fend = make_fender_polyline_arc(p_fa, r_f + 0.016, (tire_w_mm / 1000.0) * 1.15, 76.0, 212.0, steps=26)
        r_fend = make_fender_polyline_arc(p_ra, r_r + 0.016, (tire_w_mm / 1000.0) * 1.15, 4.0, 166.0, steps=28)
        stay_parts = []
        for side in (-1.0, 1.0):
            # Front & rear fender support stays
            stay_parts.append(make_tapered_tube(p_fa + np.array([0, 0, side * (f_hub_w * 0.56)]), p_fa + np.array([-(r_f + 0.015) * 0.90, -(r_f + 0.015) * 0.42, side * 0.032]), 0.003, 0.003, 0.003, 0.003, segments=6, rings=1))
            stay_parts.append(make_tapered_tube(p_ra + np.array([0, 0, side * (r_hub_w * 0.56)]), p_ra + np.array([-(r_r + 0.015) * 0.88, (r_r + 0.015) * 0.44, side * 0.032]), 0.003, 0.003, 0.003, 0.003, segments=6, rings=1))
        named_parts.append(("accessories_fenders", _apply_mat(trimesh.util.concatenate([f_fend, r_fend] + stay_parts), mats["dark_alloy"])))

    if has_rear_rack:
        rack_y = p_ra[1] + r_r + 0.046
        rack_x0 = p_ra[0] - r_r * 0.72
        rack_x1 = p_ra[0] + r_r * 0.62
        rack_parts = []
        for side in (-1.0, 1.0):
            z_r = side * 0.072
            p_r0 = np.array([rack_x0, rack_y, z_r])
            p_r1 = np.array([rack_x1, rack_y, z_r])
            p_drop = p_ra + np.array([0.0, 0.010, side * (r_hub_w * 0.56)])
            rack_parts.append(make_tapered_tube(p_r0, p_r1, 0.007, 0.007, 0.007, 0.007, segments=10, rings=2))
            rack_parts.append(make_tapered_tube(p_drop, p_r0 + np.array([0.06, 0, 0]), 0.006, 0.006, 0.006, 0.006, segments=8, rings=1))
            rack_parts.append(make_tapered_tube(p_drop, p_r1 - np.array([0.06, 0, 0]), 0.006, 0.006, 0.006, 0.006, segments=8, rings=1))
            rack_parts.append(make_tapered_tube(p_r1, p_st_top + np.array([-0.02, -0.05, side * 0.022]), 0.006, 0.006, 0.006, 0.006, segments=8, rings=1))
        for rx in np.linspace(rack_x0, rack_x1, 4):
            rack_parts.append(make_tapered_tube(np.array([rx, rack_y, -0.072]), np.array([rx, rack_y, 0.072]), 0.006, 0.006, 0.006, 0.006, segments=8, rings=1))
        named_parts.append(("accessories_rear_rack", _apply_mat(trimesh.util.concatenate(rack_parts), mats["dark_alloy"])))

    if has_front_rack:
        fr_y = p_ht_bot[1] + 0.045
        fr_x0 = p_ht_bot[0] + 0.02
        fr_x1 = p_fa[0] + 0.08
        fr_parts = []
        for side in (-1.0, 1.0):
            fr_parts.append(make_tapered_tube(np.array([fr_x0, fr_y, side * 0.115]), np.array([fr_x1, fr_y, side * 0.115]), 0.007, 0.007, 0.007, 0.007, segments=10, rings=2))
            fr_parts.append(make_tapered_tube(p_ht_bot + np.array([0, 0.02, side * 0.025]), np.array([fr_x0 + 0.04, fr_y, side * 0.115]), 0.007, 0.007, 0.007, 0.007, segments=8, rings=1))
        for fx in (fr_x0, 0.5 * (fr_x0 + fr_x1), fr_x1):
            fr_parts.append(make_tapered_tube(np.array([fx, fr_y, -0.115]), np.array([fx, fr_y, 0.115]), 0.007, 0.007, 0.007, 0.007, segments=8, rings=1))
        named_parts.append(("accessories_front_rack", _apply_mat(trimesh.util.concatenate(fr_parts), mats["dark_alloy"])))

    if has_headlight:
        hl_pos = np.array([p_fa[0] + 0.03, p_ht_bot[1] + 0.01, 0.0]) if has_front_rack else (p_ht_top + np.array([0.075, -0.015, 0.0]))
        hl_body = make_tapered_tube(hl_pos + np.array([-0.030, 0, 0]), hl_pos + np.array([0.020, 0, 0]), 0.018, 0.018, 0.020, 0.020, segments=16, rings=2)
        hl_lens = make_tapered_tube(hl_pos + np.array([0.019, 0, 0]), hl_pos + np.array([0.024, 0, 0]), 0.018, 0.018, 0.017, 0.017, segments=16, rings=1)
        named_parts.append(("accessories_headlight", _apply_mat(hl_body, mats["dark_alloy"])))
        named_parts.append(("accessories_headlight_lens", _apply_mat(hl_lens, mats["lens"])))

    # --- 11. ASSEMBLE SCENE & SHIFT SO LOWEST TIRE CONTACT = EXACT Y=0.000 ---
    scene = trimesh.Scene()
    all_min_y = min(float(m.bounds[0][1]) for _, m in named_parts)
    y_shift = -all_min_y
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

    glb_path = out_dir / f"{slug}.glb"
    glb_bytes = scene.export(file_type="glb")
    glb_path.write_bytes(glb_bytes)
    glb_sha256 = hashlib.sha256(glb_bytes).hexdigest()

    # --- 12. ENGINEERING GEOMETRY QA VALIDATION ---
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
        {"check": "輪胎接地平面驗證 (Y_min)", "target": "0.00 mm", "measured": f"{ground_y_min_mm:.2f} mm", "delta": f"{abs(ground_y_min_mm):.2f} mm", "status": "通過" if abs(ground_y_min_mm) < 0.5 else "留意"},
        {"check": "前後軸距公差 (Wheelbase)", "target": f"{geo['wheelbase_mm']:.1f} mm", "measured": f"{measured_wb_mm:.1f} mm", "delta": f"{abs(measured_wb_mm - geo['wheelbase_mm']):.2f} mm", "status": "通過" if abs(measured_wb_mm - geo["wheelbase_mm"]) < 1.0 else "留意"},
        {"check": "車架前伸量座標 (Reach)", "target": f"{geo['reach_mm']:.1f} mm", "measured": f"{measured_reach_mm:.1f} mm", "delta": f"{abs(measured_reach_mm - geo['reach_mm']):.2f} mm", "status": "通過" if abs(measured_reach_mm - geo["reach_mm"]) < 1.0 else "留意"},
        {"check": "車架堆疊高度座標 (Stack)", "target": f"{geo['stack_mm']:.1f} mm", "measured": f"{measured_stack_mm:.1f} mm", "delta": f"{abs(measured_stack_mm - geo['stack_mm']):.2f} mm", "status": "通過" if abs(measured_stack_mm - geo["stack_mm"]) < 1.0 else "留意"},
        {"check": "頭管角度與前叉同軸 (HTA)", "target": f"{geo['head_angle_deg']:.2f}°", "measured": f"{measured_hta_deg:.2f}°", "delta": f"{abs(measured_hta_deg - geo['head_angle_deg']):.2f}°", "status": "通過" if abs(measured_hta_deg - geo["head_angle_deg"]) < 0.1 else "留意"},
        {"check": "立管角度 (STA)", "target": f"{geo['seat_angle_deg']:.2f}°", "measured": f"{measured_sta_deg:.2f}°", "delta": f"{abs(measured_sta_deg - geo['seat_angle_deg']):.2f}°", "status": "通過" if abs(measured_sta_deg - geo["seat_angle_deg"]) < 0.1 else "留意"},
        {"check": "後下叉有效長度 (Chainstay)", "target": f"{geo['chainstay_mm']:.1f} mm", "measured": f"{measured_cs_mm:.1f} mm", "delta": f"{abs(measured_cs_mm - geo['chainstay_mm']):.2f} mm", "status": "通過" if abs(measured_cs_mm - geo["chainstay_mm"]) < 1.5 else "留意"},
        {"check": "五通／曲柄離地淨高 (170mm)", "target": "> 95.0 mm", "measured": f"{crank_clearance_mm:.1f} mm", "delta": "正常" if crank_clearance_mm >= 95.0 else "偏低", "status": "通過" if crank_clearance_mm >= 95.0 else "留意"},
    ]

    preview_path = out_dir / f"{slug}_preview.png"
    _render_side_preview_png(scene, preview_path)

    cal_jpg_path = out_dir / f"{slug}_ref_calibrated.jpg"
    overlay_qa_path = out_dir / f"{slug}_overlay_qa.png"

    # Automatic OpenCV wheel-pair registration -> exact 1:1 metric photo overlay + CV frame/paint refinement!
    if _existing_photo_cal is None:
        photo_cal = calibrate_bike_reference_photo(
            bike.get("gallery", []),
            scene,
            anchors_3d,
            geo,
            cal_jpg_path,
            overlay_qa_path,
        )
        if photo_cal and cal_jpg_path.exists():
            vis = inspect_calibrated_photo_frame(cal_jpg_path, anchors_3d)
            title_l = f"{bike.get('model_name','')} {bike.get('title','')}".lower()
            has_sig_override = any(k in title_l for k in ("honda", "amflow ue", "orbea rise"))
            new_arch = frame_arch
            if vis.get("is_open_lowstep") and frame_arch == "low_slung_emtb":
                new_arch = "lowstep_monotube"
            new_rgb = accent
            if not has_sig_override and vis.get("downtube_rgb"):
                new_rgb = vis["downtube_rgb"]
            if new_arch != frame_arch or new_rgb != accent:
                bike["frame_arch"] = new_arch
                bike["accent_rgb"] = new_rgb
                return build_bike_3d_model(
                    bike,
                    out_dir,
                    _override_arch=new_arch,
                    _override_rgb=new_rgb,
                    _existing_photo_cal=photo_cal,
                )
    else:
        photo_cal = _existing_photo_cal
        if cal_jpg_path.exists():
            render_overlay_qa_image(cal_jpg_path, scene, anchors_3d, overlay_qa_path)

    prov = bike.get("geometry_provenance", {})
    measured_fields = [k for k, v in prov.items() if v.startswith("measured")]
    inferred_fields = [k for k, v in prov.items() if not v.startswith("measured")]

    arch_names_zh = {
        "single_pivot_gullarm": "單轉點 Gullarm 搖臂一體車架",
        "lowstep_monotube": "低跨點單下管車架 (Low-Step Monotube)",
        "stagger_midstep": "雙管下凹上管車架 (Stagger / Mid-Step)",
        "low_slung_emtb": "低重心斜上管越野／SUV 車架",
        "aero_gravel_road": "下移後上叉空力礫石／公路車架",
    }

    susp_names_zh = {
        "horst_vertical_front": "前立管直立避震四連桿 (Horst / Beamer 4-Bar)",
        "horst_horizontal_toptube": "上管水平連桿＋直推 Yoke 四連桿",
        "vpp_lower_tunnel": "下連桿 VPP 貫穿式低重心避震",
        "vertical_behind_st": "低跨點立管後置直立四連桿",
        "single_pivot_gullarm": "單轉點 Gullarm 搖臂貫穿避震",
        "hardtail_rigid": "硬尾／硬叉（無後避震）",
    }

    manifest = {
        "schema": "BIKE-PARAMETRIC-RE-v2.3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bike_slug": slug,
        "brand": bike["brand"],
        "model_name": bike["model_name"],
        "frame_arch": frame_arch,
        "frame_arch_zh": arch_names_zh.get(frame_arch, frame_arch),
        "suspension_type": suspension_type,
        "suspension_type_zh": susp_names_zh.get(suspension_type, suspension_type),
        "modeled_size": bike.get("default_size", "L"),
        "source_url": bike["url"],
        "glb_file": f"models/{slug}.glb",
        "preview_image": f"models/{slug}_preview.png",
        "photo_calibration": photo_cal,
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
            f"車架拓撲辨識為「{arch_names_zh.get(frame_arch, frame_arch)}」，後避震機構採用「{susp_names_zh.get(suspension_type, suspension_type)}」，前叉內外管嚴格與頭管軸線平行並採同軸肩蓋＋下叉前伸爪座。",
            f"標記為「實測／官方數據」({len(measured_fields)} 項) 的欄位來自原廠或媒體多尺碼幾何表（已支援德文千分位與逗號小數格式）；標記為「級距比例推估」({len(inferred_fields)} 項) 依車型級距推估。",
            "透過 OpenCV 自動偵測正側視實車照雙輪軸心、上管開放區間（自動區分單下管低跨車 vs 斜上管車架）與下管烤漆色，建立 1:1 比例疊圖校正平面。",
            "管件內部壁厚、培林座與煞車碟盤散熱孔數屬工程視覺與裝配比例重建，不代表原廠結構強度或 FEA 認證。",
        ],
        "object_inventory": object_inventory,
    }

    (out_dir / f"{slug}_qa_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{slug}_blender_rebuild.py").write_text(
        _generate_studio_blender_script(slug, bike["model_name"], glb_sha256, geo),
        encoding="utf-8",
    )

    return {
        "glb_file": f"models/{slug}.glb",
        "preview_image": f"models/{slug}_preview.png",
        "photo_calibration": photo_cal,
        "glb_sha256": glb_sha256,
        "glb_bytes": len(glb_bytes),
        "manifest_file": f"models/{slug}_qa_manifest.json",
        "blender_script": f"models/{slug}_blender_rebuild.py",
        "frame_arch": frame_arch,
        "frame_arch_zh": arch_names_zh.get(frame_arch, frame_arch),
        "suspension_type": suspension_type,
        "suspension_type_zh": susp_names_zh.get(suspension_type, suspension_type),
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
    """Render a crisp warm neutral cyclorama orthographic side-drive preview PNG."""
    w, h = 1000, 620
    img = Image.new("RGB", (w, h), (221, 217, 208))
    draw = ImageDraw.Draw(img)
    light_dir = np.array([0.32, 0.72, 0.62])
    light_dir /= np.linalg.norm(light_dir)

    tris: list[tuple[float, np.ndarray, np.ndarray, np.ndarray, tuple[int, int, int]]] = []
    all_pts = []
    for geom in scene.geometry.values():
        all_pts.append(geom.bounds)
    bounds_min = np.min([b[0] for b in all_pts], axis=0)
    bounds_max = np.max([b[1] for b in all_pts], axis=0)
    span_x = max(1.2, float(bounds_max[0] - bounds_min[0]))
    span_y = max(0.8, float(bounds_max[1] - bounds_min[1]))
    scale = min((w * 0.84) / span_x, (h * 0.78) / span_y)
    mid_x = 0.5 * float(bounds_min[0] + bounds_max[0])
    cx, cy = w * 0.50, h * 0.88

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
    draw.line([(36, cy), (w - 36, cy)], fill=(182, 177, 167), width=2)
    for _, a, b, c, col in tris:
        pts = [
            (cx + (a[0] - mid_x) * scale, cy - a[1] * scale),
            (cx + (b[0] - mid_x) * scale, cy - b[1] * scale),
            (cx + (c[0] - mid_x) * scale, cy - c[1] * scale),
        ]
        draw.polygon(pts, fill=col)
    img.save(out_png, optimize=True)


def _generate_studio_blender_script(slug: str, model_name: str, glb_sha256: str, geo: dict[str, float]) -> str:
    return f'''"""Parametric Bike Studio — Blender 4.x Import, Cyclorama & Multi-View QA Render Script.

Model      : {model_name} ({slug})
GLB SHA256 : {glb_sha256}
Geometry   : WB={geo["wheelbase_mm"]}mm | Reach={geo["reach_mm"]}mm | Stack={geo["stack_mm"]}mm | HTA={geo["head_angle_deg"]}deg | STA={geo["seat_angle_deg"]}deg

Usage:
    blender -b --python {slug}_blender_rebuild.py -- --glb {slug}.glb --out ./renders_{slug}
"""

import argparse, hashlib, json, sys
from pathlib import Path
import bpy
from mathutils import Vector

EXPECTED_SHA256 = "{glb_sha256}"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", default="{slug}.glb")
    p.add_argument("--out", default="./renders_{slug}")
    p.add_argument("--samples", type=int, default=32)
    return p.parse_args(argv)


def setup_studio_warm_cyclorama(scene):
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 32
    scene.eevee.use_raytracing = True
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"

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

    mat_floor = bpy.data.materials.new("Studio_Warm_Neutral_Cyclorama")
    mat_floor.use_nodes = True
    bsdf = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.78, 0.76, 0.72, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.82
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0.0, 0.0, 0.0))
    bpy.context.object.data.materials.append(mat_floor)

    for name, loc, energy, size, target in [
        ("Studio_Key", (1.6, -3.2, 3.8), 580.0, 3.0, (0.0, 0.0, 0.60)),
        ("Studio_Fill", (-1.4, 2.2, 2.5), 260.0, 3.0, (0.0, 0.0, 0.60)),
        ("Studio_Rim", (0.2, 1.8, 3.5), 420.0, 2.0, (0.0, 0.0, 0.68)),
    ]:
        ldata = bpy.data.lights.new(name, "AREA")
        ldata.energy, ldata.shape, ldata.size, ldata.use_shadow = energy, "DISK", size, True
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
    assert actual_sha == EXPECTED_SHA256, f"SHA256 mismatch: {{actual_sha}}"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    scene = bpy.context.scene
    setup_studio_warm_cyclorama(scene)

    cam_data = bpy.data.cameras.new("Studio_Ortho_Camera")
    cam_data.type = "ORTHO"
    cam_obj = bpy.data.objects.new("Studio_Ortho_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x, scene.render.resolution_y = 1200, 900
    scene.eevee.taa_render_samples = args.samples

    for name, eye, target, scale in [
        ("01_side_drive", (0.0, -4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("02_side_brake", (0.0, 4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("03_front", (4.0, 0.0, 0.68), (0.4, 0.0, 0.58), 1.45),
        ("04_rear", (-4.0, 0.0, 0.68), (-0.4, 0.0, 0.58), 1.45),
        ("05_front_45", (3.0, -3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("06_rear_45", (-3.0, 3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("07_cockpit", (0.15, -0.70, 1.65), (0.35, 0.0, 0.98), 0.95),
    ]:
        cam_obj.location = Vector(eye)
        cam_obj.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat("-Z", "Y").to_euler()
        cam_data.ortho_scale = scale
        scene.render.filepath = str(out_dir / f"{{name}}.png")
        bpy.ops.render.render(write_still=True)

    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "{slug}_studio.blend"))
    print(json.dumps({{"status": "ok", "model": "{slug}", "sha256": actual_sha}}))


if __name__ == "__main__":
    main()
'''
