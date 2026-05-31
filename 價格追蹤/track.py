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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).parent
SEARCH_PY = BASE.parent / ".claude/skills/search-flights/search.py"
TARGETS_FILE = BASE / "targets.json"
HISTORY_FILE = BASE / "history.json"
TMP_RESULTS = Path("/tmp/flight_results.json")
TMP_ONEWAY  = Path("/tmp/flight_oneway.json")

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


# ---------------------------------------------------------------------------
# One-way / open-jaw helpers
# ---------------------------------------------------------------------------

def _query_oneway_leg(origin: str, dest: str, date_str: str) -> Optional[dict]:
    """Query a single one-way leg; return cheapest result dict or None."""
    cmd = ["python3", str(SEARCH_PY), "--oneway", origin, dest, date_str, date_str]
    print(f"    → 單程查詢：{origin} → {dest} {date_str}...", end=" ", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ {result.stderr[:80]}")
        return None
    if not TMP_ONEWAY.exists():
        print("❌ 找不到結果檔案")
        return None
    with open(TMP_ONEWAY, encoding="utf-8") as f:
        data = json.load(f)
    if not data:
        print("❌ 查無結果")
        return None
    best = min(data, key=lambda r: r.get("price_ow", 999_999))
    print(f"最低 TWD {best['price_ow']:,}（{best['flight_no']} {best['dep']}→{best['arr']}）")
    return best


def _query_open_jaw(target: dict) -> Optional[dict]:
    """Query both legs of an open-jaw itinerary and return combined result."""
    print(f"  查詢中：{target['name']} (開口票)")
    leg_out = _query_oneway_leg(target["origin"], target["dest"],       target["depart_date"])
    leg_ret = _query_oneway_leg(target["return_from"], target["origin"], target["return_date"])
    if not leg_out or not leg_ret:
        return None
    combined = leg_out["price_ow"] + leg_ret["price_ow"]
    print(f"  合計：TWD {leg_out['price_ow']:,} + TWD {leg_ret['price_ow']:,} = TWD {combined:,}")
    return {"type": "open_jaw", "combined_price": combined, "leg_out": leg_out, "leg_ret": leg_ret}


# ---------------------------------------------------------------------------
# Round-trip query (original)
# ---------------------------------------------------------------------------

def query_target(target: dict):
    if target.get("type") == "open_jaw":
        return _query_open_jaw(target)

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


# ---------------------------------------------------------------------------
# Snapshot recording
# ---------------------------------------------------------------------------

def _record_open_jaw_snapshot(history: dict, target_id: str, result: dict) -> dict:
    """Record open-jaw snapshot. inbound = 去程(into Japan), outbound = 回程(out of Japan)."""
    out = result["leg_out"]   # e.g. TPE→KIX
    ret = result["leg_ret"]   # e.g. OKJ→TPE
    snapshot = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "price": result["combined_price"],
        "depart_date": out["depart_date"],
        "return_date": ret["depart_date"],
        "inbound": {          # 去程 leg (inbound to destination country)
            "airline":   out["airline"],
            "flight_no": out["flight_no"],
            "dep":       out["dep"],
            "arr":       out["arr"],
            "price":     out["price_ow"],
        },
        "outbound": {         # 回程 leg (outbound from destination country)
            "airline":   ret["airline"],
            "flight_no": ret["flight_no"],
            "dep":       ret["dep"],
            "arr":       ret["arr"],
            "price":     ret["price_ow"],
        },
    }
    history.setdefault(target_id, []).append(snapshot)
    return history


