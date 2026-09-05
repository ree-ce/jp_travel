# 商店街地圖 App — 需求分析與規格

> 目標：一張**沒有廣告雜訊**的手機地圖，能把「商店街／大賣場」畫成**半透明色塊範圍**（而不是一個點），
> 能收藏並分類自己的點，能表達「這家店在這個商場／商店街裡面」的階層，並一鍵丟給 Google Maps 導航。
>
> POC 範圍：**高松**。之後可加丸亀等城市。

---

## 1. 需求分析

### 1.1 核心痛點

| 痛點 | 對應設計 |
| --- | --- |
| Google Maps 塞滿它想推銷的東西 | 自繪向量底圖，**只畫我們要的圖層**；沒有贊助標記、沒有評分星星 |
| 商店街／賣場是「一塊」不是「一個點」 | 面資料模型（帶狀 / 多邊形），半透明色塊疊加 |
| 店在商場裡，看不出從屬關係 | `parent` 階層 + 麵包屑 + 樓層欄位 |
| 出國沒網路 | 單一 HTML 全內嵌，開檔即用，零外部請求 |
| 手機操作 | 全螢幕地圖 + 可拖曳底部面板 + 拇指區 FAB |

### 1.2 使用情境

1. **行前規劃**（電腦）：把想去的店輸入／匯入，歸到某條商店街或某個商場底下。
2. **現場使用**（手機、可能沒網路）：開檔 → 看到自己在哪 → 看商店街範圍 → 點色塊看裡面有哪幾家我標的店 → 按導航 → 跳出 Google Maps 走路模式。
3. **臨時新增**（手機）：路上看到想記的店，長按地圖新增點，之後匯出 JSON 回存 repo。

### 1.3 明確**不做**的事（避免範圍膨脹）

- 不做路線規劃／步行導航本身 —— 交給 Google Maps app。
- 不做即時營業狀態、評分、照片牆。
- 不做多人同步／帳號。
- 不做全日本涵蓋；一個城市一份資料檔。

---

## 2. 技術選型與取捨

### 2.1 底圖：三個選項的實測結論

| 方案 | 離線 | 縮放品質 | 樣式可控 | 疊色塊 | 體積 | 在 Claude Artifact 可用 |
| --- | --- | --- | --- | --- | --- | --- |
| A. 線上 OSM raster 圖磚 | ✗ | 固定級數、放大糊 | ✗（別人的樣式） | ○ | 0 | **✗ 被 CSP 擋** |
| B. 離線 PMTiles 向量 | ✓ | 連續、銳利 | ✓ | ✓ | 15–20 MB | **✗ 需 fetch，被擋** |
| C. 截圖底圖 | ✓ | 只有 3–4 級、放大糊 | ○ | ○ | 2–5 MB | △（需 base64 內嵌） |
| **D. 內嵌向量自繪（採用）** | ✓ | 連續、永遠銳利 | ✓✓ 完全 | ✓✓ | **~0.6 MB** | **✓** |

**決定：以 D 為主，A 為可選加值層。**

原本你選的是「先線上 OSM，之後再離線化」，但同時要求「能在 Claude Artifact 跑」。
這兩者互斥 —— Artifact 的 CSP 只允許從 cdnjs/jsdelivr 載**腳本**，
外部**圖片、fetch、XHR 一律封鎖**，所以 `tile.openstreetmap.org` 的圖磚在 Artifact 裡會全黑且無錯誤訊息。

解法是把順序顛倒過來：**先做離線的內嵌向量底圖**（本來就是最終目標），
再把線上圖磚當成一個「本機開啟時可用」的可選圖層。這樣兩個需求都滿足，而且不用做兩次。

實作上這也不繞遠路：我們本來就要從 Overpass 抓商店街的線，
順手多抓海岸線／水域／鐵路／道路／公園／有名建物，就是一份底圖，總共 ~0.6 MB。

> **重要**：不用 Leaflet 或 MapLibre。它們的價值在圖磚管理，而我們沒有圖磚；
> 且 Leaflet 的 CSS 在 Artifact 也載不進來。改用 **Canvas 2D 自繪 + 自寫 Web Mercator 投影**，
> 約 400 行，換來 100% 樣式控制與零外部相依。

