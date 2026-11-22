"""Unified English & German -> Traditional Chinese (zh-TW) translator with cycling glossary & disk cache."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

# Exact Traditional Chinese mapping for English & German geometry table row labels
GEO_LABEL_ZH: list[tuple[str, str]] = [
    (r"^size$|rahmengr[öo]ß?e|gr[öo]ß?e", "尺碼"),
    (r"seat\s*tube(?:\s*length)?|sitzrohr", "立管長度"),
    (r"(?:effective\s*)?top\s*tube(?:\s*length)?|oberrohr", "上管長度"),
    (r"head\s*tube(?:\s*length)?|steuerrohr", "頭管長度"),
    (r"head(?:\s*tube)?\s*angle|lenkwinkel", "頭管角度"),
    (r"(?:effective\s*)?seat(?:\s*tube)?\s*angle|sitzwinkel", "立管角度"),
    (r"chain\s*stays?(?:\s*length)?|kettenstrebe", "後下叉長度"),
    (r"bb\s*drop|bottom\s*bracket\s*drop|tretlagerabsenkung", "五通下沉量 (BB Drop)"),
    (r"bb\s*height|tretlagerh[öo]he", "五通離地高"),
    (r"wheelbase|radstand", "前後軸距"),
    (r"\breach\b", "前伸量 (Reach)"),
    (r"\bstack\b", "堆疊高度 (Stack)"),
    (r"standover|überstandsh[öo]he", "跨高 (Standover)"),
    (r"fork\s*(?:offset|rake)|gabelvorlauf|offset", "前叉偏移量 (Offset)"),
    (r"fork\s*(?:length|axle\s*to\s*crown)", "前叉軸肩距"),
    (r"front\s*center", "前輪中心距"),
    (r"travel|federweg", "避震行程"),
    (r"wheel\s*size|laufradgr[öo]ß?e", "輪徑"),
    (r"stem\s*length|vorbau", "龍頭長度"),
    (r"crank\s*length|kurbel", "曲柄長度"),
    (r"handlebar\s*width|lenkerbreite", "車把寬度"),
]

# Cycling domain terminology polish (applied after machine translation)
GLOSSARY_REPLACEMENTS: list[tuple[str, str]] = [
    ("礫石自行車", "礫石越野車 (Gravel)"),
    ("礫石車", "礫石越野車 (Gravel)"),
    ("電動登山車", "電輔越野車 (e-MTB)"),
    ("電動山地車", "電輔越野車 (e-MTB)"),
    ("電動自行車", "電輔車 (e-Bike)"),
    ("越野自行車", "越野車"),
    ("山地自行車", "登山車 (MTB)"),
    ("山地車", "登山車 (MTB)"),
    ("公路自行車", "公路車"),
    ("自行車越野賽", "公路越野賽 (CX)"),
    ("越野車世界盃", "公路越野世界盃 (CX)"),
    ("迴轉式變速器", "變速系統"),
    ("傳動系統變速器", "傳動系統"),
    ("鏈條撐桿", "後下叉"),
    ("後下叉撐桿", "後下叉"),
    ("座管角度", "立管角度"),
    ("頭管角", "頭管角度"),
    ("五通下降", "五通下沉量"),
    ("滴管座管", "升降座管"),
    ("下沉座管", "升降座管"),
    ("旅行前叉", "行程前叉"),
    ("更多的旅行", "更大避震行程"),
    ("更多行程", "更大避震行程"),
    ("更多的行程", "更大避震行程"),
    ("全懸吊", "全避震"),
    ("全懸掛", "全避震"),
    ("避震叉", "避震前叉"),
    ("懸吊叉", "避震前叉"),
    ("懸架", "避震"),
    ("輪組套裝", "輪組"),
    ("碳纖框架", "碳纖車架"),
    ("更輕的框架", "更輕量車架"),
    ("框架", "車架"),
    ("車把", "車把"),
    ("輪胎間隙", "最大胎寬容納"),
    ("自由騎", "自由騎 (Freeride)"),
    ("下坡信心", "下坡操控信心"),
    ("速降", "下坡賽 (DH)"),
    ("耐力賽", "耐力越野 (Enduro)"),
    ("自動換檔", "自動變速 (AutoShift)"),
    ("銷售停止", "停售公告"),
    ("停止銷售", "停售公告"),
    ("回憶", "召回"),
    ("測試中", "實測"),
    ("審查", "深度評測"),
    ("評論：", "評測："),
    ("評論:", "評測："),
    ("第一騎", "首騎評測"),
    ("首次騎行", "首騎評測"),
]

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def translate_geo_label(label: str) -> str:
    """Map English/German geometry row labels cleanly to Traditional Chinese."""
    clean = label.strip()
    for pat, zh in GEO_LABEL_ZH:
        if re.search(pat, clean, re.I):
            return zh
    return clean


def polish_cycling_zh(text: str) -> str:
    out = text.strip()
    for src, dst in GLOSSARY_REPLACEMENTS:
        out = out.replace(src, dst)
    # Clean extra spaces around Chinese punctuation
    out = re.sub(r"\s*([：，。！？；（）「」])\s*", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


class ZhTranslator:
    """Fast cached EN/DE -> zh-TW translator using Google Translate endpoint with graceful fallback."""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.cache: dict[str, str] = {}
        self.dirty = False
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}

    def save(self) -> None:
        if not self.dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Cap cache at 2500 entries so repository stays light
        if len(self.cache) > 2500:
            keys = list(self.cache.keys())[-2000:]
            self.cache = {k: self.cache[k] for k in keys}
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.dirty = False

    def _needs_translation(self, text: str, src_lang: str = "auto") -> bool:
        if not text or len(text.strip()) < 2:
            return False
        if re.fullmatch(r"[\d\s.,°%€$£/+\-–—mmcmkglbsWhNminxX]+", text.strip()):
            return False
        # Simplified Chinese (e.g., biketo.com) MUST be converted to Traditional Chinese (zh-TW)!
        if src_lang.lower() in ("zh-cn", "zh-hans"):
            return True
        cjk_cnt = len(CJK_RE.findall(text))
        if cjk_cnt >= max(4, len(text) * 0.35):
            return False
        return True

    def _call_translate(self, text: str, src_lang: str = "auto") -> str | None:
        try:
            resp = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": src_lang,
                    "tl": "zh-TW",
                    "dt": "t",
                    "q": text,
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if payload and isinstance(payload[0], list):
                    translated = "".join(seg[0] for seg in payload[0] if seg and seg[0])
                    if translated.strip():
                        return translated.strip()
        except Exception:
            return None
        return None

    def translate(self, text: str, src_lang: str = "auto") -> str:
        clean = re.sub(r"\s+", " ", (text or "")).strip()
        if not self._needs_translation(clean, src_lang=src_lang):
            return clean
        key = f"{src_lang}:{clean}"
        if key in self.cache:
            return self.cache[key]
        raw = self._call_translate(clean, src_lang=src_lang)
        if raw:
            polished = polish_cycling_zh(raw)
            self.cache[key] = polished
            self.dirty = True
            return polished
        return clean

    def translate_batch(self, texts: list[str], src_lang: str = "auto") -> dict[str, str]:
        """Batch-translate unique strings efficiently using newline delimiters."""
        unique = []
        seen = set()
        results: dict[str, str] = {}
        for t in texts:
            clean = re.sub(r"\s+", " ", (t or "")).strip()
            if not clean:
                continue
            if not self._needs_translation(clean, src_lang=src_lang):
                results[clean] = clean
                continue
            key = f"{src_lang}:{clean}"
            if key in self.cache:
                results[clean] = self.cache[key]
            elif clean not in seen:
                seen.add(clean)
                unique.append(clean)

        # Process in chunks keeping payload under ~1800 chars per request
        chunk: list[str] = []
        chunk_len = 0
        batches: list[list[str]] = []
        for item in unique:
            if chunk and chunk_len + len(item) > 1600:
                batches.append(chunk)
                chunk = []
                chunk_len = 0
            chunk.append(item)
            chunk_len += len(item) + 1
        if chunk:
            batches.append(chunk)

        for batch in batches:
            joined = "\n".join(batch)
            raw = self._call_translate(joined, src_lang=src_lang)
            if raw:
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                if len(lines) == len(batch):
                    for orig, tr in zip(batch, lines):
                        polished = polish_cycling_zh(tr)
                        self.cache[f"{src_lang}:{orig}"] = polished
                        results[orig] = polished
                        self.dirty = True
                    time.sleep(0.08)
                    continue
            # Fallback to item-by-item if newline count shifted
            for orig in batch:
                results[orig] = self.translate(orig, src_lang=src_lang)
                time.sleep(0.04)

        return results
