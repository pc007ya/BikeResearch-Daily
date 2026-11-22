"""Generate a 16:9 Traditional Chinese daily cycling intelligence PowerPoint deck (.pptx)
with explicit source citations in every slide footer."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import requests
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

# Swiss Warm Neutral Cyclorama Palette (matching the GitHub Pages site & studio stage)
C_BG = RGBColor(0xF4, 0xF2, 0xEC)
C_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
C_SUBTLE = RGBColor(0xE8, 0xE4, 0xDA)
C_INK = RGBColor(0x17, 0x17, 0x15)
C_SEC = RGBColor(0x55, 0x53, 0x4C)
C_MUTED = RGBColor(0x78, 0x74, 0x6B)
C_ACCENT = RGBColor(0xC8, 0x4B, 0x28)
C_VERIFIED = RGBColor(0x1D, 0x63, 0x4F)
C_BORDER = RGBColor(0xD5, 0xD0, 0xC5)

FONT_ZH = "Microsoft JhengHei"
ALL_SOURCES_SHORT = (
    "Bikerumor、Pinkbike、Cyclingnews、eMTB-News.de、E-MOUNTAINBIKE、road.cc、美騎網 Biketo"
)


def _set_slide_bg(slide, color: RGBColor = C_BG) -> None:
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(
    slide,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    font_size: int = 12,
    bold: bool = False,
    color: RGBColor = C_INK,
    align: PP_ALIGN = PP_ALIGN.LEFT,
) -> Any:
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Pt(2)
    tf.margin_right = Pt(2)
    tf.margin_top = Pt(2)
    tf.margin_bottom = Pt(2)
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = FONT_ZH
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color
    return tb


def _add_card(slide, left: float, top: float, width: float, height: float, fill_color: RGBColor = C_WHITE) -> Any:
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shp.adjustments[0] = 0.04
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill_color
    shp.line.color.rgb = C_BORDER
    shp.line.width = Pt(0.75)
    return shp


def _add_header(slide, kicker: str, title: str, date_str: str) -> None:
    _add_textbox(slide, 0.55, 0.28, 9.0, 0.28, kicker, font_size=10, bold=True, color=C_ACCENT)
    _add_textbox(slide, 0.55, 0.52, 10.6, 0.50, title, font_size=22, bold=True, color=C_INK)
    _add_textbox(slide, 11.1, 0.35, 1.7, 0.35, date_str, font_size=10, bold=True, color=C_MUTED, align=PP_ALIGN.RIGHT)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.06), Inches(12.23), Inches(0.015))
    line.fill.solid()
    line.fill.fore_color.rgb = C_BORDER
    line.line.fill.background()


def _add_source_footer(slide, source_text: str, page_num: int, total_pages: int, date_str: str) -> None:
    """Render a consistent, clearly readable source citation bar in every slide footer."""
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.0), Inches(7.02), Inches(13.333), Inches(0.48))
    bar.fill.solid()
    bar.fill.fore_color.rgb = C_SUBTLE
    bar.line.fill.background()

    top_rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.0), Inches(7.02), Inches(13.333), Inches(0.015))
    top_rule.fill.solid()
    top_rule.fill.fore_color.rgb = C_BORDER
    top_rule.line.fill.background()

    footer_msg = f"資料來源：{source_text} ｜ 擷取日期：{date_str}"
    _add_textbox(slide, 0.50, 7.09, 11.1, 0.34, footer_msg[:155], font_size=8.5, bold=False, color=C_SEC)
    _add_textbox(
        slide,
        11.65,
        7.09,
        1.20,
        0.34,
        f"頁次 {page_num:02d} / {total_pages:02d}",
        font_size=8.5,
        bold=True,
        color=C_INK,
        align=PP_ALIGN.RIGHT,
    )


def _fetch_image_bytes(url: str) -> io.BytesIO | None:
    if not url or not url.startswith("http"):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200 or len(r.content) < 2000:
            return None
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((1100, 720))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=86)
        buf.seek(0)
        return buf
    except Exception:
        return None


def _style_table_cell(cell, text: str, font_size: int = 9.5, bold: bool = False, color: RGBColor = C_INK, bg: RGBColor | None = None) -> None:
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    if bg is not None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = bg
    tf = cell.text_frame
    tf.word_wrap = True
    tf.margin_left = Pt(5)
    tf.margin_right = Pt(5)
    tf.margin_top = Pt(3)
    tf.margin_bottom = Pt(3)
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = str(text)
    run.font.name = FONT_ZH
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color


def build_daily_pptx(report: dict[str, Any], docs_dir: Path, out_path: Path) -> Path:
    """Create complete 16:9 Traditional Chinese executive slide deck with source footers."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    date_str = report.get("date", "")
    summary = report.get("summary", {})
    counts = summary.get("counts", {})
    bikes = report.get("complete_bikes", [])
    # Prioritize top 8 bikes with highest measured geometry ratio for crisp deck length
    featured_bikes = sorted(bikes, key=lambda b: -(b.get("measured_ratio") or 0))[:8]
    total_pages = 6 + len(featured_bikes)
    page = 0

    # --- SLIDE 1: COVER ---
    page += 1
    s1 = prs.slides.add_slide(blank)
    _set_slide_bg(s1, C_BG)
    _add_textbox(s1, 0.75, 0.85, 8.0, 0.35, "每日全球自行車產業情報與 3D 逆向建模簡報", font_size=12, bold=True, color=C_ACCENT)
    _add_textbox(s1, 0.75, 1.32, 11.8, 1.15, "全球自行車每日中文情報站", font_size=38, bold=True, color=C_INK)
    _add_textbox(
        s1,
        0.75,
        2.55,
        11.5,
        0.65,
        f"追蹤品牌、焦點、趨勢及熱門話題 ｜ 報告日期：{report.get('generated_at_cst', date_str)}",
        font_size=15,
        color=C_SEC,
    )

    kpis = [
        ("七站抓取總篇數", str(counts.get("total_articles", 0))),
        ("整車 3D 逆向建模", str(counts.get("complete_bikes", 0))),
        ("活躍追蹤品牌", str(counts.get("brands_tracked", 0))),
        ("賽事與展會動態", str(counts.get("events_tracked", 0))),
        ("評測與新品發布", str(counts.get("reviews", 0) + counts.get("launches", 0))),
    ]
    for i, (lbl, val) in enumerate(kpis):
        x = 0.75 + i * 2.42
        _add_card(s1, x, 3.55, 2.24, 1.45, C_WHITE)
        _add_textbox(s1, x + 0.16, 3.72, 1.92, 0.35, lbl, font_size=11, color=C_SEC)
        _add_textbox(s1, x + 0.16, 4.12, 1.92, 0.65, val, font_size=30, bold=True, color=C_ACCENT if i == 1 else C_INK)

    _add_card(s1, 0.75, 5.28, 11.83, 1.35, C_WHITE)
    _add_textbox(s1, 0.95, 5.40, 11.4, 0.30, "本日七大監測媒體（英文／德文／簡中 → 統一繁體中文）", font_size=11, bold=True, color=C_INK)
    def _lang_lbl(l: str) -> str:
        return "德文轉繁中" if l == "de" else ("簡中轉繁中" if l.lower() == "zh-cn" else "英文轉繁中")
    src_line = "  ｜  ".join(
        f"{s['name']}（{s['item_count']} 篇 · {_lang_lbl(s['lang'])}）"
        for s in report.get("sources", [])
    )
    _add_textbox(s1, 0.95, 5.76, 11.4, 0.72, src_line, font_size=9.5, color=C_SEC)
    _add_source_footer(s1, ALL_SOURCES_SHORT, page, total_pages, date_str)

    # --- SLIDE 2: EXECUTIVE CONCLUSIONS ---
    page += 1
    s2 = prs.slides.add_slide(blank)
    _set_slide_bg(s2)
    _add_header(s2, "01 / 每日產業情報結論", "今日全球自行車產業核心結論（品牌・賽事・整車・召回）", date_str)

    conclusions = summary.get("conclusions", [])[:4]
    coords = [(0.55, 1.32), (6.80, 1.32), (0.55, 4.18), (6.80, 4.18)]
    for idx, item in enumerate(conclusions):
        x, y = coords[idx]
        _add_card(s2, x, y, 5.98, 2.62, C_WHITE)
        _add_textbox(s2, x + 0.22, y + 0.18, 5.5, 0.30, f"■ {item['tag']}", font_size=11, bold=True, color=C_ACCENT)
        _add_textbox(s2, x + 0.22, y + 0.52, 5.54, 0.72, item["title"], font_size=15, bold=True, color=C_INK)
        _add_textbox(s2, x + 0.22, y + 1.32, 5.54, 1.15, item["detail"], font_size=11.5, color=C_SEC)
    _add_source_footer(s2, ALL_SOURCES_SHORT, page, total_pages, date_str)

    # --- SLIDE 3: COMPONENT & MOTOR BRAND SHARE STATISTICS ---
    page += 1
    s_comp = prs.slides.add_slide(blank)
    _set_slide_bg(s_comp)
    _add_header(s_comp, "02 / 核心電機與零組件品牌佔比統計", "本日整車裝配品牌市佔：電機・前叉・變速・輪胎・輪組・煞車", date_str)
    comp_shares = summary.get("component_shares", [])[:6]
    grid_coords = [
        (0.55, 1.24), (4.68, 1.24), (8.81, 1.24),
        (0.55, 4.12), (4.68, 4.12), (8.81, 4.12),
    ]
    bar_colors = [C_ACCENT, C_VERIFIED, RGBColor(0x2B, 0x5B, 0x84), RGBColor(0xB8, 0x7A, 0x1E), C_SEC]
    for idx, cat in enumerate(comp_shares):
        cx, cy = grid_coords[idx]
        _add_card(s_comp, cx, cy, 3.97, 2.72, C_WHITE)
        _add_textbox(
            s_comp, cx + 0.18, cy + 0.14, 2.45, 0.30,
            f"{cat['label_zh']} ({cat['en']})",
            font_size=11, bold=True, color=C_INK,
        )
        _add_textbox(
            s_comp, cx + 2.55, cy + 0.14, 1.26, 0.28,
            f"樣本 {cat['sample_count']}/{cat['eligible_count']} 台",
            font_size=8.5, bold=True, color=C_MUTED, align=PP_ALIGN.RIGHT,
        )
        brands_list = cat.get("brands", [])[:5]
        if not brands_list:
            _add_textbox(s_comp, cx + 0.18, cy + 1.10, 3.60, 0.40, "本日報導未揭露此項配件品牌", font_size=9.5, color=C_MUTED)
        else:
            for bi, br in enumerate(brands_list):
                ry = cy + 0.54 + bi * 0.41
                _add_textbox(s_comp, cx + 0.18, ry, 2.25, 0.24, br["brand"], font_size=9.2, bold=True, color=C_INK)
                _add_textbox(
                    s_comp, cx + 2.45, ry, 1.35, 0.24,
                    f"{br['share_pct']:.1f}% ({br['count']}台)",
                    font_size=8.8, bold=True, color=C_ACCENT if bi == 0 else C_SEC, align=PP_ALIGN.RIGHT,
                )
                # Background track
                track = s_comp.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(cx + 0.18), Inches(ry + 0.24), Inches(3.60), Inches(0.08))
                track.fill.solid()
                track.fill.fore_color.rgb = C_SUBTLE
                track.line.fill.background()
                # Fill bar
                bw = max(0.08, 3.60 * (br["share_pct"] / 100.0))
                fill_b = s_comp.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(cx + 0.18), Inches(ry + 0.24), Inches(bw), Inches(0.08))
                fill_b.fill.solid()
                fill_b.fill.fore_color.rgb = bar_colors[bi % len(bar_colors)]
                fill_b.line.fill.background()
    _add_source_footer(s_comp, ALL_SOURCES_SHORT, page, total_pages, date_str)

    # --- SLIDE 4: TOP BRANDS ---
    page += 1
    s3 = prs.slides.add_slide(blank)
    _set_slide_bg(s3)
    _add_header(s3, "03 / 品牌動態排行", "本日高聲量品牌與重點動作總表（全中文彙整）", date_str)
    top_brands = summary.get("top_brands", [])[:10]
    tbl_shape = s3.shapes.add_table(len(top_brands) + 1, 5, Inches(0.55), Inches(1.26), Inches(12.23), Inches(5.45))
    tbl = tbl_shape.table
    widths = [0.75, 1.95, 1.45, 1.55, 6.53]
    for ci, w in enumerate(widths):
        tbl.columns[ci].width = Inches(w)
    headers = ["排名", "品牌名稱", "品牌定位", "動態訊號", "代表報導中文摘要與來源"]
    for ci, h in enumerate(headers):
        _style_table_cell(tbl.cell(0, ci), h, font_size=10, bold=True, color=C_WHITE, bg=C_INK)
    for ri, b in enumerate(top_brands, start=1):
        bg = C_WHITE if ri % 2 == 1 else C_BG
        rep = b.get("articles", [{}])[0]
        rep_txt = f"[{rep.get('source','')}] {rep.get('title_zh') or rep.get('title','')}"
        _style_table_cell(tbl.cell(ri, 0), f"{ri:02d} ({b['mentions']}則)", font_size=9.5, bold=True, bg=bg)
        _style_table_cell(tbl.cell(ri, 1), b["name"], font_size=10, bold=True, bg=bg)
        _style_table_cell(tbl.cell(ri, 2), b["type"], font_size=9.5, color=C_SEC, bg=bg)
        _style_table_cell(tbl.cell(ri, 3), " / ".join(b.get("signals", [])[:2]), font_size=9.5, color=C_ACCENT, bg=bg)
        _style_table_cell(tbl.cell(ri, 4), rep_txt[:95], font_size=9.5, bg=bg)
    _add_source_footer(s3, ALL_SOURCES_SHORT, page, total_pages, date_str)

    # --- SLIDE 5: RACES & EVENTS ---
    page += 1
    s4 = prs.slides.add_slide(blank)
    _set_slide_bg(s4)
    _add_header(s4, "04 / 賽事與產業展會", "全球賽事戰報、車隊陣容與產業活動追蹤", date_str)
    events = summary.get("events", [])[:9]
    if events:
        t4_shape = s4.shapes.add_table(len(events) + 1, 4, Inches(0.55), Inches(1.26), Inches(12.23), Inches(5.45))
        t4 = t4_shape.table
        for ci, w in enumerate([3.0, 1.55, 1.75, 5.93]):
            t4.columns[ci].width = Inches(w)
        for ci, h in enumerate(["賽事／活動名稱", "活動類型", "報導媒體", "重點報導中文標題"]):
            _style_table_cell(t4.cell(0, ci), h, font_size=10, bold=True, color=C_WHITE, bg=C_INK)
        for ri, ev in enumerate(events, start=1):
            bg = C_WHITE if ri % 2 == 1 else C_BG
            hl = ev.get("headlines", [{}])[0]
            hl_txt = hl.get("title_zh") or hl.get("title", "")
            _style_table_cell(t4.cell(ri, 0), ev["name"], font_size=9.5, bold=True, bg=bg)
            _style_table_cell(t4.cell(ri, 1), ev["kind"], font_size=9.5, color=C_ACCENT, bg=bg)
            _style_table_cell(t4.cell(ri, 2), "、".join(ev.get("sources", [])), font_size=9, color=C_SEC, bg=bg)
            _style_table_cell(t4.cell(ri, 3), hl_txt[:95], font_size=9.5, bg=bg)
    else:
        _add_textbox(s4, 0.7, 2.0, 10.0, 0.6, "本日尚無新增賽事或展會動態。", font_size=14, color=C_SEC)
    _add_source_footer(s4, ALL_SOURCES_SHORT, page, total_pages, date_str)

    # --- SLIDES 5..N: COMPLETE BIKES + PARAMETRIC 3D REVERSE ENGINEERING ---
    for bike in featured_bikes:
        page += 1
        sb = prs.slides.add_slide(blank)
        _set_slide_bg(sb)
        pct = int(round((bike.get("measured_ratio") or 0) * 100))
        m3d = bike.get("model_3d", {})
        _add_header(
            sb,
            f"04 / 整車規格與參數化 3D 逆向建模 ｜ 實測幾何 {pct}% ｜ QA {m3d.get('qa_pass_count',0)}/{m3d.get('qa_total_count',8)} 通過",
            f"{bike['brand']} — {bike['model_name']}（{bike['category_zh']}）",
            date_str,
        )

        # Left Top: Real scraped photo
        _add_card(sb, 0.55, 1.24, 5.55, 2.75, C_WHITE)
        _add_textbox(sb, 0.70, 1.30, 5.2, 0.25, f"來源實車照片（{bike['source_name']}）", font_size=9.5, bold=True, color=C_SEC)
        photo_bytes = _fetch_image_bytes(bike.get("hero_image", ""))
        if photo_bytes is not None:
            sb.shapes.add_picture(photo_bytes, Inches(0.70), Inches(1.58), width=Inches(5.25), height=Inches(2.30))
        else:
            _add_textbox(sb, 0.80, 2.40, 5.0, 0.5, "（原站圖片無法即時內嵌，請點擊網頁檢視）", font_size=10, color=C_MUTED, align=PP_ALIGN.CENTER)

        # Left Bottom: Parametric 3D Reverse Engineered orthographic side render
        _add_card(sb, 0.55, 4.10, 5.55, 2.76, C_WHITE)
        _add_textbox(
            sb,
            0.70,
            4.16,
            5.25,
            0.25,
            f"3D 逆向工程正交側視圖（{m3d.get('object_count',0)} 分件 · 尺碼 {bike.get('default_size','L')}）",
            font_size=9.5,
            bold=True,
            color=C_VERIFIED,
        )
        preview_rel = m3d.get("preview_image", "")
        preview_abs = docs_dir / preview_rel if preview_rel else None
        if preview_abs and preview_abs.exists():
            sb.shapes.add_picture(str(preview_abs), Inches(0.70), Inches(4.44), width=Inches(5.25), height=Inches(2.32))

        # Right Top: Product Specs Table (ZH-TW)
        specs = bike.get("specs", {})
        spec_rows = [
            ("車款分類", bike.get("category_zh", "—")),
            ("車架材質", specs.get("frame_material", "碳纖維 / 鋁合金（依規格）")),
            ("輪徑 / 胎寬", f"{specs.get('wheel_size', str(bike['geometry_resolved']['wheel_front_in']) + ' 吋')} / {bike['geometry_resolved']['tire_width_mm']} mm"),
            ("前 / 後避震行程", f"{bike['geometry_resolved']['travel_front_mm']:.0f} mm / {bike['geometry_resolved']['travel_rear_mm']:.0f} mm"),
            ("電輔馬達 / 電池", f"{specs.get('motor', '無（純人力）')} / {specs.get('battery', '—')}"),
            ("傳動 / 煞車系統", f"{specs.get('drivetrain', '—')} ｜ {specs.get('brakes', '—')}"),
            ("重量 / 參考售價", f"{specs.get('weight', '—')} ｜ {specs.get('price', '—')}"),
        ]
        st_shape = sb.shapes.add_table(len(spec_rows) + 1, 2, Inches(6.28), Inches(1.24), Inches(6.50), Inches(2.75))
        st = st_shape.table
        st.columns[0].width = Inches(1.85)
        st.columns[1].width = Inches(4.65)
        _style_table_cell(st.cell(0, 0), "產品規格項目", font_size=9.5, bold=True, color=C_WHITE, bg=C_INK)
        _style_table_cell(st.cell(0, 1), "擷取參數（全中文對照）", font_size=9.5, bold=True, color=C_WHITE, bg=C_INK)
        for ri, (k, v) in enumerate(spec_rows, start=1):
            bg = C_WHITE if ri % 2 == 1 else C_BG
            _style_table_cell(st.cell(ri, 0), k, font_size=9, bold=True, color=C_SEC, bg=bg)
            _style_table_cell(st.cell(ri, 1), str(v)[:62], font_size=9, bg=bg)

        # Right Bottom: Geometry Table with Provenance
        geo = bike.get("geometry_resolved", {})
        prov = bike.get("geometry_provenance", {})

        def _p(key: str) -> str:
            return "實測/官方" if str(prov.get(key, "")).startswith("measured") else "級距推估"

        geo_rows = [
            ("前後軸距 (Wheelbase)", f"{geo['wheelbase_mm']:.0f} mm", _p("wheelbase_mm")),
            ("前伸量 (Reach)", f"{geo['reach_mm']:.0f} mm", _p("reach_mm")),
            ("堆疊高度 (Stack)", f"{geo['stack_mm']:.0f} mm", _p("stack_mm")),
            ("頭管角度 (HTA)", f"{geo['head_angle_deg']:.2f}°", _p("head_angle_deg")),
            ("立管角度 (STA)", f"{geo['seat_angle_deg']:.2f}°", _p("seat_angle_deg")),
            ("後下叉長度 (Chainstay)", f"{geo['chainstay_mm']:.0f} mm", _p("chainstay_mm")),
            ("五通下沉量 (BB Drop)", f"{geo['bb_drop_mm']:.0f} mm", _p("bb_drop_mm")),
        ]
        gt_shape = sb.shapes.add_table(len(geo_rows) + 1, 3, Inches(6.28), Inches(4.10), Inches(6.50), Inches(2.76))
        gt = gt_shape.table
        gt.columns[0].width = Inches(2.65)
        gt.columns[1].width = Inches(1.95)
        gt.columns[2].width = Inches(1.90)
        _style_table_cell(gt.cell(0, 0), f"3D 建模幾何參數（Size {bike.get('default_size','L')}）", font_size=9.5, bold=True, color=C_WHITE, bg=C_INK)
        _style_table_cell(gt.cell(0, 1), "數值", font_size=9.5, bold=True, color=C_WHITE, bg=C_INK)
        _style_table_cell(gt.cell(0, 2), "資料溯源", font_size=9.5, bold=True, color=C_WHITE, bg=C_INK)
        for ri, (k, v, p_lbl) in enumerate(geo_rows, start=1):
            bg = C_WHITE if ri % 2 == 1 else C_BG
            p_col = C_VERIFIED if p_lbl == "實測/官方" else C_ACCENT
            _style_table_cell(gt.cell(ri, 0), k, font_size=9, bold=True, bg=bg)
            _style_table_cell(gt.cell(ri, 1), v, font_size=9, bold=True, bg=bg)
            _style_table_cell(gt.cell(ri, 2), p_lbl, font_size=9, bold=True, color=p_col, bg=bg)

        # Slide footer explicitly citing this specific bike's source media & URL!
        _add_source_footer(sb, f"{bike['source_name']} ｜ {bike['url']}", page, total_pages, date_str)

    # --- LAST SLIDE: REVIEWS, LAUNCHES & RECALLS HIGHLIGHTS ---
    page += 1
    slast = prs.slides.add_slide(blank)
    _set_slide_bg(slast)
    _add_header(slast, "05 / 評測、零組件新品與安全警示精選", "本日重要產品評測、電輔更新與召回公告（全中文翻譯）", date_str)
    highlights = [
        a for a in report.get("articles", [])
        if a["classification"]["signal"] in ("召回警示", "產品評測", "新品/動態")
    ][:9]
    th_shape = slast.shapes.add_table(len(highlights) + 1, 4, Inches(0.55), Inches(1.26), Inches(12.23), Inches(5.45))
    th = th_shape.table
    for ci, w in enumerate([1.55, 1.35, 5.25, 4.08]):
        th.columns[ci].width = Inches(w)
    for ci, h in enumerate(["媒體來源", "動態標籤", "中文翻譯標題", "產業結論摘要"]):
        _style_table_cell(th.cell(0, ci), h, font_size=10, bold=True, color=C_WHITE, bg=C_INK)
    for ri, a in enumerate(highlights, start=1):
        bg = C_WHITE if ri % 2 == 1 else C_BG
        sig = a["classification"]["signal"]
        _style_table_cell(th.cell(ri, 0), a["source_name"], font_size=9, bold=True, bg=bg)
        _style_table_cell(th.cell(ri, 1), sig, font_size=9, bold=True, color=C_ACCENT if sig == "召回警示" else C_VERIFIED, bg=bg)
        _style_table_cell(th.cell(ri, 2), (a.get("title_zh") or a["title"])[:65], font_size=9, bold=True, bg=bg)
        _style_table_cell(th.cell(ri, 3), a.get("takeaway_zh", "")[:62], font_size=8.8, color=C_SEC, bg=bg)
    _add_source_footer(slast, ALL_SOURCES_SHORT, page, total_pages, date_str)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path
