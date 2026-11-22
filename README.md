# 全球自行車每日中文情報站

> 追蹤品牌、焦點、趨勢及熱門話題

基於 **GitHub Pages + GitHub Actions** 的全自動每日自行車產業情報系統，固定每天台灣時間 `07:00 CST` 自動抓取全球 **7 大權威自行車媒體**，將英文、德文與簡體中文統一翻譯為繁體中文，整理**品牌動態、賽事活動、新品發布與評測結論**；針對**整車（Complete Bike）**自動擷取實車圖片、多尺碼幾何與產品規格表，並完成參數化 3D 逆向工程（`.glb` + QA Manifest + Blender 4.x 攝影棚腳本）與每日中文簡報 `.pptx`（每頁頁尾標註來源）。

## 每日固定監測 7 大媒體

| 媒體 | 網址 | 語系處理 | 報導重點 |
| --- | --- | --- | --- |
| **Bikerumor** | https://bikerumor.com/ | 英文 → 繁體中文 | 全球自行車新品科技、整車首發、零組件 |
| **Pinkbike** | https://www.pinkbike.com/ | 英文 → 繁體中文 | MTB、Trail、Enduro、DH 深度實測與賽事 |
| **Cyclingnews** | https://www.cyclingnews.com/ | 英文 → 繁體中文 | UCI 公路大環賽、CX 世界盃、職業車隊與器材 |
| **eMTB-News.de** | https://www.emtb-news.de/news/ | 德文 → 繁體中文 | 德語區 e-MTB、電輔馬達系統、歐洲展會與召回 |
| **E-MOUNTAINBIKE** | https://ebike-mtb.com/en/ | 英文 → 繁體中文 | 深度 e-MTB / SUV 電輔整車實測、完整多尺碼幾何表 |
| **road.cc** | https://road.cc/ | 英文 → 繁體中文 | 英國公路車、Gravel、通勤器材評測與科技新聞 |
| **美騎網 Biketo** | https://www.biketo.com/ | 簡中 → 繁體中文 | 華語自行車產業動態、品牌贊助、賽事與新品 |

## 核心功能與架構

1. **英、德文統一翻譯為繁體中文（`pipeline/translator.py`）**
   - 所有來自英文（Bikerumor、Pinkbike、Cyclingnews、E-MOUNTAINBIKE）與德文（eMTB-News.de）的標題、摘要、幾何欄位名稱與 QA 檢核項目，皆自動翻譯並套用自行車專業術語詞庫統一為繁體中文。
2. **每日中文投影片簡報模式與 `.pptx` 匯出（`pipeline/slides_builder.py`）**
   - 網頁內建 16:9「投影片簡報模式」（支援鍵盤 `←`/`→` 切頁），並每日自動產生可下載的 `docs/data/daily_briefing.pptx`（含封面、核心結論、品牌排行、賽事追蹤、每台整車實車照＋3D 側視渲染圖＋規格幾何表）。
   - **每一張投影片頁尾皆固定標註原始資料來源與網址**（`資料來源：<媒體名稱>｜<完整網址>｜擷取日期｜頁次`）。
3. **每日產業結論（Executive Briefing）**
   - 自動彙整活躍品牌聲量排行（支援 120+ 整車、避震、傳動、電輔、輪組與職業車隊品牌）。
   - 自動追蹤 UCI 世界盃、三大環賽、CX 賽事、European Bike Show 等產業活動。
   - 針對產品評測、新品發布、電輔韌體更新與安全召回生成中文情報結論。
4. **整車圖片、幾何與產品參數表**
   - 自動辨識整車文章，優先解析原廠多尺碼 HTML 幾何表（支援英文與德文欄位如 `Lenkwinkel`, `Radstand`, `Kettenstrebe` 並自動中文化）與內文規格參數。
   - 每項幾何數據明確標記資料溯源等級：`實測／官方幾何表`、`官方規格數據`、`報導原文數據` 或 `級距比例推估`。
5. **參數化 3D 逆向工程流水線（`pipeline/reconstruct_3d.py`）**
   - 依抓取之實車幾何（Wheelbase、Reach、Stack、HTA、STA、Chainstay、BB Drop、Head/Seat Tube、前/後行程、輪徑、胎寬、碟盤直徑、是否為電輔／全避震／彎把或平把）以毫米精度建構 20+ 分件 PBR 3D 模型（`.glb`）。
   - 自動執行 **8 項幾何公差 QA 檢核**（輪胎接地 `Y=0`、軸距誤差、Reach/Stack 座標、頭管/立管角度、後下叉長度、曲柄離地高）並產出含 SHA256 雜湊與 Scope Qualifications 聲明的 `*_qa_manifest.json`。
   - 為每台車同步產出專屬 **Blender 4.x 棚拍腳本**（`*_blender_rebuild.py`），內建暖中性無縫背景棚（Warm Neutral Cyclorama）、AgX 色彩管理、三點柔光盤與 `01_side_drive` 至 `07_cockpit` 七視角正交相機陣列。
   - 網頁內建互動式 **Three.js 3D 棚拍檢視器**，支援七視角切換、正交／透視切換、PBR／Clay 黏土／Wireframe 檢視模式與 3D CAD 幾何標註線。

## 本地執行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pipeline.run_daily --docs-dir docs
python3 -m http.server 8080 --directory docs
```

## 使用輸出的 Blender 4.x 腳本渲染七視角正交棚拍圖

```bash
blender -b --python docs/models/<slug>_blender_rebuild.py -- \
  --glb docs/models/<slug>.glb \
  --out ./renders_<slug>
```
