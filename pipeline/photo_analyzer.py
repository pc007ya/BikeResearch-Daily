"""Photo-assisted frame color sampling and frame architecture classification."""

from __future__ import annotations

import io
import re
from typing import Any

import numpy as np
import requests
from PIL import Image

# Default tasteful studio paint fallbacks per architecture (if photo fetch fails)
ARCH_DEFAULT_COLORS: dict[str, tuple[list[float], list[float]]] = {
    "single_pivot_gullarm": ([0.80, 0.82, 0.84], [0.16, 0.17, 0.19]),
    "step_through_commuter": ([0.90, 0.90, 0.88], [0.14, 0.14, 0.15]),
    "low_slung_emtb": ([0.78, 0.82, 0.85], [0.14, 0.15, 0.17]),
    "aero_gravel_road": ([0.22, 0.34, 0.28], [0.14, 0.14, 0.15]),
}


def sample_frame_color_from_photo(image_url: str, fallback_rgb: list[float]) -> list[float]:
    """Sample dominant non-background, non-tire paint color from the central bike region."""
    if not image_url or not image_url.startswith("http"):
        return list(fallback_rgb)
    try:
        resp = requests.get(image_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code != 200 or len(resp.content) < 2000:
            return list(fallback_rgb)
        im = Image.open(io.BytesIO(resp.content)).convert("RGB")
        im = im.resize((240, 160))
        arr = np.asarray(im, dtype=np.float32) / 255.0

        # Estimate border background color (sky/wall/ground) to reject background pixels
        border = np.concatenate(
            [arr[:12, :, :].reshape(-1, 3), arr[-12:, :, :].reshape(-1, 3), arr[:, :12, :].reshape(-1, 3), arr[:, -12:, :].reshape(-1, 3)],
            axis=0,
        )
        bg_med = np.median(border, axis=0)

        # Central frame box (where main triangle lives in side-profile shots)
        crop = arr[44:122, 72:176, :].reshape(-1, 3)

        # Filter out pixels close to background, pure dark tire rubber, pure sky blue, or foliage green
        dist_bg = np.linalg.norm(crop - bg_med[None, :], axis=1)
        lum = 0.299 * crop[:, 0] + 0.587 * crop[:, 1] + 0.114 * crop[:, 2]
        sat = np.max(crop, axis=1) - np.min(crop, axis=1)

        is_sky = (crop[:, 2] > crop[:, 0] + 0.16) & (crop[:, 2] > 0.55)
        is_foliage = (crop[:, 1] > crop[:, 0] + 0.08) & (crop[:, 1] > crop[:, 2] + 0.08) & (lum < 0.52)
        mask = (dist_bg > 0.18) & (lum > 0.16) & (lum < 0.94) & (~is_sky) & (~is_foliage)
        cand = crop[mask]
        if len(cand) < 40:
            return list(fallback_rgb)

        # Prefer either clean painted saturated pixels OR clean silver/white frame finish
        sat_cand = cand[sat[mask] > 0.18]
        if len(sat_cand) > len(cand) * 0.25 and len(sat_cand) >= 40:
            col = np.median(sat_cand, axis=0)
        else:
            # Metallic silver / light grey / pearl white / stealth graphite frame
            bright_cand = cand[lum[mask] > 0.52]
            col = np.median(bright_cand if len(bright_cand) >= 40 else cand, axis=0)
        return [round(float(np.clip(c, 0.10, 0.92)), 3) for c in col]
    except Exception:
        return list(fallback_rgb)


def classify_frame_architecture(
    model_name: str,
    title: str,
    category_key: str,
    specs: dict[str, str],
    full_text: str,
) -> dict[str, Any]:
    """Determine accurate frame architecture and bike-specific equipment cues."""
    blob = f"{model_name} {title} {' '.join(specs.values())} {full_text[:3000]}".lower()
    title_l = f"{model_name} {title}".lower()

    # 1. Architecture selection
    if "honda" in title_l and "rn0" in title_l or "gullarm" in blob:
        arch = "single_pivot_gullarm"
    elif (
        category_key == "urban_ebike"
        or "wave" in title_l
        or "step-through" in blob
        or "step through" in blob
        or "tiefeinsteiger" in blob
        or "amflow ue" in title_l
    ):
        arch = "step_through_commuter"
    elif category_key in ("gravel", "road"):
        arch = "aero_gravel_road"
    else:
        arch = "low_slung_emtb"

    # 2. Equipment & drivetrain cues
    is_suv_or_city = category_key in ("suv_ebike", "urban_ebike") or arch == "step_through_commuter"
    has_belt_drive = bool(
        re.search(r"\b(?:belt\s*drive|gates\s*(?:cdx|carbon)|riemenantrieb|zahnriemen|pinion\s+mgu)\b", blob, re.I)
        or "amflow ue" in title_l
    )
    has_fenders = is_suv_or_city or bool(re.search(r"\b(?:fender|mudguard|schutzblech)\b", blob, re.I))
    has_rear_rack = is_suv_or_city or bool(re.search(r"\b(?:rear\s*rack|luggage\s*rack|gepäckträger|pannier)\b", blob, re.I))
    has_front_rack = ("amflow ue" in title_l) or bool(re.search(r"\b(?:front\s*(?:rack|carrier|gepäckträger)|frontgepäckträger)\b", blob, re.I))
    has_headlight = is_suv_or_city or bool(re.search(r"\b(?:headlight|front\s*light|scheinwerfer|supernova|lupine)\b", blob, re.I))

    primary_def, secondary_def = ARCH_DEFAULT_COLORS[arch]
    two_tone_lower = arch == "single_pivot_gullarm"

    # Known signature paint overrides for verified high-profile bikes where background can skew sampling
    paint_override: list[float] | None = None
    if "honda" in title_l and "rn0" in title_l:
        paint_override = [0.80, 0.82, 0.83]  # Signature cool silver-grey upper + matte dark lower
    elif "amflow ue" in title_l:
        paint_override = [0.90, 0.90, 0.87]  # Pearl white carbon monocoque
    elif "orbea" in title_l and "rise" in title_l:
        paint_override = [0.81, 0.85, 0.88]  # Ice silver-blue carbon frame

    return {
        "frame_arch": arch,
        "has_belt_drive": has_belt_drive,
        "has_fenders": has_fenders,
        "has_rear_rack": has_rear_rack,
        "has_front_rack": has_front_rack,
        "has_headlight": has_headlight,
        "two_tone_lower": two_tone_lower,
        "default_primary_rgb": primary_def,
        "secondary_rgb": secondary_def,
        "paint_override": paint_override,
    }
