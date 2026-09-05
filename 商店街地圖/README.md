# 商店街地圖

一張自己控制的離線地圖：把**商店街與商場畫成半透明範圍色塊**（而不是一個點），
標自己的店、表達「店在商場裡」的階層，一鍵丟給 Google Maps 導航。

完整的需求分析、技術取捨與規格在 **[SPEC.md](SPEC.md)**。

## 直接使用

```
takamatsu_map.html            ← 開這個。單一檔案，離線可用
```

用瀏覽器打開（手機可先傳到手機再用檔案 App 開，或放進 iCloud/Google Drive）。
沒有網路也能完整運作 —— 地圖、範圍色塊、標記、階層全都內嵌在檔案裡。
只有「導航」按鈕會離開 App 去叫 Google Maps。

`takamatsu_map.artifact.html` 是同一份東西的 body-only 版本，給 Claude Artifact 發佈用。

## 操作

| 動作 | 結果 |
| --- | --- |
| 單指拖曳 / 雙指縮放 | 平移、縮放（放開有慣性） |
| 點色塊 | 底部面板顯示該商店街／商場，含麵包屑與裡面的標記 |
| 點圖釘 | 顯示該店詳情 + 導航按鈕 |
| **長按地圖** | 在該位置新增標記（自動判斷落在哪個範圍內） |
| 頂部分類 chips | 篩選要顯示的分類 |
| 搜尋框 | 中／日文名稱即時搜尋 |
| ⌖ | 我的位置（需 HTTPS 或本機檔案授權） |
| ☰ | 圖層開關、匯出／匯入 JSON |

新增與修改存在**這台裝置的 localStorage**，換一版 HTML 不會消失。
要永久保存就用 ☰ → 匯出 JSON，貼回 `data/takamatsu.json` 後重跑 build。

## 重新產生

三步，都只用 Python 標準函式庫，不需要 pip install：

```bash
cd 商店街地圖

# 1. 從 OpenStreetMap 抓幾何（需網路；逐圖層快取在 data/.cache/，可中斷續跑）
python3 tools/fetch_osm.py takamatsu

# 2. 由海岸線推導出可填色的海域多邊形
python3 tools/derive_sea.py takamatsu

# 3. 把散落的 OSM 線段整理成有階層的商店街／商場
python3 tools/make_areas.py takamatsu

# 4.（選用）加入標記，自動判斷它落在哪個商店街／商場裡
python3 tools/add_pois.py takamatsu data/takamatsu_pois.seed.json

# 5. 打包成單一 HTML
python3 tools/build.py takamatsu
```

第 4 步的 `add_pois.py` 是**之後匯入你自己的點**要走的路徑。輸入是一個 JSON 陣列，
每筆需要名稱，加上 `coord: [lon, lat]` 或 `osm: "way/123"`（指向已抓下來的 OSM 元素），
其餘欄位（`cat`／`floor`／`note`／`url`／`hours`）照抄。
`parent` 不用填 —— 它會自己算：先看點落在哪個商場多邊形裡（取最小的那個），
沒有的話再找最近、且距離在「中心線 ± 寬度/2 + 8 公尺」內的商店街。

## 測試

```bash
python3 tools/test_derive_sea.py         # 海域封閉的幾何邏輯
npm i playwright && node tools/test_app.js   # 建置後的 App 端對端行為
```

`test_app.js` 會真的開一個手機尺寸的瀏覽器，檢查階層麵包屑、樓層分組、長按新增與
自動歸屬、搜尋（中日文）、導航 URL 格式、重新載入後編輯是否保留、匯出往返，
以及**整個 App 是否真的零外部網路請求**。

想加城市：在 `tools/fetch_osm.py` 的 `CITIES` 加 bbox，
在 `tools/make_areas.py` 的 `CITY_CONFIG` 加階層設定，然後跑同樣四步。
`marugame`（丸亀）的 bbox 已經預留好了。

## 檔案

```
SPEC.md                       需求分析與規格
takamatsu_map.html            成品（單檔、離線）
takamatsu_map.artifact.html   成品（Artifact 用的 body-only 版）
src/app.template.html         App 原始碼（HTML/CSS/JS，資料以佔位符注入）
data/
  takamatsu.json              ★ 策劃過的範圍 + 我的標記（要手改就改這個）
  takamatsu_pois.seed.json    示範標記的輸入範例
  takamatsu_basemap.json      底圖幾何（機器產生，別手改）
  takamatsu_areas.osm.json    OSM 原始候選（機器產生）
  .cache/                     Overpass 原始回應快取（git 忽略）
tools/
  fetch_osm.py                Overpass 下載
  derive_sea.py               海岸線 → 海域多邊形
  make_areas.py               OSM 線段 → 階層化商店街
  add_pois.py                 加入標記並自動判斷所屬範圍
  build.py                    模板 + 資料 → 單一 HTML
  test_derive_sea.py          海域幾何測試
  test_app.js                 App 端對端測試（需 playwright）
```

## 目前的高松資料

`高松中央商店街`（8 段拱廊）＋ 5 個商場，全部來自 OSM 實際幾何：

```
高松中央商店街
├── 兵庫町商店街    ├── 片原町商店街    ├── 南新町商店街
├── 常磐町商店街    ├── 田町商店街      ├── 獅子通商店街
├── 常盤街
└── 丸龜町商店街 ── 463 m
    ├── 丸龜町壹番街（東館＋西館）
    ├── 丸龜町參番街（東館＋西館）
    ├── 丸龜町 GREEN（東館＋西館，商店街從兩棟之間穿過）
    └── 高松三越
海洋廣場高松（サンポート，獨立）
```

標記目前只有 8 個示範點（`（示範）樓層標記` 是用來展示樓層分組的，可刪）。

## 為什麼不是 Leaflet + OSM 圖磚

三個需求同時成立時，圖磚方案會壞掉：

1. **離線** —— 圖磚要嘛連網，要嘛預先下載幾千張（且違反 OSM 的使用政策）。
2. **能在 Claude Artifact 跑** —— Artifact 的 CSP 封鎖所有外部圖片與 fetch，
   圖磚會靜默失敗變成全黑。
3. **不要 Google 那些廣告雜訊** —— 用別人的圖磚就是用別人的樣式。

所以底圖改成**內嵌的 OSM 向量幾何 + Canvas 自繪**：約 0.6 MB、連續縮放不失真、
樣式 100% 自己決定、零外部請求。線上圖磚保留成一個可選圖層（☰ 裡切換），
在本機開檔時可用，在 Artifact 中會自動偵測失敗並切回向量。

## 授權

幾何資料來自 OpenStreetMap，授權 [ODbL](https://www.openstreetmap.org/copyright)。
App 內已顯示出處，散布時請保留。
