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
                "note": "號稱「四國第一長」的拱廊商店街，總長約 2.7 km，逾千家店舖，"
                        "由官方 8 條街道組成：兵庫町・片原町・丸龜町・獅子通・南新町・常磐町・田町・御坊町。"
                        "全程有頂棚，下雨天也能逛。",
            },
            {
                "id": "ARC-HYOGOMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "兵庫町商店街", "name_zh": "兵庫町商店街",
                "match": ["兵庫町商店街"], "width_m": 13,
                "note": "最靠近 JR 高松站的一段，往東接丸亀町。\n"
                        "代表性地標：入口有巨大的紅色圓柱拱門。連鎖藥妝店多，也有許多餐廳、居酒屋。",
            },
            {
                "id": "ARC-KATAHARAMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "片原町商店街", "name_zh": "片原町商店街",
                "match": ["片原町商店街", "片原町商店街 (Kataharamachi)"], "width_m": 13,
                "note": "東西向的一段，連到琴電片原町站。\n"
                        "與兵庫町相連，風格較生活化，有許多在地小攤與傳統商店。",
            },
            {
                "id": "ARC-MARUGAMEMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "高松丸亀町商店街", "name_zh": "丸龜町商店街",
                "match": ["高松丸亀町商店街", "丸亀町商店街"], "width_m": 15,
                "note": "整條商店街的核心，2006 年起分區重建，最北端就是丸亀町壱番街與大鐘樓廣場。\n"
                        "精品戰區！地標是「米蘭風格玻璃圓頂」。街道最寬敞，進駐 LV、COACH 等國際精品與時髦咖啡廳。",
            },
            {
                "id": "ARC-MINAMISHINMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "南新町商店街", "name_zh": "南新町商店街",
                "match": ["南新町商店街"], "width_m": 13,
                "note": "有大創、二手書店、烏龍麵連鎖店，年輕人多。",
            },
            {
                "id": "ARC-TOKIWAMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "常磐町商店街", "name_zh": "常磐町商店街",
                "match": ["常磐町商店街"], "width_m": 13,
                "note": "靠近瓦町站的橫向街道。動漫、卡牌遊戲、音樂表演空間的聚集地。",
            },
            {
                "id": "ARC-TAMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "田町商店街", "name_zh": "田町商店街",
                "match": ["田町商店街"], "width_m": 13,
                "note": "最南端的一段，靠近瓦町。\n"
                        "整個商店街的最南端，氣氛最悠閒、步調最慢，有許多布料行、茶葉店、傳統超市。",
            },
            {
                "id": "ARC-LION", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "ライオン通商店街", "name_zh": "獅子通商店街",
                "match": ["ライオン通"], "width_m": 10,
                "note": "橫向的飲食店街，晚上熱鬧。\n"
                        "美食天堂，與丸龜町平行。夜晚最熱鬧，聚集大量的居酒屋、拉麵店，是高松宵夜勝地！",
                "optional": True,
            },
            {
                "id": "ARC-TOKIWA-GAI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "トキワ街", "name_zh": "常盤街",
                "match": ["トキワ街", "トキワ新町"], "width_m": 11,
                "note": "常磐町旁的分支拱廊。",
                "optional": True,
            },
            {
                "id": "ARC-GOBOMACHI", "kind": "arcade", "parent": "GRP-CENTRAL",
                "name_ja": "御坊町商店街", "name_zh": "御坊町商店街",
                "match": ["御坊町"], "width_m": 12,
                "note": "高松中央商店街官方 8 條街道之一（兵庫町・片原町・丸龜町・獅子通・"
                        "南新町・常磐町・田町・御坊町，號稱四國第一長，全長約 2.7km、逾千店舖）。\n"
                        "8 條街中長度最短，主要以佛具店和傳統工藝小店為主，氣氛安靜。",
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
                "id": "MALL-ICHIBANGAI", "parent": "ARC-MARUGAMEMACHI",
                "name_ja": "高松丸亀町壱番街", "name_zh": "丸龜町壹番街",
                "match": ["高松丸亀町壱番街"],
                "floors": ["1F", "2F", "3F", "4F", "5F"],
                "note": "丸亀町重建的第一街區，東館與西館夾著大鐘樓廣場，與高松三越相連。"
                        "東館 1F：Rolex、Gucci、Brooks Brothers；西館 1F：Tiffany & Co.；"
                        "4F 有小型會館與餐廳，5F 以上為住宅。精品購物廊道，非平價商場。",
            },
            # 高松丸亀町参番街 (Sanbangai) is deliberately not listed here: it's a
            # gym (JOYFIT24, RIZAP) and a Red Cross blood-donation room, not a
            # shopping venue, so it has no place on a shopping-street map.
            {
                "id": "MALL-MITSUKOSHI", "parent": "ARC-MARUGAMEMACHI",
                "name_ja": "高松三越", "name_zh": "高松三越",
                "match": ["高松三越"],
                "note": "位於丸亀町商店街北段。",
            },
            {
                "id": "MALL-MARITIME", "name_ja": "マリタイムプラザ高松",
                "name_zh": "海洋廣場高松",
                "match": ["マリタイムプラザ高松"],
                "note": "サンポート高松，JR 高松站北側的港灣複合設施。",
            },
        ],
        # Malls with no matching OSM building outline (outside the fetched
        # bbox, or just untagged). `center` is a verified real-world
        # coordinate (address lookup), not derived from geometry, so we draw
        # a synthetic placeholder box around it rather than leaving the mall
        # as a bare point -- that's what lets tenant stores nest under it with
        # floors, same as every OSM-derived mall.
        "manual_malls": [
            {
                "id": "MALL-YUME-TAKAMATSU", "name_ja": "ゆめタウン高松",
                "name_zh": "Youme Town 高松",
                "center": [134.04171, 34.31671],
                "floors": ["1F", "2F", "3F"],
                "note": "香川県高松市三条町608-1。OSM 無建物輪廓，範圍為依地址座標估算的示意方框（約 120×80m），非實際外觀。",
                "box_m": [60, 40],
            },
            {
                "id": "MALL-YUME-MARUGAME", "name_ja": "ゆめタウン丸亀",
                "name_zh": "Youme Town 丸龜",
                "center": [133.785403, 34.273531],
                "floors": ["1F", "2F"],
                "note": "香川県丸亀市新田町150。OSM 無建物輪廓，範圍為依地址座標估算的示意方框（約 120×80m），非實際外觀。",
                "box_m": [60, 40],
            },
            {
                "id": "MALL-FLAG", "name_ja": "瓦町FLAG",
                "name_zh": "瓦町 FLAG",
                "center": [134.0525472, 34.3389917],
                "floors": ["1F", "2F", "3F", "4F", "5F"],
                "note": "香川県高松市常磐町1-3-1，直接連通琴電瓦町駅（コトデン瓦町ビル）。"
                        "單棟建物，地上約 8-10 層＋地下 3 層，商業樓地板約 29,700㎡，2015 年開幕。"
                        "1F Starbucks、1-2F Beams、3F 丸善書店／駿河屋、4F 大創 DAISO、5F 阿卡將本舖。"
                        "OSM 無此建物輪廓（附近的「瓦町ビル」way 是另一棟建物），範圍為依地址座標估算的示意方框（約 100×80m），非實際外觀。",
                "box_m": [50, 40],
            },
        ],
    },
}