### 2.2 商店街「面」怎麼來 —— 一個關鍵發現

OSM 裡商店街**不是多邊形**，而是 `highway=pedestrian` + `covered=arcade` 的**線**：

```
way/466231921  兵庫町商店街    covered=arcade
way/62159669   高松丸亀町商店街  covered=arcade
way/62159670   南新町商店街    covered=arcade
way/44419402   片原町商店街    covered=arcade
way/44419401   田町商店街     covered=arcade
way/150725761  常磐町商店街    covered=arcade
```

要變成色塊有兩條路：

- ❌ 離線把線 buffer 成多邊形 → 需要 shapely（環境沒有），且相鄰段落要做聯集，麻煩。
- ✅ **存「線 + 寬度（公尺）」，在瀏覽器用粗線條畫**（`lineCap/lineJoin = round`，半透明填色）。
  瀏覽器的描邊天生就是 buffer，轉角自動圓角、重疊自動聯集，
  而且寬度用「公尺 → 像素」換算，縮放時範圍才會正確跟著變。

商場（丸亀町グリーン、ゆめタウン、瓦町 FLAG…）在 OSM 是真正的多邊形，直接填色。

所以資料模型有兩種「面」：

| kind | 幾何 | 畫法 |
| --- | --- | --- |
| `arcade` 商店街 | LineString / MultiLineString + `width_m` | 半透明粗描邊 |
| `mall` 商場／賣場 | Polygon | 半透明填色 + 實線外框 |
| `group` 商店街群 | 無幾何（只是容器） | 不畫，只出現在麵包屑 |

### 2.3 階層 —— 高松剛好是最好的例子

`高松中央商店街` 是全日本最長的拱廊街（約 2.7 km），本身是**一群**商店街的合稱；
而 `丸亀町グリーン` 是蓋在 `高松丸亀町商店街` 上的商場。天然三層：

```
高松中央商店街 (group)
├── 兵庫町商店街 (arcade)
├── 片原町商店街 (arcade)
├── 高松丸亀町商店街 (arcade)
│   ├── 丸亀町グリーン (mall)      ← 商場在商店街裡
│   │   └── 〈某家店〉 3F          ← 店在商場裡，還有樓層
│   └── 〈某家店〉                  ← 店直接在商店街上
├── 南新町商店街 (arcade)
├── 田町商店街 (arcade)
└── 常磐町商店街 (arcade)

ゆめタウン高松 (mall, 無 parent)
```

用單一 `parent` 欄位（自我參照）表達，深度不限。UI 上：

- 點色塊 → 底部面板顯示 **麵包屑**（`高松中央商店街 › 丸亀町商店街 › 丸亀町グリーン`）
- 面板列出**子項**（子商店街／子商場）與**所屬的點**，點依樓層分組（`B1 / 1F / 2F …`）

### 2.4 為何不用截圖底圖

- 只能給 3–4 級縮放，放大就糊；商店街內部要看店家位置時解析度不夠。
- 每加一個城市都要重做一次，且無法用程式產生。
- **不能用 Google Maps 截圖**（授權問題）；OSM 截圖則不如直接用它的向量資料。

---

## 3. 規格

### 3.1 資料模型

單一 JSON，可拆城市。`商店街地圖/data/takamatsu.json`：

