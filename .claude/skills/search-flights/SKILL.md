---
name: search-flights
description: 掃描 Google Flights 找某段日期區間內的便宜來回機票。使用者說「幫我找機票」、「掃描便宜航班」、「查台北到大阪的票價」、「看整月價格」、「整季走勢」時觸發。
argument-hint: "[origin] [destinations] [depart_start] [depart_end] [trip_days] [budget] [airlines] [--nonstop]"
allowed-tools: Bash
---

## 你的任務

幫使用者找指定日期區間內最便宜的來回機票，支援三種模式：逐日掃描、日曆網格（整週/整月矩陣）、日曆折線（跨季走勢）。

---

## 三種模式與指令

### 模式一：逐日掃描（預設）

逐日查詢特定行程天數的最低票價，含詳細航班資訊與價格評級。適合已決定好旅遊天數、要找最便宜出發日的情況。

```bash
python3 ${CLAUDE_SKILL_DIR}/search.py <origin> <dest> <depart_start> <depart_end> <trip_days> [budget=15000] [airlines] [--nonstop]
```

範例：
```bash
python3 ${CLAUDE_SKILL_DIR}/search.py TPE JP 2026-07-01 2026-07-31 7 14000 CI,BR --nonstop
python3 ${CLAUDE_SKILL_DIR}/search.py TPE KIX 2026-08-01 2026-08-31 5
```

### 模式二：日曆網格 `--grid`

一次查詢出發日 × 回程日的完整價格矩陣，結果依票價排序。適合彈性日期、想看哪個組合最便宜。

```bash
python3 ${CLAUDE_SKILL_DIR}/search.py --grid <origin> <dest> <出發範圍start> <出發範圍end> <回程範圍start> <回程範圍end> [airlines] [--nonstop]
```

範例：
```bash
python3 ${CLAUDE_SKILL_DIR}/search.py --grid TPE KIX 2026-07-18 2026-07-24 2026-07-24 2026-07-30 CI,BR,IT --nonstop
```

### 模式三：日曆折線 `--graph`

查詢大範圍日期內（最多數月）每個出發日的最低票價，適合找出整季最便宜的出發時機。

```bash
python3 ${CLAUDE_SKILL_DIR}/search.py --graph <origin> <dest> <date_start> <date_end> <min_days> <max_days> [airlines] [--nonstop]
```

範例：
```bash
python3 ${CLAUDE_SKILL_DIR}/search.py --graph TPE KIX 2026-07-14 2026-09-11 5 7 CI,BR,IT --nonstop
```

---

## 如何判斷使用哪個模式

| 使用者說 | 建議模式 |
|---------|---------|
| 「7月有沒有便宜的票」、「幫我找最便宜的一週」 | 模式一（逐日掃描） |
| 「7/18~7/24出發，7/24~7/30回來，哪個組合最便宜」 | 模式二（日曆網格） |
| 「7月到9月整季的票價走勢」、「什麼時候飛最便宜」 | 模式三（日曆折線） |

---

## 直飛篩選

所有模式皆支援 `--nonstop`，加上後只回傳直飛航班。使用者說「直飛」、「不要轉機」時加上此參數。

---

## 若使用者未提供參數，主動詢問：

1. 出發地（機場代碼，如 TPE）
2. 目的地（可用國家代碼如 JP，或機場代碼如 NRT,HND）
3. 日期範圍（出發日起訖）
4. 行程天數（模式一/三用；模式二不需要）
5. 只看直飛？（是否加 `--nonstop`）
6. 預算上限（模式一用，選填，預設 15,000 TWD）
7. 指定航空公司（選填，預設 CI BR JX MM TR IT GK JL NH）

---

## 結果解讀與建議（模式一）

### 結果摘要
- 掃描期間、找到幾筆
- **最推薦前 3 筆**（「超值」或「便宜」評級優先）

### 每筆結果
- 去程航班（航空、班號、時間、直飛/停靠）
- 來回票價
- 價格評級（超值 / 便宜 / 一般偏低 / 一般 / 偏高 / 高）
- 與歷史低點的比較
- 推薦回程選項（最多 3 個）

### 購買建議
- `rating_label` 是「超值」或「便宜」→ 明確建議現在買
- 目前票價接近 `history_min` → 說明已是近期低點
- 目前票價遠高於 `history_min` → 提醒可能還有空間等待

---

## 常用目的地代碼

目的地可用**國家代碼**（自動展開）或**機場代碼**（逗號分隔）。

| 國家 | 代碼 | 展開機場 |
|------|------|---------|
| 日本 | JP | NRT, HND, KIX, NGO, FUK, CTS, OKA |
| 韓國 | KR | ICN, GMP, PUS |
| 泰國 | TH | BKK, DMK, HKT, CNX |
| 新加坡 | SG | SIN |
| 馬來西亞 | MY | KUL, PEN |
| 越南 | VN | HAN, SGN, DAD |
| 香港 | HK | HKG |
| 澳門 | MO | MFM |

