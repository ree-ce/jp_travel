#!/usr/bin/env python3
"""
Google Flights 便宜機票掃描器

模式一（掃描模式，預設）：
  python search.py <origin> <dest> <depart_start> <depart_end> <trip_days> [budget] [airlines] [--nonstop]

模式一b（單程掃描）：
  python search.py --oneway <origin> <dest> <depart_start> <depart_end> [budget] [airlines] [--nonstop]

模式二（日曆網格，快速看整月價格矩陣）：
  python search.py --grid <origin> <dest> <outbound_start> <outbound_end> <return_start> <return_end> [airlines] [--nonstop]

模式三（日曆折線，看跨季價格走勢）：
  python search.py --graph <origin> <dest> <date_start> <date_end> <min_days> <max_days> [airlines] [--nonstop]

destinations: 逗號分隔機場 或 國家代碼（如 JP）
"""
import json
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Optional

DEFAULT_AIRLINES = ["CI", "BR", "JX", "MM", "TR", "IT", "GK", "JL", "NH"]

COUNTRY_AIRPORTS = {
    "JP": ["NRT", "HND", "KIX", "NGO", "FUK", "CTS", "OKA"],
    "KR": ["ICN", "GMP", "PUS"],
    "TH": ["BKK", "DMK", "HKT", "CNX"],
    "SG": ["SIN"],
    "MY": ["KUL", "PEN"],
    "VN": ["HAN", "SGN", "DAD"],
    "HK": ["HKG"],
    "MO": ["MFM"],
    "US": ["LAX", "SFO", "JFK", "ORD", "SEA"],
    "EU": ["LHR", "CDG", "FRA", "AMS"],
}
PRICE_RATING = {1: "超值", 2: "便宜", 3: "一般偏低", 4: "一般", 5: "偏高", 6: "高"}
_BL_FALLBACK = "boq_travel-frontend-flights-ui_20260429.01_p0"
BASE_URL_TEMPLATE = (
    "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights"
    ".FlightsFrontendService/{endpoint}"
    "?f.sid=-4216850837332470657"
    "&bl={bl}"
    "&hl=zh-TW&soc-app=162&soc-platform=1&soc-device=1&_reqid=1&rt=c"
)


def _fetch_bl() -> str:
    """每次啟動時從 Google Flights 首頁抓最新 bl 版本號，避免因版本過期導致 API error 3。"""
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5", "https://www.google.com/travel/flights",
             "-H", "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"],
            capture_output=True, text=True, timeout=8,
        )
        m = re.search(r"boq_travel-frontend-flights-ui_\d{8}[^'\"\\s]+", r.stdout)
        if m:
            return m.group(0)
    except Exception:
        pass
    return _BL_FALLBACK


_BL = _fetch_bl()
HEADERS = [
    "-H", "accept: */*",
    "-H", "content-type: application/x-www-form-urlencoded;charset=UTF-8",
    "-H", "origin: https://www.google.com",
    "-H", "referer: https://www.google.com/travel/flights/",
    "-H", "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "-H", 'x-goog-ext-259736195-jspb: ["zh-TW","TW","TWD",1,null,[-480],null,null,7,[]]',
    "-H", "x-same-domain: 1",
]

# leg array index 3: 0 = 任意停靠, 1 = 僅直飛
STOPS_ANY = 0
STOPS_NONSTOP = 1


def call_api(endpoint: str, body: str) -> str:
    url = BASE_URL_TEMPLATE.format(endpoint=endpoint, bl=_BL)
    result = subprocess.run(
        ["curl", "-s", url] + HEADERS + ["--data-raw", body],
        capture_output=True, text=True
    )
    return result.stdout


def parse_chunks(raw: str) -> list:
    chunks = []
    for m in re.finditer(r'\[\["wrb\.fr"', raw):
        start = m.start()
        depth = end = 0
        for i, c in enumerate(raw[start:], start):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            chunk = json.loads(raw[start:end])
            if chunk[0][2]:
                chunks.append(json.loads(chunk[0][2]))
        except Exception:
            pass
    return chunks


