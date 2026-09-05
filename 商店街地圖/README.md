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

# 4. 打包成單一 HTML
python3 tools/build.py takamatsu
```

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
  takamatsu_basemap.json      底圖幾何（機器產生，別手改）
  takamatsu_areas.osm.json    OSM 原始候選（機器產生）
  .cache/                     Overpass 原始回應快取（git 忽略）
tools/
  fetch_osm.py                Overpass 下載
  derive_sea.py               海岸線 → 海域多邊形
  make_areas.py               OSM 線段 → 階層化商店街
  build.py                    模板 + 資料 → 單一 HTML
```

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
