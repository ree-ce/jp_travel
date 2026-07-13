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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).parent
SEARCH_PY = BASE.parent / ".claude/skills/search-flights/search.py"
TARGETS_FILE = BASE / "targets.json"
HISTORY_FILE = BASE / "history.json"
TMP_RESULTS = Path("/tmp/flight_results.json")
TMP_ONEWAY  = Path("/tmp/flight_oneway.json")

RATING_SCORE = {"超值": 1, "便宜": 2, "一般偏低": 3, "一般": 4, "偏高": 5, "高": 6}
RATING_LABEL = {
    "超值":     "🔥 [1/6] 超值",
    "便宜":     "✅ [2/6] 便宜",
    "一般偏低": "🟡 [3/6] 一般偏低",
    "一般":     "➖ [4/6] 一般",
    "偏高":     "🔺 [5/6] 偏高",
    "高":       "❌ [6/6] 高",
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
# One-way / open-jaw query helpers
# ---------------------------------------------------------------------------

def _query_oneway_leg(origin: str, dest: str, date_start: str,
                      date_end: Optional[str] = None,
                      airlines: Optional[str] = None,
                      min_dep: Optional[str] = None,
                      max_arr: Optional[str] = None,
                      nonstop: bool = False) -> Optional[dict]:
    """Query a single one-way leg over a date range; return cheapest result dict or None.

    min_dep: "HH:MM" — skip flights departing before this time (e.g. "15:00").
    max_arr: "HH:MM" — skip flights arriving after this time (e.g. "21:00").
    """
    end = date_end or date_start
    cmd = ["python3", str(SEARCH_PY), "--oneway", origin, dest, date_start, end]
    if airlines:
        cmd.extend(["15000", airlines])
    if nonstop:
        cmd.append("--nonstop")
    label = f"{date_start}" if end == date_start else f"{date_start}~{end}"
    time_note = ("".join([
        f" dep≥{min_dep}" if min_dep else "",
        f" arr≤{max_arr}" if max_arr else "",
    ]))
    print(f"    → 單程查詢：{origin} → {dest} {label}{time_note}...", end=" ", flush=True)
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
    candidates = data
    if min_dep:
        candidates = [r for r in candidates if r.get("dep", "00:00") >= min_dep]
    if max_arr:
        candidates = [r for r in candidates if r.get("arr", "99:99") <= max_arr]
    if not candidates:
        print(f"❌ 無符合時間限制的航班")
        return None
    best = min(candidates, key=lambda r: r.get("price_ow", 999_999))
    print(f"最低 TWD {best['price_ow']:,}（{best['flight_no']} {best['dep']}→{best['arr']}）")
    return best


def _query_open_jaw(target: dict) -> Optional[dict]:
    """Query both legs of an open-jaw itinerary (fixed dates)."""
    print(f"  查詢中：{target['name']} (開口票)")
    inb_airlines = target.get("inbound_airlines")
    out_airlines = target.get("outbound_airlines")
    leg_out = _query_oneway_leg(target["origin"], target["dest"], target["depart_date"], None, inb_airlines)
    leg_ret = _query_oneway_leg(target["return_from"], target["origin"], target["return_date"], None, out_airlines)
    if not leg_out or not leg_ret:
        return None
    combined = leg_out["price_ow"] + leg_ret["price_ow"]
    print(f"  合計：TWD {leg_out['price_ow']:,} + TWD {leg_ret['price_ow']:,} = TWD {combined:,}")
    return {"type": "open_jaw", "combined_price": combined, "leg_out": leg_out, "leg_ret": leg_ret}


def _query_open_jaw_range(target: dict) -> Optional[dict]:
    """Query open-jaw with flexible inbound range, maintaining fixed trip_days duration.

    For each depart date D in inbound range, pairs it with return date D+trip_days,
    skipping pairs where the return falls outside the outbound date range.
    Returns the cheapest (depart, return) pair found.
    """
    inb       = target["inbound"]
    out       = target["outbound"]
    trip_days = target.get("trip_days", 5)

    inb_start = date.fromisoformat(inb["date_start"])
    inb_end   = date.fromisoformat(inb["date_end"])
    out_start = date.fromisoformat(out["date_start"])
    out_end   = date.fromisoformat(out["date_end"])

    inb_airlines = inb.get("airlines")
    out_airlines = out.get("airlines")

    total = (inb_end - inb_start).days + 1
    print(f"  查詢中：{target['name']} (開口票，{trip_days}夜，掃 {total} 組日期)")

    best_combined = None
    best_leg_in   = None
    best_leg_out  = None

    current = inb_start
    while current <= inb_end:
        return_date = current + timedelta(days=trip_days)
        if return_date < out_start or return_date > out_end:
            current += timedelta(days=1)
            continue

        leg_in  = _query_oneway_leg(inb["origin"], inb["dest"],
                                    current.isoformat(), None, inb_airlines,
                                    max_arr=inb.get("max_arr"))
        leg_out = _query_oneway_leg(out["origin"], out["dest"],
                                    return_date.isoformat(), None, out_airlines,
                                    min_dep=out.get("min_dep"))

        if leg_in and leg_out:
            combined = leg_in["price_ow"] + leg_out["price_ow"]
            if best_combined is None or combined < best_combined:
                best_combined = combined
                best_leg_in   = leg_in
                best_leg_out  = leg_out

        current += timedelta(days=1)

    if best_combined is None:
        return None

    print(f"  最優組合：TWD {best_leg_in['price_ow']:,} + TWD {best_leg_out['price_ow']:,} = TWD {best_combined:,}")
    return {"type": "open_jaw", "combined_price": best_combined,
            "leg_out": best_leg_in, "leg_ret": best_leg_out}


# ---------------------------------------------------------------------------
# Round-trip query
# ---------------------------------------------------------------------------

def query_target(target: dict):
    if target.get("type") == "open_jaw":
        if "inbound" in target:
            return _query_open_jaw_range(target)
        return _query_open_jaw(target)

    if target.get("type") == "oneway":
        return _query_oneway_leg(
            target["origin"], target["dest"],
            target["date_start"], target.get("date_end"),
            target.get("airlines"),
        )

    date_start = target.get("date_start") or target["depart_date"]
    date_end   = target.get("date_end") or date_start
    cmd = [
        "python3", str(SEARCH_PY),
        target["origin"], target["dest"],
        date_start, date_end,
        str(target["days"]),
    ]
    if target.get("airlines"):
        cmd.extend([str(target.get("budget", 15000)), target["airlines"]])
    if target.get("nonstop"):
        cmd.append("--nonstop")
    print(f"  查詢中：{target['name']} ({target['origin']} → {target['dest']} "
          f"{date_start}~{date_end} {target['days']}天{' 直飛' if target.get('nonstop') else ''})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 查詢失敗：{result.stderr[:100]}")
        return []
    if not TMP_RESULTS.exists():
        print("  ❌ 找不到結果檔案")
        return []
    with open(TMP_RESULTS, encoding="utf-8") as f:
        data = json.load(f)
    results = data if isinstance(data, list) else []

    # Apply min_ret_dep filter — drop return options that depart too early.
    min_ret_dep = target.get("min_ret_dep")
    nonstop = bool(target.get("nonstop"))
    if min_ret_dep:
        for r in results:
            r["return_options"] = [
                opt for opt in (r.get("return_options") or [])
                if opt.get("dep", "00:00") >= min_ret_dep
            ]

    if min_ret_dep or nonstop:
        # Constraints active: scan mode only provides return_options for the
        # cheapest outbound. Supplement ALL dates with empty return_options so
        # valid combos (e.g. Nov 14 out → Nov 18 CI179) aren't silently dropped.
        for r in results:
            if not r.get("return_options"):
                ret_date   = r.get("return_date")
                ret_origin = r.get("to", "")
                if ret_date and ret_origin:
                    print(f"    → 補查回程：{ret_origin} → {target['origin']} {ret_date}...", end=" ", flush=True)
                    ret_leg = _query_oneway_leg(ret_origin, target["origin"], ret_date, None,
                                                target.get("airlines"), min_dep=min_ret_dep,
                                                nonstop=nonstop)
                    if ret_leg:
                        r["return_options"] = [ret_leg]
        results = [r for r in results if r.get("return_options")]
    else:
        # No constraints: supplement only the single cheapest result.
        best = best_result(results)
        if best and not (best.get("return_options") or []):
            ret_date   = best.get("return_date")
            ret_origin = best.get("to", "")
            if ret_date and ret_origin:
                print(f"    → 補查回程：{ret_origin} → {target['origin']} {ret_date}...", end=" ", flush=True)
                ret_leg = _query_oneway_leg(ret_origin, target["origin"], ret_date, None,
                                            target.get("airlines"))
                if ret_leg:
                    best["return_options"] = [ret_leg]

    return results


def best_result(results: list) -> Optional[dict]:
    if not results:
        return None
    return min(results, key=lambda r: r.get("price_rt", 999999))


# ---------------------------------------------------------------------------
# Canonical snapshot schema + compat reader
# ---------------------------------------------------------------------------
# All recording functions write the same 16 fields regardless of target type.
# normalize_snapshot() maps old snapshots (field names varied by type) to the
# same shape, so render code never needs to branch on type to pick a field name.
#
# Canonical fields:
#   checked_at, price, depart_date, return_date,
#   out_airline, out_flight_no, out_dep, out_arr, out_price,
#   ret_airline, ret_flight_no, ret_dep, ret_arr, ret_price,
#   rating, google_low, top3

def normalize_snapshot(snap: dict, target_type: str = "roundtrip") -> dict:
    """Return a canonical view of any snapshot (old or new format)."""
    if "out_flight_no" in snap:
        return snap  # already canonical

    if target_type == "open_jaw":
        inb = snap.get("inbound", {})
        out = snap.get("outbound", {})
        return {
            "checked_at":    snap["checked_at"],
            "price":         snap["price"],
            "depart_date":   snap.get("depart_date"),
            "return_date":   snap.get("return_date"),
            "out_airline":   inb.get("airline"),
            "out_flight_no": inb.get("flight_no"),
            "out_dep":       inb.get("dep"),
            "out_arr":       inb.get("arr"),
            "out_price":     inb.get("price"),
            "ret_airline":   out.get("airline"),
            "ret_flight_no": out.get("flight_no"),
            "ret_dep":       out.get("dep"),
            "ret_arr":       out.get("arr"),
            "ret_price":     out.get("price"),
            "rating":        None,   # OJ rating computed from history at render time
            "google_low":    None,
            "top3":          None,
        }

    if target_type == "oneway":
        return {
            "checked_at":    snap["checked_at"],
            "price":         snap["price"],
            "depart_date":   snap.get("depart_date"),
            "return_date":   None,
            "out_airline":   snap.get("airline"),
            "out_flight_no": snap.get("flight_no"),
            "out_dep":       snap.get("dep"),
            "out_arr":       snap.get("arr"),
            "out_price":     snap.get("price"),
            "ret_airline":   None,
            "ret_flight_no": None,
            "ret_dep":       None,
            "ret_arr":       None,
            "ret_price":     None,
            "rating":        None,
            "google_low":    None,
            "top3":          None,
        }

    # roundtrip — old format: flight_no / ret_flight_no / history_min
    return {
        "checked_at":    snap["checked_at"],
        "price":         snap["price"],
        "depart_date":   snap.get("depart_date"),
        "return_date":   snap.get("return_date"),
        "out_airline":   snap.get("airline"),
        "out_flight_no": snap.get("flight_no"),
        "out_dep":       snap.get("dep"),
        "out_arr":       snap.get("arr"),
        "out_price":     None,
        "ret_airline":   snap.get("ret_airline"),
        "ret_flight_no": snap.get("ret_flight_no"),
        "ret_dep":       snap.get("ret_dep"),
        "ret_arr":       snap.get("ret_arr"),
        "ret_price":     None,
        "rating":        snap.get("rating"),
        "google_low":    snap.get("history_min") or snap.get("google_low"),
        "top3":          snap.get("top3"),
    }


def oj_rating(price: int, records: list) -> str:
    """Rate an open-jaw price relative to tracked history."""
    prices = [r["price"] for r in records if r.get("price")]
    if len(prices) < 2:
        return f"❓ 資料不足（僅 {len(prices)} 筆）"
    atl = min(prices)
    if price <= atl:
        return f"🔥 [1/6] 超值（歷史低點 TWD {atl:,}）"
    gap = (price - atl) / atl
    if gap <= 0.05:
        label = "✅ [2/6] 便宜"
    elif gap <= 0.15:
        label = "🟡 [3/6] 一般偏低"
    elif gap <= 0.30:
        label = "➖ [4/6] 一般"
    elif gap <= 0.50:
        label = "🔺 [5/6] 偏高"
    else:
        label = "❌ [6/6] 高"
    return f"{label}（歷史低點 TWD {atl:,}，差 +{gap*100:.0f}%）"


def effective_rating(price: int, google_rating: str, history_min: Optional[int]) -> str:
    """Adjust Google's rating using the gap to the historical floor.

    Computes a gap-based rating with the same thresholds as oj_rating(),
    then returns the WORSE of Google's rating vs the gap-based one.
    This prevents Google from over-rating a price that is well above the floor.
    """
    if not history_min:
        return google_rating
    if price <= history_min:
        return "超值"
    gap = (price - history_min) / history_min
    if gap <= 0.05:     gap_rating = "便宜"
    elif gap <= 0.15:   gap_rating = "一般偏低"
    elif gap <= 0.30:   gap_rating = "一般"
    elif gap <= 0.50:   gap_rating = "偏高"
    else:               gap_rating = "高"
    adjusted = max(RATING_SCORE.get(google_rating, 4), RATING_SCORE[gap_rating])
    return next(k for k, v in RATING_SCORE.items() if v == adjusted)


# ---------------------------------------------------------------------------
# Snapshot recording — all three types write the same canonical fields
# ---------------------------------------------------------------------------

def _record_open_jaw_snapshot(history: dict, target_id: str, result: dict) -> dict:
    out = result["leg_out"]   # TPE→destination (inbound to Japan)
    ret = result["leg_ret"]   # destination→TPE (outbound from Japan)
    snapshot = {
        "checked_at":    datetime.now(timezone.utc).isoformat(),
        "price":         result["combined_price"],
        "depart_date":   out.get("depart_date", ""),
        "return_date":   ret.get("depart_date", ""),
        "out_airline":   out.get("airline"),
        "out_flight_no": out.get("flight_no"),
        "out_dep":       out.get("dep"),
        "out_arr":       out.get("arr"),
        "out_price":     out.get("price_ow"),
        "ret_airline":   ret.get("airline"),
        "ret_flight_no": ret.get("flight_no"),
        "ret_dep":       ret.get("dep"),
        "ret_arr":       ret.get("arr"),
        "ret_price":     ret.get("price_ow"),
        "rating":        None,   # OJ rating computed from history at render time
        "google_low":    None,
        "top3":          None,
    }
    history.setdefault(target_id, []).append(snapshot)
    return history


def record_snapshot(history: dict, target_id: str, results) -> dict:
    if isinstance(results, dict) and results.get("type") == "open_jaw":
        return _record_open_jaw_snapshot(history, target_id, results)

    # One-way leg
    if isinstance(results, dict) and "price_ow" in results:
        snapshot = {
            "checked_at":    datetime.now(timezone.utc).isoformat(),
            "price":         results["price_ow"],
            "depart_date":   results.get("depart_date", ""),
            "return_date":   None,
            "out_airline":   results.get("airline"),
            "out_flight_no": results.get("flight_no", "?"),
            "out_dep":       results.get("dep", "?"),
            "out_arr":       results.get("arr", "?"),
            "out_price":     results["price_ow"],
            "ret_airline":   None,
            "ret_flight_no": None,
            "ret_dep":       None,
            "ret_arr":       None,
            "ret_price":     None,
            "rating":        None,
            "google_low":    None,
            "top3":          None,
        }
        history.setdefault(target_id, []).append(snapshot)
        return history

    # Round-trip — pre-compute effective rating at record time
    best = best_result(results)
    if not best:
        return history
    ret = (best.get("return_options") or [None])[0]
    eff_rating = effective_rating(
        best["price_rt"], best.get("rating_label", "一般"), best.get("history_min")
    )
    snapshot = {
        "checked_at":    datetime.now(timezone.utc).isoformat(),
        "price":         best["price_rt"],
        "depart_date":   best.get("depart_date", ""),
        "return_date":   best.get("return_date"),
        "out_airline":   best.get("airline"),
        "out_flight_no": best.get("flight_no"),
        "out_dep":       best.get("dep"),
        "out_arr":       best.get("arr"),
        "out_price":     None,
        "ret_airline":   ret["airline"] if ret else None,
        "ret_flight_no": ret["flight_no"] if ret else None,
        "ret_dep":       ret["dep"] if ret else None,
        "ret_arr":       ret["arr"] if ret else None,
        "ret_price":     None,
        "rating":        eff_rating,
        "google_low":    best.get("history_min"),
        "top3": [
            {
                "out_airline":   r.get("airline"),
                "out_flight_no": r.get("flight_no"),
                "out_dep":       r.get("dep"),
                "out_arr":       r.get("arr"),
                "price":         r["price_rt"],
                "rating":        effective_rating(
                    r["price_rt"], r.get("rating_label", "一般"), r.get("history_min")
                ),
                "google_low":    r.get("history_min"),
            }
            for r in sorted(results, key=lambda x: x["price_rt"])[:3]
        ],
    }
    history.setdefault(target_id, []).append(snapshot)
    return history


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
# Reporting — single unified path via normalize_snapshot
# ---------------------------------------------------------------------------

def print_report(targets: list, history: dict):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"  機票價格追蹤報告  {now_str}")
    print(f"{'='*60}")

    for target in targets:
        tid   = target["id"]
        ttype = target.get("type", "roundtrip")
        records = history.get(tid, [])
        print(f"\n【{target['name']}】")

        if not records:
            print("  （尚無查詢記錄）")
            continue

        norm   = normalize_snapshot(records[-1], ttype)
        prev_r = records[-2] if len(records) >= 2 else None
        prev   = normalize_snapshot(prev_r, ttype) if prev_r else None
        atl    = all_time_low(history, tid)
        price  = norm["price"]

        # ── route / date header ───────────────────────────────────────
        if ttype == "open_jaw" and "inbound" in target:
            inb_cfg = target["inbound"]
            out_cfg = target["outbound"]
            print(f"  {inb_cfg['origin']}→{inb_cfg['dest']} "
                  f"{inb_cfg['date_start']}~{inb_cfg['date_end']}  ＋  "
                  f"{out_cfg['origin']}→{out_cfg['dest']} "
                  f"{out_cfg['date_start']}~{out_cfg['date_end']}")
        elif ttype == "open_jaw":
            print(f"  {target['origin']}→{target['dest']} {target.get('depart_date','')}  ＋  "
                  f"{target.get('return_from','')}→{target['origin']} {target.get('return_date','')}")
        elif ttype == "oneway":
            print(f"  {target['origin']}→{target['dest']}  "
                  f"{target.get('date_start','')}~{target.get('date_end','')}")
        else:
            date_start = target.get("date_start", target.get("depart_date", ""))
            print(f"  {target['origin']} → {target['dest']}  "
                  f"{date_start} 出發  {target.get('days','')}天")
        print(f"  備注：{target.get('notes','')}")

        # ── price + rating ────────────────────────────────────────────
        if ttype == "open_jaw":
            rating_str = oj_rating(price, records)
        else:
            rating_str = RATING_LABEL.get(norm.get("rating") or "一般", "")
        print(f"\n  現在最低  TWD {price:,}  {rating_str}")

        # ── flights ───────────────────────────────────────────────────
        out_fn   = norm.get("out_flight_no") or "?"
        out_dep  = norm.get("out_dep") or ""
        out_arr  = norm.get("out_arr") or ""
        out_date = norm.get("depart_date") or ""
        arr_note = " ⚠️" if out_arr == "00:00" else ""
        print(f"  去 {out_fn}  {out_date}  {out_dep}→{out_arr}{arr_note}")

        ret_fn   = norm.get("ret_flight_no")
        ret_date = norm.get("return_date") or ""
        days     = target.get("days") or target.get("trip_days")
        days_str = f"  共{days}天" if days else ""
        if ret_fn:
            ret_dep = norm.get("ret_dep") or "?"
            ret_arr = norm.get("ret_arr") or "?"
            print(f"  回 {ret_fn}  {ret_date}  {ret_dep}→{ret_arr}{days_str}")
        elif ret_date:
            print(f"  回 {ret_date}{days_str}")

        # ── OJ individual leg prices ──────────────────────────────────
        if ttype == "open_jaw" and norm.get("out_price"):
            ret_p = norm.get("ret_price") or 0
            print(f"  去程 TWD {norm['out_price']:,}  +  回程 TWD {ret_p:,}")

        # ── change vs previous ────────────────────────────────────────
        if prev:
            diff = price - prev["price"]
            sign, color = ("↑", "漲") if diff > 0 else ("↓", "降")
            print(f"  上次記錄  TWD {prev['price']:,}  "
                  f"({sign}{color} {abs(diff):,}，{days_ago(prev['checked_at'])})")

        # ── all-time low ──────────────────────────────────────────────
        diff_from_atl = 0
        if atl:
            diff_from_atl = price - atl
            if diff_from_atl == 0:
                print(f"  歷史最低  TWD {atl:,}  ← 目前即歷史低點！")
            else:
                print(f"  歷史最低  TWD {atl:,}  （距低點還差 TWD {diff_from_atl:,}）")

        # ── Google historical floor ───────────────────────────────────
        if norm.get("google_low"):
            google_low = norm["google_low"]
            diff = price - google_low
            if diff <= 0:
                print(f"  Google低點 TWD {google_low:,}  ← 已達或低於 Google 歷史低！")
            else:
                print(f"  Google低點 TWD {google_low:,}  （差 TWD {diff:,}）")

        # ── 建議 ─────────────────────────────────────────────────────
        threshold = target.get("alert_threshold")
        if ttype in ("open_jaw", "oneway"):
            if threshold:
                if price <= threshold:
                    print(f"\n  🔥 已達目標價！TWD {price:,} ≤ TWD {threshold:,}，可出手！")
                else:
                    print(f"\n  💡 建議：繼續等，距目標 TWD {threshold:,} 還差 TWD {price - threshold:,}。")
        else:
            rating = norm.get("rating") or "一般"
            if rating == "超值":
                print(f"\n  💡 建議：超值票，現在可考慮出手。")
            elif rating == "便宜":
                if atl and diff_from_atl == 0:
                    print(f"\n  💡 建議：便宜且為歷史低點，可出手。")
                else:
                    print(f"\n  💡 建議：便宜，但還有空間可等更低。")
            else:
                print(f"\n  💡 建議：繼續等，尚未到買點。")

        # ── top 3 ────────────────────────────────────────────────────
        if norm.get("top3"):
            print(f"\n  前3低價選項：")
            for i, r in enumerate(norm["top3"], 1):
                adj  = r.get("rating") or "一般"
                icon = RATING_LABEL.get(adj, "")
                hmin = f"Google低點 {r['google_low']:,}" if r.get("google_low") else ""
                fn   = r.get("out_flight_no") or r.get("flight_no", "?")
                dep  = r.get("out_dep") or r.get("dep", "")
                arr  = r.get("out_arr") or r.get("arr", "")
                print(f"  {i}. TWD {r['price']:,} {icon}  "
                      f"{r.get('out_airline') or r.get('airline','')} {fn}  {dep}→{arr}  {hmin}")

    print(f"\n{'='*60}")
    print(f"  歷史記錄已存至 {HISTORY_FILE.name}（共 "
          f"{sum(len(v) for v in history.values())} 筆）")
    print(f"{'='*60}\n")