def _build_search_params(origin, dest_airports, depart_date, return_date, airlines, stops, cabin,
                          selected_outbound=None, selected_return=None, return_origin_airports=None,
                          one_way=False):
    orig = [[[origin, 0]]]
    dest = [[[a, 0]] for a in dest_airports]
    # open-jaw: return departs from a different airport than the outbound destination
    ret_orig = [[[a, 0]] for a in return_origin_airports] if return_origin_airports else dest
    trip_type = 2 if one_way else 1
    outbound_leg = [orig, dest, None, stops, airlines, None, depart_date,
                    None, selected_outbound, None, None, None, None, None, cabin]
    legs = [outbound_leg] if one_way else [
        outbound_leg,
        [ret_orig, orig, None, stops, airlines, None, return_date,
         None, selected_return, None, None, None, None, None, cabin],
    ]
    return [
        None, None, trip_type, None, [], 1, [1, 0, 0, 0],
        None, None, None, None, None, None,
        legs,
        None, None, None, 1,
    ]


def _extract_selected_flight(offer: dict, date_str: str) -> Optional[list]:
    if not offer or not offer.get("segments"):
        return None
    airline_code = offer["airline_code"]
    flight_no = offer["segments"][0]["flight_no"]  # e.g. "IT232"
    flight_num = flight_no[len(airline_code):]      # e.g. "232"
    return [[offer["from"], date_str, offer["to"], None, airline_code, flight_num]]


# ---------------------------------------------------------------------------
# Content-based field extractors — robust across route variants
# Instead of hard-coded indices, we identify fields by their shape/content.
# ---------------------------------------------------------------------------

def _is_iata(x) -> bool:
    """3-letter uppercase ASCII airport code, e.g. 'TPE', 'OKJ'."""
    return isinstance(x, str) and len(x) == 3 and x.isalpha() and x.isupper()


def _is_hhmm(x) -> bool:
    """[h, m] time pair, e.g. [14, 40]."""
    return (isinstance(x, list) and len(x) == 2
            and isinstance(x[0], int) and isinstance(x[1], int)
            and 0 <= x[0] <= 23 and 0 <= x[1] <= 59)


def _is_duration(x) -> bool:
    """Flight duration in minutes: plausible range 30–720 min."""
    return isinstance(x, int) and 30 <= x <= 720


def _scan(lst, pred, n=1):
    """Return the n-th element (1-based) of lst satisfying pred, or None."""
    count = 0
    for x in lst:
        if pred(x):
            count += 1
            if count == n:
                return x
    return None


def _fmt_hhmm(t) -> str:
    return "%02d:%02d" % (t[0], t[1]) if _is_hhmm(t) else "?"


def _parse_segment(seg: list, fallback_airline: str) -> Optional[dict]:
    """Parse one flight segment using content-based field detection."""
    if not isinstance(seg, list) or len(seg) < 8:
        return None

    from_ap = _scan(seg, _is_iata, 1)
    to_ap   = _scan(seg, _is_iata, 2)
    if not from_ap or not to_ap:
        return None

    # Exclude [0, 0] here too — same padding issue as leg-level parsing.
    dep_t = _scan(seg, lambda x: _is_hhmm(x) and x != [0, 0], 1)
    arr_t = _scan(seg, lambda x: _is_hhmm(x) and x != [0, 0], 2)
    dur   = _scan(seg, _is_duration)

    # Flight-number entry: ['IT', '214', ...] — first element is 2-3 char
    # airline code, second element starts with a digit.
    fn_code = fn_num = None
    for x in seg:
        if (isinstance(x, list) and len(x) >= 2
                and isinstance(x[0], str) and 1 < len(x[0]) <= 3 and x[0].isupper()
                and isinstance(x[1], str) and x[1] and x[1][0].isdigit()):
            fn_code, fn_num = x[0], x[1]
            break

    # Aircraft: string containing a known keyword or matching A/B prefix pattern
    aircraft = None
    for x in seg:
        if isinstance(x, str) and len(x) > 3 and any(
                k in x for k in ("Airbus", "Boeing", "A320", "A321", "A330",
                                  "B737", "B738", "B777", "B787", "E190")):
            aircraft = x
            break

    # CO2 in grams: large integer, usually near end of segment
    co2_g = None
    for x in reversed(seg):
        if isinstance(x, int) and 50_000 <= x <= 500_000:
            co2_g = x
            break

    return {
        "flight_no": f"{fn_code or fallback_airline}{fn_num or '?'}",
        "from": from_ap,
        "to": to_ap,
        "dep": _fmt_hhmm(dep_t),
        "arr": _fmt_hhmm(arr_t),
        "duration_min": dur or 0,
        "aircraft": aircraft,
        "co2_kg": co2_g // 1000 if co2_g else None,
    }


