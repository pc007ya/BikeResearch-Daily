"""Daily orchestrator: crawl 5 cycling media -> translate EN/DE to zh-TW -> extract complete bikes -> 3D reverse-engineer -> export PPTX slides."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipeline.bike_extractor import extract_complete_bike, is_complete_bike_article
from pipeline.reconstruct_3d import build_bike_3d_model
from pipeline.slides_builder import build_daily_pptx
from pipeline.sources import crawl_all_sources
from pipeline.taxonomy import (
    build_executive_summary,
    classify_article,
    detect_brands,
    detect_events,
    make_zh_takeaway,
)
from pipeline.translator import ZhTranslator, translate_geo_label

CST = timezone(timedelta(hours=8))


def run_pipeline(docs_dir: Path, max_per_source: int = 18, max_bikes: int = 12) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_cst = now_utc.astimezone(CST)
    date_str = now_cst.strftime("%Y-%m-%d")

    data_dir = docs_dir / "data"
    archive_dir = data_dir / "archive"
    models_dir = docs_dir / "models"
    archive_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] Crawling 7 cycling sources (date={date_str})...")
    raw_feeds = crawl_all_sources(max_per_source=max_per_source)

    source_stats: list[dict[str, Any]] = []
    all_raw_items: list[dict[str, Any]] = []
    for feed in raw_feeds:
        src = feed["source"]
        source_stats.append(
            {
                "id": src["id"],
                "name": src["name"],
                "url": src["url"],
                "focus": src["focus"],
                "lang": src["lang"],
                "status": feed["status"],
                "error": feed["error"],
                "item_count": len(feed["items"]),
                "elapsed_sec": feed["elapsed_sec"],
            }
        )
        print(f"   - {src['name']:15s}: status={feed['status']} items={len(feed['items'])} ({feed['elapsed_sec']}s)")
        all_raw_items.extend(feed["items"])

    # Deduplicate by URL and sort newest first
    seen_urls: set[str] = set()
    unique_items: list[dict[str, Any]] = []
    for it in all_raw_items:
        u = it["url"].rstrip("/")
        if u not in seen_urls:
            seen_urls.add(u)
            unique_items.append(it)
    unique_items.sort(key=lambda x: x["published_at"], reverse=True)

    # Batch translate ALL English, German & Simplified Chinese titles/summaries to Traditional Chinese
    print(f"[2/5] Translating {len(unique_items)} EN/DE/zh-CN articles uniformly to Traditional Chinese (zh-TW)...")
    translator = ZhTranslator(data_dir / "translation_cache.json")
    en_texts: list[str] = []
    de_texts: list[str] = []
    zhcn_texts: list[str] = []
    for it in unique_items:
        if it["source_lang"] == "de":
            bucket = de_texts
        elif it["source_lang"].lower() == "zh-cn":
            bucket = zhcn_texts
        else:
            bucket = en_texts
        bucket.append(it["title"])
        if it.get("summary_raw"):
            bucket.append(it["summary_raw"][:220])
    tr_en = translator.translate_batch(en_texts, src_lang="en")
    tr_de = translator.translate_batch(de_texts, src_lang="de")
    tr_zhcn = translator.translate_batch(zhcn_texts, src_lang="zh-CN")

    def _get_zh(raw: str, lang: str) -> str:
        clean = " ".join((raw or "").split())
        if not clean:
            return ""
        if lang == "de":
            mapping = tr_de
        elif lang.lower() == "zh-cn":
            mapping = tr_zhcn
        else:
            mapping = tr_en
        return mapping.get(clean) or translator.translate(clean, src_lang=lang)

    print(f"[3/5] Analyzing articles, extracting complete bikes & building ALSO-style 3D models...")
    for old_f in models_dir.glob("*"):
        if old_f.is_file():
            old_f.unlink()

    articles: list[dict[str, Any]] = []
    bikes: list[dict[str, Any]] = []
    seen_bike_keys: dict[str, int] = {}

    for it in unique_items:
        lang = it["source_lang"]
        title_zh = _get_zh(it["title"], lang)
        summary_zh = _get_zh(it.get("summary_raw", "")[:220], lang)

        text_for_nlp = f"{it['title']} {it['summary_raw']} {it['full_text'][:3500]}"
        brands = detect_brands(text_for_nlp, it.get("categories"), title=it["title"])
        events = detect_events(text_for_nlp, it.get("categories"))
        is_bike = is_complete_bike_article(it)

        bike_data: dict[str, Any] | None = None
        if is_bike and len(bikes) < max_bikes:
            try:
                bike_data = extract_complete_bike(it, brands)
                bike_data["title_zh"] = title_zh
                # Translate multi-size geometry row labels (EN/DE -> zh-TW)
                gt = bike_data.get("geometry_table") or {}
                for row in gt.get("raw_rows") or []:
                    row["label_zh"] = translate_geo_label(row.get("label", ""))

                norm_model_key = "".join(ch for ch in bike_data["model_name"].lower() if ch.isalnum())
                if norm_model_key in seen_bike_keys:
                    prev_idx = seen_bike_keys[norm_model_key]
                    if bike_data["measured_ratio"] > bikes[prev_idx]["measured_ratio"]:
                        model_info = build_bike_3d_model(bike_data, models_dir)
                        bike_data["model_3d"] = model_info
                        bikes[prev_idx] = bike_data
                        print(f"   ^ Upgraded duplicate bike: {bike_data['model_name']} ({int(bike_data['measured_ratio']*100)}%)")
                    else:
                        bike_data = bikes[prev_idx]
                else:
                    print(
                        f"   + Complete bike: [{bike_data['source_name']}] "
                        f"{bike_data['brand']} {bike_data['model_name']} "
                        f"({bike_data['category_key']}, measured={int(bike_data['measured_ratio']*100)}%)"
                    )
                    model_info = build_bike_3d_model(bike_data, models_dir)
                    bike_data["model_3d"] = model_info
                    seen_bike_keys[norm_model_key] = len(bikes)
                    bikes.append(bike_data)
            except Exception as exc:
                print(f"   ! Failed bike extraction/3D for {it['title'][:50]}: {exc}", file=sys.stderr)
                is_bike = False
                bike_data = None

        cls = classify_article(it, is_complete_bike=(bike_data is not None))
        takeaway_zh = make_zh_takeaway(it, brands, events, cls, bike_data)

        articles.append(
            {
                "id": it["id"],
                "source_id": it["source_id"],
                "source_name": it["source_name"],
                "source_lang": lang,
                "title": it["title"],
                "title_zh": title_zh,
                "url": it["url"],
                "published_at": it["published_at"],
                "author": it["author"],
                "categories": it["categories"][:5],
                "summary_raw": it["summary_raw"][:280],
                "summary_zh": summary_zh,
                "takeaway_zh": takeaway_zh,
                "hero_image": (bike_data["hero_image"] if bike_data else it["hero_image"]),
                "brands": brands,
                "events": events,
                "classification": cls,
                "bike_slug": bike_data["slug"] if bike_data else None,
            }
        )

    translator.save()

    print(f"[4/5] Synthesizing executive summary ({len(bikes)} complete bikes) & generating Chinese PPTX slides...")
    summary = build_executive_summary(articles, bikes, source_stats)

    pptx_rel = "data/daily_briefing.pptx"
    pptx_archive_rel = f"data/archive/{date_str}_briefing.pptx"

    report = {
        "schema_version": "1.1",
        "date": date_str,
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_cst": now_cst.strftime("%Y-%m-%d %H:%M CST"),
        "pptx_file": pptx_rel,
        "sources": source_stats,
        "summary": summary,
        "complete_bikes": bikes,
        "articles": articles,
    }

    # Build 16:9 Traditional Chinese PowerPoint deck with source citation footers on EVERY slide
    pptx_path = docs_dir / pptx_rel
    build_daily_pptx(report, docs_dir=docs_dir, out_path=pptx_path)
    shutil.copy2(pptx_path, docs_dir / pptx_archive_rel)

    # Write daily archive JSON and latest.json
    archive_path = archive_dir / f"{date_str}.json"
    latest_path = data_dir / "latest.json"
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    archive_path.write_text(serialized, encoding="utf-8")
    latest_path.write_text(serialized, encoding="utf-8")

    # Update archive index (keep last 30 days)
    archive_files = sorted(archive_dir.glob("20*.json"), reverse=True)[:30]
    index_entries = []
    for af in archive_files:
        try:
            d = json.loads(af.read_text(encoding="utf-8"))
            index_entries.append(
                {
                    "date": d.get("date", af.stem),
                    "generated_at_cst": d.get("generated_at_cst", ""),
                    "total_articles": d.get("summary", {}).get("counts", {}).get("total_articles", 0),
                    "complete_bikes": d.get("summary", {}).get("counts", {}).get("complete_bikes", 0),
                    "file": f"data/archive/{af.name}",
                }
            )
        except Exception:
            continue
    (data_dir / "index.json").write_text(
        json.dumps({"latest_date": date_str, "archives": index_entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[5/5] Done! Wrote {latest_path}, {pptx_path}, and {len(bikes)} 3D packages into {models_dir}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BikeResearch-Daily crawl, translation, 3D & PPTX pipeline")
    parser.add_argument("--docs-dir", default="docs", help="Output directory for GitHub Pages site")
    parser.add_argument("--max-per-source", type=int, default=18)
    parser.add_argument("--max-bikes", type=int, default=12)
    args = parser.parse_args()
    run_pipeline(Path(args.docs_dir), max_per_source=args.max_per_source, max_bikes=args.max_bikes)


if __name__ == "__main__":
    main()