常用機場：TPE（台北）、NRT（東京成田）、HND（東京羽田）、KIX（大阪）、NGO（名古屋）、FUK（福岡）、CTS（札幌）、OKA（沖繩）

## 常用航空代碼

| 代碼 | 航空 |
|------|------|
| CI | 中華航空 |
| BR | 長榮航空 |
| JX | 星宇航空 |
| MM | 樂桃航空 |
| TR | 酷航 |
| IT | 台灣虎航 |
| GK | 捷星日本 |
| JL | 日本航空 |
| NH | 全日空 |

---

## 注意事項

- 模式一逐日掃描，每天約 2–3 秒，超過 30 天建議先用模式三確認走勢再縮小範圍。
- 模式二、三速度快（單次 API，約 2 秒），但僅回傳最低票價，無詳細航班資訊。

---

---

# Google Flights API 技術參考

> 透過 Chrome DevTools 逆向工程取得，無需登入 Cookie。
> 以下為完整 API 規格，是 search.py 的唯一權威參考。

---

## 共用設定

### Base URL

```
https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/{endpoint}
```

### 共用 Query Parameters

```
?f.sid=-4216850837332470657
&bl=boq_travel-frontend-flights-ui_20260428.01_p0
&hl=zh-TW&soc-app=162&soc-platform=1&soc-device=1&_reqid=1&rt=c
```

> `bl` 包含日期版本，若回傳空值可從 Chrome DevTools 抓取最新值。

### 必要 Headers（無需 Cookie）

```
accept: */*
content-type: application/x-www-form-urlencoded;charset=UTF-8
origin: https://www.google.com
referer: https://www.google.com/travel/flights/
user-agent: Mozilla/5.0 ... Chrome/147 ...
x-goog-ext-259736195-jspb: ["zh-TW","TW","TWD",1,null,[-480],null,null,7,[]]
x-same-domain: 1
```

> `x-goog-ext-259736195-jspb` 控制語言/國家/貨幣/時區。台灣時區 UTC+8 = `-480`（Google 用負值）。

### Request Body 格式

```
f.req=<URL_ENCODED_JSON>&
```

外層結構永遠是：
```python
outer = [None, json.dumps(inner_req)]
body = "f.req=" + urllib.parse.quote(json.dumps(outer)) + "&"
```

### 共用 search_params 結構（各 endpoint 的 inner_req[1]）

```python
search_params = [
    None, None, 1, None, [], 1, [1, 0, 0, 0],
    None, None, None, None, None, None,
    [leg_out, leg_ret],
    None, None, None, 1,
]
```

### Leg 陣列格式

```python
leg = [
    orig,          # [0] [[["TPE", 0]]]  出發機場列表
    dest,          # [1] [[["NRT", 0]], [["HND", 0]]]  目的機場列表（可多個）
    None,          # [2]
    stops,         # [3] 0=不限，1=僅直飛
    airlines,      # [4] ["CI", "BR", ...]  空 list = 不限航空
    None,          # [5]
    date,          # [6] "2026-07-21"  YYYY-MM-DD
    None, None, None, None, None, None, None,
    cabin,         # [14] 1=頭等 2=商務 3=經濟 4=豪華經濟
]
```

機場格式：
- 單一：`[[["NRT", 0]]]`
- 多個：`[[["NRT", 0]], [["HND", 0]], [["KIX", 0]]]`

> **注意**：只接受 IATA 機場代碼，不接受國家代碼（如 JP）或 KG ID（如 `/m/03_3d`）。
> 國家代碼由 search.py 的 `COUNTRY_AIRPORTS` dict 展開為機場列表。

---

## Endpoint 1：GetShoppingResults

取得去程班機清單（含預估來回票價）。

```python
inner_req = [[], search_params, 0, 0, 0, 1]
```

### 回應解析

Response 開頭有 `)]}'` 保護字串，格式為 HTTP chunked。用 regex 找所有 `[["wrb.fr"` 並取 `chunk[0][2]`（JSON string 需再 parse）。

```python
def parse_chunks(raw: str) -> list:
    chunks = []
    for m in re.finditer(r'\[\["wrb\.fr"', raw):
        start = m.start()
        depth = end = 0
        for i, c in enumerate(raw[start:], start):
            if c == '[': depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0: end = i + 1; break
        try:
            chunk = json.loads(raw[start:end])
            if chunk[0][2]:
                chunks.append(json.loads(chunk[0][2]))
        except Exception:
            pass
    return chunks
```

去程 offer 清單：`chunks[0][2][0]`（list of offers）

### Offer 結構

```
offer[0]       = leg（航班主資料）
offer[1][0][1] = price_rt（來回票價 TWD，Google 估算，去程+最便宜回程）
offer[1][1]    = token（帶入 GetBookingResults 用）
```

### Leg 欄位