def parse_offer(offer: list) -> Optional[dict]:
    if not isinstance(offer, list) or len(offer) < 2:
        return None
    leg = offer[0]
    # leg[0] must be the airline IATA code (2-char uppercase string)
    if not isinstance(leg, list) or not leg or not isinstance(leg[0], str):
        return None

    airline_code = leg[0]
    airline_name = leg[1][0] if isinstance(leg[1], list) and leg[1] else airline_code

    # Price and booking token — standard location offer[1][0][1] / offer[1][1]
    price_rt = token = None
    try:
        price_rt = offer[1][0][1]
        token    = offer[1][1]
        if not isinstance(price_rt, (int, float)):
            price_rt = None
    except (IndexError, TypeError):
        pass

    # Segments are at leg[2]
    segs = []
    for raw_seg in (leg[2] if isinstance(leg[2], list) else []):
        s = _parse_segment(raw_seg, airline_code)
        if s:
            segs.append(s)

    # Leg-level fields: try fixed indices first (fastest, most precise),
    # fall back to content-based scan when the slot contains unexpected data.
    def _leg_iata(idx):
        v = leg[idx] if len(leg) > idx else None
        return v if _is_iata(v) else None

    def _leg_hhmm(idx):
        v = leg[idx] if len(leg) > idx else None
        # WARNING: Do NOT remove the `v != [0, 0]` guard.
        # Some routes (e.g. GK50 OKJ→KIX) pad the leg array with [0, 0] at positions
        # before the real arrival time. Without this guard, [0, 0] silently becomes
        # "00:00" — a data corruption that looks valid but isn't.
        return v if _is_hhmm(v) and v != [0, 0] else None

    def _leg_dur(idx):
        v = leg[idx] if len(leg) > idx else None
        return v if _is_duration(v) else None

    # Field layout observed across tested routes (indices may shift by route variant):
    #   leg[0]  = airline code (str)         leg[1]  = [airline name, ...]
    #   leg[2]  = segments list              leg[3]  = origin IATA
    #   leg[5]  = departure [h, m]           leg[6]  = destination IATA
    #   leg[8]  = arrival [h, m]             leg[9]  = total duration (min)
    # Fixed-index read first; content-scan as fallback when index holds unexpected data.
    # The `x != [0, 0]` exclusion in both paths is load-bearing — see _leg_hhmm comment.
    from_ap = _leg_iata(3) or _scan(leg, _is_iata, 1)
    to_ap   = _leg_iata(6) or _scan(leg, _is_iata, 2)
    dep_t   = _leg_hhmm(5) or _scan(leg, lambda x: _is_hhmm(x) and x != [0, 0], 1)
    arr_t   = _leg_hhmm(8) or _scan(leg, lambda x: _is_hhmm(x) and x != [0, 0], 2)
    dur     = _leg_dur(9)  or _scan(leg, _is_duration)

    # Last-resort fallback: if leg-level times are still missing (e.g. IT240/FUK),
    # borrow dep/arr from the parsed segments which use independent content-scan.
    dep_str = _fmt_hhmm(dep_t) if dep_t else (segs[0]["dep"]  if segs else "?")
    arr_str = _fmt_hhmm(arr_t) if arr_t else (segs[-1]["arr"] if segs else "?")

    return {
        "airline": airline_name,
        "airline_code": airline_code,
        "from": from_ap or "",
        "to": to_ap or "",
        "dep": dep_str,
        "arr": arr_str,
        "total_duration_min": dur or 0,
        "stops": max(0, len(segs) - 1),
        "segments": segs,
        "price_rt": int(price_rt) if price_rt else None,
        "token": token,
    }


def parse_price_insight(pi: list) -> dict:
    # pi[10] = [[[timestamp_ms, price], ...]] — ~60-day price history
    history = []
    try:
        raw_hist = pi[10][0]
        history = [
            {
                "date": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "price": price,
            }
            for ts, price in raw_hist
            if isinstance(ts, int) and isinstance(price, (int, float))
        ]
    except (IndexError, TypeError):
        pass

    try:
        return {
            "rating": pi[0],
            "rating_label": PRICE_RATING.get(pi[0], "?"),
            "current_price": pi[1][1],
            "typical_low": pi[4][1],
            "typical_high": pi[5][1],
            "history": history,
        }
    except (IndexError, TypeError):
        return {}


