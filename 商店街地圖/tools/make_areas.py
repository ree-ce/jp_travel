#!/usr/bin/env python3
"""Fold the raw OSM seed into the curated, hierarchical area file.

OSM splits one arcade into a dozen ``highway=pedestrian`` ways and gives them
no notion of belonging to 高松中央商店街. This script applies the hand-written
hierarchy below, gathers every OSM way whose name matches, and emits
``data/<city>.json`` -- the file the app actually ships.

Existing points in that file are preserved, so re-running after an OSM refresh
never clobbers curated content.

Usage:
    python3 tools/make_areas.py takamatsu
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# --------------------------------------------------------------------------
# Curation. `match` values are matched against the OSM `name` tag; a plain
# string means "name contains this". `width_m` is the real arcade width and
# drives how thick the translucent ribbon is drawn at any zoom.
# --------------------------------------------------------------------------
CITY_CONFIG = {
    "takamatsu": {
        "meta": {
            "city": "takamatsu",
            "name_zh": "高松",
            "name_ja": "高松",
            "center": [134.0497, 34.3430],
            "zoom": 15.4,
            "schema": 1,
        },
        "areas": [
            {
                "id": "GRP-CENTRAL",
                "kind": "group",
                "name_ja": "高松中央商店街",
                "name_zh": "高松中央商店街",
                "note": "日本最長的拱廊商店街，總長約 2.7 km，由下列數條商店街串連而成，全程有頂棚，下雨天也能逛。",
            },
            {
                "id": "ARC-HYOGOMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "兵庫町商店街", "name_zh": "兵庫町商店街",
                "match": ["兵庫町商店街"], "width_m": 13,
                "note": "最靠近 JR 高松站的一段，往東接丸亀町。",
            },
            {
                "id": "ARC-KATAHARAMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "片原町商店街", "name_zh": "片原町商店街",
                "match": ["片原町商店街", "片原町商店街 (Kataharamachi)"], "width_m": 13,
                "note": "東西向的一段，連到琴電片原町站。",
            },
            {
                "id": "ARC-MARUGAMEMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "高松丸亀町商店街", "name_zh": "丸龜町商店街",
                "match": ["高松丸亀町商店街", "丸亀町商店街"], "width_m": 15,
                "note": "整條商店街的核心，2006 年起分區重建，最北端就是丸亀町壱番街與大鐘樓廣場。",
            },
            {
                "id": "ARC-MINAMISHINMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "南新町商店街", "name_zh": "南新町商店街",
                "match": ["南新町商店街"], "width_m": 13,
            },
            {
                "id": "ARC-TOKIWAMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "常磐町商店街", "name_zh": "常磐町商店街",
                "match": ["常磐町商店街"], "width_m": 13,
            },
            {
                "id": "ARC-TAMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "田町商店街", "name_zh": "田町商店街",
                "match": ["田町商店街"], "width_m": 13,
                "note": "最南端的一段，靠近瓦町。",
            },
            {
                "id": "ARC-LION", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "ライオン通商店街", "name_zh": "獅子通商店街",
                "match": ["ライオン通"], "width_m": 10,
                "note": "橫向的飲食店街，晚上熱鬧。",
                "optional": True,
            },
        ],
        # Malls are real polygons in OSM; `parent` puts them inside an arcade
        # where that is geographically true.
        "malls": [
            {
                "id": "MALL-GREEN", "parent": "ARC-MARUGAMEMACHI",
                "name_ja": "丸亀町グリーン", "name_zh": "丸龜町 GREEN",
                "match": ["丸亀町グリーン", "丸亀町グリーン ケヤキ広場"],
                "floors": ["B1", "1F", "2F", "3F", "4F"],
                "note": "蓋在丸亀町商店街上的複合商場，中庭有櫸樹廣場。",
            },
            {
                "id": "MALL-YUME", "name_ja": "ゆめタウン高松", "name_zh": "youme town 高松",
                "match": ["ゆめタウン高松", "ゆめタウン"],
                "floors": ["1F", "2F", "3F"],
                "note": "市郊大型購物中心，需搭車前往。",
            },
            {
                "id": "MALL-FLAG", "name_ja": "瓦町FLAG", "name_zh": "瓦町 FLAG",
                "match": ["瓦町FLAG", "瓦町 FLAG", "瓦町ＦＬＡＧ"],
                "floors": ["1F", "2F", "3F", "4F", "5F", "6F", "7F", "8F"],
                "note": "琴電瓦町站上蓋商業設施。",
            },
            {
                "id": "MALL-MITSUKOSHI", "parent": "ARC-MARUGAMEMACHI",
                "name_ja": "高松三越", "name_zh": "高松三越",
                "match": ["高松三越", "三越"],
                "note": "位於丸亀町商店街北段。",
            },
            {
                "id": "MALL-TENMAYA", "name_ja": "天満屋", "name_zh": "天滿屋",
                "match": ["天満屋"],
            },
        ],
    },
}


def norm(s: str) -> str:
    return (s or "").replace("　", "").replace(" ", "")


def matches(name: str, patterns) -> bool:
    n = norm(name)
    return any(norm(p) in n for p in patterns)


def lines_of(feature):
    g = feature["geometry"]
    if g["type"] == "LineString":
        return [g["coordinates"]]
    if g["type"] in ("MultiLineString", "Polygon"):
        return list(g["coordinates"])
    if g["type"] == "MultiPolygon":
        return [r for poly in g["coordinates"] for r in poly]
    return []


def seg_len(a, b):
    # Rough metres; good enough for picking the longest run for a label.
    kx = 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 110540)


def label_point(lines):
    """Midpoint of the longest constituent line -- labels sit on the busiest run."""
    best, best_len = None, -1.0
    for line in lines:
        total = sum(seg_len(line[i - 1], line[i]) for i in range(1, len(line)))
        if total > best_len:
            best_len, best = total, line
    if not best:
        return None
    half, run = best_len / 2, 0.0
    for i in range(1, len(best)):
        d = seg_len(best[i - 1], best[i])
        if run + d >= half:
            t = (half - run) / d if d else 0
            return [best[i - 1][0] + (best[i][0] - best[i - 1][0]) * t,
                    best[i - 1][1] + (best[i][1] - best[i - 1][1]) * t]
        run += d
    return best[len(best) // 2]


def polygon_center(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]


def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "takamatsu"
    cfg = CITY_CONFIG.get(city)
    if not cfg:
        print(f"no curation config for {city!r}", file=sys.stderr)
        return 2

    seed_path = DATA_DIR / f"{city}_areas.osm.json"
    if not seed_path.exists():
        print(f"missing {seed_path}; run fetch_osm.py first", file=sys.stderr)
        return 2
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    # The `arcade` and `arcade_open` queries overlap, so the same way arrives
    # twice; keep one copy per OSM id.
    feats, seen = [], set()
    for f in seed["features"]:
        osm = f["properties"].get("osm")
        if osm and osm in seen:
            continue
        if osm:
            seen.add(osm)
        feats.append(f)

    out_path = DATA_DIR / f"{city}.json"
    existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    kept_pois = existing.get("pois", [])

    areas, sources = [], {}

    for spec in cfg["areas"]:
        area = {k: v for k, v in spec.items()
                if k not in ("match", "optional")}
        area.setdefault("parent", None)
        if spec["kind"] == "group":
            areas.append(area)
            continue
        picked = [f for f in feats
                  if f["properties"].get("name") and matches(f["properties"]["name"], spec["match"])]
        lines = [ln for f in picked for ln in lines_of(f) if len(ln) >= 2]
        if not lines:
            level = "note" if spec.get("optional") else "WARN"
            print(f"  {level}: no OSM geometry for {spec['id']} {spec['match']}", file=sys.stderr)
            if spec.get("optional"):
                continue
            areas.append(area)
            continue
        area["geometry"] = {"type": "MultiLineString", "coordinates": lines}
        area["label_at"] = label_point(lines)
        sources[spec["id"]] = sorted({f["properties"]["osm"] for f in picked})
        area["source"] = sources[spec["id"]]
        areas.append(area)

    for spec in cfg.get("malls", []):
        picked = [f for f in feats
                  if f["properties"].get("name")
                  and matches(f["properties"]["name"], spec["match"])
                  and f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
        if not picked:
            print(f"  WARN: no OSM polygon for {spec['id']} {spec['match']}", file=sys.stderr)
            continue
        # Keep the largest match; OSM sometimes has both a building and a
        # separate landuse polygon under the same name.
        def area_of(f):
            rings = lines_of(f)
            xs = [p[0] for r in rings for p in r]
            ys = [p[1] for r in rings for p in r]
            return (max(xs) - min(xs)) * (max(ys) - min(ys))
        picked.sort(key=area_of, reverse=True)
        rings = lines_of(picked[0])
        mall = {k: v for k, v in spec.items() if k != "match"}
        mall["kind"] = "mall"
        mall.setdefault("parent", None)
        mall["geometry"] = {"type": "Polygon", "coordinates": rings}
        mall["label_at"] = polygon_center(rings)
        mall["source"] = [picked[0]["properties"]["osm"]]
        areas.append(mall)

    doc = {"meta": cfg["meta"], "areas": areas, "pois": kept_pois}
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out_path} — {len(areas)} areas, {len(kept_pois)} points kept",
          file=sys.stderr)
    for a in areas:
        mark = "·" if a.get("geometry") else "!"
        print(f"  {mark} {a['id']:<22} {a.get('name_zh', ''):<14} "
              f"{'geom' if a.get('geometry') else 'NO GEOMETRY'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
