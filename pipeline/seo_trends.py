"""Daily Global Cycling SEO Keyword Trends Collector (7-day & 30-day Analysis).

Collects daily localized SEO & search interest signals across 9 key markets
(US, CA, DE, GB, FR, NL, TW, JP, AU) and 10 cycling categories:
  bicycle, race, ebike, mtb, road, city, commuter, cargo, parts, events.

Data sources (100% live, zero paid API keys, resilient in GitHub Actions):
  1. Google Autocomplete / Suggest API (localized by country `gl` & language `hl`)
     -> exact live user search queries & long-tail SEO keywords per market.
  2. Google News localized RSS (`when:30d`, `gl`, `hl`, `ceid`)
     -> exact 7-day, prior-7-day, 30-day & 30-day daily topic velocity.
  3. Wikimedia Pageviews REST API (exact daily user lookup counts over 30 days
     across en / de / fr / nl / ja / zh Wikipedias).

Outputs docs/data/seo_trends.json with day-over-day NEW keyword diffing.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import email.utils
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from pipeline.translator import ZhTranslator

CST = timezone(timedelta(hours=8))

USER_AGENT = (
    "BikeResearchDaily/1.2 (+https://github.com/pc007ya/BikeResearch-Daily; "
    "cycling market & SEO intelligence)"
)

SEO_REGIONS: list[dict[str, str]] = [
    {"id": "europe", "name_zh": "歐洲", "color": "#1d634f"},
    {"id": "americas", "name_zh": "美洲", "color": "#2b5b84"},
    {"id": "apac", "name_zh": "亞太", "color": "#c84b28"},
]

SEO_COUNTRIES: list[dict[str, str]] = [
    {"iso2": "DE", "name_zh": "德國", "region": "europe", "gl": "de", "hl": "de", "ceid": "DE:de", "wiki_lang": "de", "lang_label": "德語"},
    {"iso2": "GB", "name_zh": "英國", "region": "europe", "gl": "gb", "hl": "en-GB", "ceid": "GB:en", "wiki_lang": "en", "lang_label": "英語"},
    {"iso2": "FR", "name_zh": "法國", "region": "europe", "gl": "fr", "hl": "fr", "ceid": "FR:fr", "wiki_lang": "fr", "lang_label": "法語"},
    {"iso2": "NL", "name_zh": "荷蘭", "region": "europe", "gl": "nl", "hl": "nl", "ceid": "NL:nl", "wiki_lang": "nl", "lang_label": "荷語"},
    {"iso2": "US", "name_zh": "美國", "region": "americas", "gl": "us", "hl": "en-US", "ceid": "US:en", "wiki_lang": "en", "lang_label": "英語"},
    {"iso2": "CA", "name_zh": "加拿大", "region": "americas", "gl": "ca", "hl": "en-CA", "ceid": "CA:en", "wiki_lang": "en", "lang_label": "英語"},
    {"iso2": "TW", "name_zh": "台灣", "region": "apac", "gl": "tw", "hl": "zh-TW", "ceid": "TW:zh-Hant", "wiki_lang": "zh", "lang_label": "繁中"},
    {"iso2": "JP", "name_zh": "日本", "region": "apac", "gl": "jp", "hl": "ja", "ceid": "JP:ja", "wiki_lang": "ja", "lang_label": "日語"},
    {"iso2": "AU", "name_zh": "澳洲", "region": "apac", "gl": "au", "hl": "en-AU", "ceid": "AU:en", "wiki_lang": "en", "lang_label": "英語"},
]

SEO_CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "bicycle",
        "name_zh": "自行車（綜合）",
        "short_zh": "自行車",
        "icon": "🚲",
        "color": "#171715",
        "queries": {
            "en": "bicycle",
            "de": "Fahrrad",
            "fr": "vélo",
            "nl": "fiets",
            "ja": "自転車",
            "zh": "自行車",
        },
        "news_queries": {
            "en": "(bicycle OR cycling) market OR trends",
            "de": "Fahrrad Trends OR Markt",
            "fr": "vélo marché OR tendances",
            "nl": "fiets markt OR trends",
            "ja": "自転車 市場 OR 人気",
            "zh": "自行車 OR 腳踏車 趨勢",
        },
        "wiki": {
            "en": "Bicycle",
            "de": "Fahrrad",
            "fr": "Bicyclette",
            "nl": "Fiets",
            "ja": "自転車",
            "zh": "自行车",
        },
    },
    {
        "id": "race",
        "name_zh": "自行車賽事",
        "short_zh": "自行車賽事",
        "icon": "🏆",
        "color": "#b42318",
        "queries": {
            "en": "cycling race",
            "de": "Radsport Rennen",
            "fr": "course cycliste",
            "nl": "wielrennen",
            "ja": "自転車レース",
            "zh": "自行車賽事",
        },
        "news_queries": {
            "en": '("Tour de France" OR UCI OR "cycling race" OR cyclocross OR Giro)',
            "de": "(Radsport OR Radrennen OR UCI OR Cyclocross)",
            "fr": "(cyclisme OR \"Tour de France\" OR UCI OR \"course cycliste\")",
            "nl": "(wielrennen OR veldrijden OR UCI)",
            "ja": "(自転車レース OR ツール・ド・フランス OR UCI OR ロードレース)",
            "zh": "(自行車賽 OR 環法 OR 單車賽事 OR 環台賽)",
        },
        "wiki": {
            "en": "Cycle_sport",
            "de": "Radsport",
            "fr": "Cyclisme",
            "nl": "Wielersport",
            "ja": "自転車競技",
            "zh": "自行車運動",
        },
    },
    {
        "id": "ebike",
        "name_zh": "電動車 (e-Bike)",
        "short_zh": "電動車",
        "icon": "⚡",
        "color": "#c84b28",
        "queries": {
            "en": "e-bike",
            "de": "E-Bike",
            "fr": "vélo électrique",
            "nl": "elektrische fiets",
            "ja": "電動アシスト自転車",
            "zh": "電動自行車",
        },
        "news_queries": {
            "en": '("e-bike" OR "electric bike" OR ebike)',
            "de": '("E-Bike" OR Pedelec)',
            "fr": '("vélo électrique" OR VAE)',
            "nl": '("elektrische fiets" OR "e-bike" OR fatbike)',
            "ja": "(電動アシスト自転車 OR e-bike)",
            "zh": "(電輔車 OR 電動輔助自行車 OR 電動自行車)",
        },
        "wiki": {
            "en": "Electric_bicycle",
            "de": "E-Bike",
            "fr": "Vélo_à_assistance_électrique",
            "nl": "Elektrische_fiets",
            "ja": "電動アシスト自転車",
            "zh": "電動自行車",
        },
    },
    {
        "id": "mtb",
        "name_zh": "登山車 (MTB)",
        "short_zh": "登山車",
        "icon": "🏔️",
        "color": "#1d634f",
        "queries": {
            "en": "mountain bike",
            "de": "Mountainbike",
            "fr": "VTT",
            "nl": "mountainbike",
            "ja": "マウンテンバイク",
            "zh": "登山車",
        },
        "news_queries": {
            "en": '("mountain bike" OR MTB OR "e-MTB")',
            "de": "(Mountainbike OR E-MTB OR MTB)",
            "fr": "(VTT OR VTTAE)",
            "nl": "(mountainbike OR MTB)",
            "ja": "(マウンテンバイク OR MTB)",
            "zh": "(登山車 OR 越野單車 OR MTB)",
        },
        "wiki": {
            "en": "Mountain_bike",
            "de": "Mountainbike",
            "fr": "Vélo_tout-terrain",
            "nl": "Mountainbike",
            "ja": "マウンテンバイク",
            "zh": "山地自行車",
        },
    },
    {
        "id": "road",
        "name_zh": "公路車 (Road & Gravel)",
        "short_zh": "公路車",
        "icon": "🚴",
        "color": "#2b5b84",
        "queries": {
            "en": "road bike",
            "de": "Rennrad",
            "fr": "vélo de route",
            "nl": "racefiets",
            "ja": "ロードバイク",
            "zh": "公路車",
        },
        "news_queries": {
            "en": '("road bike" OR "gravel bike")',
            "de": "(Rennrad OR Gravelbike)",
            "fr": '("vélo de route" OR "vélo gravel")',
            "nl": "(racefiets OR gravelfiets)",
            "ja": "(ロードバイク OR グラベルバイク)",
            "zh": "(公路車 OR 礫石車)",
        },
        "wiki": {
            "en": "Road_bicycle",
            "de": "Rennrad",
            "fr": "Vélo_de_route",
            "nl": "Racefiets",
            "ja": "ロードバイク",
            "zh": "公路自行車",
        },
    },
    {
        "id": "city",
        "name_zh": "城市車 (City Bike)",
        "short_zh": "城市車",
        "icon": "🏙️",
        "color": "#b87a1e",
        "queries": {
            "en": "city bike",
            "de": "Citybike",
            "fr": "vélo de ville",
            "nl": "stadsfiets",
            "ja": "シティサイクル",
            "zh": "城市單車",
        },
        "news_queries": {
            "en": '("city bike" OR "urban bike" OR "bike share")',
            "de": "(Citybike OR Stadtrad OR Trekkingrad)",
            "fr": '("vélo de ville" OR "vélo urbain")',
            "nl": "(stadsfiets OR deelfiets)",
            "ja": "(シティサイクル OR クロスバイク OR シェアサイクル)",
            "zh": "(城市車 OR 都會自行車 OR YouBike)",
        },
        "wiki": {
            "en": "Utility_bicycle",
            "de": "Stadtrad",
            "fr": "Vélo_de_ville",
            "nl": "Stadsfiets",
            "ja": "軽快車",
            "zh": "城市自行車",
        },
    },
    {
        "id": "commuter",
        "name_zh": "通勤車 (Commuter)",
        "short_zh": "通勤車",
        "icon": "💼",
        "color": "#6e4b8a",
        "queries": {
            "en": "commuter bike",
            "de": "Pendlerfahrrad",
            "fr": "vélotaf",
            "nl": "woon-werk fiets",
            "ja": "通勤 自転車",
            "zh": "通勤腳踏車",
        },
        "news_queries": {
            "en": '("commuter bike" OR "bike commuting" OR "cycle to work")',
            "de": "(Pendler Fahrrad OR Dienstrad OR JobRad)",
            "fr": "(vélotaf OR \"vélo trajet travail\")",
            "nl": '("woon-werk" fiets OR fietsplan)',
            "ja": "(自転車通勤 OR 通勤 クロスバイク)",
            "zh": "(單車通勤 OR 通勤自行車 OR 通勤腳踏車)",
        },
        "wiki": {
            "en": "Bicycle_commuting",
            "de": "Fahrradverkehr",
            "fr": "Vélotaf",
            "nl": "Forensenfiets",
            "ja": "自転車通勤",
            "zh": "自行車通勤",
        },
    },
    {
        "id": "cargo",
        "name_zh": "貨物車 (Cargo Bike)",
        "short_zh": "貨物車",
        "icon": "📦",
        "color": "#8c5a3c",
        "queries": {
            "en": "cargo bike",
            "de": "Lastenrad",
            "fr": "vélo cargo",
            "nl": "bakfiets",
            "ja": "カーゴバイク",
            "zh": "貨運自行車",
        },
        "news_queries": {
            "en": '("cargo bike" OR "e-cargo bike")',
            "de": "(Lastenrad OR E-Lastenrad)",
            "fr": '("vélo cargo" OR biporteur)',
            "nl": "(bakfiets OR vrachtfiets)",
            "ja": "(カーゴバイク OR 貨物自転車)",
            "zh": "(貨運自行車 OR 載貨單車 OR Cargo Bike)",
        },
        "wiki": {
            "en": "Cargo_bike",
            "de": "Lastenfahrrad",
            "fr": "Vélo_cargo",
            "nl": "Bakfiets",
            "ja": "カーゴバイク",
            "zh": "載貨自行車",
        },
    },
    {
        "id": "parts",
        "name_zh": "零配件 (Parts & Gear)",
        "short_zh": "零配件",
        "icon": "⚙️",
        "color": "#4c6a5a",
        "queries": {
            "en": "bike parts",
            "de": "Fahrradteile",
            "fr": "pièces vélo",
            "nl": "fietsonderdelen",
            "ja": "自転車 パーツ",
            "zh": "自行車 零配件",
        },
        "news_queries": {
            "en": '(Shimano OR SRAM OR "bike helmet" OR "bike tires" OR "bike components")',
            "de": "(Shimano OR SRAM OR Fahrradteile OR Fahrradhelm)",
            "fr": "(Shimano OR SRAM OR \"pièces vélo\" OR \"accessoires vélo\")",
            "nl": "(Shimano OR fietsonderdelen OR fietshelm)",
            "ja": "(シマノ OR 自転車 パーツ OR サイクルウェア)",
            "zh": "(自行車 零配件 OR Shimano OR 單車安全帽 OR 輪組)",
        },
        "wiki": {
            "en": "Shimano",
            "de": "Shimano",
            "fr": "Shimano",
            "nl": "Shimano",
            "ja": "シマノ",
            "zh": "禧瑪諾",
        },
    },
    {
        "id": "events",
        "name_zh": "活動與展會 (Events & Expo)",
        "short_zh": "活動／展會",
        "icon": "🎪",
        "color": "#0e7490",
        "queries": {
            "en": "cycling event",
            "de": "Fahrradmesse",
            "fr": "salon du vélo",
            "nl": "fietsevenement",
            "ja": "自転車 イベント",
            "zh": "自行車 活動",
        },
        "news_queries": {
            "en": '(Eurobike OR "Sea Otter" OR "gran fondo" OR "cycling event" OR "bike expo")',
            "de": "(Eurobike OR Fahrradmesse OR \"Cyclingworld\" OR Radveranstaltung)",
            "fr": '(\"salon du vélo\" OR \"Vélo in Paris\" OR cyclosportive)',
            "nl": "(fietsevenement OR toertocht OR Bike Motion)",
            "ja": "(サイクルモード OR 自転車 イベント OR ファンライド)",
            "zh": "(台北國際自行車展 OR 自行車節 OR 單車活動 OR 約騎)",
        },
        "wiki": {
            "en": "Eurobike",
            "de": "Eurobike",
            "fr": "Eurobike",
            "nl": "Eurobike",
            "ja": "サイクルモードインターナショナル",
            "zh": "台北國際自行車展",
        },
    },
]


def _lang_bucket(hl: str) -> str:
    h = hl.lower()
    if h.startswith("de"):
        return "de"
    if h.startswith("fr"):
        return "fr"
    if h.startswith("nl"):
        return "nl"
    if h.startswith("ja"):
        return "ja"
    if h.startswith("zh"):
        return "zh"
    return "en"


def _fetch_google_suggest(country: dict[str, str], query: str) -> list[str]:
    """Fetch localized Google Autocomplete hot search keywords for a country & category."""
    results: list[str] = []
    seen: set[str] = set()
    # Query both bare keyword and keyword + space to maximize rich long-tail SEO phrases
    for q in (f"{query} ", query):
        try:
            resp = requests.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "firefox", "gl": country["gl"], "hl": country["hl"], "q": q},
                headers={"User-Agent": USER_AGENT},
                timeout=8,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list):
                    for item in payload[1]:
                        s = str(item).strip()
                        key = s.lower()
                        if s and key not in seen and key != query.strip().lower():
                            seen.add(key)
                            results.append(s)
        except Exception:
            continue
        if len(results) >= 8:
            break
    return results[:8]


def _fetch_gnews_30d_hist(country: dict[str, str], query: str, date_keys: list[str]) -> dict[str, Any]:
    """Fetch localized Google News RSS over last 30 days and bucket exact daily counts."""
    daily_map = {dk: 0 for dk in date_keys}
    recent_titles: list[str] = []
    try:
        full_q = f"{query} when:30d"
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(full_q)
            + f"&hl={urllib.parse.quote(country['hl'])}&gl={country['gl'].upper()}&ceid={urllib.parse.quote(country['ceid'])}"
        )
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=11)
        if resp.status_code != 200:
            return {"status": f"http_{resp.status_code}", "daily": [0] * len(date_keys), "titles": []}
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            pub = item.findtext("pubDate") or ""
            title = (item.findtext("title") or "").strip()
            if pub:
                try:
                    dt = email.utils.parsedate_to_datetime(pub)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dk = dt.astimezone(CST).strftime("%Y-%m-%d")
                    if dk in daily_map:
                        daily_map[dk] += 1
                        if len(recent_titles) < 3 and title:
                            clean_t = re.sub(r"\s+-\s+[^-]{2,45}$", "", title).strip()
                            recent_titles.append(clean_t)
                except Exception:
                    pass
        return {"status": "ok", "daily": [daily_map[dk] for dk in date_keys], "titles": recent_titles}
    except Exception as exc:
        return {"status": f"err:{type(exc).__name__}", "daily": [0] * len(date_keys), "titles": []}


def _fetch_wikimedia_30d(wiki_lang: str, article: str, start_ymd: str, end_ymd: str, date_keys: list[str]) -> list[int]:
    """Fetch exact daily real-user pageviews for the last 30 days from Wikimedia REST API."""
    daily_map = {dk: 0 for dk in date_keys}
    try:
        enc_art = urllib.parse.quote(article, safe="")
        url = (
            f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            f"{wiki_lang}.wikipedia/all-access/user/{enc_art}/daily/{start_ymd}/{end_ymd}"
        )
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=9)
        if resp.status_code != 200:
            return [0] * len(date_keys)
        for row in resp.json().get("items") or []:
            ts = str(row.get("timestamp") or "")
            if len(ts) >= 8:
                dk = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
                if dk in daily_map:
                    daily_map[dk] = int(row.get("views") or 0)
        return [daily_map[dk] for dk in date_keys]
    except Exception:
        return [0] * len(date_keys)


def run_seo_trends(docs_dir: Path) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_cst = now_utc.astimezone(CST)
    date_str = now_cst.strftime("%Y-%m-%d")

    # 30-day window ending yesterday/today (Wikimedia data is complete through yesterday UTC)
    end_date = now_cst.date()
    date_keys = [(end_date - timedelta(days=29 - i)).isoformat() for i in range(30)]
    wiki_start = (end_date - timedelta(days=30)).strftime("%Y%m%d")
    wiki_end = end_date.strftime("%Y%m%d")

    out_path = docs_dir / "data" / "seo_trends.json"

    # Load previous day's keywords per (iso2, cat_id) to tag newly appearing hot search queries as `is_new`
    prev_kw_map: dict[str, set[str]] = {}
    prev_date: str | None = None
    if out_path.exists():
        try:
            prev_doc = json.loads(out_path.read_text(encoding="utf-8"))
            if prev_doc.get("date") != date_str:
                prev_date = prev_doc.get("date")
            else:
                prev_date = prev_doc.get("compared_with_date")
            for r in prev_doc.get("rows") or []:
                k = f"{r.get('country_iso2')}:{r.get('category_id')}"
                prev_kw_map[k] = {
                    str(kw.get("query") or "").lower()
                    for kw in (r.get("top_keywords") or [])
                }
        except Exception:
            pass

    print(f"[seo-trends] Collecting 7d & 30d SEO keyword trends for {len(SEO_COUNTRIES)} markets x {len(SEO_CATEGORIES)} categories...")

    # 1. Fetch Wikimedia 30-day daily user views in parallel (deduplicated by (wiki_lang, cat_id))
    wiki_tasks: dict[tuple[str, str], str] = {}
    for c in SEO_COUNTRIES:
        wl = c["wiki_lang"]
        for cat in SEO_CATEGORIES:
            art = cat["wiki"].get(wl)
            if art:
                wiki_tasks[(wl, cat["id"])] = art

    wiki_results: dict[tuple[str, str], list[int]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futs = {
            pool.submit(_fetch_wikimedia_30d, wl, art, wiki_start, wiki_end, date_keys): (wl, cid)
            for (wl, cid), art in wiki_tasks.items()
        }
        for fut in concurrent.futures.as_completed(futs):
            wiki_results[futs[fut]] = fut.result()

    # 2. Fetch Google Suggest + Google News 30d histograms for all 90 (country, category) pairs
    pair_jobs: list[tuple[dict[str, str], dict[str, Any]]] = [
        (c, cat) for c in SEO_COUNTRIES for cat in SEO_CATEGORIES
    ]

    def _collect_pair(pair: tuple[dict[str, str], dict[str, Any]]) -> dict[str, Any]:
        c, cat = pair
        lb = _lang_bucket(c["hl"])
        seed_q = cat["queries"][lb]
        news_q = cat["news_queries"][lb]
        suggestions = _fetch_google_suggest(c, seed_q)
        gnews = _fetch_gnews_30d_hist(c, news_q, date_keys)
        return {
            "iso2": c["iso2"],
            "cat_id": cat["id"],
            "seed_query": seed_q,
            "suggestions": suggestions,
            "gnews_daily": gnews["daily"],
            "gnews_status": gnews["status"],
        }

    pair_data: dict[tuple[str, str], dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as pool:
        for res in pool.map(_collect_pair, pair_jobs):
            pair_data[(res["iso2"], res["cat_id"])] = res

    # 3. Batch-translate non-Chinese Google Suggest keywords into Traditional Chinese
    translator = ZhTranslator(docs_dir / "data" / "translation_cache.json")
    by_lang_texts: dict[str, list[str]] = {"en": [], "de": [], "fr": [], "nl": [], "ja": []}
    for c in SEO_COUNTRIES:
        lb = _lang_bucket(c["hl"])
        if lb == "zh":
            continue
        for cat in SEO_CATEGORIES:
            for s in pair_data[(c["iso2"], cat["id"])]["suggestions"][:6]:
                by_lang_texts.setdefault(lb, []).append(s)

    tr_maps: dict[str, dict[str, str]] = {}
    for lb, texts in by_lang_texts.items():
        if texts:
            tr_maps[lb] = translator.translate_batch(texts, src_lang=lb)
    translator.save()

    # 4. Build unified 7d & 30d metrics per (country, category)
    rows: list[dict[str, Any]] = []
    # Compute per-country scaling denominators so scores 0..100 reflect true relative intensity
    raw_entries: list[dict[str, Any]] = []

    for c in SEO_COUNTRIES:
        wl = c["wiki_lang"]
        lb = _lang_bucket(c["hl"])
        for cat in SEO_CATEGORIES:
            pd = pair_data[(c["iso2"], cat["id"])]
            wiki_d = wiki_results.get((wl, cat["id"]), [0] * 30)
            news_d = pd["gnews_daily"]

            # Wikimedia daily views can be 0 on the final partial day; shift window safely if last day == 0
            w_eff = wiki_d[:-1] if (len(wiki_d) == 30 and wiki_d[-1] == 0 and sum(wiki_d[:-1]) > 0) else wiki_d
            wiki_7d = sum(w_eff[-7:])
            wiki_prev_7d = sum(w_eff[-14:-7])
            wiki_30d = sum(w_eff)

            news_7d = sum(news_d[-7:])
            news_prev_7d = sum(news_d[-14:-7])
            news_30d = sum(news_d)

            # Combined normalized 30-day daily sparkline (wiki normalized + news velocity)
            w_max = max(max(wiki_d), 1)
            n_max = max(max(news_d), 1)
            daily_30d: list[int] = []
            for i in range(30):
                w_norm = (wiki_d[i] / w_max) * 65.0 if sum(wiki_d) > 0 else 0.0
                n_norm = (news_d[i] / n_max) * (35.0 if sum(wiki_d) > 0 else 100.0)
                daily_30d.append(round(w_norm + n_norm))

            # True 7d vs prior-7d WoW% (prefer Wikimedia user search volume when >= 140 weekly views, blended with News)
            if wiki_prev_7d >= 100 and news_prev_7d >= 3:
                w_wow = ((wiki_7d - wiki_prev_7d) / wiki_prev_7d) * 100.0
                n_wow = ((news_7d - news_prev_7d) / news_prev_7d) * 100.0
                wow_pct = round(0.65 * w_wow + 0.35 * max(-60.0, min(120.0, n_wow)), 1)
            elif wiki_prev_7d >= 50:
                wow_pct = round(((wiki_7d - wiki_prev_7d) / wiki_prev_7d) * 100.0, 1)
            elif news_prev_7d >= 1:
                wow_pct = round(max(-75.0, min(180.0, ((news_7d - news_prev_7d) / news_prev_7d) * 100.0)), 1)
            else:
                wow_pct = 0.0

            # 7-day vs 30-day weekly average momentum (%)
            wiki_weekly_avg = wiki_30d / (len(w_eff) / 7.0) if w_eff else 0.0
            news_weekly_avg = news_30d / (30.0 / 7.0)
            if wiki_weekly_avg >= 100 and news_weekly_avg >= 3:
                w_m = ((wiki_7d - wiki_weekly_avg) / wiki_weekly_avg) * 100.0
                n_m = ((news_7d - news_weekly_avg) / news_weekly_avg) * 100.0
                mom_7v30 = round(0.65 * w_m + 0.35 * max(-60.0, min(120.0, n_m)), 1)
            elif wiki_weekly_avg >= 50:
                mom_7v30 = round(((wiki_7d - wiki_weekly_avg) / wiki_weekly_avg) * 100.0, 1)
            elif news_weekly_avg >= 0.5:
                mom_7v30 = round(max(-75.0, min(180.0, ((news_7d - news_weekly_avg) / news_weekly_avg) * 100.0)), 1)
            else:
                mom_7v30 = 0.0

            # Raw composite power for 0..100 scoring (log-compressed wiki + news + suggest coverage)
            import math
            raw_7d = math.log1p(wiki_7d) * 6.2 + news_7d * 1.45 + len(pd["suggestions"]) * 1.2
            raw_30d = math.log1p(wiki_30d / 4.286) * 6.2 + (news_30d / 4.286) * 1.45 + len(pd["suggestions"]) * 1.2

            key_id = f"{c['iso2']}:{cat['id']}"
            prev_set = prev_kw_map.get(key_id, set())
            kw_objs = []
            for s in pd["suggestions"][:6]:
                zh = s if lb == "zh" else (tr_maps.get(lb, {}).get(s) or s)
                kw_objs.append({
                    "query": s,
                    "query_zh": zh,
                    "is_new": bool(prev_set and s.lower() not in prev_set),
                })

            raw_entries.append({
                "country_iso2": c["iso2"],
                "country_zh": c["name_zh"],
                "region": c["region"],
                "lang_label": c["lang_label"],
                "category_id": cat["id"],
                "category_zh": cat["name_zh"],
                "category_short": cat["short_zh"],
                "seed_query": pd["seed_query"],
                "raw_7d": raw_7d,
                "raw_30d": raw_30d,
                "wiki_7d": wiki_7d,
                "wiki_30d": wiki_30d,
                "news_7d": news_7d,
                "news_30d": news_30d,
                "wow_pct": wow_pct,
                "momentum_7v30_pct": mom_7v30,
                "daily_30d": daily_30d,
                "top_keywords": kw_objs,
                "new_keywords_count": sum(1 for k in kw_objs if k["is_new"]),
            })

    # Normalize 7d & 30d scores cleanly onto 15..100 scale across the matrix
    max_raw = max((max(r["raw_7d"], r["raw_30d"]) for r in raw_entries), default=1.0)
    min_raw = min((min(r["raw_7d"], r["raw_30d"]) for r in raw_entries), default=0.0)
    span = max(max_raw - min_raw, 1.0)

    for r in raw_entries:
        s7 = round(18 + ((r["raw_7d"] - min_raw) / span) * 82, 1)
        s30 = round(18 + ((r["raw_30d"] - min_raw) / span) * 82, 1)
        r["score_7d"] = min(100.0, max(12.0, s7))
        r["score_30d"] = min(100.0, max(12.0, s30))
        r.pop("raw_7d", None)
        r.pop("raw_30d", None)
        rows.append(r)

    ok_news = sum(1 for v in pair_data.values() if v["gnews_status"] == "ok")
    total_kws = sum(len(r["top_keywords"]) for r in rows)

    payload = {
        "schema_version": "1.0",
        "date": date_str,
        "compared_with_date": prev_date,
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_cst": now_cst.strftime("%Y-%m-%d %H:%M CST"),
        "window_7d": f"{date_keys[-7]} ～ {date_keys[-1]}",
        "window_30d": f"{date_keys[0]} ～ {date_keys[-1]}",
        "date_keys_30d": date_keys,
        "meta": {
            "schedule_zh": "每日 07:00 CST 自動撈取更新",
            "pairs_count": len(rows),
            "gnews_ok_pairs": ok_news,
            "total_hot_keywords": total_kws,
            "methodology_zh": (
                "結合三大每日即時公開搜尋訊號計算各國、各自行車類別 SEO 熱度："
                "（1）Google Autocomplete 區域在地化即時熱搜長尾詞（按國家 gl 與語系 hl 即時擷取）；"
                "（2）Google News 區域在地化 7 日與 30 日新聞搜尋聲量與每日分布；"
                "（3）Wikimedia 官方各語系（英／德／法／荷／日／中）近 30 日每日真實用戶查詢量。"
                "「7日 vs 30日動能」為近 7 日熱度相對 30 日週平均之增減百分比，正值代表近期搜尋升溫。"
            ),
        },
        "regions": SEO_REGIONS,
        "countries": SEO_COUNTRIES,
        "categories": [
            {k: v for k, v in c.items() if k in ("id", "name_zh", "short_zh", "icon", "color")}
            for c in SEO_CATEGORIES
        ],
        "rows": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[seo-trends] Wrote {out_path} ({len(rows)} country×category rows, "
        f"{total_kws} live Google Suggest keywords, gnews ok={ok_news}/{len(rows)})"
    )
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily cycling SEO keyword trends collector (7d & 30d)")
    ap.add_argument("--docs-dir", type=Path, default=Path("docs"))
    args = ap.parse_args()
    run_seo_trends(args.docs_dir)


if __name__ == "__main__":
    main()