def search_flights(origin, dest_airports, depart_date, return_date, airlines,
                   stops=STOPS_ANY, cabin=3, return_origin_airports=None, one_way=False):
    search_params = _build_search_params(
        origin, dest_airports, depart_date, return_date, airlines, stops, cabin,
        return_origin_airports=return_origin_airports,
        one_way=one_way,
    )
    inner_req = [[], search_params, 0, 0, 0, 1]
    body = "f.req=" + urllib.parse.quote(json.dumps([None, json.dumps(inner_req)])) + "&"
    raw = call_api("GetShoppingResults", body)

    chunks = parse_chunks(raw)
    if not chunks:
        return []

    # Primary path: offers at c[2][0] (most routes)
    offers = []
    try:
        offers = chunks[0][2][0] or []
    except (IndexError, TypeError):
        pass

    # Fallback: small/regional airports (confirmed: OKJ, possibly TAK, MMY) return
    # offers at c[3] instead of c[2][0]. Each entry is wrapped in an extra single-element
    # list, so unwrap with o[0]. Do NOT merge this into the primary path — major airports
    # (KIX, NRT, FUK…) do NOT have c[3], and blindly reading it would throw IndexError.
    if not offers:
        try:
            raw3 = chunks[0][3] or []
            offers = [o[0] for o in raw3 if isinstance(o, list) and o]
        except (IndexError, TypeError):
            pass

    if not offers:
        return []

    flights = [parse_offer(x) for x in offers]
    return [f for f in flights if f]


def get_booking_details(token, origin, dest_airports, depart_date, return_date, airlines,
                        stops=STOPS_ANY, cabin=3, outbound_offer=None, return_origin_airports=None):
    selected_outbound = _extract_selected_flight(outbound_offer, depart_date) if outbound_offer else None

    # GetBookingResults requires a return flight to be selected too.
    # For open-jaw, the return departs from return_origin_airports; otherwise from dest_airports.
    selected_return = None
    if outbound_offer:
        ret_date = datetime.strptime(return_date, "%Y-%m-%d")
        stub_return_date = (ret_date + timedelta(days=3)).strftime("%Y-%m-%d")
        ret_dep = return_origin_airports or (
            [dest_airports[0]] if len(dest_airports) == 1 else [outbound_offer["to"]]
        )
        ret_candidates = search_flights(
            ret_dep[0], [origin], return_date, stub_return_date, airlines, stops, cabin,
        )
        if ret_candidates:
            selected_return = _extract_selected_flight(ret_candidates[0], return_date)

    search_params = _build_search_params(
        origin, dest_airports, depart_date, return_date, airlines, stops, cabin,
        selected_outbound=selected_outbound,
        selected_return=selected_return,
        return_origin_airports=return_origin_airports,
    )
    inner_req = [[None, token], search_params, None, 0]
    body = "f.req=" + urllib.parse.quote(json.dumps([None, json.dumps(inner_req)])) + "&"
    raw = call_api("GetBookingResults", body)

    chunks = parse_chunks(raw)
    if len(chunks) < 2:
        return [], {}

    ret_flights = []
    try:
        # FRAGILE index: GetBookingResults places return-leg offers at c[0][1][5][0]
        # for all tested routes. If return flights silently go missing, inspect with:
        #   print(json.dumps(chunks[0][1][:8], ensure_ascii=False))
        # Small airports (OKJ etc.) may need the c[3] fallback here too — not yet tested.
        ret_offers = chunks[0][1][5][0]
        ret_flights = [parse_offer(x) for x in ret_offers]
        ret_flights = [f for f in ret_flights if f]
        ret_flights.sort(key=lambda x: x["price_rt"] or 999999)
    except (IndexError, TypeError, KeyError):
        pass

    insight = {}
    try:
        insight = parse_price_insight(chunks[1][1][12])
    except (IndexError, TypeError, KeyError):
        pass

    return ret_flights, insight


def get_calendar_grid(origin, dest_airports, outbound_start, outbound_end,
                      return_start, return_end, airlines, stops=STOPS_ANY, cabin=3):
    """
    日曆網格：回傳指定出發日 × 回程日 組合的最低來回票價。
    適合快速掃描整週/整月的價格矩陣。

    回傳：list of {"depart": str, "return": str, "price": int, "token": str}
    """
    # 使用 outbound 範圍中間日作為 leg 基準日（實際日期由 date range 參數控制）
    search_params = _build_search_params(
        origin, dest_airports, outbound_start, return_start, airlines, stops, cabin
    )
    inner_req = [
        None,
        search_params,
        [outbound_start, outbound_end],
        [return_start, return_end],
    ]
    body = "f.req=" + urllib.parse.quote(json.dumps([None, json.dumps(inner_req)])) + "&"
    raw = call_api("GetCalendarGrid", body)

    chunks = parse_chunks(raw)
    if not chunks:
        return []

    results = []
    try:
        for entry in chunks[0][1]:
            # entry: [depart_date, return_date, [[None, price], token], stops_int]
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            price_info = entry[2]
            if not isinstance(price_info, list) or len(price_info) < 2:
                continue
            price = price_info[0][1] if isinstance(price_info[0], list) and len(price_info[0]) > 1 else None
            results.append({
                "depart": entry[0],
                "return": entry[1],
                "price": price,
                "token": price_info[1] if len(price_info) > 1 else None,
            })
    except (IndexError, TypeError):
        pass

    return sorted(results, key=lambda x: x["price"] or 999999)