```jsonc
{
  "meta": {
    "city": "takamatsu",
    "name_zh": "高松",
    "center": [134.0497, 34.3430],   // [lon, lat]
    "zoom": 15.6,
    "schema": 1
  },
  "areas": [
    {
      "id": "GRP-CENTRAL",
      "kind": "group",                // group | arcade | mall
      "name_ja": "高松中央商店街",
      "name_zh": "高松中央商店街",
      "parent": null,
      "note": "日本最長拱廊商店街，全長約 2.7 km",
      "color": "arcade"               // 對應樣式色票
    },
    {
      "id": "ARC-MARUGAMEMACHI",
      "kind": "arcade",
      "name_ja": "高松丸亀町商店街",
      "name_zh": "丸龜町商店街",
      "parent": "GRP-CENTRAL",
      "width_m": 16,                  // 拱廊實際寬度，決定色塊粗細
      "geometry": { "type": "MultiLineString", "coordinates": [ /* … */ ] },
      "source": "OSM way/62159669"
    },
    {
      "id": "MALL-GREEN",
      "kind": "mall",
      "name_ja": "丸亀町グリーン",
      "name_zh": "丸龜町 GREEN",
      "parent": "ARC-MARUGAMEMACHI",
      "floors": ["B1", "1F", "2F", "3F", "4F"],
      "geometry": { "type": "Polygon", "coordinates": [ /* … */ ] }
    }
  ],
  "pois": [
    {
      "id": "P001",
      "name_ja": "瀬戸の祭寿し 兵庫町店",
      "name_zh": "瀨戶祭壽司 兵庫町店",
      "cat": "restaurant",            // 見 3.2
      "coord": [134.0480, 34.3466],
      "parent": "ARC-HYOGOMACHI",     // 可為 null（獨立點）
      "floor": null,                  // 在商場內時填 "3F"
      "note": "迴轉壽司・¥100 起",
      "url": "https://…",
      "hours": "11:00-22:00",
      "fav": false
    }
  ]
}
```

**設計理由**

- `parent` 用 id 字串而非巢狀結構 → 好編輯、好 diff、階層調整不用搬移大段 JSON。
- 幾何用標準 GeoJSON 子集 → 可貼進 geojson.io 檢視／編修。
- `width_m` 存**現實寬度**而非像素，縮放才正確。
- POI 與 area 分開兩個陣列，因為它們的編輯頻率差很多（面幾乎不動，點常改）。

### 3.2 分類

| key | 中文 | 圖示 | 色 |
| --- | --- | --- | --- |
| `restaurant` | 餐廳 | 🍜 | 橘 |
| `shop` | 商店 | 🛍️ | 藍 |
| `cafe` | 咖啡／甜點 | ☕ | 棕 |
| `sight` | 景點 | ⛩️ | 綠 |
| `hotel` | 住宿 | 🛏️ | 紫 |
| `transit` | 車站／交通 | 🚉 | 灰 |
| `other` | 其他 | 📍 | 中性 |

分類可在 `CATEGORIES` 常數加，UI 篩選 chips 自動生成。

### 3.3 功能規格

| 編號 | 功能 | 說明 | 優先級 |
| --- | --- | --- | --- |
| F1 | 向量地圖顯示 | 海岸線／水域／鐵路／道路／公園／建物，連續縮放、慣性拖曳、雙指縮放 | P0 |
| F2 | 面色塊疊加 | arcade 帶狀 + mall 多邊形，半透明，縮放時保持現實寬度 | P0 |
| F3 | 面點擊 | 點色塊 → 底部面板：麵包屑、說明、子項、所屬點 | P0 |
| F4 | 點標記 | 依分類上色的圖釘，縮放到一定程度才顯示名稱標籤 | P0 |
| F5 | 點詳情 | 名稱（日/中）、分類、樓層、備註、營業時間、連結 | P0 |
| F6 | 導航按鈕 | 開 `https://www.google.com/maps/dir/?api=1&destination=lat,lng&travelmode=walking` | P0 |
| F7 | 分類篩選 | 頂部 chips，多選 | P1 |
| F8 | 搜尋 | 名稱（中/日）即時過濾，結果列表點擊飛到該點 | P1 |
| F9 | 我的位置 | `navigator.geolocation`，藍點 + 精度圈；不強制，拒絕授權要能正常用 | P1 |
| F10 | 現場新增點 | 長按地圖 → 新增表單 → 存 localStorage | P1 |
| F11 | 匯出／匯入 | 匯出合併後 JSON（可貼回 repo）、匯入覆蓋 | P1 |
| F12 | 線上圖磚圖層（可選） | 本機開啟時可切 OSM raster 當底；載入失敗自動關閉並提示 | P2 |
| F13 | 圖層開關 | 建物／道路標籤／面標籤 分別開關 | P2 |

### 3.4 手機 UI 規格

