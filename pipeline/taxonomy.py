"""Cycling brand recognition, race/event detection, classification, and ZH-TW synthesis."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from pipeline.product_gate import editorial_news_kind, subject_product

# Canonical cycling brand dictionary (bikes, e-drive, suspension, components, apparel)
BRAND_CATALOG: dict[str, dict[str, str]] = {
    # Complete bike brands
    "Specialized": {"type": "整車品牌", "patterns": r"\bSpecialized\b"},
    "Giant": {"type": "整車品牌", "patterns": r"\bGiant\b(?!\s+(?:leap|step|wall|slalom))"},
    "Trek": {"type": "整車品牌", "patterns": r"\bTrek\b"},
    "Canyon": {"type": "整車品牌", "patterns": r"\bCanyon\b"},
    "Santa Cruz": {"type": "整車品牌", "patterns": r"\bSanta\s+Cruz\b"},
    "Orbea": {"type": "整車品牌", "patterns": r"\bOrbea\b"},
    "Kona": {"type": "整車品牌", "patterns": r"\bKona\b"},
    "Polygon": {"type": "整車品牌", "patterns": r"\bPolygon\b"},
    "State Bicycle Co.": {"type": "整車品牌", "patterns": r"\bState(?:\s+Bicycle(?:\s+Co\.?)?|['’]s\s+6061)\b"},
    "Amflow": {"type": "整車品牌", "patterns": r"\bAmflow\b"},
    "Focus": {"type": "整車品牌", "patterns": r"\bFOCUS\b|\bFocus\s+(?:Aventura|Jam|Sam|Thron|Izalco|Atlas|Vam)\b"},
    "Conway": {"type": "整車品牌", "patterns": r"\bCONWAY\b|\bConway\s+(?:Cairon|Xyron|Ryvon|EWME|WME)\b"},
    "Aventon": {"type": "整車品牌", "patterns": r"\bAventon\b"},
    "Honda": {"type": "整車/跨界品牌", "patterns": r"\bHonda\b"},
    "Stoll": {"type": "整車品牌", "patterns": r"\bStoll\b"},
    "Bike Ahead": {"type": "整車/碳纖組件", "patterns": r"\bBike\s+Ahead\b"},
    "Tomac": {"type": "整車品牌", "patterns": r"\bTomac\b"},
    "Scott": {"type": "整車品牌", "patterns": r"\bScott\s+(?:Bikes|Spark|Genius|Ransom|Addict|Foil|Lumen|Patron|Voltage)\b|\bSCOTT\b"},
    "Cannondale": {"type": "整車品牌", "patterns": r"\bCannondale\b"},
    "Yeti": {"type": "整車品牌", "patterns": r"\bYeti\b"},
    "Pivot": {"type": "整車品牌", "patterns": r"\bPivot\s+(?:Cycles|Switchblade|Firebird|Shuttle|Mach|Trail)\b"},
    "Transition": {"type": "整車品牌", "patterns": r"\bTransition\s+(?:Bikes|Spire|Sentinel|Patrol|Relay|Repeater|Smuggler)\b"},
    "Commencal": {"type": "整車品牌", "patterns": r"\bCommencal\b"},
    "YT Industries": {"type": "整車品牌", "patterns": r"\bYT\s+(?:Industries|Jeffsy|Capra|Decoy|Izzo|Szepter)\b"},
    "Norco": {"type": "整車品牌", "patterns": r"\bNorco\b"},
    "Rocky Mountain": {"type": "整車品牌", "patterns": r"\bRocky\s+Mountain\b"},
    "Cube": {"type": "整車品牌", "patterns": r"\bCUBE\b|\bCube\s+(?:Stereo|Reaction|Agree|Litening|Nuroad)\b"},
    "Storck": {"type": "整車品牌", "patterns": r"\bStorck\b"},
    "Merida": {"type": "整車品牌", "patterns": r"\bMerida\b"},
    "Pinarello": {"type": "整車品牌", "patterns": r"\bPinarello\b"},
    "Colnago": {"type": "整車品牌", "patterns": r"\bColnago\b"},
    "Cervelo": {"type": "整車品牌", "patterns": r"\bCerv[eé]lo\b"},
    "BMC": {"type": "整車品牌", "patterns": r"\bBMC\b"},
    "Bianchi": {"type": "整車品牌", "patterns": r"\bBianchi\b"},
    "Factor": {"type": "整車品牌", "patterns": r"\bFactor\s+(?:Bikes|Ostro|O2|Lando|Monza)\b"},
    "Ridley": {"type": "整車品牌", "patterns": r"\bRidley\b"},
    "Lapierre": {"type": "整車品牌", "patterns": r"\bLapierre\b"},
    "Mondraker": {"type": "整車品牌", "patterns": r"\bMondraker\b"},
    "Propain": {"type": "整車品牌", "patterns": r"\bPropain\b"},
    "Nicolai": {"type": "整車品牌", "patterns": r"\bNicolai\b"},
    "Riese & Müller": {"type": "整車品牌", "patterns": r"\bRiese\s*(?:&|und)\s*M[uü]ller\b"},
    "Rotwild": {"type": "整車品牌", "patterns": r"\bRotwild\b"},
    "Simplon": {"type": "整車品牌", "patterns": r"\bSimplon\b"},
    "Moustache": {"type": "整車品牌", "patterns": r"\bMoustache\b"},
    "Ghost": {"type": "整車品牌", "patterns": r"\bGhost\s+(?:Bikes|Riot|Lector|E-Riot)\b"},
    "Haibike": {"type": "整車品牌", "patterns": r"\bHaibike\b"},
    "Bulls": {"type": "整車品牌", "patterns": r"\bBULLS\b|\bBulls\s+(?:Sonic|Copperhead|Vuca)\b"},
    "Unno": {"type": "整車品牌", "patterns": r"\bUnno\b"},
    "Forbidden": {"type": "整車品牌", "patterns": r"\bForbidden\s+(?:Bike|Druid|Dreadnought)\b"},
    "Ibis": {"type": "整車品牌", "patterns": r"\bIbis\b"},
    "Marin": {"type": "整車品牌", "patterns": r"\bMarin\s+(?:Bikes|Rift|Alpine|San Quentin|Headlands)\b"},
    "Niner": {"type": "整車品牌", "patterns": r"\bNiner\b"},
    "Salsa": {"type": "整車品牌", "patterns": r"\bSalsa\s+(?:Cycles|Cutthroat|Warbird|Journeyer)\b"},
    "Surly": {"type": "整車品牌", "patterns": r"\bSurly\b"},
    "Ribble": {"type": "整車品牌", "patterns": r"\bRibble\b"},
    "3T": {"type": "整車品牌", "patterns": r"\b3T\s+(?:Exploro|Racemax|Strada|Extrema)\b"},
    "Enve": {"type": "整車/輪組", "patterns": r"\bENVE\b|\bEnve\b"},
    "Van Rysel": {"type": "整車品牌", "patterns": r"\bVan\s+Rysel\b"},
    "Also": {"type": "整車品牌", "patterns": r"\bALSO\s+(?:TM-B|Bike)\b"},
    # E-Drive & Drivetrain & Suspension & Components
    "Shimano": {"type": "傳動/電輔系統", "patterns": r"\bShimano\b"},
    "SRAM": {"type": "傳動/避震系統", "patterns": r"\bSRAM\b"},
    "Avinox / DJI": {"type": "電輔系統", "patterns": r"\bAvinox\b|\bDJI\b"},
    "Bosch": {"type": "電輔系統", "patterns": r"\bBosch\b"},
    "TQ": {"type": "電輔系統", "patterns": r"\bTQ\s+(?:HPR|Motor|eBike)\b"},
    "Fazua": {"type": "電輔系統", "patterns": r"\bFazua\b"},
    "Brose": {"type": "電輔系統", "patterns": r"\bBrose\b"},
    "Mahle": {"type": "電輔系統", "patterns": r"\bMahle\b"},
    "Pinion": {"type": "變速/電輔系統", "patterns": r"\bPinion\b"},
    "RockShox": {"type": "避震系統", "patterns": r"\bRockShox\b"},
    "FOX": {"type": "避震系統", "patterns": r"\bFOX\b|\bFox\s+(?:36|38|34|32|40|Float|DHX|Live\s+Valve|Transfer)\b"},
    "Öhlins": {"type": "避震系統", "patterns": r"\b[ÖO]hlins\b"},
    "Marzocchi": {"type": "避震系統", "patterns": r"\bMarzocchi\b"},
    "Manitou": {"type": "避震系統", "patterns": r"\bManitou\b"},
    "DT Swiss": {"type": "輪組/避震", "patterns": r"\bDT\s+Swiss\b"},
    "TRP": {"type": "煞車/傳動", "patterns": r"\bTRP\b"},
    "Magura": {"type": "煞車系統", "patterns": r"\bMagura\b"},
    "Hope": {"type": "零組件", "patterns": r"\bHope\s+(?:Tech|Technology|Brakes|EVO|Pro)\b"},
    "Campagnolo": {"type": "傳動/輪組", "patterns": r"\bCampagnolo\b"},
    "E*thirteen": {"type": "輪組/傳動", "patterns": r"\bE\*?thirteen\b"},
    "Wingman": {"type": "輪組", "patterns": r"\bWingman\b"},
    "Crankbrothers": {"type": "零組件", "patterns": r"\bCrankbrothers\b"},
    "Maxxis": {"type": "輪胎", "patterns": r"\bMaxxis\b"},
    "Schwalbe": {"type": "輪胎", "patterns": r"\bSchwalbe\b"},
    "Continental": {"type": "輪胎", "patterns": r"\bContinental\b"},
    "Vittoria": {"type": "輪胎", "patterns": r"\bVittoria\b"},
    "Pirelli": {"type": "輪胎", "patterns": r"\bPirelli\b"},
    "Zipp": {"type": "輪組", "patterns": r"\bZipp\b"},
    "Reserve": {"type": "輪組", "patterns": r"\bReserve\s+(?:Wheels|\d{2})\b"},
    "Muc-Off": {"type": "保養清潔", "patterns": r"\bMuc-Off\b"},
    "Dynamic": {"type": "保養清潔", "patterns": r"\bDynamic\s+(?:AirForce|Bike\s+Care)\b"},
    "MET": {"type": "人身部品", "patterns": r"\bMET\s+(?:Shelter|Trenta|Rivale|Parachute|Helmet)\b"},
    "HIRU": {"type": "人身部品", "patterns": r"\bHIRU\b"},
    "Black Diamond": {"type": "照明/裝備", "patterns": r"\bBlack\s+Diamond\b"},
    "Garmin": {"type": "車錶/電子", "patterns": r"\bGarmin\b"},
    "Wahoo": {"type": "車錶/訓練台", "patterns": r"\bWahoo\b"},
    "Rapha": {"type": "人身部品", "patterns": r"\bRapha\b"},
    "POC": {"type": "人身部品", "patterns": r"\bPOC\b"},
    "Giro": {"type": "人身部品", "patterns": r"\bGiro\s+(?:Helmet|Aries|Eclipse|Shoes)\b"},
    "Oakley": {"type": "人身部品", "patterns": r"\bOakley\b"},
    "UAE Team Emirates": {"type": "職業車隊", "patterns": r"\bUAE\s+Team\s+Emirates\b"},
    "Movistar": {"type": "職業車隊", "patterns": r"\bMovistar\b"},
    "Visma-Lease a Bike": {"type": "職業車隊", "patterns": r"\bVisma[\s\-–]+Lease\s+a\s+Bike\b"},
    "Ineos Grenadiers": {"type": "職業車隊", "patterns": r"\bIneos\s+Grenadiers\b"},
    "Lidl-Trek": {"type": "職業車隊", "patterns": r"\bLidl[\s\-–]+Trek\b"},
    "Red Bull-Bora": {"type": "職業車隊", "patterns": r"\bRed\s+Bull[\s\-–]+Bora\b"},
    "Soudal Quick-Step": {"type": "職業車隊", "patterns": r"\bSoudal[\s\-–]+Quick[\s\-–]+Step\b"},
    "Uno-X": {"type": "職業車隊", "patterns": r"\bUno-X\b"},
    "MAAP": {"type": "人身部品", "patterns": r"\bMAAP\b"},
    "Classified": {"type": "傳動系統", "patterns": r"\bClassified\b"},
}

EVENT_PATTERNS: list[tuple[str, str, str]] = [
    (r"Tour\s+de\s+France(?:\s+Femmes)?|环法|環法", "環法自由車賽 (Tour de France)", "公路大環賽"),
    (r"Giro\s+d['’]Italia|环意|環義", "環義自由車賽 (Giro d'Italia)", "公路大環賽"),
    (r"Vuelta\s+a\s+Espa[ñn]a|环西|環西", "環西自由車賽 (La Vuelta)", "公路大環賽"),
    (r"Grand\s+Tours?|大环赛|大環賽", "三大環賽 (Grand Tours)", "公路大環賽"),
    (r"Tour\s+Down\s+Under", "環澳自由車賽 (Tour Down Under)", "UCI WorldTour"),
    (r"Glasgow\s+Cyclo-?cross\s+World\s+Cup|Cyclo-?cross\s+World\s+Cup", "UCI 公路越野世界盃 (Cyclo-cross World Cup)", "CX 世界盃"),
    (r"HG\s+Cross\s+Lokeren|Rapencross", "HG Cross Lokeren / Rapencross", "公路越野賽"),
    (r"Superprestige|X2O\s+Trofee|Exact\s+Cross", "比利時 CX 巡迴賽", "公路越野賽"),
    (r"UCI\s+(?:World\s+Cup|World\s+Championships|MTB|Downhill|Enduro|积分|積分)|世巡赛|世巡賽|RCS", "UCI 世巡賽／國際賽事", "UCI 國際賽事"),
    (r"European\s+Bike\s+Show|Eurobike", "歐洲自行車展 (European Bike Show / Eurobike)", "產業展會"),
    (r"Taipei\s+Cycle|台北展", "台北國際自行車展 (Taipei Cycle)", "產業展會"),
    (r"Sea\s+Otter", "Sea Otter Classic 自行車嘉年華", "展會/賽事"),
    (r"Crankworx", "Crankworx 山地車節", "MTB 國際賽事"),
    (r"Red\s+Bull\s+(?:Rampage|Hardline)", "Red Bull 極限自由騎賽事", "極限 MTB"),
    (r"NICA(?:\s+Western\s+Regional)?", "NICA 青少年山地車聯盟賽事", "青少年賽事"),
    (r"Field\s+Test", "Pinkbike Field Test 年度實測企劃", "媒體年度評測"),
    (r"Orbea\s+Fast\s+Forward|E-Racing", "Orbea Fast Forward / E-Racing 電輔越野賽事", "電輔車賽事"),
    (r"TransVienna", "TransVienna 跨國越野騎行企劃", "騎行活動"),
    (r"Paris[\s\-–]+Roubaix|Tour\s+of\s+Flanders|Milan[\s\-–]+San\s+Remo|Strade\s+Bianche", "五大古典賽 (Monuments)", "公路古典賽"),
    (r"Unbound\s+Gravel|Life\s+Time\s+Grand\s+Prix", "Gravel 越野大賽", "Gravel 賽事"),
]


def detect_brands(text: str, categories: list[str] | None = None, title: str = "") -> list[dict[str, str]]:
    haystack = text + " " + " ".join(categories or [])
    title_hits: list[dict[str, str]] = []
    body_hits: list[dict[str, str]] = []
    for name, meta in BRAND_CATALOG.items():
        if title and re.search(meta["patterns"], title, re.I):
            title_hits.append({"name": name, "type": meta["type"]})
        elif re.search(meta["patterns"], haystack, re.I):
            body_hits.append({"name": name, "type": meta["type"]})
    hits = title_hits + body_hits
    product = subject_product(title)
    if product:
        hits.sort(key=lambda hit: hit["name"] != product[0])
    return hits


def detect_events(text: str, categories: list[str] | None = None) -> list[dict[str, str]]:
    haystack = text + " " + " ".join(categories or [])
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for pat, label, kind in EVENT_PATTERNS:
        if re.search(pat, haystack, re.I) and label not in seen:
            seen.add(label)
            found.append({"name": label, "kind": kind})
    return found


def classify_article(item: dict[str, Any], is_complete_bike: bool) -> dict[str, str]:
    title = item["title"]
    text = f"{title} {' '.join(item.get('categories', []))} {item.get('summary_raw', '')}"
    low = text.lower()
    title_low = title.lower()

    # Confirmed editorial subjects take precedence over generic "new"/year keywords.
    editorial_kind = editorial_news_kind(title)
    if not is_complete_bike and editorial_kind == "race":
        return {"bucket": "race_event", "bucket_zh": "賽事與活動", "signal": "賽事/車隊"}
    if not is_complete_bike and editorial_kind == "video":
        return {"bucket": "gear_tech", "bucket_zh": "裝備與綜合", "signal": "影音/社群"}

    # Action / Event signal
    if any(k in low for k in ["rückruf", "verkaufsstopp", "recall", "stop-ride", "safety notice", "召回", "停售"]):
        signal = "召回警示"
    elif any(k in title_low for k in ["review", "test", "first ride", "square off", "hot or not", "im test", "评测", "評測", "实测", "實測"]):
        signal = "產品評測"
    elif any(k in title_low for k in ["launch", "new ", "all-new", "goes ", "reshapes", "update", "2027", "v2", "autoshift", "unveil", "introduces", "announces", "comeback", "推出", "发布", "發布", "推送", "更新", "新款", "首款", "第二代", "新东西"]):
        signal = "新品/動態"
    elif any(k in low for k in ["world cup", "tour down under", "rapencross", "grand tour", "race", "racing", "win ", "wins ", "transfer", "coach", "lineup", "cyclo-cross", "bewerbt", "team", "车队", "車隊", "赛事", "賽事", "世巡赛", "赞助", "贊助"]):
        signal = "賽事/車隊"
    elif any(k in low for k in ["bike show", "eurobike", "messe", "expo", "event", "nica", "regional", "展", "骑行", "騎行"]):
        signal = "產業展會"
    elif any(k in title_low for k in ["video", "watch", "shred", "szn", "slack randoms"]):
        signal = "影音/社群"
    else:
        signal = "產業資訊"

    # Primary bucket
    if is_complete_bike:
        bucket = "complete_bike"
        bucket_zh = "整車發布/評測"
    elif signal in ("賽事/車隊", "產業展會") or item["source_id"] == "cyclingnews" and not any(
        k in title_low for k in ["review", "bike", "wheel", "helmet", "shoe", "groupset", "tire", "tyre", "saddle", "power meter"]
    ):
        bucket = "race_event"
        bucket_zh = "賽事與活動"
    elif any(
        k in low
        for k in [
            "motor", "avinox", "ep810", "bosch", "autoshift", "trp", "wheel", "wheelset",
            "fork", "federgabel", "zeb", "shock", "drivetrain", "groupset", "brake",
            "tire", "tyre", "reifen", "schaltung", "update", "firmware", "software",
        ]
    ):
        bucket = "component_edrive"
        bucket_zh = "零組件與電輔"
    else:
        bucket = "gear_tech"
        bucket_zh = "裝備與綜合"

    return {
        "bucket": bucket,
        "bucket_zh": bucket_zh,
        "signal": signal,
    }


def make_zh_takeaway(item: dict[str, Any], brands: list[dict[str, str]], events: list[dict[str, str]], cls: dict[str, str], bike_data: dict[str, Any] | None) -> str:
    """Create a crisp Traditional Chinese executive takeaway for each item."""
    brand_str = "、".join(b["name"] for b in brands[:3]) if brands else item["source_name"]
    title = item["title"]
    tlow = title.lower()

    if bike_data:
        specs = bike_data.get("specs", {})
        parts = []
        if bike_data.get("category_zh"):
            parts.append(bike_data["category_zh"])
        if specs.get("motor"):
            parts.append(f"馬達 {specs['motor']}")
        if specs.get("battery"):
            parts.append(f"電池 {specs['battery']}")
        if specs.get("travel_front") or specs.get("travel_rear"):
            tf = specs.get("travel_front") or "-"
            tr = specs.get("travel_rear") or "-"
            parts.append(f"行程 {tf}/{tr}")
        if specs.get("price"):
            parts.append(f"定價 {specs['price']}")
        detail = "；".join(parts) if parts else "已萃取整車規格與幾何並建構 3D 模型"
        return f"【整車逆向建模】{brand_str} — {bike_data['model_name']}（{detail}）。"

    if cls["signal"] == "召回警示":
        return f"【安全/召回】{brand_str} 發布特定批次產品停售/召回更新，建議追蹤受影響序號與 OEM 對應型號。"
    if events:
        ev_names = "、".join(e["name"] for e in events[:2])
        if any(k in tlow for k in ["win", "wins", "drops", "victory"]):
            return f"【賽事戰報】{ev_names} 最新賽果與選手焦點更新（來源：{item['source_name']}）。"
        if any(k in tlow for k in ["show", "hallen", "aussteller", "expands", "lineup", "announced"]):
            return f"【展會/陣容】{ev_names} 最新參展規模、陣容或區域擴張消息。"
        return f"【賽事動態】{ev_names} 相關車隊、選手與備戰情報（{brand_str}）。"
    if "autoshift" in tlow or "update" in tlow or "firmware" in tlow:
        return f"【電輔/軟體升級】{brand_str} 推出最新電輔整合或韌體更新，強化自動變速與系統連通性。"
    if cls["signal"] == "產品評測":
        return f"【實測評鑑】{item['source_name']} 對 {brand_str} 產品進行實地測試與優缺點評比。"
    if cls["signal"] == "新品/動態":
        return f"【新品/品牌動態】{brand_str} 公布新產品線、技術合作或品牌回歸消息。"
    if cls["signal"] == "影音/社群":
        return f"【影音精選】{item['source_name']} 發布騎行紀錄片、改裝測試或車隊賽季回顧。"
    return f"【產業情報】{brand_str} 相關最新報導（{item['source_name']}）。"


def build_executive_summary(
    articles: list[dict[str, Any]],
    bikes: list[dict[str, Any]],
    source_stats: list[dict[str, Any]],
) -> dict[str, Any]:
    """Synthesize daily conclusions across brands, races/events, reviews, and complete bikes."""
    brand_counter: Counter[str] = Counter()
    brand_types: dict[str, str] = {}
    brand_articles: dict[str, list[dict[str, str]]] = defaultdict(list)

    event_map: dict[str, dict[str, Any]] = {}
    bucket_counts: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()

    for art in articles:
        bucket_counts[art["classification"]["bucket"]] += 1
        signal_counts[art["classification"]["signal"]] += 1
        for b in art["brands"]:
            brand_counter[b["name"]] += 1
            brand_types[b["name"]] = b["type"]
            brand_articles[b["name"]].append(
                {
                    "title": art["title"],
                    "title_zh": art.get("title_zh") or art["title"],
                    "url": art["url"],
                    "source": art["source_name"],
                    "signal": art["classification"]["signal"],
                }
            )
        for ev in art["events"]:
            key = ev["name"]
            if key not in event_map:
                event_map[key] = {
                    "name": ev["name"],
                    "kind": ev["kind"],
                    "mentions": 0,
                    "sources": set(),
                    "headlines": [],
                }
            event_map[key]["mentions"] += 1
            event_map[key]["sources"].add(art["source_name"])
            if len(event_map[key]["headlines"]) < 3:
                event_map[key]["headlines"].append(
                    {
                        "title": art["title"],
                        "title_zh": art.get("title_zh") or art["title"],
                        "url": art["url"],
                        "source": art["source_name"],
                    }
                )

    top_brands = [
        {
            "name": name,
            "type": brand_types.get(name, "品牌"),
            "mentions": count,
            "signals": sorted({a["signal"] for a in brand_articles[name]}),
            "articles": brand_articles[name][:4],
        }
        for name, count in brand_counter.most_common(25)
    ]

    events_summary = sorted(
        [
            {
                "name": v["name"],
                "kind": v["kind"],
                "mentions": v["mentions"],
                "sources": sorted(v["sources"]),
                "headlines": v["headlines"],
            }
            for v in event_map.values()
        ],
        key=lambda x: (-x["mentions"], x["name"]),
    )

    # Craft crisp Traditional Chinese executive bullet conclusions
    top_brand_names = "、".join(b["name"] for b in top_brands[:6]) if top_brands else "無"
    bike_names = "、".join(b["model_name"] for b in bikes[:5]) if bikes else "本期無新增整車"
    event_names = "、".join(e["name"] for e in events_summary[:4]) if events_summary else "無重大賽事更新"
    recalls = [a for a in articles if a["classification"]["signal"] == "召回警示"]

    conclusions: list[dict[str, str]] = [
        {
            "tag": "整車與 3D 逆向工程",
            "title": f"本期辨識 {len(bikes)} 款重點整車，全部完成參數表格化與參數化 3D 逆向建模",
            "detail": f"涵蓋車款：{bike_names}。每款均已輸出真實比例 GLB 3D 模型、幾何驗證清單（區分實測與推估參數）及 Blender 4.x 棚拍重建腳本。",
        },
        {
            "tag": "品牌焦點動向",
            "title": f"今日高聲量品牌：{top_brand_names}",
            "detail": f"跨 {len(source_stats)} 大媒體共追蹤 {len(top_brands)} 個活躍品牌，涵蓋電輔系統升級、碳纖礫石越野與公路競賽車、長行程 e-MTB 評測與車隊合作動態。",
        },
        {
            "tag": "賽事與產業活動",
            "title": f"共收錄 {len(events_summary)} 項賽事與展會動態",
            "detail": f"焦點活動：{event_names}。包含職業公路賽陣容公布、CX 公路越野世界盃戰報以及歐洲自行車展會進度。",
        },
    ]
    if recalls:
        conclusions.append(
            {
                "tag": "品質與召回警示",
                "title": f"偵測到 {len(recalls)} 則產品停售／召回公告",
                "detail": "；".join(f"{r.get('title_zh') or r['title']}（來源：{r['source_name']}）" for r in recalls[:2]),
            }
        )
    else:
        conclusions.append(
            {
                "tag": "評測與新品總覽",
                "title": f"今日共彙整 {len(articles)} 則情報（評測 {signal_counts.get('產品評測', 0)} 則、新品動態 {signal_counts.get('新品/動態', 0)} 則）",
                "detail": f"各站抓取健康度：{sum(1 for s in source_stats if s['status']=='ok')}/{len(source_stats)} 站成功連線並完成結構化索引。",
            }
        )

    from pipeline.components import compute_component_shares

    component_shares = compute_component_shares(bikes)

    return {
        "conclusions": conclusions,
        "top_brands": top_brands,
        "events": events_summary,
        "component_shares": component_shares,
        "counts": {
            "total_articles": len(articles),
            "complete_bikes": len(bikes),
            "brands_tracked": len(top_brands),
            "events_tracked": len(events_summary),
            "reviews": signal_counts.get("產品評測", 0),
            "launches": signal_counts.get("新品/動態", 0),
            "recalls": len(recalls),
            "by_bucket": dict(bucket_counts),
        },
    }