def _call_calendar_graph_chunk(origin, dest_airports, chunk_start, chunk_end,
                               nights_min, nights_max, airlines, stops, cabin) -> list:
    """單次 CalendarGraph API 呼叫，回傳原始 entry 清單。"""
    mid_return = (datetime.strptime(chunk_start, "%Y-%m-%d") + timedelta(days=nights_min)).strftime("%Y-%m-%d")
    search_params = _build_search_params(
        origin, dest_airports, chunk_start, mid_return, airlines, stops, cabin
    )
    inner_req = [
        None,
        search_params,
        [chunk_start, chunk_end],
        None,
        [nights_min, nights_max],
    ]
    body = "f.req=" + urllib.parse.quote(json.dumps([None, json.dumps(inner_req)])) + "&"
    raw = call_api("GetCalendarGraph", body)

    chunks = parse_chunks(raw)
    if not chunks:
        return []

    results = []
    try:
        # NOTE: GetCalendarGraph data lives at c[0][1], same structure as GetCalendarGrid.
        # Small airports (OKJ) may return sparse/empty results here — if so, apply the
        # same c[3] fallback pattern used in search_flights(). Not yet investigated.
        for entry in chunks[0][1]:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            price_info = entry[2]
            price = price_info[0][1] if isinstance(price_info, list) and isinstance(price_info[0], list) and len(price_info[0]) > 1 else None
            results.append({"depart": entry[0], "return": entry[1], "price": price})
    except (IndexError, TypeError):
        pass
    return results


def get_calendar_graph(origin, dest_airports, date_start, date_end,
                       min_days, max_days, airlines, stops=STOPS_ANY, cabin=3):
    """
    日曆折線：回傳大日期範圍內每個出發日的最低來回票價。
    適合找出整季最便宜的出發時機。

    trip_days 為含頭含尾的日曆天數（6天 = 出發日+5天後回程）。
    API 接受 nights（= days - 1），自動換算。
    日期範圍超過 60 天自動分段查詢，避免 API error 3。

    回傳：list of {"depart": str, "return": str, "price": int}
    """
    nights_min = min_days - 1
    nights_max = max_days - 1

    # 分段：每段最多 60 天，避免 GetCalendarGraph API 拒絕過長範圍
    CHUNK_DAYS = 60
    start_dt = datetime.strptime(date_start, "%Y-%m-%d")
    end_dt = datetime.strptime(date_end, "%Y-%m-%d")

    all_results = []
    chunk_start_dt = start_dt
    while chunk_start_dt <= end_dt:
        chunk_end_dt = min(chunk_start_dt + timedelta(days=CHUNK_DAYS - 1), end_dt)
        chunk_results = _call_calendar_graph_chunk(
            origin, dest_airports,
            chunk_start_dt.strftime("%Y-%m-%d"),
            chunk_end_dt.strftime("%Y-%m-%d"),
            nights_min, nights_max, airlines, stops, cabin,
        )
        all_results.extend(chunk_results)
        chunk_start_dt = chunk_end_dt + timedelta(days=1)

    return sorted(all_results, key=lambda x: x["price"] or 999999)