def record_snapshot(history: dict, target_id: str, results) -> dict:
    if isinstance(results, dict) and results.get("type") == "open_jaw":
        return _record_open_jaw_snapshot(history, target_id, results)

    best = best_result(results)
    if not best:
        return history
    ret = (best.get("return_options") or [None])[0]
    snapshot = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "price": best["price_rt"],
        "airline": best["airline"],
        "flight_no": best["flight_no"],
        "dep": best["dep"],
        "arr": best["arr"],
        "return_date": best.get("return_date"),
        "ret_airline": ret["airline"] if ret else None,
        "ret_flight_no": ret["flight_no"] if ret else None,
        "ret_dep": ret["dep"] if ret else None,
        "ret_arr": ret["arr"] if ret else None,
        "rating": best["rating_label"],
        "history_min": best.get("history_min"),
        "top3": [
            {
                "airline": r["airline"],
                "flight_no": r["flight_no"],
                "dep": r["dep"],
                "arr": r["arr"],
                "price": r["price_rt"],
                "rating": r["rating_label"],
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


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_open_jaw_report(target: dict, records: list, history: dict):
    tid = target["id"]
    latest = records[-1]
    prev   = prev_snapshot(history, tid)
    atl    = all_time_low(history, tid)

    print(f"  {target['origin']}→{target['dest']} {target['depart_date']}  ＋"
          f"  {target['return_from']}→{target['origin']} {target['return_date']}")
    print(f"  備注：{target['notes']}")

    inb = latest["inbound"]
    out = latest["outbound"]
    print(f"\n  合計  TWD {latest['price']:,}")
    print(f"  去程  {inb['airline']} {inb['flight_no']}  "
          f"{inb['dep']}→{inb['arr']}  TWD {inb['price']:,}")
    print(f"  回程  {out['airline']} {out['flight_no']}  "
          f"{out['dep']}→{out['arr']}  TWD {out['price']:,}")

    if prev:
        diff = latest["price"] - prev["price"]
        sign, color = ("↑", "漲") if diff > 0 else ("↓", "降")
        print(f"  上次記錄  TWD {prev['price']:,}  ({sign}{color} {abs(diff):,}，{days_ago(prev['checked_at'])})")

    if atl:
        diff_atl = latest["price"] - atl
        if diff_atl == 0:
            print(f"  歷史最低  TWD {atl:,}  ← 目前即歷史低點！")
        else:
            print(f"  歷史最低  TWD {atl:,}  （距低點還差 TWD {diff_atl:,}）")

    threshold = target.get("alert_threshold")
    if threshold:
        if latest["price"] <= threshold:
            print(f"\n  🔥 已達目標價！TWD {latest['price']:,} ≤ TWD {threshold:,}，可出手！")
        else:
            gap = latest["price"] - threshold
            print(f"\n  💡 建議：繼續等，距目標 TWD {threshold:,} 還差 TWD {gap:,}。")


def print_report(targets: list, history: dict):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"  機票價格追蹤報告  {now_str}")
    print(f"{'='*60}")

    for target in targets:
        tid = target["id"]
        records = history.get(tid, [])
        print(f"\n【{target['name']}】")

        if not records:
            print("  （尚無查詢記錄）")
            continue

        # Open-jaw targets have their own display logic
        if target.get("type") == "open_jaw":
            _print_open_jaw_report(target, records, history)
            continue

        # --- Round-trip display ---
        print(f"  {target['origin']} → {target['dest']}  "
              f"{target['depart_date']} 出發  {target['days']}天")
        print(f"  備注：{target['notes']}")

        latest = records[-1]
        prev = prev_snapshot(history, tid)
        atl = all_time_low(history, tid)
        eff_rating = effective_rating(latest["price"], latest["rating"], latest.get("history_min"))
        rating_icon = RATING_LABEL.get(eff_rating, "")

        print(f"\n  現在最低  TWD {latest['price']:,}  "
              f"{rating_icon}  "
              f"{latest['airline']} {latest['flight_no']}  "
              f"{latest['dep']}→{latest['arr']}")
        if latest.get("ret_flight_no"):
            print(f"  回程       {latest.get('ret_airline', '')} {latest['ret_flight_no']}  "
                  f"{latest.get('return_date', '')}  "
                  f"{latest.get('ret_dep', '?')}→{latest.get('ret_arr', '?')}")

        if prev:
            diff = latest["price"] - prev["price"]
            sign = "↑" if diff > 0 else "↓"
            color = "漲" if diff > 0 else "降"
            ago = days_ago(prev["checked_at"])
            print(f"  上次記錄  TWD {prev['price']:,}  "
                  f"({sign}{color} {abs(diff):,}，{ago})")

        diff_from_atl = 0
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
                print(f"  Google低點 TWD {google_low:,}  ← 已達或低於 Google 歷史低！")
            else:
                print(f"  Google低點 TWD {google_low:,}  （差 TWD {diff:,}）")

        # 建議
        rating = eff_rating
        if rating == "超值":
            print(f"\n  💡 建議：超值票，現在可考慮出手。")
        elif rating == "便宜":
            if atl and diff_from_atl == 0:
                print(f"\n  💡 建議：便宜且為歷史低點，可出手。")
            else:
                print(f"\n  💡 建議：便宜，但還有空間可等更低。")
        else:
            print(f"\n  💡 建議：繼續等，尚未到買點。")

        # Top 3
        if latest.get("top3"):
            print(f"\n  前3低價選項：")
            for i, r in enumerate(latest["top3"], 1):
                adj = effective_rating(r["price"], r["rating"], r.get("history_min"))
                icon = RATING_LABEL.get(adj, "")
                hmin = f"歷史低 {r['history_min']:,}" if r.get("history_min") else ""
                print(f"  {i}. TWD {r['price']:,} {icon}  "
                      f"{r['airline']} {r['flight_no']}  {r['dep']}→{r['arr']}  {hmin}")

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
        is_oj = target.get("type") == "open_jaw"
        for r in records:
            ago = days_ago(r["checked_at"])
            checked_local = datetime.fromisoformat(r["checked_at"]).strftime("%m/%d %H:%M")
            if is_oj:
                inb = r.get("inbound", {})
                out = r.get("outbound", {})
                print(f"  {checked_local} ({ago:>5})  合計 TWD {r['price']:,}  "
                      f"去程 {inb.get('flight_no','?')} TWD {inb.get('price','?'):,}  "
                      f"回程 {out.get('flight_no','?')} TWD {out.get('price','?'):,}")
            else:
                adj = effective_rating(r["price"], r.get("rating", "一般"), r.get("history_min"))
                icon = RATING_LABEL.get(adj, "")
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
        results = query_target(target)
        if results:
            history = record_snapshot(history, target["id"], results)
            if isinstance(results, dict):  # open_jaw
                print(f"  ✓ 開口票合計 TWD {results['combined_price']:,}")
            else:
                print(f"  ✓ 找到 {len(results)} 筆，最低 TWD {best_result(results)['price_rt']:,}")
        else:
            print(f"  ✗ {target['name']} 查無結果")

    save_history(history)
    print_report(targets, history)


if __name__ == "__main__":
    main()