```
leg[0]  = 航空公司 IATA 代碼  e.g. "IT"
leg[1]  = [航空公司中文名]    e.g. ["台灣虎航"]
leg[2]  = [航段列表]          → segments
leg[3]  = 出發機場代碼        e.g. "TPE"
leg[5]  = 出發時間            [hour, minute]
leg[6]  = 抵達機場代碼        e.g. "KIX"
leg[8]  = 抵達時間            [hour, minute]
leg[9]  = 總飛行時間（分鐘）
```

### Segment 欄位

```
seg[3]   = 出發機場代碼
seg[6]   = 抵達機場代碼
seg[8]   = 出發時間  [hour, minute]
seg[10]  = 抵達時間  [hour, minute]
seg[11]  = 航段飛行時間（分鐘）
seg[17]  = 機型名稱  e.g. "Airbus A320"
seg[22]  = [航空代碼, 班號, None, 航空名]  e.g. ["IT","212",None,"台灣虎航"]
seg[31]  = CO2 排放量（公克）→ ÷1000 = 公斤
```

---

## Endpoint 2：GetBookingResults

**必須同時指定去程和回程的選定航班**，才能取得精確票價 + 價格歷史。

```python
inner_req = [[None, token], search_params, None, 0]
```

> **重要**：`search_params` 中兩條 leg 的 index 8 都必須填入選定航班：
> ```python
> outbound_leg[8] = [['TPE', '2026-12-05', 'OKA', None, 'IT', '232']]  # [from, date, to, None, airline, flight_num]
> return_leg[8]   = [['OKA', '2026-12-10', 'TPE', None, 'IT', '231']]
> ```
> 若只填去程、回程留 None，API 會回傳 INVALID_ARGUMENT（error 3）。
> 實作方式：先用 GetShoppingResults 取得去程，再對回程路線做一次 GetShoppingResults 取最便宜回程，再組合呼叫。

### 回應：兩個 wrb.fr chunk

**Chunk 0：回程班機替代選項**
```
chunks[0][1][5][0]  →  list of return offers（同 parse_offer 格式）
```

**Chunk 1：價格洞察**
```
chunks[1][1][12]  →  price_insight list (pi)

pi[0]       = 評級 int（1=超值 2=便宜 3=一般偏低 4=一般 5=偏高 6=高）
pi[1][1]    = 目前來回票價 TWD
pi[4][1]    = 典型最低價 TWD
pi[5][1]    = 典型最高價 TWD
pi[10][0]   = [[timestamp_ms, price], ...]  約 60 天歷史價格
```

---

## Endpoint 3：GetCalendarGrid

日曆網格：出發日 × 回程日 的最低票價矩陣。速度快，單次 API。

```python
inner_req = [
    None,
    search_params,
    [outbound_start, outbound_end],   # 出發日範圍
    [return_start, return_end],       # 回程日範圍
]
```

### 回應解析

```
chunks[0][1]  →  list of entries

entry[0]      = 出發日  "2026-07-21"
entry[1]      = 回程日  "2026-07-28"
entry[2][0][1] = 來回票價 TWD
entry[2][1]   = booking token
entry[3]      = 1 表示直飛
```

---

## Endpoint 4：GetCalendarGraph

日曆折線：跨月大範圍每個出發日的最低票價。速度快，單次 API。

```python
inner_req = [
    None,
    search_params,
    [date_start, date_end],    # 查詢日期範圍（可跨數月）
    None,
    [min_days, max_days],      # 行程天數範圍
]
```

### 回應解析

```
chunks[0][1]  →  list of entries（同 CalendarGrid 格式）

entry[0]       = 出發日
entry[1]       = 回程日（最便宜的那個）
entry[2][0][1] = 最低來回票價 TWD
```

---

## 三步驟流程（掃描模式）

```
Step 1  GetShoppingResults(origin, dest, depart_date, return_date)
  └─ 取得去程清單，每筆含 price_rt + token
  └─ 篩選 price_rt <= budget 的航班

Step 2  GetShoppingResults(dest, origin, return_date, return_date+3)
  └─ 取得回程候選，取最便宜一筆作為 selected_return

Step 3  GetBookingResults(token, selected_outbound, selected_return)
  └─ 兩條 leg 都必須填入 [from, date, to, None, airline, flight_num]
  └─ Chunk 0: 回程替代選項
  └─ Chunk 1: 價格洞察
       - current_price：當前票價
       - typical_low：Google 定義的「正常低點」
       - rating_label：超值/便宜/一般/偏高/高
       - history[]：pi[10][0] → [[timestamp_ms, price], ...]
```

---

## 速率限制與注意事項

- 掃描多個日期時，每次查詢間隔 1.5 秒，避免被限流。
- `price_rt` 是 Google 估算值（去程 + 最便宜回程），與 GetBookingResults 的精確票價可能略有差異。
- 價格歷史的 `typical_low` 是「值不值得買」的參考門檻；`history_min` 是這 60 天的實際最低點。
- Rate limiting 發生時 response 為空；直接重試通常可成功。