def scan_dates(origin, destinations, depart_start, depart_end, trip_days,
               budget, airlines, stops=STOPS_ANY, cabin=3, delay=1.5,
               return_origin_airports=None):
    results = []
    current = depart_start
    nonstop_label = "（僅直飛）" if stops == STOPS_NONSTOP else ""
    openjaw_label = f"（開口票，回程從 {','.join(return_origin_airports)} 出發）" if return_origin_airports else ""

    total_days = (depart_end - depart_start).days + 1
    print(f"掃描 {total_days} 個出發日期，預算上限 TWD {budget:,}{nonstop_label}{openjaw_label}...\n", flush=True)

    while current <= depart_end:
        depart_str = current.strftime("%Y-%m-%d")
        return_str = (current + timedelta(days=trip_days - 1)).strftime("%Y-%m-%d")

        print(f"  [{depart_str} → {return_str}] 查詢中...", end=" ", flush=True)

        flights = search_flights(origin, destinations, depart_str, return_str, airlines, stops, cabin,
                                 return_origin_airports=return_origin_airports)
        cheap = [f for f in flights if f["price_rt"] and f["price_rt"] <= budget]

        if not cheap:
            over_budget = [f["price_rt"] for f in flights if f["price_rt"]]
            if over_budget:
                print(f"無符合結果（最低 TWD {min(over_budget):,}，超預算）")
            else:
                print("無符合結果")
        else:
            print(f"找到 {len(cheap)} 筆，最低 TWD {min(f['price_rt'] for f in cheap):,}")
            for f in cheap:
                time.sleep(delay)
                ret_flights, insight = get_booking_details(
                    f["token"], origin, destinations, depart_str, return_str, airlines, stops, cabin,
                    outbound_offer=f, return_origin_airports=return_origin_airports,
                )
                results.append({
                    "depart_date": depart_str,
                    "return_date": return_str,
                    "airline": f["airline"],
                    "airline_code": f["airline_code"],
                    "flight_no": f["segments"][0]["flight_no"] if f["segments"] else "?",
                    "stops": f["stops"],
                    "dep": f["dep"],
                    "arr": f["arr"],
                    "duration_min": f["total_duration_min"],
                    "price_rt": f["price_rt"],
                    "rating_label": insight.get("rating_label", "?"),
                    "typical_low": insight.get("typical_low"),
                    "typical_high": insight.get("typical_high"),
                    "current_insight_price": insight.get("current_price"),
                    "return_options": [
                        {
                            "airline": r["airline"],
                            "flight_no": r["segments"][0]["flight_no"] if r["segments"] else "?",
                            "dep": r["dep"],
                            "arr": r["arr"],
                            "price_rt": r["price_rt"],
                        }
                        for r in ret_flights[:3]
                    ],
                    "history_min": min(h["price"] for h in insight.get("history", [])) if insight.get("history") else None,
                    "history_max": max(h["price"] for h in insight.get("history", [])) if insight.get("history") else None,
                })

        current += timedelta(days=1)
        time.sleep(delay)

    return sorted(results, key=lambda x: x["price_rt"])


def scan_oneway_dates(origin, destinations, depart_start, depart_end,
                      budget, airlines, stops=STOPS_ANY, cabin=3, delay=1.5):
    results = []
    current = depart_start
    nonstop_label = "（僅直飛）" if stops == STOPS_NONSTOP else ""
    total_days = (depart_end - depart_start).days + 1
    print(f"掃描 {total_days} 個出發日期（單程），預算上限 TWD {budget:,}{nonstop_label}...\n", flush=True)

    while current <= depart_end:
        depart_str = current.strftime("%Y-%m-%d")
        print(f"  [{depart_str}] 查詢中...", end=" ", flush=True)

        flights = search_flights(origin, destinations, depart_str, None, airlines, stops, cabin, one_way=True)
        cheap = [f for f in flights if f["price_rt"] and f["price_rt"] <= budget]

        if not cheap:
            over_budget = [f["price_rt"] for f in flights if f["price_rt"]]
            if over_budget:
                print(f"無符合結果（最低 TWD {min(over_budget):,}，超預算）")
            else:
                print("無符合結果")
        else:
            print(f"找到 {len(cheap)} 筆，最低 TWD {min(f['price_rt'] for f in cheap):,}")
            for f in cheap:
                results.append({
                    "depart_date": depart_str,
                    "airline": f["airline"],
                    "airline_code": f["airline_code"],
                    "flight_no": f["segments"][0]["flight_no"] if f["segments"] else "?",
                    "stops": f["stops"],
                    "dep": f["dep"],
                    "arr": f["arr"],
                    "duration_min": f["total_duration_min"],
                    "price_ow": f["price_rt"],
                })

        current += timedelta(days=1)
        time.sleep(delay)

    return sorted(results, key=lambda x: x["price_ow"])