def print_history_only(targets: list, history: dict):
    print(f"\n{'='*60}  價格歷史  {'='*20}")
    for target in targets:
        tid   = target["id"]
        ttype = target.get("type", "roundtrip")
        records = history.get(tid, [])
        print(f"\n【{target['name']}】")
        if not records:
            print("  （尚無記錄）")
            continue
        for r in records:
            norm  = normalize_snapshot(r, ttype)
            ago   = days_ago(norm["checked_at"])
            ts    = datetime.fromisoformat(norm["checked_at"]).strftime("%m/%d %H:%M")
            fn    = norm.get("out_flight_no") or "?"
            icon  = RATING_LABEL.get(norm.get("rating") or "", "")
            print(f"  {ts} ({ago:>5})  TWD {norm['price']:,}  {icon}  {fn}")
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
        try:
            results = query_target(target)
            if results:
                history = record_snapshot(history, target["id"], results)
                if isinstance(results, dict):  # open_jaw
                    print(f"  ✓ 開口票合計 TWD {results['combined_price']:,}")
                else:
                    print(f"  ✓ 找到 {len(results)} 筆，最低 TWD {best_result(results)['price_rt']:,}")
            else:
                print(f"  ✗ {target['name']} 查無結果")
        except Exception as e:
            print(f"  ❌ {target['name']} 查詢異常：{e}")

    save_history(history)
    print_report(targets, history)


if __name__ == "__main__":
    main()
