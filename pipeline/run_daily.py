"""Daily orchestrator: crawl 5 cycling media -> analyze -> extract complete bikes -> 3D reverse-engineer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipeline.bike_extractor import extract_complete_bike, is_complete_bike_article
from pipeline.reconstruct_3d import build_bike_3d_model
from pipeline.sources import crawl_all_sources
from pipeline.taxonomy import (
    build_executive_summary,
    classify_article,
    detect_brands,
    detect_events,
    make_zh_takeaway,
)

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

    print(f"[1/4] Crawling 5 cycling sources (date={date_str})...")
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

    print(f"[2/4] Analyzing {len(unique_items)} articles & extracting complete bikes...")
    # Remove stale model artifacts before regenerating current run
    for old_f in models_dir.glob("*"):
        if old_f.is_file():
            old_f.unlink()

    articles: list[dict[str, Any]] = []
    bikes: list[dict[str, Any]] = []
    seen_bike_keys: dict[str, int] = {}

    for it in unique_items:
        text_for_nlp = f"{it['title']} {it['summary_raw']} {it['full_text'][:3500]}"
        brands = detect_brands(text_for_nlp, it.get("categories"), title=it["title"])
        events = detect_events(text_for_nlp, it.get("categories"))
        is_bike = is_complete_bike_article(it)

        bike_data: dict[str, Any] | None = None
        if is_bike and len(bikes) < max_bikes:
            try:
                bike_data = extract_complete_bike(it, brands)
                norm_model_key = "".join(ch for ch in bike_data["model_name"].lower() if ch.isalnum())
                if norm_model_key in seen_bike_keys:
                    # Keep whichever report has richer measured geometry data
                    prev_idx = seen_bike_keys[norm_model_key]
                    if bike_data["measured_ratio"] > bikes[prev_idx]["measured_ratio"]:
                        model_info = build_bike_3d_model(bike_data, models_dir)
                        bike_data["model_3d"] = model_info
                        bikes[prev_idx] = bike_data
                        print(f"   ^ Upgraded duplicate bike with higher measured ratio: {bike_data['model_name']} ({int(bike_data['measured_ratio']*100)}%)")
                    else:
                        bike_data = bikes[prev_idx]
                else:
                    print(
                        f"   + Complete bike detected: [{bike_data['source_name']}] "
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
                "source_lang": it["source_lang"],
                "title": it["title"],
                "url": it["url"],
                "published_at": it["published_at"],
                "author": it["author"],
                "categories": it["categories"][:5],
                "summary_raw": it["summary_raw"][:280],
                "takeaway_zh": takeaway_zh,
                "hero_image": (bike_data["hero_image"] if bike_data else it["hero_image"]),
                "brands": brands,
                "events": events,
                "classification": cls,
                "bike_slug": bike_data["slug"] if bike_data else None,
            }
        )

    print(f"[3/4] Synthesizing executive summary ({len(bikes)} complete bikes reconstructed in 3D)...")
    summary = build_executive_summary(articles, bikes, source_stats)

    report = {
        "schema_version": "1.0",
        "date": date_str,
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_cst": now_cst.strftime("%Y-%m-%d %H:%M CST"),
        "sources": source_stats,
        "summary": summary,
        "complete_bikes": bikes,
        "articles": articles,
    }

    # Write daily archive and latest.json
    archive_path = archive_dir / f"{date_str}.json"
    latest_path = data_dir / "latest.json"
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    archive_path.write_text(serialized, encoding="utf-8")
    latest_path.write_text(serialized, encoding="utf-8")

    # Update archive index (keep last 30 days)
    archive_files = sorted(archive_dir.glob("*.json"), reverse=True)[:30]
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

    print(f"[4/4] Done! Wrote {latest_path} and {len(bikes)} 3D GLB + Blender packages into {models_dir}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BikeResearch-Daily crawl & 3D reconstruction pipeline")
    parser.add_argument("--docs-dir", default="docs", help="Output directory for GitHub Pages site")
    parser.add_argument("--max-per-source", type=int, default=18)
    parser.add_argument("--max-bikes", type=int, default=12)
    args = parser.parse_args()
    run_pipeline(Path(args.docs_dir), max_per_source=args.max_per_source, max_bikes=args.max_bikes)


if __name__ == "__main__":
    main()