def format_oneway_results(results: list) -> str:
    if not results:
        return "找不到符合預算的單程航班。"

    lines = [f"找到 {len(results)} 筆符合結果（依票價排序）\n"]
    lines.append(f"{'#':<3} {'出發日':<12} {'航空':<10} {'航班':<8} {'時間':<16} {'停靠':<4} {'票價':>8}")
    lines.append("-" * 70)

    for i, r in enumerate(results, 1):
        stops = "直飛" if r["stops"] == 0 else f"{r['stops']}停"
        lines.append(
            f"{i:<3} {r['depart_date']:<12} "
            f"{r['airline']:<10} {r['flight_no']:<8} "
            f"{r['dep']}→{r['arr']:<6} {stops:<4} "
            f"TWD {r['price_ow']:>7,}"
        )

    return "\n".join(lines)


def format_results(results: list) -> str:
    if not results:
        return "找不到符合預算的航班。"

    lines = [f"找到 {len(results)} 筆符合結果（依票價排序）\n"]
    lines.append(f"{'#':<3} {'出發日':<12} {'回程日':<12} {'航空':<10} {'航班':<8} {'去程時間':<14} {'停靠':<4} {'票價':>8} {'評級':<8} {'歷史低'}")
    lines.append("-" * 100)

    for i, r in enumerate(results, 1):
        stops = "直飛" if r["stops"] == 0 else f"{r['stops']}停"
        hist_low = f"TWD {r['history_min']:,}" if r["history_min"] else "  ?"
        lines.append(
            f"{i:<3} {r['depart_date']:<12} {r['return_date']:<12} "
            f"{r['airline']:<10} {r['flight_no']:<8} "
            f"{r['dep']}→{r['arr']:<5} {stops:<4} "
            f"TWD {r['price_rt']:>7,} {r['rating_label']:<8} {hist_low}"
        )
        if r["return_options"]:
            for ro in r["return_options"]:
                price_str = f"TWD {ro['price_rt']:,}" if ro["price_rt"] else "?"
                lines.append(f"     ↩ 回程選項: {ro['airline']} {ro['flight_no']} {ro['dep']}→{ro['arr']} ({price_str})")
        lines.append("")

    return "\n".join(lines)


def format_grid(results: list) -> str:
    if not results:
        return "無資料。"
    lines = [f"{'出發日':<12} {'回程日':<12} {'票價':>10}"]
    lines.append("-" * 38)
    for r in results[:30]:
        price_str = f"TWD {r['price']:,}" if r["price"] else "?"
        lines.append(f"{r['depart']:<12} {r['return']:<12} {price_str:>10}")
    return "\n".join(lines)


def format_graph(results: list) -> str:
    if not results:
        return "無資料。"
    lines = [f"{'出發日':<12} {'回程日':<12} {'最低票價':>10}"]
    lines.append("-" * 38)
    for r in results[:60]:
        price_str = f"TWD {r['price']:,}" if r["price"] else "?"
        lines.append(f"{r['depart']:<12} {r['return']:<12} {price_str:>10}")
    return "\n".join(lines)


def resolve_destinations(raw: str):
    key = raw.upper()
    if key in COUNTRY_AIRPORTS:
        airports = COUNTRY_AIRPORTS[key]
        print(f"（{key} 展開為 {', '.join(airports)}）")
        return airports
    return [d.upper() for d in raw.split(",")]


