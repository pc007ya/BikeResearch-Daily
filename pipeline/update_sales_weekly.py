"""Weekly Friday Global Bicycle Sales Data Crawler & Updater.

Runs every Friday at 08:00 CST (00:00 UTC) via GitHub Actions (.github/workflows/weekly-sales-crawl.yml):
1. Rebuilds and mathematically validates the 15-country (2023-2025) official sales baseline.
2. Actively crawls live trade & association RSS feeds (Bike Europe, BRAIN, Cycling Industry News,
   and targeted Google News Europe/Americas/APAC association queries) for the latest official
   bicycle & e-bike market statistics, export updates, and association releases.
3. Translates bulletins into Traditional Chinese (zh-TW), extracts numeric highlights, tags
   region/country/category, and writes updated docs/data/sales_market.json.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from pipeline.sales_data import build_sales_dataset
from pipeline.translator import ZhTranslator

CST = timezone(timedelta(hours=8))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SALES_FEEDS: list[dict[str, str]] = [
    {
        "id": "bike_europe_gnews",
        "name": "Bike Europe（歐洲產業貿易誌）",
        "region_hint": "europe",
        "url": (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote("site:bike-eu.com (sales OR market OR e-bike OR exports OR ZIV OR CONEBI OR RAI OR AMBE OR ANCMA OR Traxio)")
            + "&hl=en-US&gl=US&ceid=US:en"
        ),
    },
    {
        "id": "brain_rss",
        "name": "Bicycle Retailer (BRAIN)",
        "region_hint": "americas",
        "url": "https://www.bicycleretailer.com/rss.xml",
    },
    {
        "id": "brain_sales_gnews",
        "name": "北美市場與進口統計 (BRAIN / PeopleForBikes)",
        "region_hint": "americas",
        "url": (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote('("Bicycle Retailer" OR PeopleForBikes OR Circana) (bicycle OR e-bike) (sales OR imports OR market) when:180d')
            + "&hl=en-US&gl=US&ceid=US:en"
        ),
    },
    {
        "id": "eu_assoc_gnews",
        "name": "歐洲各國公會銷售報告 (ZIV/USC/RAI/AMBE/ANCMA/Traxio/VSSÖ)",
        "region_hint": "europe",
        "url": (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(
                '(ZIV OR CONEBI OR "RAI Vereniging" OR AMBE OR ANCMA OR Traxio OR Velosuisse OR "Bicycle Association") '
                '(bicycle OR e-bike) (sales OR market OR units) when:180d'
            )
            + "&hl=en-US&gl=US&ceid=US:en"
        ),
    },
    {
        "id": "apac_sales_gnews",
        "name": "亞太市場與台灣出口快訊 (TBA/JBPI/BIA/CBA)",
        "region_hint": "apac",
        "url": (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(
                '("Taiwan bicycle" OR "Taiwan e-bike" OR "Japan e-bike" OR "Australia e-bike" OR "China bicycle") '
                '(sales OR exports OR imports OR market) when:180d'
            )
            + "&hl=en-US&gl=US&ceid=US:en"
        ),
    },
]

SPAM_RE = re.compile(
    r"\b(203[0-9]|forecast\s+to\s+203|tourism\s+market|market\s+size,?\s*share|cagr|"
    r"global\s+.*?\s+market\s+report\s+203|sales\s+manager|area\s+sales|account\s+manager|"
    r"m/f/d|m/w/d|vacancy|we\s+are\s+hiring|job\s+opening)\b",
    re.I,
)

SALES_KEYWORDS = re.compile(
    r"\b(sales?|market|units?|export|exports|import|imports|revenue|turnover|growth|decline|drop|surge|"
    r"rebound|share|penetration|asp|average\s+price|statistics?|figures?|report|data|registrations?|"
    r"profit|earnings|quarter|q[1-4]|"
    r"ziv|conebi|eci|usc|rai|bovag|ancma|ambe|traxio|vssoe|vssö|velosuisse|peopleforbikes|circana|jbpi|tba|bia)\b",
    re.I,
)

COUNTRY_PATTERNS: list[tuple[str, str, str, re.Pattern[str]]] = [
    ("DE", "德國", "europe", re.compile(r"\b(germany|german|ziv|zweirad|bike24)\b", re.I)),
    ("FR", "法國", "europe", re.compile(r"\b(france|french|union\s+sport|usc)\b", re.I)),
    ("GB", "英國", "europe", re.compile(r"\b(uk|u\.k\.|britain|british|bicycle\s+association)\b", re.I)),
    ("IT", "義大利", "europe", re.compile(r"\b(italy|italian|ancma)\b", re.I)),
    ("ES", "西班牙", "europe", re.compile(r"\b(spain|spanish|ambe)\b", re.I)),
    ("NL", "荷蘭", "europe", re.compile(r"\b(netherlands|dutch|rai\s+vereniging|bovag|accell|pon)\b", re.I)),
    ("BE", "比利時", "europe", re.compile(r"\b(belgium|belgian|traxio)\b", re.I)),
    ("AT", "奧地利", "europe", re.compile(r"\b(austria|austrian|vss[öo]|pierer)\b", re.I)),
    ("CH", "瑞士", "europe", re.compile(r"\b(switzerland|swiss|velosuisse)\b", re.I)),
    ("US", "美國", "americas", re.compile(r"\b(u\.s\.|us\s+bicycle|united\s+states|america|american|peopleforbikes|circana|fox\s+factory|trek|sram)\b", re.I)),
    ("CA", "加拿大", "americas", re.compile(r"\b(canada|canadian|statcan)\b", re.I)),
    ("TW", "台灣", "apac", re.compile(r"\b(taiwan|taiwanese|tba|giant\s+(?:group|manufacturing|q[1-4]|operating|sales)|merida)\b", re.I)),
    ("JP", "日本", "apac", re.compile(r"\b(japan|japanese|jbpi|shimano|yen)\b", re.I)),
    ("AU", "澳洲", "apac", re.compile(r"\b(australia|australian|nrma)\b", re.I)),
    ("CN", "中國", "apac", re.compile(r"\b(china|chinese|dji|amflow)\b", re.I)),
]

REGION_FALLBACK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("europe", re.compile(r"\b(europe|european|eu27|conebi|eurobike)\b", re.I)),
    ("americas", re.compile(r"\b(north\s+america|americas|tariff)\b", re.I)),
    ("apac", re.compile(r"\b(asia|apac|pacific)\b", re.I)),
]

CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ebike", re.compile(r"\b(e-?bikes?|pedelec|electric\s+bike|e-?mtb|e-?cargo)\b", re.I)),
    ("mtb", re.compile(r"\b(mtb|mountain\s+bike|e-?mtb)\b", re.I)),
    ("road", re.compile(r"\b(road\s+bike|gravel)\b", re.I)),
    ("city", re.compile(r"\b(city\s+bike|commuter|urban|trekking|cargo)\b", re.I)),
]

METRIC_RE = re.compile(
    r"(?:€|\$|US\$|A\$|£)\s?\d+(?:[.,]\d+)?\s?(?:billion|million|bn|m|k|B|M)?|"
    r"[+-]?\d+(?:\.\d+)?%|"
    r"\b\d+(?:[.,]\d+)?\s?(?:million|thousand)\s+(?:bikes?|e-?bikes?|units?)\b",
    re.I,
)


def compute_next_friday_cst(now_cst: datetime) -> str:
    # weekday(): Monday=0 ... Friday=4 ... Sunday=6
    days_ahead = (4 - now_cst.weekday()) % 7
    target = now_cst.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if target <= now_cst:
        target += timedelta(days=7)
    return target.strftime("%Y-%m-%d 08:00 CST")


def strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_pubdate(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CST).strftime("%Y-%m-%d")
    except Exception:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
        return m.group(1) if m else ""


def fetch_rss_items(feed: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    try:
        resp = requests.get(
            feed["url"],
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
            timeout=14,
        )
        if resp.status_code != 200:
            return f"http_{resp.status_code}", []
        root = ET.fromstring(resp.content)
        items: list[dict[str, Any]] = []
        # Support both RSS <item> and Atom <entry>
        for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = (node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link = (node.findtext("link") or "").strip()
            if not link:
                link_el = node.find("{http://www.w3.org/2005/Atom}link")
                if link_el is not None:
                    link = (link_el.attrib.get("href") or "").strip()
            desc = strip_html(
                node.findtext("description")
                or node.findtext("{http://www.w3.org/2005/Atom}summary")
                or ""
            )
            pub = (
                node.findtext("pubDate")
                or node.findtext("{http://www.w3.org/2005/Atom}updated")
                or node.findtext("{http://www.w3.org/2005/Atom}published")
                or ""
            )
            src_el = node.find("source")
            src_name = (src_el.text.strip() if src_el is not None and src_el.text else feed["name"])
            if title and link:
                # Strip trailing " - Publisher" from Google News titles
                clean_title = re.sub(r"\s+-\s+[^-]{2,45}$", "", title).strip() if "gnews" in feed["id"] else title
                items.append({
                    "title": clean_title,
                    "url": link,
                    "summary": desc[:260],
                    "date": parse_pubdate(pub),
                    "source_name": src_name,
                    "feed_id": feed["id"],
                    "region_hint": feed["region_hint"],
                })
        return "ok", items
    except Exception as exc:
        return f"error:{type(exc).__name__}", []


def classify_bulletin(item: dict[str, Any]) -> dict[str, Any] | None:
    blob = f"{item['title']} {item['summary']}"
    if SPAM_RE.search(blob):
        return None
    matches = SALES_KEYWORDS.findall(blob)
    if not matches:
        return None
    # Require cycling context so generic financial stories don't leak in
    if not re.search(r"\b(bike|bikes|bicycle|bicycles|cycling|e-?bike|pedelec|zweirad|velo|ziv|conebi|ancma|ambe|traxio|peopleforbikes|jbpi|tba)\b", blob, re.I):
        return None

    iso2 = None
    country_zh = None
    region = None
    for code, name_zh, reg, pat in COUNTRY_PATTERNS:
        if pat.search(blob):
            iso2 = code
            country_zh = name_zh
            region = reg
            break

    if not region:
        for reg, pat in REGION_FALLBACK_PATTERNS:
            if pat.search(blob):
                region = reg
                break
    if not region:
        region = item.get("region_hint") or "global"

    cats = [cid for cid, pat in CATEGORY_PATTERNS if pat.search(blob)]
    metrics = []
    for m in METRIC_RE.findall(item["title"] + " " + item["summary"][:140]):
        s = m.strip()
        if s and s not in metrics:
            metrics.append(s)
        if len(metrics) >= 3:
            break

    score = len(set(m.lower() for m in matches)) * 2 + (3 if iso2 else 0) + (2 if metrics else 0)
    return {
        "title": item["title"],
        "url": item["url"],
        "date": item["date"],
        "source_name": item["source_name"],
        "region": region,
        "country_iso2": iso2,
        "country_zh": country_zh,
        "categories": cats,
        "metrics": metrics,
        "score": score,
    }


def run_weekly_sales_update(docs_dir: Path, max_bulletins: int = 15) -> dict[str, Any]:
    now_cst = datetime.now(CST)
    out_path = docs_dir / "data" / "sales_market.json"

    # Load any prior bulletins so offline runs never wipe existing bulletins
    prev_bulletins: list[dict[str, Any]] = []
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            prev_bulletins = prev.get("meta", {}).get("weekly_sync", {}).get("latest_bulletins", []) or []
        except Exception:
            prev_bulletins = []

    dataset = build_sales_dataset()
    dataset["meta"]["updated_at"] = now_cst.strftime("%Y-%m-%d")

    sources_status: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for feed in SALES_FEEDS:
        status, raw_items = fetch_rss_items(feed)
        matched = 0
        for it in raw_items[:30]:
            classified = classify_bulletin(it)
            if classified:
                candidates.append(classified)
                matched += 1
        sources_status.append({
            "id": feed["id"],
            "name": feed["name"],
            "status": status,
            "fetched": len(raw_items),
            "matched": matched,
        })

    # Deduplicate by normalized title
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    candidates.sort(key=lambda x: (x["date"] or "0000-00-00", x["score"]), reverse=True)
    for c in candidates:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", c["title"].lower())[:64]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(c)

    selected = unique[:max_bulletins]

    if selected:
        translator = ZhTranslator(docs_dir / "data" / "zh_cache.json")
        for b in selected:
            b["title_zh"] = translator.translate(b["title"], src_lang="auto")
            b.pop("score", None)
        translator.save()
        final_bulletins = selected
    else:
        final_bulletins = prev_bulletins

    dataset["meta"]["weekly_sync"] = {
        "schedule_cron_utc": "0 0 * * 5",
        "schedule_zh": "每週五 08:00 CST 自動撈取更新",
        "last_synced_at_cst": now_cst.strftime("%Y-%m-%d %H:%M CST"),
        "next_friday_cst": compute_next_friday_cst(now_cst),
        "sources_status": sources_status,
        "live_matched_count": len(unique),
        "latest_bulletins": final_bulletins,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ok_feeds = sum(1 for s in sources_status if s["status"] == "ok")
    print(
        f"[weekly-sales] Updated {out_path} at {dataset['meta']['weekly_sync']['last_synced_at_cst']} "
        f"(feeds ok: {ok_feeds}/{len(sources_status)}, bulletins: {len(final_bulletins)})"
    )
    return dataset


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly Friday global bicycle sales crawler & dataset updater")
    ap.add_argument("--docs-dir", type=Path, default=Path("docs"))
    ap.add_argument("--max-bulletins", type=int, default=15)
    args = ap.parse_args()
    run_weekly_sales_update(args.docs_dir, max_bulletins=args.max_bulletins)


if __name__ == "__main__":
    main()
