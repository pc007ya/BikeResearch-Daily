"""Complete-bike detector, geometry table parser, spec extractor, and provenance tracker."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from pipeline.components import build_bike_components, extract_prose_component_fallbacks
from pipeline.photo_analyzer import classify_frame_architecture, sample_frame_color_from_photo
from pipeline.sources import extract_images_from_html, fetch_article_html

# Negative keywords indicating an article is NOT a complete bike review/launch
NON_BIKE_TITLE_RE = re.compile(
    r"\b(?:helmet|helm|headlamp|shorts|chamois|shoes?|goggles?|jacket|jersey|gloves?|"
    r"wheelset|wheels?\b|tire|tyre|reifen|motor\s+review|motor\s+test|autoshift|"
    r"airforce|trockenblasen|verkaufsstopp|rückruf|recall|giveaway|ps5|poll:|"
    r"slack\s+randoms|check\s+out:|geile\s+teile|bike\s+show|hallen|herbst-update|"
    r"video:|transvienna|fast\s+forward\s+team|world\s+cup|tour\s+down\s+under|"
    r"rapencross|grand\s+tour|transfer|coach|nica\s+expands|menstrual|comeback|"
    r"upgrades?\s+unter|die\s+\d+\s+besten|top\s+\d+\s+upgrades?|best\s+upgrades?)\b",
    re.I,
)

# Positive indicators of a complete bicycle
BIKE_MODEL_HINTS_RE = re.compile(
    r"\b(?:tallboy|remote\s*160|g32\s*superfast|tambora|all-road\s*v2|rise\s*lt|"
    r"aventura|turbo\s*vado|rn0|ue\s*carbon|stumpjumper|levo|epic|tarmac|aethos|"
    r"fuel\s*ex|slash|madone|checkpoint|aeroad|spectral|strive|neuron|grail|grizl|"
    r"trance|reign|anthem|propel|defy|tcr|revolt|megatower|hightower|bronson|nomad|"
    r"heckler|bullit|valia|spark|genius|ransom|foil|addict|scalpel|supersix|topstone|"
    r"jekyll|habit|motera|sb140|sb160|switchblade|firebird|shuttle|spire|sentinel|"
    r"smuggler|relay|meta|clash|supreme|jeffsy|capra|decoy|izzo|sight|range|fluid|"
    r"altitude|instinct|slayer|powerplay|wild|occam|oiz|orca|terra|stereo|crafty|"
    r"neat|dune|tyee|spindrift|ekan|jam²|sam²|thron²|s-works|roubaix|diverge|"
    r"gravel\s+bike|road\s+bike|mountain\s+bike|trail\s+bike|enduro\s+bike|"
    r"downhill\s+bike|all-road|suv\s+ebike|e-?mtb|e-?bike\s+review|carbon\s+pro\s+on\s+test)\b",
    re.I,
)

# Category baseline geometry templates (used ONLY to fill unstated dimensions, explicitly tagged as "inferred")
CATEGORY_TEMPLATES: dict[str, dict[str, Any]] = {
    "emtb_full": {
        "category_zh": "全避震電輔越野車 (Full-Sus e-MTB)",
        "is_ebike": True,
        "full_suspension": True,
        "handlebar_type": "riser",
        "wheel_front_in": 29.0,
        "wheel_rear_in": 29.0,
        "tire_width_mm": 62.0,
        "head_angle_deg": 64.5,
        "seat_angle_deg": 77.5,
        "reach_mm": 475.0,
        "stack_mm": 632.0,
        "wheelbase_mm": 1255.0,
        "chainstay_mm": 445.0,
        "bb_drop_mm": 26.0,
        "head_tube_mm": 120.0,
        "seat_tube_mm": 430.0,
        "travel_front_mm": 160.0,
        "travel_rear_mm": 150.0,
        "rotor_front_mm": 203.0,
        "rotor_rear_mm": 203.0,
        "accent_rgb": [0.18, 0.25, 0.30],
    },
    "mtb_trail": {
        "category_zh": "全避震林道山地車 (Trail MTB)",
        "is_ebike": False,
        "full_suspension": True,
        "handlebar_type": "riser",
        "wheel_front_in": 29.0,
        "wheel_rear_in": 29.0,
        "tire_width_mm": 60.0,
        "head_angle_deg": 65.5,
        "seat_angle_deg": 76.5,
        "reach_mm": 470.0,
        "stack_mm": 620.0,
        "wheelbase_mm": 1228.0,
        "chainstay_mm": 435.0,
        "bb_drop_mm": 35.0,
        "head_tube_mm": 115.0,
        "seat_tube_mm": 430.0,
        "travel_front_mm": 140.0,
        "travel_rear_mm": 130.0,
        "rotor_front_mm": 180.0,
        "rotor_rear_mm": 180.0,
        "accent_rgb": [0.22, 0.36, 0.31],
    },
    "suv_ebike": {
        "category_zh": "全避震 SUV 跨界電輔車 (SUV e-Bike)",
        "is_ebike": True,
        "full_suspension": True,
        "handlebar_type": "riser",
        "wheel_front_in": 29.0,
        "wheel_rear_in": 29.0,
        "tire_width_mm": 57.0,
        "head_angle_deg": 67.5,
        "seat_angle_deg": 75.5,
        "reach_mm": 450.0,
        "stack_mm": 645.0,
        "wheelbase_mm": 1210.0,
        "chainstay_mm": 455.0,
        "bb_drop_mm": 35.0,
        "head_tube_mm": 135.0,
        "seat_tube_mm": 450.0,
        "travel_front_mm": 120.0,
        "travel_rear_mm": 110.0,
        "rotor_front_mm": 203.0,
        "rotor_rear_mm": 180.0,
        "accent_rgb": [0.25, 0.28, 0.32],
    },
    "urban_ebike": {
        "category_zh": "都會輕量電輔車 (Urban / Commuter e-Bike)",
        "is_ebike": True,
        "full_suspension": False,
        "handlebar_type": "flat",
        "wheel_front_in": 27.5,
        "wheel_rear_in": 27.5,
        "tire_width_mm": 50.0,
        "head_angle_deg": 69.5,
        "seat_angle_deg": 74.0,
        "reach_mm": 430.0,
        "stack_mm": 615.0,
        "wheelbase_mm": 1135.0,
        "chainstay_mm": 445.0,
        "bb_drop_mm": 55.0,
        "head_tube_mm": 150.0,
        "seat_tube_mm": 460.0,
        "travel_front_mm": 0.0,
        "travel_rear_mm": 0.0,
        "rotor_front_mm": 180.0,
        "rotor_rear_mm": 180.0,
        "accent_rgb": [0.85, 0.85, 0.83],
    },
    "gravel": {
        "category_zh": "礫石競速／全地形公路車 (Gravel / All-Road)",
        "is_ebike": False,
        "full_suspension": False,
        "handlebar_type": "drop",
        "wheel_front_in": 28.0,  # 700c
        "wheel_rear_in": 28.0,
        "tire_width_mm": 48.0,
        "head_angle_deg": 71.0,
        "seat_angle_deg": 73.5,
        "reach_mm": 395.0,
        "stack_mm": 575.0,
        "wheelbase_mm": 1045.0,
        "chainstay_mm": 432.0,
        "bb_drop_mm": 72.0,
        "head_tube_mm": 145.0,
        "seat_tube_mm": 500.0,
        "travel_front_mm": 0.0,
        "travel_rear_mm": 0.0,
        "rotor_front_mm": 160.0,
        "rotor_rear_mm": 160.0,
        "accent_rgb": [0.76, 0.30, 0.16],
    },
    "road": {
        "category_zh": "空力／競賽公路車 (Road Race)",
        "is_ebike": False,
        "full_suspension": False,
        "handlebar_type": "drop",
        "wheel_front_in": 28.0,
        "wheel_rear_in": 28.0,
        "tire_width_mm": 30.0,
        "head_angle_deg": 73.0,
        "seat_angle_deg": 73.5,
        "reach_mm": 392.0,
        "stack_mm": 555.0,
        "wheelbase_mm": 995.0,
        "chainstay_mm": 410.0,
        "bb_drop_mm": 70.0,
        "head_tube_mm": 140.0,
        "seat_tube_mm": 510.0,
        "travel_front_mm": 0.0,
        "travel_rear_mm": 0.0,
        "rotor_front_mm": 160.0,
        "rotor_rear_mm": 140.0,
        "accent_rgb": [0.14, 0.16, 0.20],
    },
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "bike-model"


def is_complete_bike_article(item: dict[str, Any]) -> bool:
    title = item["title"]
    if NON_BIKE_TITLE_RE.search(title):
        return False
    cats = " ".join(item.get("categories", []))
    combined = f"{title} {cats}"
    if BIKE_MODEL_HINTS_RE.search(combined):
        return True
    # Also check if RSS categories explicitly mark a bike category
    if re.search(r"\b(?:gravel bikes|mountain bikes|road bikes|e-bikes|complete bikes)\b", cats, re.I):
        if any(k in title.lower() for k in ["review", "test", "bike", "frame", "v2", "carbon", "alloy", "2026", "2027"]):
            return True
    return False


def infer_bike_category(title: str, text: str, specs: dict[str, str]) -> str:
    title_l = title.lower()
    blob = f"{title} {text[:2500]} {' '.join(specs.values())}".lower()
    if any(k in title_l for k in ["for the city", "commuter", "urban", "downtown", "ue carbon"]):
        return "urban_ebike"
    if any(k in blob for k in ["suv ebike", "suv e-bike", "trekking e-bike", "aventura", "turbo vado"]):
        if "vado" in blob and "full suspension" not in blob and "rear shock" not in blob:
            return "urban_ebike"
        return "suv_ebike"
    if any(k in blob for k in ["gravel", "all-road", "tambora", "g32"]):
        return "gravel"
    if any(k in blob for k in ["emtb", "e-mtb", "ep810", "avinox", "bosch", "remote 160", "rise lt", "honda rn0", "battery", "wh "]):
        if any(k in blob for k in ["rear shock", "full suspension", "150 mm", "160 mm", "140 mm", "emtb", "e-mtb", "remote 160", "rise lt", "rn0"]):
            return "emtb_full"
        return "urban_ebike"
    if any(k in blob for k in ["tallboy", "downhill", "trail bike", "enduro", "mtb", "mountain bike", "travel"]):
        return "mtb_trail"
    if any(k in blob for k in ["road bike", "aero road", "peloton"]):
        return "road"
    return "mtb_trail"


def clean_model_name(title: str) -> str:
    # Remove leading prefixes like "Review:", "First Ride:", "The New"
    name = re.sub(r"^(?:Review|First\s+Ride|Test|Tested|The\s+New|Check\s+Out)\s*[:–—-]\s*", "", title, flags=re.I).strip()
    # Cut at em-dash / colon / "Review" / "on Test" / "in Review" / German "im ersten Test"
    name = re.split(
        r"\s+[–—-]\s+|\s*:\s+|\s+(?:Review|on\s+Test|in\s+Review|im\s+(?:ersten\s+)?Test|First\s+Ride|Goes\s+|Reshapes\s+)",
        name,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    name = re.sub(r"^The\s+New\s+", "", name, flags=re.I).strip()
    name = name.replace("’s ", " ").replace("'s ", " ")
    return name[:64] if name else title[:50]


PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "head_angle_deg": (61.0, 75.5),
    "seat_angle_deg": (67.0, 81.5),
    "reach_mm": (330.0, 560.0),
    "stack_mm": (480.0, 750.0),
    "wheelbase_mm": (920.0, 1420.0),
    "chainstay_mm": (390.0, 515.0),
    "bb_drop_mm": (-15.0, 90.0),
    "head_tube_mm": (80.0, 240.0),
    "seat_tube_mm": (350.0, 620.0),
    "travel_front_mm": (0.0, 220.0),
    "travel_rear_mm": (0.0, 220.0),
    "fork_offset_mm": (30.0, 60.0),
    "wheel_table_in": (20.0, 32.5),
}


def _parse_num(val: str) -> float | None:
    """Locale-aware numeric parser supporting English (1,267.5) and German (1.113 / 53,5) formats."""
    if not val:
        return None
    s = val.replace("\xa0", " ").replace("°", "").replace("″", "").replace('"', "").replace("mm", "").replace("cm", "").strip()
    m = re.search(r"(-?\d[\d.,]*)", s)
    if not m:
        return None
    tok = m.group(1)
    # 1. Both '.' and ',' present
    if "." in tok and "," in tok:
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")  # German 1.113,5
        else:
            tok = tok.replace(",", "")  # English 1,267.5
    elif "," in tok:
        # German decimal (e.g. 53,5 or 72,6) vs English thousands (e.g. 1,267)
        if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", tok):
            tok = tok.replace(",", "")
        else:
            tok = tok.replace(",", ".")
    elif "." in tok:
        # German thousands separator (e.g. 1.113 or 1.014 -> exactly 3 digits after dot, leading 1..2)
        if re.fullmatch(r"-?[12]\.\d{3}", tok):
            tok = tok.replace(".", "")
    try:
        return float(tok)
    except ValueError:
        return None


GEO_ROW_MAP: list[tuple[str, str]] = [
    (r"head\s*(?:tube\s*)?angle|lenkwinkel", "head_angle_deg"),
    (r"sitzwinkel.*effektiv|effective\s*seat(?:\s*tube)?\s*angle", "seat_angle_deg"),
    (r"seat\s*(?:tube\s*)?angle|sitzwinkel(?!.*real)", "seat_angle_deg"),
    (r"\breach\b", "reach_mm"),
    (r"\bstack\b", "stack_mm"),
    (r"wheelbase|radstand", "wheelbase_mm"),
    (r"chain\s*stay|kettenstrebe", "chainstay_mm"),
    (r"bb\s*drop|tretlagerabsenkung|bottom\s*bracket\s*drop", "bb_drop_mm"),
    (r"head\s*tube(?:\s*length)?|steuerrohr", "head_tube_mm"),
    (r"seat\s*tube(?:\s*length)?|sitzrohr", "seat_tube_mm"),
    (r"top\s*tube(?:\s*length)?|oberrohr", "top_tube_mm"),
    (r"laufradgr[öo]ß?e|wheel\s*size", "wheel_table_in"),
    (r"federweg\s*\(vorn\)|front\s*travel|fork\s*travel", "travel_front_mm"),
    (r"gabel[- ]?offset|fork\s*(?:offset|rake)", "fork_offset_mm"),
]


def parse_geometry_tables(soup: BeautifulSoup) -> dict[str, Any]:
    """Parse multi-size HTML geometry tables (e.g., S/M/L/XL or XS/Regular) from full HTML."""
    for table in soup.find_all("table"):
        txt = table.get_text(" ", strip=True).lower()
        if not any(k in txt for k in ["reach", "wheelbase", "head angle", "lenkwinkel", "radstand"]):
            continue
        rows = table.find_all("tr")
        if len(rows) < 4:
            continue
        grid: list[list[str]] = []
        for tr in rows:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                grid.append(cells)
        if not grid or len(grid[0]) < 2:
            continue

        header = grid[0]
        sizes = [c for c in header[1:] if c and len(c) <= 14]
        if not sizes:
            continue

        by_size: dict[str, dict[str, float]] = {sz: {} for sz in sizes}
        raw_rows: list[dict[str, Any]] = []
        matched_fields = 0

        for row in grid[1:]:
            if len(row) < 2:
                continue
            label = row[0]
            vals = row[1 : 1 + len(sizes)]
            raw_rows.append({"label": label, "values": dict(zip(sizes, vals))})
            for pat, field_key in GEO_ROW_MAP:
                if re.search(pat, label, re.I):
                    matched_fields += 1
                    for sz, v_str in zip(sizes, vals):
                        if field_key in by_size[sz]:
                            continue  # Keep higher-priority match (e.g. effective seat angle over real)
                        num = _parse_num(v_str)
                        if num is not None:
                            lo, hi = PHYSICAL_BOUNDS.get(field_key, (-1e9, 1e9))
                            if lo <= num <= hi:
                                by_size[sz][field_key] = num
                    break

        if matched_fields >= 4:
            default_size = (
                "L"
                if "L" in sizes
                else ("Regular" if "Regular" in sizes else ("M" if "M" in sizes else sizes[-1]))
            )
            return {
                "sizes": sizes,
                "default_size": default_size,
                "by_size": by_size,
                "raw_rows": raw_rows,
                "source": "html_table",
            }
    return {}


def parse_spec_blocks(soup: BeautifulSoup, full_text: str) -> dict[str, str]:
    """Extract structured bicycle specs from HTML spec blocks & regex text mining."""
    specs: dict[str, str] = {}

    # 1. E-MOUNTAINBIKE / eMTB-News.de / WordPress structured spec blocks (dt/dd or key/val spans)
    for el in soup.select("[class*='spec'], [class*='fact'], dl, table"):
        txt = el.get_text(" | ", strip=True)
        if 40 < len(txt) < 2200 and any(
            k in txt.lower()
            for k in ["motor", "antrieb", "fork", "federgabel", "drivetrain", "schaltung", "brakes", "bremsen", "battery", "akku"]
        ):
            # Parse pairs from pipe-separated tokens
            tokens = [t.strip() for t in txt.split("|") if t.strip()]
            key_labels = {
                "motor": "motor",
                "antrieb": "motor",
                "battery": "battery",
                "akku": "battery",
                "display": "display",
                "fork": "fork",
                "federgabel": "fork",
                "gabel": "fork",
                "rear shock": "rear_shock",
                "shock": "rear_shock",
                "dämpfer": "rear_shock",
                "seatpost": "seatpost",
                "sattelstütze": "seatpost",
                "brakes": "brakes",
                "bremsen": "brakes",
                "bremse": "brakes",
                "drivetrain": "drivetrain",
                "schaltung": "drivetrain",
                "schaltwerk": "drivetrain",
                "stem": "stem",
                "vorbau": "stem",
                "handlebar": "handlebar",
                "lenker": "handlebar",
                "wheelset": "wheels",
                "wheels": "wheels",
                "laufräder": "wheels",
                "laufradsatz": "wheels",
                "tires": "tires",
                "tyres": "tires",
                "reifen": "tires",
                "weight": "weight",
                "gewicht": "weight",
                "price": "price",
                "preis": "price",
                "max. system weight": "max_weight",
            }
            i = 0
            while i < len(tokens):
                low_tok = tokens[i].lower().rstrip(":")
                if low_tok in key_labels:
                    dest = key_labels[low_tok]
                    vals = []
                    j = i + 1
                    while j < len(tokens) and tokens[j].lower().rstrip(":") not in key_labels and len(vals) < 2:
                        if tokens[j].lower() not in ("specifications", "technical data", "ausstattung", "spezifikationen"):
                            vals.append(tokens[j])
                        j += 1
                    if vals and dest not in specs:
                        specs[dest] = " / ".join(vals)
                    i = j
                else:
                    # Capture leading price like € 10,999
                    if re.match(r"^[€$£]\s*[\d,.]+$", tokens[i]) and "price" not in specs:
                        specs["price"] = tokens[i]
                    i += 1
            if len(specs) >= 4:
                break

    # 2. Text regex fallbacks for Bikerumor / Pinkbike / eMTB-News / road.cc
    if "price" not in specs:
        m = re.search(r"((?:USD\s*)?\$[\d,]+(?:\.\d{2})?|€\s*[\d,.]+|[\d,.]+\s*€|£[\d,]+)", full_text)
        if m:
            specs["price"] = m.group(1).strip()

    if "motor" not in specs:
        m = re.search(
            r"\b(Shimano\s+EP\d+(?:\s*RS)?|Bosch\s+Performance\s+Line\s+(?:CX|SX)(?:\s+Race)?|"
            r"Avinox(?:\s+M\d)?|DJI\s+Avinox|Specialized\s+(?:SL\s*1\.\d|2\.\d|3\.\d)|"
            r"TQ\s+HPR\d+|Fazua\s+Ride\s+60|Pinion\s+MGU|Mahle\s+X\d+)\b",
            full_text,
            re.I,
        )
        if m:
            specs["motor"] = m.group(1)

    if "battery" not in specs:
        m = re.search(r"\b(\d{3,4}\s*Wh(?:\s*/\s*\d{3,4}\s*Wh)?)\b", full_text, re.I)
        if m:
            specs["battery"] = m.group(1)

    if "torque" not in specs:
        m = re.search(r"\b(\d{2,3}\s*Nm)\b", full_text)
        if m:
            specs["torque"] = m.group(1)

    if "weight" not in specs:
        m = re.search(
            r"(?:weight[^.\n]{0,25}?|weighs\s*(?:in\s*at\s*)?)(\d{1,2}(?:\.\d{1,2})?\s*(?:kg|lbs?)|\d{3,4}\s*g\b)",
            full_text,
            re.I,
        )
        if m:
            specs["weight"] = m.group(1)

    if "frame_material" not in specs:
        if re.search(r"\b(?:carbon|cfr|fact\s*\d+r|omr|cc\s+carbon)\b", full_text, re.I):
            specs["frame_material"] = "碳纖維 (Carbon)"
        elif re.search(r"\b(?:6061|7005|alloy|alumin(?:um|ium))\b", full_text, re.I):
            specs["frame_material"] = "鋁合金 (Alloy)"
        elif re.search(r"\b(?:titanium|ti\s+frame)\b", full_text, re.I):
            specs["frame_material"] = "鈦合金 (Titanium)"
        elif re.search(r"\b(?:chromoly|steel|reynolds)\b", full_text, re.I):
            specs["frame_material"] = "鋼管 (Steel)"

    if "tire_clearance" not in specs:
        m = re.search(r"(\d{2}(?:\.\d)?\s*mm|2\.\d{1,2}[\"”'])\s*(?:max\s*)?(?:tire|tyre)\s*clearance", full_text, re.I)
        if not m:
            m = re.search(r"(?:tire|tyre)\s*clearance[^.\n]{0,25}?(\d{2}\s*mm|2\.\d{1,2}[\"”'])", full_text, re.I)
        if m:
            specs["tire_clearance"] = m.group(1)

    if "wheel_size" not in specs:
        if re.search(r"\b32[\s\"”′-]*inch|\b32[\"”′]\s*(?:wheel|gravel)", full_text, re.I):
            specs["wheel_size"] = '32"'
        elif re.search(r"\bmullet\b|\bmx\s+wheel|\b29\s*/\s*27\.5", full_text, re.I):
            specs["wheel_size"] = '29" / 27.5" Mullet'
        elif re.search(r"\b29(?:er|[\"”′]|\s*inch)", full_text, re.I):
            specs["wheel_size"] = '29"'
        elif re.search(r"\b700c\b", full_text, re.I):
            specs["wheel_size"] = "700c"
        elif re.search(r"\b27\.5|650b\b", full_text, re.I):
            specs["wheel_size"] = '27.5" / 650b'

    if "drivetrain" not in specs:
        m = re.search(
            r"\b(Shimano\s+(?:XTR|Deore\s+XT|XT|Deore|GRX|Ultegra|Dura-Ace|105|CUES|SLX)(?!\s*(?:four|two|4|2)-piston|\s*brakes?)(?:\s+(?:Di2|1x\d{2}|1×\d{2}|\d{2}-speed|drivetrain|shifting))?|"
            r"SRAM\s+(?:XX|X0|GX|S1000|Apex|Rival|Force|Red|Eagle|Transmission)(?:\s+(?:AXS|Eagle|Transmission|T-Type|1x\d{2}))*|"
            r"Gates\s+Carbon\s+Drive[^,.;\n]{0,14}|Pinion\s+[A-Z0-9\.]+|Enviolo[^,.;\n]{0,14}|microSHIFT\s+[A-Za-z0-9]+)\b",
            full_text,
            re.I,
        )
        if m:
            specs["drivetrain"] = m.group(1).strip()

    # Extract fork, rear_shock, brakes, tires, wheels, motor fallbacks from prose
    extract_prose_component_fallbacks(full_text, specs)

    # Extract travel numbers if mentioned
    if "travel_front" not in specs:
        if "fork" in specs:
            mf = re.search(r"(\d{2,3})\s*mm", specs["fork"])
            if mf:
                specs["travel_front"] = f"{mf.group(1)} mm"
        if "travel_front" not in specs:
            m = re.search(r"\b(\d{2,3})\s*mm\s*(?:of\s*)?(?:front\s*)?travel", full_text, re.I)
            if m:
                specs["travel_front"] = f"{m.group(1)} mm"

    if "travel_rear" not in specs:
        if "rear_shock" in specs:
            mr = re.search(r"(\d{2,3})\s*mm", specs["rear_shock"])
            if mr:
                specs["travel_rear"] = f"{mr.group(1)} mm"
        if "travel_rear" not in specs:
            m = re.search(r"\b(\d{2,3})\s*mm\s*(?:of\s*)?rear\s*travel", full_text, re.I)
            if not m:
                m = re.search(r"\b(\d{2,3})\s*/\s*(\d{2,3})\s*mm\s*travel", full_text, re.I)
                if m:
                    specs["travel_front"] = f"{m.group(1)} mm"
                    specs["travel_rear"] = f"{m.group(2)} mm"
            elif m:
                specs["travel_rear"] = f"{m.group(1)} mm"

    return specs


def extract_inline_geometry(full_text: str) -> dict[str, float]:
    """Regex-mine geometry measurements directly from prose when no HTML table exists."""
    geo: dict[str, float] = {}
    patterns = [
        ("head_angle_deg", r"head(?:\s*tube)?\s*angle[s]?\s*(?:of|is|at|:|are|sits\s+at)?[^0-9]{0,20}(\d{2}(?:\.\d{1,2})?)\s*°"),
        ("seat_angle_deg", r"seat(?:\s*tube)?\s*angle[s]?\s*(?:of|is|at|:|are)?[^0-9]{0,20}(\d{2}(?:\.\d{1,2})?)\s*°"),
        ("chainstay_mm", r"chainstays?\s*(?:are|is|of|at|:)?[^0-9]{0,18}(\d{3}(?:\.\d)?)\s*mm"),
        ("bb_drop_mm", r"(\d{2}(?:\.\d)?)\s*mm\s*(?:of\s*)?(?:bb|bottom\s*bracket)\s*drop"),
        ("bb_drop_mm", r"(?:bb|bottom\s*bracket)\s*drop\s*(?:of|is|at|:)?[^0-9]{0,12}(\d{2}(?:\.\d)?)\s*mm"),
        ("reach_mm", r"\breach\s*(?:of|is|at|:)?[^0-9]{0,12}(\d{3}(?:\.\d)?)\s*mm"),
        ("stack_mm", r"\bstack\s*(?:of|is|at|:)?[^0-9]{0,12}(\d{3}(?:\.\d)?)\s*mm"),
        ("wheelbase_mm", r"wheelbase\s*(?:of|is|at|:)?[^0-9]{0,12}(1,?\d{3}(?:\.\d)?)\s*mm"),
    ]
    for key, pat in patterns:
        if key in geo:
            continue
        m = re.search(pat, full_text, re.I)
        if m:
            v = _parse_num(m.group(1))
            if v is not None:
                geo[key] = v
    return geo


def select_best_gallery(images: list[dict[str, str]], model_name: str) -> list[dict[str, str]]:
    """Score & rank images so full-bike side-profile / hero photos come first."""
    scored: list[tuple[int, dict[str, str]]] = []
    tokens = [t.lower() for t in re.split(r"\W+", model_name) if len(t) >= 3]
    for idx, img in enumerate(images):
        url_l = img["url"].lower()
        alt_l = img.get("alt", "").lower()
        score = 0
        if any(k in url_l or k in alt_l for k in ["complete", "hero", "side", "profile", "angled", "full"]):
            score += 30
        if any(k in url_l for k in ["1536x", "1140x", "1200x", "1600x", "2000x", "2048x"]):
            score += 20
        if any(t in url_l or t in alt_l for t in tokens):
            score += 15
        if any(k in url_l for k in ["600x400", "300x", "thumb", "small"]):
            score -= 10
        if any(k in url_l for k in ["screen-shot", "screenshot", "chart", "logo"]):
            score -= 20
        # Slight preference for early editorial images
        score += max(0, 10 - idx)
        scored.append((score, img))
    scored.sort(key=lambda x: -x[0])
    return [img for _, img in scored[:8]]


def extract_complete_bike(item: dict[str, Any], brands: list[dict[str, str]]) -> dict[str, Any]:
    """Deeply parse a complete-bike article into specs, multi-size geometry, images, and 3D inputs."""
    raw_html = item.get("content_html") or ""
    full_text = item.get("full_text") or ""
    images = list(item.get("images") or [])

    # Politely enrich with full page HTML (especially unlocks E-MOUNTAINBIKE geometry tables & spec cards!)
    if item["source_id"] in ("ebike_mtb", "emtb_news", "cyclingnews") or len(raw_html) < 2000:
        page_html = fetch_article_html(item["url"])
        if page_html:
            raw_html = page_html
            soup = BeautifulSoup(page_html, "lxml")
            main_node = soup.find("article") or soup.find("main") or soup
            page_imgs = extract_images_from_html(str(main_node), base_url=item["url"])
            existing = {i["url"] for i in images}
            for pi in page_imgs:
                if pi["url"] not in existing:
                    images.append(pi)
                    existing.add(pi["url"])
            for tag in main_node(["script", "style", "noscript"]):
                tag.decompose()
            full_text = re.sub(r"\s+", " ", main_node.get_text(" ", strip=True))[:24000]
        else:
            soup = BeautifulSoup(raw_html, "lxml")
    else:
        soup = BeautifulSoup(raw_html, "lxml")

    model_name = clean_model_name(item["title"])
    brand_name = brands[0]["name"] if brands else model_name.split()[0]
    slug = slugify(f"{item['source_id']}-{model_name}")

    geo_table = parse_geometry_tables(soup)
    specs = parse_spec_blocks(soup, full_text)
    inline_geo = extract_inline_geometry(full_text)
    category_key = infer_bike_category(item["title"], full_text, specs)
    template = dict(CATEGORY_TEMPLATES[category_key])

    # Assemble canonical geometry for 3D reconstruction + explicit measured/inferred provenance
    resolved_geo: dict[str, float] = {}
    provenance: dict[str, str] = {}

    # Base from HTML table default size if available, else inline_geo
    table_default = {}
    if geo_table:
        table_default = geo_table["by_size"].get(geo_table["default_size"], {})

    geo_fields = [
        "head_angle_deg",
        "seat_angle_deg",
        "reach_mm",
        "stack_mm",
        "wheelbase_mm",
        "chainstay_mm",
        "bb_drop_mm",
        "head_tube_mm",
        "seat_tube_mm",
    ]
    for f in geo_fields:
        lo, hi = PHYSICAL_BOUNDS.get(f, (-1e9, 1e9))
        if f in table_default and lo <= float(table_default[f]) <= hi:
            resolved_geo[f] = float(table_default[f])
            provenance[f] = "measured_table"
        elif f in inline_geo and lo <= float(inline_geo[f]) <= hi:
            resolved_geo[f] = float(inline_geo[f])
            provenance[f] = "measured_text"
        else:
            resolved_geo[f] = float(template[f])
            provenance[f] = "inferred_category"

    # Fork offset (measured from table if present, else realistic category default)
    if "fork_offset_mm" in table_default and 30 <= float(table_default["fork_offset_mm"]) <= 60:
        resolved_geo["fork_offset_mm"] = float(table_default["fork_offset_mm"])
        provenance["fork_offset_mm"] = "measured_table"
    else:
        resolved_geo["fork_offset_mm"] = 44.0 if category_key in ("emtb_full", "mtb_trail", "suv_ebike") else 48.0
        provenance["fork_offset_mm"] = "inferred_category"

    # Travel specs (table -> spec block -> template)
    tf = table_default.get("travel_front_mm")
    if tf is None:
        tf = _parse_num(specs.get("travel_front", ""))
    tr = _parse_num(specs.get("travel_rear", ""))
    if tf is not None and 20 <= float(tf) <= 220:
        resolved_geo["travel_front_mm"] = float(tf)
        provenance["travel_front_mm"] = "measured_table" if "travel_front_mm" in table_default else "measured_spec"
    else:
        resolved_geo["travel_front_mm"] = float(template["travel_front_mm"])
        provenance["travel_front_mm"] = "inferred_category"

    if tr is not None and 20 <= float(tr) <= 220:
        resolved_geo["travel_rear_mm"] = float(tr)
        provenance["travel_rear_mm"] = "measured_spec"
    else:
        resolved_geo["travel_rear_mm"] = float(template["travel_rear_mm"])
        provenance["travel_rear_mm"] = "inferred_category"

    # Wheel sizes (strictly avoid false mullet triggers!)
    title_l = item["title"].lower()
    ws = specs.get("wheel_size", "")
    explicit_mullet = bool(
        re.search(r"\bmullet\b|\bmx\s+wheel|\b29\s*/\s*27\.5|\b29[\"”′]?\s+front\s+and\s+27\.5", full_text[:5000], re.I)
        or ("honda" in title_l and "rn0" in title_l)
    )
    if "wheel_table_in" in table_default and 20.0 <= float(table_default["wheel_table_in"]) <= 32.5:
        wt = float(table_default["wheel_table_in"])
        resolved_geo["wheel_front_in"] = wt
        resolved_geo["wheel_rear_in"] = wt
        provenance["wheel_size"] = "measured_table"
        specs["wheel_size"] = f'{wt:g}"'
    elif '32"' in item["title"] or "32″" in item["title"] or "32" in ws:
        resolved_geo["wheel_front_in"] = 32.0
        resolved_geo["wheel_rear_in"] = 32.0
        provenance["wheel_size"] = "measured_spec"
        specs["wheel_size"] = '32"'
    elif category_key in ("gravel", "road"):
        resolved_geo["wheel_front_in"] = 28.0
        resolved_geo["wheel_rear_in"] = 28.0
        provenance["wheel_size"] = "measured_spec" if "700c" in full_text.lower() else "inferred_category"
        specs["wheel_size"] = "700c"
    elif explicit_mullet:
        resolved_geo["wheel_front_in"] = 29.0
        resolved_geo["wheel_rear_in"] = 27.5
        provenance["wheel_size"] = "measured_spec"
        specs["wheel_size"] = '29" / 27.5" Mullet'
    elif "29" in ws:
        resolved_geo["wheel_front_in"] = 29.0
        resolved_geo["wheel_rear_in"] = 29.0
        provenance["wheel_size"] = "measured_spec"
        specs["wheel_size"] = '29"'
    elif "27.5" in ws or "650b" in ws.lower():
        resolved_geo["wheel_front_in"] = 27.5
        resolved_geo["wheel_rear_in"] = 27.5
        provenance["wheel_size"] = "measured_spec"
    else:
        resolved_geo["wheel_front_in"] = float(template["wheel_front_in"])
        resolved_geo["wheel_rear_in"] = float(template["wheel_rear_in"])
        provenance["wheel_size"] = "inferred_category"

    # Tire width
    tc = _parse_num(specs.get("tire_clearance", ""))
    if tc is not None:
        if 1.5 <= tc <= 4.5:  # inches
            resolved_geo["tire_width_mm"] = round(tc * 25.4, 1)
        elif 25 <= tc <= 75:
            resolved_geo["tire_width_mm"] = tc
        else:
            resolved_geo["tire_width_mm"] = float(template["tire_width_mm"])
        provenance["tire_width_mm"] = "measured_spec"
    else:
        resolved_geo["tire_width_mm"] = float(template["tire_width_mm"])
        provenance["tire_width_mm"] = "inferred_category"

    # Brake rotor diameters
    brakes_str = specs.get("brakes", "")
    rm = re.search(r"(\d{3})\s*/\s*(\d{3})\s*mm", brakes_str)
    if rm:
        resolved_geo["rotor_front_mm"] = float(rm.group(1))
        resolved_geo["rotor_rear_mm"] = float(rm.group(2))
        provenance["rotors_mm"] = "measured_spec"
    else:
        resolved_geo["rotor_front_mm"] = float(template["rotor_front_mm"])
        resolved_geo["rotor_rear_mm"] = float(template["rotor_rear_mm"])
        provenance["rotors_mm"] = "inferred_category"

    # Visual cues + true frame architecture + photo-sampled paint RGB!
    kashima_gold = bool(
        re.search(r"\b(?:factory|kashima)\b", f"{specs.get('fork','')} {specs.get('rear_shock','')} {full_text[:4000]}", re.I)
        or ("honda" in title_l and "rn0" in title_l)
    )
    gallery = select_best_gallery(images, model_name)
    hero_url = gallery[0]["url"] if gallery else item.get("hero_image", "")

    arch_info = classify_frame_architecture(model_name, item["title"], category_key, specs, full_text)
    if arch_info["paint_override"] is not None:
        accent_rgb = arch_info["paint_override"]
    else:
        accent_rgb = sample_frame_color_from_photo(hero_url, arch_info["default_primary_rgb"])

    measured_count = sum(1 for v in provenance.values() if v.startswith("measured"))
    total_geo_keys = len(provenance)

    is_ebike = template["is_ebike"] or bool(specs.get("motor") or specs.get("battery"))
    components = build_bike_components(specs, is_ebike=is_ebike, has_belt_drive=arch_info["has_belt_drive"])

    return {
        "slug": slug,
        "brand": brand_name,
        "model_name": model_name,
        "title": item["title"],
        "source_id": item["source_id"],
        "source_name": item["source_name"],
        "url": item["url"],
        "published_at": item["published_at"],
        "category_key": category_key,
        "category_zh": template["category_zh"],
        "frame_arch": arch_info["frame_arch"],
        "has_belt_drive": arch_info["has_belt_drive"],
        "has_fenders": arch_info["has_fenders"],
        "has_rear_rack": arch_info["has_rear_rack"],
        "has_front_rack": arch_info["has_front_rack"],
        "has_headlight": arch_info["has_headlight"],
        "two_tone_lower": arch_info["two_tone_lower"],
        "secondary_rgb": arch_info["secondary_rgb"],
        "is_ebike": is_ebike,
        "full_suspension": template["full_suspension"] or resolved_geo["travel_rear_mm"] > 0,
        "handlebar_type": template["handlebar_type"],
        "kashima_gold": kashima_gold,
        "accent_rgb": accent_rgb,
        "hero_image": hero_url,
        "gallery": gallery,
        "specs": specs,
        "components": components,
        "geometry_resolved": resolved_geo,
        "geometry_provenance": provenance,
        "geometry_table": geo_table,
        "measured_ratio": round(measured_count / max(1, total_geo_keys), 2),
        "default_size": geo_table.get("default_size", "L"),
    }