def main():
    args = sys.argv[1:]
    nonstop = "--nonstop" in args
    if nonstop:
        args = [a for a in args if a != "--nonstop"]
    stops = STOPS_NONSTOP if nonstop else STOPS_ANY

    one_way = "--oneway" in args
    if one_way:
        args = [a for a in args if a != "--oneway"]

    # --return-from NRT,HND  (open-jaw: return from different airports)
    return_origin_airports = None
    for i, a in enumerate(args):
        if a == "--return-from" and i + 1 < len(args):
            return_origin_airports = [x.upper() for x in args[i + 1].split(",")]
            args = args[:i] + args[i + 2:]
            break

    if not args:
        print(__doc__)
        sys.exit(1)

    mode = args[0] if args[0].startswith("--") else "scan"
    if mode in ("--grid", "--graph"):
        args = args[1:]

    if mode == "--grid":
        # --grid <origin> <dest> <out_start> <out_end> <ret_start> <ret_end> [airlines]
        if len(args) < 6:
            print("用法: python search.py --grid <origin> <dest> <out_start> <out_end> <ret_start> <ret_end> [airlines] [--nonstop]")
            sys.exit(1)
        origin = args[0].upper()
        destinations = resolve_destinations(args[1])
        out_start, out_end, ret_start, ret_end = args[2], args[3], args[4], args[5]
        airlines = args[6].upper().split(",") if len(args) > 6 else DEFAULT_AIRLINES

        nonstop_label = "（僅直飛）" if nonstop else ""
        print(f"日曆網格: {origin} → {','.join(destinations)}{nonstop_label}")
        print(f"出發範圍: {out_start} ~ {out_end}，回程範圍: {ret_start} ~ {ret_end}\n")

        results = get_calendar_grid(origin, destinations, out_start, out_end, ret_start, ret_end, airlines, stops)
        print(format_grid(results))

        with open("/tmp/flight_grid.json", "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n詳細資料已存至 /tmp/flight_grid.json")

    elif mode == "--graph":
        # --graph <origin> <dest> <date_start> <date_end> <min_days> <max_days> [airlines]
        if len(args) < 6:
            print("用法: python search.py --graph <origin> <dest> <date_start> <date_end> <min_days> <max_days> [airlines] [--nonstop]")
            sys.exit(1)
        origin = args[0].upper()
        destinations = resolve_destinations(args[1])
        date_start, date_end = args[2], args[3]
        min_days, max_days = int(args[4]), int(args[5])
        airlines = args[6].upper().split(",") if len(args) > 6 else DEFAULT_AIRLINES

        nonstop_label = "（僅直飛）" if nonstop else ""
        print(f"日曆折線: {origin} → {','.join(destinations)}{nonstop_label}")
        days_label = f"{min_days} 天" if min_days == max_days else f"{min_days}~{max_days} 天"
        print(f"日期範圍: {date_start} ~ {date_end}，行程 {days_label}（含頭含尾）\n")

        results = get_calendar_graph(origin, destinations, date_start, date_end, min_days, max_days, airlines, stops)
        print(format_graph(results))

        with open("/tmp/flight_graph.json", "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n詳細資料已存至 /tmp/flight_graph.json")

    elif one_way:
        # 單程掃描模式：--oneway <origin> <dest> <depart_start> <depart_end> [budget] [airlines]
        if len(args) < 4:
            print("用法: python search.py --oneway <origin> <dest> <depart_start> <depart_end> [budget=15000] [airlines] [--nonstop]")
            print("範例: python search.py --oneway KIX TPE 2026-11-01 2026-11-30 5000 TR,IT,MM")
            sys.exit(1)
        origin = args[0].upper()
        destinations = resolve_destinations(args[1])
        depart_start = date.fromisoformat(args[2])
        depart_end = date.fromisoformat(args[3])
        budget = int(args[4]) if len(args) > 4 else 15000
        airlines = args[5].upper().split(",") if len(args) > 5 else DEFAULT_AIRLINES

        nonstop_label = "（僅直飛）" if nonstop else ""
        print(f"搜尋（單程）: {origin} → {','.join(destinations)}{nonstop_label}")
        print(f"日期: {depart_start} ~ {depart_end}")
        print(f"預算: TWD {budget:,}")
        print(f"航空: {', '.join(airlines)}\n")

        results = scan_oneway_dates(origin, destinations, depart_start, depart_end, budget, airlines, stops)

        print("\n" + "=" * 100)
        print(format_oneway_results(results))

        with open("/tmp/flight_oneway.json", "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n詳細資料已存至 /tmp/flight_oneway.json")

    else:
        # 掃描模式
        if len(args) < 5:
            print("用法: python search.py <origin> <dest> <depart_start> <depart_end> <trip_days> [budget=15000] [airlines] [--nonstop]")
            print("範例: python search.py TPE JP 2026-07-01 2026-07-31 7 14000 CI,BR --nonstop")
            sys.exit(1)
        origin = args[0].upper()
        destinations = resolve_destinations(args[1])
        depart_start = date.fromisoformat(args[2])
        depart_end = date.fromisoformat(args[3])
        trip_days = int(args[4])
        budget = int(args[5]) if len(args) > 5 else 15000
        airlines = args[6].upper().split(",") if len(args) > 6 else DEFAULT_AIRLINES

        nonstop_label = "（僅直飛）" if nonstop else ""
        print(f"搜尋: {origin} → {','.join(destinations)}{nonstop_label}")
        print(f"日期: {depart_start} ~ {depart_end}，行程 {trip_days} 天")
        print(f"預算: TWD {budget:,}")
        print(f"航空: {', '.join(airlines)}\n")

        results = scan_dates(origin, destinations, depart_start, depart_end, trip_days, budget, airlines, stops,
                             return_origin_airports=return_origin_airports)

        print("\n" + "=" * 100)
        print(format_results(results))

        with open("/tmp/flight_results.json", "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n詳細資料已存至 /tmp/flight_results.json")


if __name__ == "__main__":
    main()
