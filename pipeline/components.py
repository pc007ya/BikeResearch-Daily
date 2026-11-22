"""Component brand extraction & market-share statistics across complete bikes.

Extracts normalized brands for:
- motor (e-bike drive unit)
- fork (suspension / rigid fork)
- rear_shock
- drivetrain (groupset / shifting / belt)
- tires
- wheels (wheelset / rims)
- brakes

and computes per-category adoption share percentages across complete bikes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

# Ordered (pattern, canonical_brand) lists — more specific patterns first!
COMPONENT_BRAND_RULES: dict[str, list[tuple[str, str]]] = {
    "motor": [
        (r"\b(?:dji\s+avinox|avinox)\b", "DJI Avinox"),
        (r"\bbosch\b", "Bosch"),
        (r"\bshimano\b|\bep8\d{2}\b|\bep6\d{2}\b|\bsteps\b", "Shimano"),
        (r"\bspecialized\b|\bbrose\b", "Specialized / Brose"),
        (r"\btq\b|\bhpr\s*\d+", "TQ"),
        (r"\bfazua\b", "Fazua"),
        (r"\bpinion\s*mgu\b|\bmgu\b", "Pinion MGU"),
        (r"\bmahle\b", "Mahle"),
        (r"\byamaha\b|\bpw-?(?:x3|s2|xm)\b", "Yamaha"),
        (r"\bbafang\b", "Bafang"),
        (r"\baventon\b|\bultro\b", "Aventon"),
        (r"\bzf\b|\bcentrix\b", "ZF Bike Eco"),
        (r"\bsram\s+eagle\s+powertrain\b|\bpowertrain\b", "SRAM Powertrain"),
        (r"\bpolini\b", "Polini"),
        (r"\bsachs\b", "Sachs"),
        (r"\bdyname\b", "Rocky Mountain Dyname"),
        (r"\bflyon\b|\bgiant\s+syncdrive\b|\bsyncdrive\b", "Giant SyncDrive"),
    ],
    "fork": [
        (r"\bfox\b|\bkashima\b", "Fox"),
        (r"\brock\s*shox\b|\bzeb\b|\blyrik\b|\bpsylo\b|\bpike\b|\bdomain\b|\bboxxer\b|\bsid\b", "RockShox"),
        (r"\b(?:sr|st)\s*suntour\b|\bsuntour\b|\bmobie\s*\d+", "SR Suntour"),
        (r"\bx-?fusion\b", "X-Fusion"),
        (r"\bmarzocchi\b|\bbomber\s+z\d", "Marzocchi"),
        (r"\böhlins\b|\bohlins\b|\brxf\s*3\d", "Öhlins"),
        (r"\bmanitou\b|\bmezzer\b|\bmattoc\b", "Manitou"),
        (r"\bdvo\b", "DVO"),
        (r"\bdt\s*swiss\b", "DT Swiss"),
        (r"\bformula\b", "Formula"),
        (r"\bintend\b", "Intend"),
        (r"\bcannondale\b|\blefty\b", "Cannondale Lefty"),
        (r"\bstate\b|\bcarbon\s+monster\b", "State Bicycle"),
        (r"\bgiant\b", "Giant"),
        (r"\bspecialized\b|\bfuture\s+shock\b", "Specialized"),
        (r"\b(?:rigid|carbon)\s+fork\b|\b碳纖硬叉\b", "原廠碳纖硬叉"),
    ],
    "rear_shock": [
        (r"\bfox\b|\bfloat\s+x\b|\bdhx\b", "Fox"),
        (r"\brock\s*shox\b|\bsuper\s+deluxe\b|\bdeluxe\b|\bvivid\b|\bsidluxe\b", "RockShox"),
        (r"\b(?:sr|st)\s*suntour\b|\bsuntour\b", "SR Suntour"),
        (r"\bx-?fusion\b", "X-Fusion"),
        (r"\böhlins\b|\bohlins\b|\bttx\b", "Öhlins"),
        (r"\bmarzocchi\b", "Marzocchi"),
        (r"\bext\b|\bstoria\b", "EXT"),
        (r"\bcane\s*creek\b|\bkitsuma\b", "Cane Creek"),
        (r"\bdvo\b", "DVO"),
        (r"\bdt\s*swiss\b", "DT Swiss"),
        (r"\bmanitou\b", "Manitou"),
    ],
    "drivetrain": [
        (r"\bshimano\b|\bxtr\b|\bdeore\b|\bcues\b|\bgrx\b|\bultegra\b|\bdura-?ace\b|\bslx\b|\bdi2\b|\balfine\b|\bnexus\b", "Shimano"),
        (r"\bsram\b|\beagle\b|\btransmission\b|\baxs\b|\bs1000\b|\bgx\b|\bx0\b|\bxx\b|\bapex\b|\brival\b|\bforce\b", "SRAM"),
        (r"\bgates\b|\bcarbon\s+drive\b", "Gates 皮帶"),
        (r"\bpinion\b", "Pinion"),
        (r"\benviolo\b", "Enviolo"),
        (r"\brohloff\b", "Rohloff"),
        (r"\bmicro\s*shift\b", "microSHIFT"),
        (r"\bcampagnolo\b|\bekar\b", "Campagnolo"),
        (r"\btrp\b", "TRP"),
        (r"\bstate\b", "State Bicycle"),
    ],
    "brakes": [
        (r"\bshimano\b|\bxtr\b|\bdeore\b|\bmt\d{3}\b|\bslx\b|\bgrx\b", "Shimano"),
        (r"\bsram\b|\bmaven\b|\bcode\b|\bdb[68]\b|\blevel\b|\bg2\b", "SRAM"),
        (r"\bmagura\b|\bmt[57]\b|\blouise\b|\bgustav\b", "Magura"),
        (r"\btektro\b|\bhd-?m\d+", "Tektro"),
        (r"\btrp\b|\bdh-?r\b", "TRP"),
        (r"\bhope\b", "Hope"),
        (r"\bformula\b|\bcura\b", "Formula"),
        (r"\bhayes\b|\bdominion\b", "Hayes"),
        (r"\btrickstuff\b", "Trickstuff"),
    ],
    "tires": [
        (r"\bschwalbe\b|\bmagic\s+mary\b|\balbert\b|\bhans\s+dampf\b|\bjonny\s+watts\b|\bjohnny\s+watts\b|\bsmart\s+sam\b|\bnobby\s+nic\b|\bg-?one\b|\btacky\s+chan\b|\bbig\s+betty\b", "Schwalbe"),
        (r"\bmaxxis\b|\bassegai\b|\bminion\b|\bdhr\b|\bdhf\b|\bcrossmark\b|\bdissector\b|\brekon\b|\baspen\b|\bforekaster\b|\brambler\b", "Maxxis"),
        (r"\bcontinental\b|\bkryptotal\b|\bargotal\b|\bxynotal\b|\bgp\s*5000\b|\bterra\s+speed\b", "Continental"),
        (r"\bspecialized\b|\bhemisphere\b|\bbutcher\b|\beliminator\b|\bpathfinder\b|\bground\s+control\b", "Specialized"),
        (r"\bpirelli\b|\bscorpion\b|\bcinturato\b|\bp\s*zero\b", "Pirelli"),
        (r"\bvittoria\b|\bmezcal\b|\bmazza\b|\bcorsa\b|\bterreno\b", "Vittoria"),
        (r"\bmichelin\b|\bwild\s+enduro\b", "Michelin"),
        (r"\bwtb\b|\briddler\b|\bbyway\b|\bventure\b", "WTB"),
        (r"\bpanaracer\b|\bgravelking\b", "Panaracer"),
        (r"\bgoodyear\b", "Goodyear"),
        (r"\bkenda\b", "Kenda"),
        (r"\bhutchinson\b", "Hutchinson"),
        (r"\btufo\b", "Tufo"),
        (r"\bchallenge\b", "Challenge"),
    ],
    "wheels": [
        (r"\bdt\s*swiss\b|\bh\s*1900\b|\bex\s*1700\b|\bxm\s*1700\b|\bhx\s*1700\b|\be\s*1900\b|\bexc\s*1\d{3}\b", "DT Swiss"),
        (r"\boquo\b", "OQUO"),
        (r"\breserve\b", "Reserve"),
        (r"\broval\b", "Roval"),
        (r"\bspecialized\b", "Specialized"),
        (r"\bzipp\b", "Zipp"),
        (r"\benve\b", "ENVE"),
        (r"\bmavic\b", "Mavic"),
        (r"\bnewmen\b", "Newmen"),
        (r"\brace\s*face\b", "Race Face"),
        (r"\bcrankbrothers\b|\bsynthesis\b", "Crankbrothers"),
        (r"\bmach\s*1\b", "Mach 1"),
        (r"\brodi\b|\bconway\b", "Rodi / Conway"),
        (r"\baventon\b", "Aventon"),
        (r"\bhunt\b", "Hunt"),
        (r"\bfulcrum\b", "Fulcrum"),
        (r"\bindustry\s*nine\b|\bi9\b", "Industry Nine"),
        (r"\bsun\s*ringle\b", "SUNringlé"),
        (r"\bwtb\b", "WTB"),
        (r"\balex\s*rims\b", "Alexrims"),
        (r"\bbontrager\b", "Bontrager"),
        (r"\bsyncros\b", "Syncros"),
        (r"\bcadex\b|\bgiant\b", "Giant / CADEX"),
        (r"\bshimano\b", "Shimano"),
        (r"\bcampagnolo\b", "Campagnolo"),
        (r"\bvision\b", "Vision"),
        (r"\bamflow\b", "Amflow"),
    ],
}

COMPONENT_CATEGORIES_META: list[dict[str, str]] = [
    {"key": "motor", "label_zh": "電輔電機系統", "short_zh": "電機", "en": "Motor", "ebike_only": "1"},
    {"key": "fork", "label_zh": "前叉避震系統", "short_zh": "前叉", "en": "Fork", "ebike_only": "0"},
    {"key": "drivetrain", "label_zh": "變速與傳動系統", "short_zh": "變速", "en": "Drivetrain", "ebike_only": "0"},
    {"key": "tires", "label_zh": "外胎配置", "short_zh": "輪胎", "en": "Tires", "ebike_only": "0"},
    {"key": "wheels", "label_zh": "輪組配置", "short_zh": "輪組", "en": "Wheels", "ebike_only": "0"},
    {"key": "brakes", "label_zh": "煞車系統", "short_zh": "煞車", "en": "Brakes", "ebike_only": "0"},
]


def match_component_brand(category: str, text: str) -> str | None:
    if not text:
        return None
    for pat, brand in COMPONENT_BRAND_RULES.get(category, []):
        if re.search(pat, text, re.I):
            return brand
    return None


def extract_prose_component_fallbacks(full_text: str, specs: dict[str, str], is_ebike: bool = False) -> dict[str, str]:
    """Mine fork, rear_shock, brakes, tires, wheels, motor from prose when spec tables are absent."""
    text = full_text[:18000]

    if "motor" not in specs:
        m = re.search(
            r"\b(DJI\s+Avinox(?:\s+M\d)?|Avinox(?:\s+M\d)?|"
            r"Bosch\s+Performance\s+Line\s+(?:CX|SX)(?:\s+Race)?(?:\s*\([^)]+\))?|"
            r"Shimano\s+(?:EP810|EP801|EP800|EP6|EP8)(?:\s*RS)?|"
            r"Specialized\s+(?:SL\s*1\.\d|2\.\d|3\.\d)|"
            r"TQ\s+HPR\s*\d+|Fazua\s+Ride\s+60|Pinion\s+MGU(?:\s*E1\.\d+)?|"
            r"Mahle\s+X\d+|Yamaha\s+PW-?(?:X3|S2|XM)|ZF\s+CentriX|"
            r"SRAM\s+Eagle\s+Powertrain|Aventon\s+Ultro[^,.;\n]{0,12})\b",
            text,
            re.I,
        )
        if m:
            specs["motor"] = m.group(1).strip()

    if "fork" not in specs:
        m = re.search(
            r"\b(Fox\s+(?:32|34|36|38|40|Float|Podium)\s+[^,.;\n]{0,28}|"
            r"RockShox\s+(?:ZEB|Lyrik|Pike|SID|Domain|Psylo|BoXXer|Reba|Rudy)[^,.;\n]{0,28}|"
            r"(?:SR|ST)\s+Suntour\s+[A-Za-z0-9\-]+[^,.;\n]{0,22}|"
            r"Marzocchi\s+Bomber\s+Z\d[^,.;\n]{0,22}|"
            r"(?:Öhlins|Ohlins)\s+RXF\s*\d+[^,.;\n]{0,20}|"
            r"X-Fusion\s+[A-Za-z0-9\-]+[^,.;\n]{0,22}|"
            r"Manitou\s+(?:Mezzer|Mattoc|R8)[^,.;\n]{0,20}|"
            r"DT\s+Swiss\s+F\s*\d+[^,.;\n]{0,18})\b",
            text,
            re.I,
        )
        if m:
            specs["fork"] = m.group(1).strip()

    if "rear_shock" not in specs:
        m = re.search(
            r"\b(Fox\s+(?:Float\s+X2?|DHX2?|Float\s+DPS|Float\s+SL|Float\s+Rhythm)[^,.;\n]{0,22}|"
            r"RockShox\s+(?:Super\s+Deluxe|Deluxe|Vivid|SIDLuxe)[^,.;\n]{0,22}|"
            r"(?:SR|ST)\s+Suntour\s+(?:Edge|TriAir)[^,.;\n]{0,18}|"
            r"(?:Öhlins|Ohlins)\s+TTX[^,.;\n]{0,18}|"
            r"X-Fusion\s+O2[^,.;\n]{0,18})\b",
            text,
            re.I,
        )
        if m:
            specs["rear_shock"] = m.group(1).strip()

    if "brakes" not in specs:
        m = re.search(
            r"\b(Shimano\s+(?:XTR|XT|Deore\s+XT|Deore|SLX|MT\d{3})\s+(?:four-piston|4-piston|two-piston|brakes?|disc)[^,.;\n]{0,16}|"
            r"SRAM\s+(?:Maven|Code|Level|DB[68]|G2)\s*[A-Za-z0-9\s]{0,18}|"
            r"Magura\s+(?:MT7|MT5|Gustav|Louise)[^,.;\n]{0,18}|"
            r"TRP\s+(?:DH-R|Trail\s+Evo|Slate)[^,.;\n]{0,18}|"
            r"Tektro\s+HD-M\d+[^,.;\n]{0,14}|"
            r"Hope\s+Tech\s*4[^,.;\n]{0,14}|"
            r"Formula\s+Cura[^,.;\n]{0,14})\b",
            text,
            re.I,
        )
        if m:
            specs["brakes"] = m.group(1).strip()

    if "tires" not in specs:
        m = re.search(
            r"\b(Schwalbe\s+(?:Albert|Magic\s+Mary|Hans\s+Dampf|Nobby\s+Nic|Johnny\s+Watts|Jonny\s+Watts|Smart\s+Sam|G-One|Pro\s+One|Tacky\s+Chan|Big\s+Betty)[^,.;\n]{0,20}|"
            r"Maxxis\s+(?:Assegai|Minion\s+DH[RF]|Dissector|Rekon|Crossmark|Forekaster|Rambler|Aspen|Shorty)[^,.;\n]{0,20}|"
            r"Continental\s+(?:Kryptotal|Argotal|Xynotal|GP\s*5000|Terra\s+\w+|Dubnital)[^,.;\n]{0,20}|"
            r"Pirelli\s+(?:Scorpion|Cinturato|P\s*Zero)[^,.;\n]{0,20}|"
            r"Vittoria\s+(?:Mezcal|Mazza|Corsa|Terreno)[^,.;\n]{0,20}|"
            r"Specialized\s+(?:Butcher|Eliminator|Hemisphere|Pathfinder|Ground\s+Control)[^,.;\n]{0,20}|"
            r"Panaracer\s+GravelKing[^,.;\n]{0,18}|"
            r"Michelin\s+Wild[^,.;\n]{0,18}|"
            r"WTB\s+(?:Riddler|Byway|Venture|Vigilante|Trail\s+Boss)[^,.;\n]{0,18})\b",
            text,
            re.I,
        )
        if m:
            specs["tires"] = m.group(1).strip()

    if "wheels" not in specs:
        m = re.search(
            r"\b(DT\s+Swiss\s+(?:H\s*1900|HX\s*1700|EX\s*1700|XM\s*1700|E\s*1900|EXC\s*\d+|XRC\s*\d+|ERC\s*\d+|GRC\s*\d+|G\s*1800)[^,.;\n]{0,18}|"
            r"Reserve\s+\d{2}(?:\s*[A-Z]{2})?[^,.;\n]{0,16}|"
            r"OQUO\s+[A-Za-z0-9\s\-]{2,26}|"
            r"Roval\s+(?:Traverse|Control|Rapide|Terra|Alpinist)[^,.;\n]{0,18}|"
            r"Zipp\s+(?:303|353|404|101|3Zero)[^,.;\n]{0,16}|"
            r"ENVE\s+(?:M\d|SES|G23|Foundation)[^,.;\n]{0,16}|"
            r"Mavic\s+(?:Deemax|Crossmax|Cosmic|Allroad)[^,.;\n]{0,16}|"
            r"Newmen\s+(?:Evolution|Beskar|Phase)[^,.;\n]{0,16}|"
            r"Race\s+Face\s+(?:Turbine|Aeffect|ARC)[^,.;\n]{0,16}|"
            r"Crankbrothers\s+Synthesis[^,.;\n]{0,16}|"
            r"Hunt\s+(?:Proven|Trail|Enduro|Gravel)[^,.;\n]{0,16})\b",
            text,
            re.I,
        )
        if m:
            specs["wheels"] = m.group(1).strip()

    return specs


def build_bike_components(specs: dict[str, str], is_ebike: bool, has_belt_drive: bool = False) -> dict[str, dict[str, str]]:
    """Build normalized per-component brand/model records for one complete bike."""
    comps: dict[str, dict[str, str]] = {}
    for cat in ("motor", "fork", "rear_shock", "drivetrain", "brakes", "tires", "wheels"):
        if cat == "motor" and not is_ebike and not specs.get("motor"):
            continue
        raw = (specs.get(cat) or "").strip()
        if not raw and cat == "drivetrain" and has_belt_drive:
            raw = "Gates Carbon Drive 皮帶傳動"
        if not raw:
            continue
        brand = match_component_brand(cat, raw)
        if not brand:
            # Fall back to first meaningful alphanumeric token if a spec value exists
            tok = re.split(r"[\s/,(]+", raw)[0].strip()
            if tok and len(tok) >= 2 and not tok[0].isdigit():
                brand = tok
        if brand:
            comps[cat] = {
                "brand": brand,
                "model": raw[:80],
            }
    return comps


def compute_component_shares(bikes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute brand counts and adoption share percentages across complete bikes per component."""
    total_bikes = len(bikes)
    total_ebikes = sum(1 for b in bikes if b.get("is_ebike"))
    result: list[dict[str, Any]] = []

    for meta in COMPONENT_CATEGORIES_META:
        key = meta["key"]
        ebike_only = meta["ebike_only"] == "1"
        eligible_bikes = [b for b in bikes if (b.get("is_ebike") if ebike_only else True)]
        brand_to_bikes: dict[str, list[dict[str, str]]] = defaultdict(list)

        for b in eligible_bikes:
            comp = (b.get("components") or {}).get(key)
            if not comp or not comp.get("brand"):
                continue
            brand_to_bikes[comp["brand"]].append(
                {
                    "slug": b["slug"],
                    "model_name": b["model_name"],
                    "part_model": comp.get("model", ""),
                }
            )

        sample_count = sum(len(v) for v in brand_to_bikes.values())
        brands_ranked = []
        for brand_name, bike_refs in sorted(brand_to_bikes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            cnt = len(bike_refs)
            share_pct = round(cnt * 100.0 / sample_count, 1) if sample_count > 0 else 0.0
            brands_ranked.append(
                {
                    "brand": brand_name,
                    "count": cnt,
                    "share_pct": share_pct,
                    "bikes": bike_refs,
                }
            )

        result.append(
            {
                "key": key,
                "label_zh": meta["label_zh"],
                "short_zh": meta["short_zh"],
                "en": meta["en"],
                "ebike_only": ebike_only,
                "sample_count": sample_count,
                "eligible_count": total_ebikes if ebike_only else total_bikes,
                "brands": brands_ranked,
            }
        )

    return result
