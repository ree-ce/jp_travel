#!/usr/bin/env python3
"""
Flight price tracker — queries all target trips and records history.

Usage:
  python3 track.py              # query all targets, show summary, save to history
  python3 track.py --history    # show price history only (no new query)
  python3 track.py --id PLAN_ID # query one specific target only
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).parent
SEARCH_PY = BASE.parent / ".claude/skills/search-flights/search.py"
TARGETS_FILE = BASE / "targets.json"
HISTORY_FILE = BASE / "history.json"
TMP_RESULTS  = Path("/tmp/flight_results.json")
TMP_ONEWAY   = Path("/tmp/flight_oneway.json")
TMP_INBOUND  = Path("/tmp/flight_inbound.json")   # temp copy while open-jaw scans outbound

RATING_SCORE = {"超值": 1, "便宜": 2, "一般偏低": 3, "一般": 4, "偏高": 5, "高": 6}
# Display as rank [1/6] so hierarchy is unambiguous
RATING_LABEL = {
    "超值":   "🔥 [1/6] 超值",
    "便宜":   "✅ [2/6] 便宜",
    "一般偏低": "🟡 [3/6] 一般偏低",
    "一般":   "➖ [4/6] 一般",
    "偏高":   "🔺 [5/6] 偏高",
    "高":    "❌ [6/6] 高",
}


def load_targets() -> list:
    with open(TARGETS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def query_openjaw_target(target: dict) -> Optional[dict]:
    """Scan inbound and outbound legs separately, find cheapest combo at target trip_days."""
    inb      = target["inbound"]
    out      = target["outbound"]
    budget   = str(target.get("budget", 12000))
    trip_days = target["trip_days"]

    # --- Inbound leg: e.g. TPE → KIX ---
    print(f"  去程掃描：{inb['origin']} → {inb['dest']}  "
          f"{inb['date_start']} ~ {inb['date_end']}...")
    subprocess.run(
        ["python3", str(SEARCH_PY), "--oneway",
         inb["origin"], inb["dest"],
         inb["date_start"], inb["date_end"],
         budget, inb.get("airlines", "IT,CI,BR,JX,GK")],
        capture_output=True, text=True,
    )
    inb_results = []
    if TMP_ONEWAY.exists():
        with open(TMP_ONEWAY, encoding="utf-8") as f:
            inb_results = json.load(f)
        shutil.copy(TMP_ONEWAY, TMP_INBOUND)   # preserve before next scan overwrites it

    # --- Outbound leg: e.g. OKJ → TPE ---
    print(f"  回程掃描：{out['origin']} → {out['dest']}  "
          f"{out['date_start']} ~ {out['date_end']}...")
    subprocess.run(
        ["python3", str(SEARCH_PY), "--oneway",
         out["origin"], out["dest"],
         out["date_start"], out["date_end"],
         budget, out.get("airlines", "IT")],
        capture_output=True, text=True,
    )
    out_results = []
    if TMP_ONEWAY.exists():
        with open(TMP_ONEWAY, encoding="utf-8") as f:
            out_results = json.load(f)

    # --- Find cheapest combo where (return - depart) == trip_days - 1 ---
    best: Optional[dict] = None
    best_total = 999_999
    for ir in inb_results:
        for or_ in out_results:
            dep = date.fromisoformat(ir["depart_date"])
            ret = date.fromisoformat(or_["depart_date"])
            if (ret - dep).days == trip_days - 1:
                total = ir["price_ow"] + or_["price_ow"]
                if total < best_total:
                    best_total = total
                    best = {
                        "type":        "open_jaw",
                        "depart_date": ir["depart_date"],
                        "return_date": or_["depart_date"],
                        "total_price": total,
                        "inbound":     ir,
                        "outbound":    or_,
                    }

    return best


def query_target(target: dict) -> list:
    cmd = [
        "python3", str(SEARCH_PY),
        target["origin"], target["dest"],
        target["depart_date"], target["depart_date"],
        str(target["days"]),
    ]
    print(f"  查詢中：{target['name']} ({target['origin']} → {target['dest']} "
          f"{target['depart_date']} {target['days']}天)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 查詢失敗：{result.stderr[:100]}")
        return []
    if not TMP_RESULTS.exists():
        print("  ❌ 找不到結果檔案")
        return []
    with open(TMP_RESULTS, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def best_result(results: list) -> Optional[dict]:
    if not results:
        return None
    return min(results, key=lambda r: r.get("price_rt", 999999))


def record_snapshot(history: dict, target_id: str, results) -> dict:
    """Append a price snapshot to history. results can be a list (round trip)
    or a dict with type=='open_jaw'."""
    if isinstance(results, dict) and results.get("type") == "open_jaw":
        snapshot = {
            "checked_at":  datetime.now(timezone.utc).isoformat(),
            "type":        "open_jaw",
            "price":       results["total_price"],
            "depart_date": results["depart_date"],
            "return_date": results["return_date"],
            "inbound": {
                "airline":   results["inbound"]["airline"],
                "flight_no": results["inbound"]["flight_no"],
                "dep":       results["inbound"]["dep"],
                "arr":       results["inbound"]["arr"],
                "price":     results["inbound"]["price_ow"],
            },
            "outbound": {
                "airline":   results["outbound"]["airline"],
                "flight_no": results["outbound"]["flight_no"],
                "dep":       results["outbound"]["dep"],
                "arr":       results["outbound"]["arr"],
                "price":     results["outbound"]["price_ow"],
            },
        }
    else:
        best = best_result(results)
        if not best:
            return history
        snapshot = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "price":      best["price_rt"],
            "airline":    best["airline"],
            "flight_no":  best["flight_no"],
            "dep":        best["dep"],
            "arr":        best["arr"],
            "rating":     best["rating_label"],
            "history_min": best.get("history_min"),
            "top3": [
                {
                    "airline":    r["airline"],
                    "flight_no":  r["flight_no"],
                    "dep":        r["dep"],
                    "arr":        r["arr"],
                    "price":      r["price_rt"],
                    "rating":     r["rating_label"],
                    "history_min": r.get("history_min"),
                }
                for r in sorted(results, key=lambda x: x["price_rt"])[:3]
            ],
        }
    history.setdefault(target_id, []).append(snapshot)
    return history


def effective_rating(price: int, google_rating: str, history_min: Optional[int]) -> str:
    """Downgrade Google's rating when current price is significantly above the historical low.

    Google rates vs typical price range; history_min is the actual floor seen recently.
    A ticket can't be '超值' if it's 11% above the cheapest it's been.

    Thresholds (gap = (price - history_min) / history_min):
      <= 5%  : trust Google's rating (nearly at the floor)
       5-15% : cap at 便宜 [2/6]   — decent, but not exceptional
      > 15%  : cap at 一般偏低 [3/6] — still room to drop
    """
    if not history_min or price <= history_min:
        return google_rating
    gap = (price - history_min) / history_min
    google_score = RATING_SCORE.get(google_rating, 4)
    if gap > 0.15:
        floor_score = RATING_SCORE["一般偏低"]
    elif gap > 0.05:
        floor_score = RATING_SCORE["便宜"]
    else:
        return google_rating
    adjusted = max(google_score, floor_score)
    return next(k for k, v in RATING_SCORE.items() if v == adjusted)


def all_time_low(history: dict, target_id: str) -> Optional[int]:
    records = history.get(target_id, [])
    prices = [r["price"] for r in records if r.get("price")]
    return min(prices) if prices else None


def prev_snapshot(history: dict, target_id: str) -> Optional[dict]:
    records = history.get(target_id, [])
    return records[-2] if len(records) >= 2 else None


def days_ago(iso_str: str) -> str:
    checked = datetime.fromisoformat(iso_str)
    now = datetime.now(timezone.utc)
    delta = (now - checked).days
    if delta == 0:
        return "今天"
    return f"{delta}天前"


def print_report(targets: list, history: dict):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"  機票價格追蹤報告  {now_str}")
    print(f"{'='*60}")

    for target in targets:
        tid = target["id"]
        records = history.get(tid, [])
        print(f"\n【{target['name']}】")
        if target.get("type") == "open_jaw":
            inb, out = target["inbound"], target["outbound"]
            print(f"  {inb['origin']}→{inb['dest']} 去 / {out['origin']}→{out['dest']} 回  "
                  f"{inb['date_start']}～{out['date_end']}  {target['trip_days']}天")
        else:
            print(f"  {target['origin']} → {target['dest']}  "
                  f"{target['depart_date']} 出發  {target['days']}天")
        print(f"  備注：{target['notes']}")

        if not records:
            print("  （尚無查詢記錄）")
            continue

        latest = records[-1]
        prev   = prev_snapshot(history, tid)
        atl    = all_time_low(history, tid)

        # --- Open jaw display ---
        if latest.get("type") == "open_jaw":
            inb = latest["inbound"]
            out = latest["outbound"]
            print(f"\n  現在最低  TWD {latest['price']:,}（開口票合計）")
            print(f"  去程  {inb['airline']} {inb['flight_no']}  "
                  f"{latest['depart_date']}  {inb['dep']}→{inb['arr']}  TWD {inb['price']:,}")
            print(f"  回程  {out['airline']} {out['flight_no']}  "
                  f"{latest['return_date']}  {out['dep']}→{out['arr']}  TWD {out['price']:,}")

            if prev:
                diff = latest["price"] - prev["price"]
                if diff == 0:
                    change = f"持平，{days_ago(prev['checked_at'])}"
                else:
                    sign, word = ("↑", "漲") if diff > 0 else ("↓", "降")
                    change = f"{sign}{word} {abs(diff):,}，{days_ago(prev['checked_at'])}"
                print(f"  上次記錄  TWD {prev['price']:,}  ({change})")

            if atl:
                diff_from_atl = latest["price"] - atl
                if diff_from_atl == 0:
                    print(f"  歷史最低  TWD {atl:,}  ← 目前即歷史低點！")
                else:
                    print(f"  歷史最低  TWD {atl:,}  （距低點還差 TWD {diff_from_atl:,}）")

            threshold = target.get("alert_threshold")
            if threshold and latest["price"] <= threshold:
                print(f"\n  🔥 建議：已達目標價 TWD {threshold:,}，可考慮出手！")
            elif threshold:
                print(f"\n  💡 建議：繼續等。目標價 TWD {threshold:,}，"
                      f"還差 TWD {latest['price'] - threshold:,}")
            else:
                print(f"\n  💡 建議：繼續觀察。")

        # --- Round trip display ---
        else:
            eff_rating  = effective_rating(latest["price"], latest["rating"], latest.get("history_min"))
            rating_icon = RATING_LABEL.get(eff_rating, "")
            stops_str   = "直飛" if latest.get("stops", 0) == 0 else f"{latest.get('stops')}停"

            print(f"\n  現在最低  TWD {latest['price']:,}  {rating_icon}")
            print(f"  {latest['airline']} {latest['flight_no']}  "
                  f"{latest['dep']}→{latest['arr']}  {stops_str}  "
                  f"出發 {latest.get('depart_date', '')}")

            if prev:
                diff = latest["price"] - prev["price"]
                if diff == 0:
                    change = f"持平，{days_ago(prev['checked_at'])}"
                else:
                    sign, word = ("↑", "漲") if diff > 0 else ("↓", "降")
                    change = f"{sign}{word} {abs(diff):,}，{days_ago(prev['checked_at'])}"
                print(f"  上次記錄  TWD {prev['price']:,}  ({change})")

            if atl:
                diff_from_atl = latest["price"] - atl
                if diff_from_atl == 0:
                    print(f"  歷史最低  TWD {atl:,}  ← 目前即歷史低點！")
                else:
                    print(f"  歷史最低  TWD {atl:,}  （距低點還差 TWD {diff_from_atl:,}）")

            if latest.get("history_min"):
                google_low = latest["history_min"]
                diff = latest["price"] - google_low
                if diff <= 0:
                    print(f"  Google低點 TWD {google_low:,}  ← 已達或低於！")
                else:
                    print(f"  Google低點 TWD {google_low:,}  （差 TWD {diff:,}）")

            rating = eff_rating
            diff_from_atl = (latest["price"] - atl) if atl else 1
            if rating == "超值":
                print(f"\n  💡 建議：超值票，可考慮出手。")
            elif rating == "便宜" and diff_from_atl == 0:
                print(f"\n  💡 建議：便宜且歷史低點，可出手。")
            elif rating == "便宜":
                print(f"\n  💡 建議：便宜，但還有空間可等更低。")
            else:
                print(f"\n  💡 建議：繼續等，尚未到買點。")

            if latest.get("top3"):
                print(f"\n  前3低價選項：")
                for i, r in enumerate(latest["top3"], 1):
                    adj      = effective_rating(r["price"], r["rating"], r.get("history_min"))
                    icon     = RATING_LABEL.get(adj, "")
                    stops_r  = "直飛" if r.get("stops", 0) == 0 else f"{r.get('stops')}停"
                    hmin     = f"  歷史低 {r['history_min']:,}" if r.get("history_min") else ""
                    print(f"  {i}. TWD {r['price']:,}  {icon}")
                    print(f"     {r['airline']} {r['flight_no']}  "
                          f"{r['dep']}→{r['arr']}  {stops_r}{hmin}")

    print(f"\n{'='*60}")
    print(f"  歷史記錄已存至 {HISTORY_FILE.name}（共 "
          f"{sum(len(v) for v in history.values())} 筆）")
    print(f"{'='*60}\n")


def print_history_only(targets: list, history: dict):
    print(f"\n{'='*60}  價格歷史  {'='*20}")
    for target in targets:
        tid = target["id"]
        records = history.get(tid, [])
        print(f"\n【{target['name']}】")
        if not records:
            print("  （尚無記錄）")
            continue
        for r in records:
            ago = days_ago(r["checked_at"])
            adj = effective_rating(r["price"], r["rating"], r.get("history_min"))
            icon = RATING_LABEL.get(adj, "")
            checked_local = datetime.fromisoformat(r["checked_at"]).strftime("%m/%d %H:%M")
            print(f"  {checked_local} ({ago:>5})  TWD {r['price']:,}  "
                  f"{icon}  {r['airline']} {r['flight_no']}")
        atl = all_time_low(history, tid)
        print(f"  → 歷史最低：TWD {atl:,}")
    print()


def main():
    args = sys.argv[1:]
    history_only = "--history" in args
    target_id = None
    if "--id" in args:
        idx = args.index("--id")
        target_id = args[idx + 1] if idx + 1 < len(args) else None

    targets = load_targets()
    if target_id:
        targets = [t for t in targets if t["id"] == target_id]
        if not targets:
            print(f"找不到 ID：{target_id}")
            sys.exit(1)

    history = load_history()

    if history_only:
        print_history_only(targets, history)
        return

    print(f"\n開始查詢 {len(targets)} 個目標路線...\n")
    for target in targets:
        if target.get("type") == "open_jaw":
            print(f"  查詢中（開口票）：{target['name']}")
            result = query_openjaw_target(target)
            if result:
                history = record_snapshot(history, target["id"], result)
                print(f"  ✓ 最佳組合 {result['depart_date']} 去 / {result['return_date']} 回  "
                      f"TWD {result['total_price']:,}")
            else:
                print(f"  ✗ {target['name']} 查無符合天數的組合")
        else:
            results = query_target(target)
            if results:
                history = record_snapshot(history, target["id"], results)
                print(f"  ✓ 找到 {len(results)} 筆，最低 TWD {best_result(results)['price_rt']:,}")
            else:
                print(f"  ✗ {target['name']} 查無結果")

    save_history(history)
    print_report(targets, history)


if __name__ == "__main__":
    main()
