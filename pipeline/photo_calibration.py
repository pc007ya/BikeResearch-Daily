"""OpenCV wheel-pair detector, metric photo-to-3D registration, and Photo+3D overlay QA generator.

Finds the cleanest true side-profile photograph in a bike's gallery, detects both
wheel centers and radii with strict circular edge-ring verification (rejecting
non-side-profile macro close-ups), levels the ground plane, auto-orients facing +X,
warps the photo into the EXACT 3D world-meter coordinate frame
(X in [-1.25m, +1.25m], Y in [-0.12m, +1.43m], Y=0 ground, 400 px/m),
and renders a blended Photo-on-3D Overlay QA verification image.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
import trimesh

# Canonical metric world box for the 1000x620 calibrated reference plane (in meters!)
CAL_W_PX = 1000
CAL_H_PX = 620
CAL_X_MIN_M = -1.25
CAL_X_MAX_M = 1.25
CAL_Y_MIN_M = -0.12
CAL_Y_MAX_M = 1.43  # Span = 2.50m x 1.55m -> exact 400.0 px/m!
CAL_PX_PER_M = CAL_W_PX / (CAL_X_MAX_M - CAL_X_MIN_M)


def world_to_cal_px(x_m: float, y_m: float) -> tuple[float, float]:
    u = (x_m - CAL_X_MIN_M) * CAL_PX_PER_M
    v = (CAL_Y_MAX_M - y_m) * CAL_PX_PER_M
    return u, v


def detect_bike_wheels(img_bgr: np.ndarray, target_wb_ratio: float = 3.5) -> dict[str, Any] | None:
    """Multi-pass OpenCV wheel-pair detector with strict circular Canny edge support."""
    oh, ow = img_bgr.shape[:2]
    if ow < 320 or oh < 200:
        return None
    scale = 640.0 / max(ow, 1)
    small = cv2.resize(img_bgr, (640, max(120, int(oh * scale))), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray_f = gray.astype(np.float32)
    gx = cv2.Sobel(gray_f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_f, cv2.CV_32F, 0, 1, ksize=3)
    gmag = np.hypot(gx, gy) + 1e-5
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(clahe, (5, 5), 1.2)
    edges = cv2.Canny(blur, 55, 145)
    edges_d = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)

    all_cands: list[tuple[float, float, float]] = []
    # Pass 1: standard close-up side profile (11%..34% of min dim)
    # Pass 2: medium/wide landscape side profile (5.5%..15% of min dim)
    for (r_lo_f, r_hi_f, p1, p2) in [
        (0.11, 0.34, 90, 26),
        (0.055, 0.15, 85, 22),
    ]:
        min_r = max(14, int(min(w, h) * r_lo_f))
        max_r = int(min(w, h) * r_hi_f)
        cs = cv2.HoughCircles(
            blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(min_r * 1.8),
            param1=p1, param2=p2, minRadius=min_r, maxRadius=max_r
        )
        if cs is not None:
            for c in cs[0][:28]:
                all_cands.append((float(c[0]), float(c[1]), float(c[2])))

    if len(all_cands) < 2:
        return None

    angs = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    cos_a = np.cos(angs)
    sin_a = np.sin(angs)

    best: dict[str, Any] | None = None
    best_score = -1e9

    for i in range(len(all_cands)):
        for j in range(i + 1, len(all_cands)):
            c1, c2 = all_cands[i], all_cands[j]
            if c1[0] > c2[0]:
                c1, c2 = c2, c1
            x1, y1, r1 = c1
            x2, y2, r2 = c2
            r_avg = 0.5 * (r1 + r2)
            r_ratio = min(r1, r2) / max(r1, r2)
            if r_ratio < 0.86:
                continue
            dx = x2 - x1
            dy = abs(y2 - y1)
            wb_ratio = dx / r_avg
            if not (2.75 <= wb_ratio <= 4.15):
                continue
            if dy > dx * 0.10:
                continue
            if y1 < h * 0.26 or y2 < h * 0.26:
                continue
            if x1 - r1 < -w * 0.04 or x2 + r2 > w * 1.04:
                continue

            ring_dark = 0.0
            edge_support = 0.0
            rim_contrast = 0.0
            rad_align_sum = 0.0
            ring_vs_out_sum = 0.0
            for (cx, cy, rr) in ((x1, y1, r1), (x2, y2, r2)):
                xs_t = np.clip((cx + rr * 0.94 * cos_a).astype(int), 0, w - 1)
                ys_t = np.clip((cy + rr * 0.94 * sin_a).astype(int), 0, h - 1)
                tire_lum = float(np.mean(gray[ys_t, xs_t]))
                ring_dark += 255.0 - tire_lum

                # Interior wheel spokes area (0.55r) should not be identical solid blob
                xs_in = np.clip((cx + rr * 0.55 * cos_a).astype(int), 0, w - 1)
                ys_in = np.clip((cy + rr * 0.55 * sin_a).astype(int), 0, h - 1)
                rim_contrast += max(0.0, float(np.mean(gray[ys_in, xs_in])) - tire_lum)

                xs_e = np.clip((cx + rr * cos_a).astype(int), 0, w - 1)
                ys_e = np.clip((cy + rr * sin_a).astype(int), 0, h - 1)
                ring_e = float(np.mean(edges_d[ys_e, xs_e] > 0))
                edge_support += ring_e

                # Compare tire edge ring vs annulus just outside tire (rejects uniform grass/rock clutter)
                xs_o = np.clip((cx + rr * 1.18 * cos_a).astype(int), 0, w - 1)
                ys_o = np.clip((cy + rr * 1.18 * sin_a).astype(int), 0, h - 1)
                out_e = float(np.mean(edges_d[ys_o, xs_o] > 0))
                ring_vs_out_sum += (ring_e - out_e)

                # Radial Sobel gradient alignment around tire/rim circumference
                best_rad = 0.0
                for rf in (0.96, 0.99, 1.02, 0.86):
                    xs_g = np.clip((cx + rr * rf * cos_a).astype(int), 0, w - 1)
                    ys_g = np.clip((cy + rr * rf * sin_a).astype(int), 0, h - 1)
                    dot = (gx[ys_g, xs_g] * cos_a + gy[ys_g, xs_g] * sin_a) / gmag[ys_g, xs_g]
                    strong = gmag[ys_g, xs_g] > 28.0
                    if int(np.sum(strong)) > 10:
                        rad_val = float(np.mean(np.abs(dot[strong]))) * float(np.mean(strong))
                        if rad_val > best_rad:
                            best_rad = rad_val
                rad_align_sum += best_rad

            ring_dark *= 0.5
            edge_support *= 0.5
            rim_contrast *= 0.5
            rad_align = rad_align_sum * 0.5
            ring_vs_out = ring_vs_out_sum * 0.5

            # Strict circularity & radial-gradient gates eliminate macro shots & grass/rock false positives!
            if edge_support < 0.78 or ring_dark < 105.0 or rad_align < 0.72 or ring_vs_out < 0.22:
                continue

            ratio_err = abs(wb_ratio - target_wb_ratio)
            size_score = (dx / w) * 165.0
            level_pen = (dy / dx) * 200.0
            score = (
                ring_dark
                + edge_support * 180.0
                + rad_align * 160.0
                + ring_vs_out * 90.0
                + min(60.0, rim_contrast)
                + size_score
                - level_pen
                - ratio_err * 45.0
                + r_ratio * 35.0
            )
            if score > best_score:
                best_score = score
                best = {
                    "score": round(score, 1),
                    "edge_support": round(edge_support, 2),
                    "radial_align": round(rad_align, 2),
                    "left": (x1 / scale, y1 / scale, r1 / scale),
                    "right": (x2 / scale, y2 / scale, r2 / scale),
                    "wb_px": dx / scale,
                    "wb_ratio": round(wb_ratio, 2),
                }
    return best


def _warp_to_metric_plane(
    img_bgr: np.ndarray,
    left_c: tuple[float, float, float],
    right_c: tuple[float, float, float],
    ra_3d: list[float],
    fa_3d: list[float],
    high_quality: bool = False,
) -> np.ndarray:
    src_ra = np.array([left_c[0], left_c[1]], dtype=np.float32)
    src_fa = np.array([right_c[0], right_c[1]], dtype=np.float32)
    dst_ra = np.array(world_to_cal_px(ra_3d[0], ra_3d[1]), dtype=np.float32)
    dst_fa = np.array(world_to_cal_px(fa_3d[0], fa_3d[1]), dtype=np.float32)

    src_v = src_fa - src_ra
    dst_v = dst_fa - dst_ra
    s = float(np.linalg.norm(dst_v)) / (float(np.linalg.norm(src_v)) + 1e-6)
    ang = math.atan2(dst_v[1], dst_v[0]) - math.atan2(src_v[1], src_v[0])
    ca, sa = math.cos(ang) * s, math.sin(ang) * s
    tx = float(dst_ra[0] - (ca * src_ra[0] - sa * src_ra[1]))
    ty = float(dst_ra[1] - (sa * src_ra[0] + ca * src_ra[1]))
    M = np.array([[ca, -sa, tx], [sa, ca, ty]], dtype=np.float32)
    return cv2.warpAffine(
        img_bgr,
        M,
        (CAL_W_PX, CAL_H_PX),
        flags=cv2.INTER_LANCZOS4 if high_quality else cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(208, 217, 221),
    )


def _select_orientation_by_3d_silhouette(
    img_bgr: np.ndarray,
    left_c: tuple[float, float, float],
    right_c: tuple[float, float, float],
    scene: trimesh.Scene,
    anchors_3d: dict[str, list[float]],
) -> tuple[bool, float]:
    """Compare non-wheel 3D frame/fork silhouette against warped Canny edges for flip=False vs flip=True."""
    mask_nw = np.zeros((CAL_H_PX, CAL_W_PX), dtype=np.uint8)
    for name, geom in scene.geometry.items():
        if any(k in name for k in ("wheel", "tire", "spoke", "rotor")):
            continue
        v = geom.vertices
        f = geom.faces
        pts_u = (v[:, 0] - CAL_X_MIN_M) * CAL_PX_PER_M
        pts_v = (CAL_Y_MAX_M - v[:, 1]) * CAL_PX_PER_M
        polys = np.stack([pts_u[f], pts_v[f]], axis=-1).astype(np.int32)
        cv2.fillPoly(mask_nw, list(polys), 255)
    cnts, _ = cv2.findContours(mask_nw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask_edge = np.zeros_like(mask_nw)
    cv2.drawContours(mask_edge, cnts, -1, 255, 6)
    mask_idx = mask_edge > 0
    if not np.any(mask_idx):
        return False, 0.5

    ra_3d = anchors_3d["rear_axle"]
    fa_3d = anchors_3d["front_axle"]
    w_orig = img_bgr.shape[1]

    scores: dict[bool, float] = {}
    for flip in (False, True):
        if flip:
            im = cv2.flip(img_bgr, 1)
            lc = (w_orig - right_c[0], right_c[1], right_c[2])
            rc = (w_orig - left_c[0], left_c[1], left_c[2])
        else:
            im = img_bgr
            lc, rc = left_c, right_c
        warped = _warp_to_metric_plane(im, lc, rc, ra_3d, fa_3d, high_quality=False)
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        ed = cv2.dilate(
            cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 1.2), 50, 140),
            np.ones((7, 7), np.uint8),
            iterations=1,
        )
        scores[flip] = float(np.mean(ed[mask_idx] > 0))

    # Require flipped orientation to beat unflipped by a clear margin (+0.03)
    choose_flip = scores[True] > scores[False] + 0.03
    best_overlap = scores[True] if choose_flip else scores[False]
    return choose_flip, round(best_overlap, 3)


def render_overlay_qa_image(
    cal_jpg: Path,
    scene: trimesh.Scene,
    anchors_3d: dict[str, list[float]],
    out_png: Path,
) -> None:
    """Render blended real calibrated photo + 3D model silhouette contour & axle crosshairs."""
    bg = cv2.imread(str(cal_jpg))
    if bg is None:
        return
    overlay = bg.copy()
    mask_3d = np.zeros((CAL_H_PX, CAL_W_PX), dtype=np.uint8)
    for name, geom in scene.geometry.items():
        v = geom.vertices
        f = geom.faces
        pts_u = (v[:, 0] - CAL_X_MIN_M) * CAL_PX_PER_M
        pts_v = (CAL_Y_MAX_M - v[:, 1]) * CAL_PX_PER_M
        color = (40, 85, 225) if any(k in name for k in ("frame", "gullarm", "rear_")) else (215, 135, 30)
        if "wheel" in name and "tire" in name:
            color = (35, 200, 75)
        polys = np.stack([pts_u[f], pts_v[f]], axis=-1).astype(np.int32)
        cv2.fillPoly(mask_3d, list(polys), 255)
        for poly in polys[::4]:
            cv2.polylines(overlay, [poly], True, color, 1, cv2.LINE_AA)

    cnts, _ = cv2.findContours(mask_3d, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blended = cv2.addWeighted(bg, 0.62, overlay, 0.38, 0)
    cv2.drawContours(blended, cnts, -1, (40, 75, 235), 2, cv2.LINE_AA)
    for ak in ("rear_axle", "front_axle", "bb"):
        u, v = world_to_cal_px(anchors_3d[ak][0], anchors_3d[ak][1])
        cv2.drawMarker(blended, (int(u), int(v)), (0, 255, 255), cv2.MARKER_CROSS, 18, 2)
    cv2.imwrite(str(out_png), blended)


def calibrate_bike_reference_photo(
    gallery: list[dict[str, str]],
    scene: trimesh.Scene,
    anchors_3d: dict[str, list[float]],
    geo: dict[str, float],
    out_jpg: Path,
    out_overlay_png: Path,
) -> dict[str, Any] | None:
    """Detect best side-profile photo, warp to exact 3D metric coordinates, and render overlay QA."""
    ra_3d = anchors_3d["rear_axle"]
    fa_3d = anchors_3d["front_axle"]
    r_avg_m = 0.5 * (ra_3d[1] + fa_3d[1])
    wb_m = fa_3d[0] - ra_3d[0]
    target_wb_ratio = wb_m / max(0.25, r_avg_m)

    best_img = None
    best_det = None
    best_url = ""

    for g in (gallery or [])[:6]:
        url = g.get("url", "")
        if not url.startswith("http"):
            continue
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code != 200 or len(resp.content) < 3000:
                continue
            img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            det = detect_bike_wheels(img, target_wb_ratio=target_wb_ratio)
            if det and (best_det is None or det["score"] > best_det["score"]):
                best_det = det
                best_img = img
                best_url = url
        except Exception:
            continue

    if best_img is None or best_det is None:
        return None

    img = best_img
    left_c = best_det["left"]
    right_c = best_det["right"]

    flipped, frame_overlap = _select_orientation_by_3d_silhouette(img, left_c, right_c, scene, anchors_3d)
    if flipped:
        w_orig = img.shape[1]
        img = cv2.flip(img, 1)
        left_c, right_c = (w_orig - right_c[0], right_c[1], right_c[2]), (w_orig - left_c[0], left_c[1], left_c[2])

    warped = _warp_to_metric_plane(img, left_c, right_c, ra_3d, fa_3d, high_quality=True)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_jpg), warped, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    render_overlay_qa_image(out_jpg, scene, anchors_3d, out_overlay_png)

    return {
        "calibrated_photo": f"models/{out_jpg.name}",
        "overlay_qa_image": f"models/{out_overlay_png.name}",
        "source_photo_url": best_url,
        "wheel_score": best_det["score"],
        "edge_support": best_det["edge_support"],
        "radial_align": best_det["radial_align"],
        "frame_edge_overlap": frame_overlap,
        "flipped_horizontal": flipped,
        "plane_world_bounds": {
            "width_m": round(CAL_X_MAX_M - CAL_X_MIN_M, 3),
            "height_m": round(CAL_Y_MAX_M - CAL_Y_MIN_M, 3),
            "center_x": round(0.5 * (CAL_X_MIN_M + CAL_X_MAX_M), 3),
            "center_y": round(0.5 * (CAL_Y_MIN_M + CAL_Y_MAX_M), 3),
        },
        "detected_wb_ratio": best_det["wb_ratio"],
        "target_wb_ratio": round(target_wb_ratio, 2),
    }
