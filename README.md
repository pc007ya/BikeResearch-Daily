# VELO·INTEL 3D — 全球自行車每日情報與 ALSO 規範 3D 逆向工程站

基於 **GitHub Pages + GitHub Actions** 的全自動每日自行車產業情報系統，固定每天台灣時間 `07:00 CST` 自動抓取全球 5 大權威自行車媒體，整理**品牌動態、賽事活動、新品發布與評測結論**；一旦偵測到**整車（Complete Bike）**報導，自動擷取實車圖片、多尺碼幾何與產品規格表，並參照 **ALSO_BIKE 建模與驗證規範** 完成參數化 3D 逆向工程（`.glb` + QA Manifest + Blender 4.x 攝影棚腳本）。

## 每日固定監測 5 大媒體

| 媒體 | 網址 | 報導重點 |
| --- | --- | --- |
| **Bikerumor** | https://bikerumor.com/ | 全球自行車新品科技、整車首發、零組件 |
| **Pinkbike** | https://www.pinkbike.com/ | MTB、Trail、Enduro、DH 深度實測與賽事 |
| **Cyclingnews** | https://www.cyclingnews.com/ | UCI 公路大環賽、CX 世界盃、職業車隊與器材 |
| **eMTB-News.de** | https://www.emtb-news.de/news/ | 德語區 e-MTB、電輔馬達系統、歐洲展會與召回 |
| **E-MOUNTAINBIKE** | https://ebike-mtb.com/en/ | 深度 e-MTB / SUV 電輔整車實測、完整多尺碼幾何表 |

## 核心功能與架構

1. **每日產業結論（Executive Briefing）**
   - 自動彙整活躍品牌聲量排行（支援 120+ 整車、避震、傳動、電輔、輪組與職業車隊品牌）。
   - 自動追蹤 UCI 世界盃、三大環賽、CX 賽事、European Bike Show 等產業活動。
   - 針對產品評測、新品發布、電輔韌體更新與安全召回生成中文情報結論。
2. **整車圖片、幾何與產品參數表**
   - 自動辨識整車文章，優先解析原廠多尺碼 HTML 幾何表（支援英文與德文欄位如 `Lenkwinkel`, `Radstand`, `Kettenstrebe`）與內文規格參數。
   - 每項幾何數據明確標記資料溯源等級：`實測/官方幾何表`、`官方規格數據`、`報導原文數據` 或 `級距比例推估`。
3. **ALSO_BIKE 規範 3D 逆向工程流水線（`pipeline/reconstruct_3d.py`）**
   - 依抓取之實車幾何（Wheelbase、Reach、Stack、HTA、STA、Chainstay、BB Drop、Head/Seat Tube、前/後行程、輪徑、胎寬、碟盤直徑、是否為電輔／全避震／彎把或平把）以毫米精度建構 20+ 分件 PBR 3D 模型（`.glb`）。
   - 自動執行 **8 項幾何公差 QA 檢核**（輪胎接地 `Y=0`、軸距誤差、Reach/Stack 座標、頭管/立管角度、後下叉長度、曲柄離地高）並產出含 SHA256 雜湊與 Scope Qualifications 聲明的 `*_qa_manifest.json`。
   - 為每台車同步產出對齊 `ALSO_BIKE` 規範的 **Blender 4.x 腳本**（`*_blender_rebuild.py`），內建暖中性無縫背景棚（Warm Neutral Cyclorama）、AgX 色彩管理、三點柔光盤與 `01_side_drive` 至 `07_cockpit` 七視角正交相機陣列。
   - 網頁內建互動式 **Three.js ALSO Studio 3D 檢視器**，支援七視角切換、正交／透視切換、PBR／Clay 黏土／Wireframe 檢視模式與 3D CAD 幾何標註線。

## 本地執行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pipeline.run_daily --docs-dir docs
python3 -m http.server 8080 --directory docs
```

## 使用輸出的 Blender 4.x 腳本渲染 ALSO 棚拍七視角

```bash
blender -b --python docs/models/<slug>_blender_rebuild.py -- \
  --glb docs/models/<slug>.glb \
  --out ./renders_<slug>
```
