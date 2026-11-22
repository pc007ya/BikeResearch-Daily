"""RSS + polite HTML crawler for the 5 target cycling intelligence sources."""

from __future__ import annotations

import email.utils
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCES: list[dict[str, str]] = [
    {
        "id": "bikerumor",
        "name": "Bikerumor",
        "url": "https://bikerumor.com/",
        "feed_url": "https://bikerumor.com/feed/",
        "lang": "en",
        "focus": "新品科技・整車・零組件",
    },
    {
        "id": "pinkbike",
        "name": "Pinkbike",
        "url": "https://www.pinkbike.com/",
        "feed_url": "https://www.pinkbike.com/pinkbike_xml_feed.php",
        "lang": "en",
        "focus": "MTB・Enduro・DH 評測與賽事",
    },
    {
        "id": "cyclingnews",
        "name": "Cyclingnews",
        "url": "https://www.cyclingnews.com/",
        "feed_url": "https://www.cyclingnews.com/feeds.xml",
        "lang": "en",
        "focus": "公路賽・環法・職業車隊與器材",
    },
    {
        "id": "emtb_news",
        "name": "eMTB-News.de",
        "url": "https://www.emtb-news.de/news/",
        "feed_url": "https://www.emtb-news.de/news/feed/",
        "lang": "de",
        "focus": "德語區 e-MTB・電輔系統・展會",
    },
    {
        "id": "ebike_mtb",
        "name": "E-MOUNTAINBIKE",
        "url": "https://ebike-mtb.com/en/",
        "feed_url": "https://ebike-mtb.com/en/feed/",
        "lang": "en",
        "focus": "深度 e-MTB / SUV 電輔整車評測與幾何",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.7",
}

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}

BAD_IMG_PATTERNS = (
    "logo",
    "icon",
    "avatar",
    "gravatar",
    "flag",
    "wpml",
    "sitepress",
    "pixel",
    "1x1",
    "sprite",
    "badge",
    "spinner",
    "emoji",
    "smilies",
    ".svg",
    "data:image",
    "doubleclick",
    "facebook.com",
    "twitter.com",
    "blank.gif",
)


def parse_pubdate(raw: str | None) -> str:
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    raw = raw.strip()
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def clean_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def extract_images_from_html(raw_html: str, base_url: str = "") -> list[dict[str, str]]:
    if not raw_html:
        return []
    soup = BeautifulSoup(raw_html, "lxml")
    seen: set[str] = set()
    images: list[dict[str, str]] = []
    for img in soup.find_all("img"):
        src = (
            img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or img.get("src")
            or ""
        ).strip()
        if not src:
            # fallback to largest srcset candidate
            srcset = img.get("srcset") or img.get("data-srcset") or ""
            if srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    src = parts[-1]
        if not src:
            continue
        if base_url and src.startswith("/"):
            src = urljoin(base_url, src)
        if not src.startswith("http"):
            continue
        low = src.lower()
        if any(bad in low for bad in BAD_IMG_PATTERNS):
            continue
        # Skip tiny thumbnails like 150x150
        if re.search(r"[-_](?:150x150|100x100|80x80|64x64|32x32)\.", low):
            continue
        if src in seen:
            continue
        seen.add(src)
        alt = (img.get("alt") or img.get("title") or "").strip()
        images.append({"url": src, "alt": html.unescape(alt)})
    return images


def fetch_article_html(url: str, timeout: int = 12) -> str | None:
    """Politely fetch full HTML page when allowed; returns None on 403/timeout."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and len(resp.text) > 1500:
            return resp.text
    except Exception:
        return None
    return None


def fetch_source_feed(source: dict[str, str], max_items: int = 25) -> dict[str, Any]:
    """Fetch and normalize items from a single RSS feed."""
    started = time.time()
    result: dict[str, Any] = {
        "source": source,
        "status": "ok",
        "error": None,
        "items": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = requests.get(source["feed_url"], headers=HEADERS, timeout=18)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        raw_items = root.findall(".//item")[:max_items]
        for idx, it in enumerate(raw_items):
            title = html.unescape((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            if not title or not link:
                continue
            pub_iso = parse_pubdate(it.findtext("pubDate"))
            author = (
                it.findtext("dc:creator", namespaces=NS)
                or it.findtext("author")
                or source["name"]
            ).strip()
            categories = [
                html.unescape(c.text.strip())
                for c in it.findall("category")
                if c.text and c.text.strip()
            ]
            desc_html = it.findtext("description") or ""
            content_html = it.findtext("content:encoded", namespaces=NS) or ""
            combined_html = content_html if len(content_html) > len(desc_html) else desc_html

            images = extract_images_from_html(combined_html, base_url=source["url"])
            # Also inspect media:content & enclosure
            for media in it.findall("media:content", namespaces=NS):
                m_url = (media.get("url") or "").strip()
                if m_url and m_url.startswith("http") and not any(b in m_url.lower() for b in BAD_IMG_PATTERNS):
                    if not any(i["url"] == m_url for i in images):
                        images.insert(0, {"url": m_url, "alt": title})
            encl = it.find("enclosure")
            if encl is not None:
                e_url = (encl.get("url") or "").strip()
                if e_url and e_url.startswith("http") and not any(b in e_url.lower() for b in BAD_IMG_PATTERNS):
                    if not any(i["url"] == e_url for i in images):
                        images.insert(0, {"url": e_url, "alt": title})

            # Pinkbike RSS thumbnails use p2pb; also keep full-size URL note
            desc_text = clean_text(desc_html)
            full_text = clean_text(combined_html)

            result["items"].append(
                {
                    "id": f"{source['id']}_{idx:02d}",
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "source_lang": source["lang"],
                    "title": title,
                    "url": link.split("?trk=rss")[0],
                    "published_at": pub_iso,
                    "author": html.unescape(author),
                    "categories": categories,
                    "summary_raw": desc_text[:500],
                    "full_text": full_text[:18000],
                    "content_html": combined_html,
                    "images": images[:20],
                    "hero_image": images[0]["url"] if images else "",
                }
            )
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)

    result["elapsed_sec"] = round(time.time() - started, 2)
    return result


def crawl_all_sources(max_per_source: int = 20) -> list[dict[str, Any]]:
    results = []
    for src in SOURCES:
        res = fetch_source_feed(src, max_items=max_per_source)
        results.append(res)
    return results