```
┌────────────────────────────┐  ← safe-area-inset-top
│ 🔍 搜尋…            ☰ 圖層 │   48px 搜尋列（半透明毛玻璃）
│ [全部][🍜餐廳][🛍️商店][⛩️] │   40px 分類 chips（橫向捲動）
├────────────────────────────┤
│                            │
│         地圖 (canvas)       │   佔滿剩餘空間
│                            │
│                      ╭───╮ │
│                      │ ⌖ │ │   56px FAB 定位（右下拇指區）
├──────  ▔▔▔▔  ──────────────┤   拖曳把手
│ 高松中央商店街 › 丸亀町商店街  │   底部面板（三段：收合 72px /
│ 丸亀町グリーン                │    半開 40vh / 全開 85vh）
│ ┌─────────────────────────┐│
│ │ 3F 〈店名〉        [導航] ││
│ └─────────────────────────┘│
└────────────────────────────┘  ← safe-area-inset-bottom
```

- 觸控目標最小 **44 × 44 px**。
- 底部面板用 `transform` 動畫，`touch-action` 正確設定，避免和地圖手勢打架。
- 顏色支援深／淺色主題（跟隨系統），夜間走路時看得清楚。
- 直向為主；橫向時底部面板改為右側欄。

### 3.5 導航 URL

```js
const url = `https://www.google.com/maps/dir/?api=1`
          + `&destination=${lat},${lng}`
          + `&travelmode=walking`;
```

用官方 universal link：手機上會直接喚起 Google Maps app，桌機開網頁版。
不用 `comgooglemaps://`（iOS 需 `LSApplicationQueriesSchemes`，網頁環境不可靠），
也不用 `geo:`（iOS 不支援）。

### 3.6 離線與儲存

- **App 本體**：`takamatsu_map.html` 單檔，資料以 `<script type="application/json">` 內嵌，
  零外部請求 → 本機開檔、Claude Artifact、GitHub Pages 三種方式都能跑，且都離線。
- **使用者編輯**：存 `localStorage['ss-map-overrides-v1']`，內容是「新增／修改／刪除」的差異，
  載入時疊在內嵌資料上。**不會**因為換一版 HTML 就丟失。
- **回存 repo**：匯出按鈕產生合併後的完整 JSON → 手動貼回 `data/takamatsu.json` → 重跑 build。
  （Artifact 環境無法下載檔案，改用「複製到剪貼簿」＋顯示 JSON 文字框雙路徑。）

### 3.7 建置流程

```
Overpass API                     手動策劃
     │                                │
     ▼                                ▼
tools/fetch_osm.py  ──►  data/takamatsu_basemap.json      （底圖，機器產生）
     │                   data/takamatsu_areas.osm.json    （面的種子）
     │                                │
     │                                ▼
     │                   data/takamatsu.json              （面 + 點，人工確認）
     │                                │
     └────────────┬───────────────────┘
                  ▼
          tools/build.py  ──►  takamatsu_map.html   （單檔，可直接用）
                  ▲
          src/app.template.html
```

- `fetch_osm.py <city>` — 重抓 OSM（需網路，公用 Overpass 鏡像）
- `build.py <city>` — 把資料嵌進模板，產出單檔 HTML
- 兩支都是純標準函式庫，無需 pip install

---

## 4. 尚待你確認 / 之後補的

1. **要標的點**：你說之後提供。POC 先放少量示範點，另 repo 已有
   `景點收藏/香川餐廳/takamatsu_marugame_restaurants.csv`（37 筆），
   但**沒有座標**，要匯入需先定位 —— 是否要我做一支批次定位腳本？
2. **商場樓層**：丸亀町グリーン、瓦町 FLAG、ゆめタウン高松的樓層清單要不要建？
   建了之後點才能歸到「3F」。
3. **丸亀市**：`fetch_osm.py` 已預留 bbox，要開的時候跑一行就有。
4. **色塊調整**：拱廊寬度先用 OSM 推估值，實際看起來太粗／太細可以改 `width_m`。

---

## 5. 授權

底圖與範圍幾何來自 OpenStreetMap，授權 ODbL；
App 內已標註 `© OpenStreetMap contributors`，散布時請保留。