def synthetic_box(center, half_w_m, half_h_m):
    """A small rectangular polygon around a point, in lon/lat degrees.

    Used only where no real footprint exists yet -- good enough to host
    tenant points and draw a visible extent, not a survey of the building.
    """
    lon, lat = center
    kx = 111320 * math.cos(math.radians(lat))
    dlon, dlat = half_w_m / kx, half_h_m / 110540
    ring = [
        [lon - dlon, lat - dlat], [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat], [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


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
    """Centre of the largest ring, not of the whole bounding box.

    丸亀町グリーン is two separate buildings with the arcade running between
    them; the bbox centre falls in that gap, which would put the mall's label
    on the street and outside its own polygon.
    """
    def bbox_area(r):
        xs = [p[0] for p in r]
        ys = [p[1] for p in r]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    r = max(rings, key=bbox_area)
    xs = [p[0] for p in r]
    ys = [p[1] for p in r]
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

    # Fallback source for an arcade whose street simply isn't tagged
    # highway=pedestrian in OSM (so it never became an area candidate) --
    # e.g. 御坊町通り is mapped as an ordinary unclassified road. Matching
    # against the basemap's road layers picks up its real geometry instead of
    # leaving the street with no shape at all.
    basemap_path = DATA_DIR / f"{city}_basemap.json"
    road_feats = []
    if basemap_path.exists():
        basemap = json.loads(basemap_path.read_text(encoding="utf-8"))
        road_feats = [f for f in basemap["features"]
                      if f["properties"].get("layer") in
                      ("road_minor", "road_mid", "road_major", "footway")]

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
        # Lines only. OSM also maps parts of an arcade as pedestrian *areas*;
        # stroking such a ring would draw a loop around the plaza instead of a
        # ribbon along the street, and the centreline already covers it.
        picked = [f for f in feats
                  if f["properties"].get("name")
                  and matches(f["properties"]["name"], spec["match"])
                  and f["geometry"]["type"] in ("LineString", "MultiLineString")]
        fallback = False
        if not picked and road_feats:
            picked = [f for f in road_feats
                      if f["properties"].get("name")
                      and matches(f["properties"]["name"], spec["match"])]
            fallback = bool(picked)
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
        if fallback:
            area["note"] = (area.get("note", "") +
                             ("　" if area.get("note") else "") +
                             "（OSM 未標記為行人徒步區，此為一般道路幾何，非拱廊實測輪廓。）")
            print(f"  note: {spec['id']} used ordinary-road fallback geometry", file=sys.stderr)
        areas.append(area)

    for spec in cfg.get("malls", []):
        picked = [f for f in feats
                  if f["properties"].get("name")
                  and matches(f["properties"]["name"], spec["match"])
                  and f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
        if not picked:
            print(f"  WARN: no OSM polygon for {spec['id']} {spec['match']}", file=sys.stderr)
            continue
        # Keep every match, not just the biggest: a mall is often several
        # buildings under one name (丸亀町グリーン is an 東館 plus a 西館).
        polys = [lines_of(f) for f in picked]
        mall = {k: v for k, v in spec.items() if k != "match"}
        mall["kind"] = "mall"
        mall.setdefault("parent", None)
        mall["geometry"] = ({"type": "Polygon", "coordinates": polys[0]}
                            if len(polys) == 1
                            else {"type": "MultiPolygon", "coordinates": polys})
        mall["label_at"] = polygon_center([r for p in polys for r in p])
        mall["source"] = sorted(f["properties"]["osm"] for f in picked)
        areas.append(mall)

    for spec in cfg.get("manual_malls", []):
        w, h = spec.get("box_m", (60, 40))
        mall = {k: v for k, v in spec.items() if k not in ("center", "box_m")}
        mall["kind"] = "mall"
        mall.setdefault("parent", None)
        mall["geometry"] = synthetic_box(spec["center"], w, h)
        mall["label_at"] = spec["center"]
        mall["source"] = "manual (verified address lookup, no OSM footprint)"
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
