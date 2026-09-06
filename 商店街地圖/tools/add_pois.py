#!/usr/bin/env python3
"""Merge points into a city file, working out which area each one sits in.

The hierarchy is the reason this app exists, so a point should not have to be
told by hand that it is inside 丸亀町グリーン, which is inside 丸亀町商店街,
which is part of 高松中央商店街. Given a coordinate, this assigns the
innermost containing area:

1. the smallest mall polygon that contains the point, else
2. the nearest arcade whose ribbon (centreline ± width/2, plus a small margin
   for shopfronts set back from the centre) covers the point, else
3. nothing -- a free-standing point.

Input is a JSON list of point objects. Each needs a name and either
``coord: [lon, lat]`` or ``osm: "way/123"`` naming an element already present
in the fetched data. Everything else (``cat``, ``floor``, ``note``, ``url``,
``hours``) is optional and copied through.

Usage:
    python3 tools/add_pois.py takamatsu data/takamatsu_pois.seed.json
    python3 tools/add_pois.py takamatsu -          # read stdin
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# How far outside an arcade centreline still counts as "on" it. Shopfronts sit
# at the edge of the corridor, and OSM centrelines are approximate.
ARCADE_MARGIN_M = 8.0


def rings_of(geom):
    if not geom:
        return []
    t = geom["type"]
    if t == "Polygon":
        return list(geom["coordinates"])
    if t == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    if t == "LineString":
        return [geom["coordinates"]]
    if t == "MultiLineString":
        return list(geom["coordinates"])
    return []


def local_xy(pt, origin):
    """Metres east/north of an origin -- fine over a few km."""
    kx = 111320 * math.cos(math.radians(origin[1]))
    return ((pt[0] - origin[0]) * kx, (pt[1] - origin[1]) * 110540)


def point_in_ring(pt, ring):
    inside = False
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[i - 1]
        if (yi > pt[1]) != (yj > pt[1]):
            if pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi:
                inside = not inside
    return inside


def ring_area(ring):
    return abs(sum(ring[i][0] * ring[i - 1][1] - ring[i - 1][0] * ring[i][1]
                   for i in range(len(ring)))) / 2


def dist_to_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    t = 0.0 if not d2 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dist_to_lines_m(pt, geom):
    best = float("inf")
    for ring in rings_of(geom):
        for i in range(1, len(ring)):
            best = min(best, dist_to_segment(
                local_xy(pt, pt), local_xy(ring[i - 1], pt), local_xy(ring[i], pt)))
    return best


def bbox_of_rings(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def spread_coincident_pois(doc):
    """Nudge apart points that share one exact coordinate under one parent.

    A mall with no known OSM footprint (Youme Town, 瓦町FLAG) gets a single
    placeholder coordinate, and every tenant added under it inherits that same
    point verbatim -- fine for the hierarchy (parent/floor), but on the map
    their pins land exactly on top of each other. Only the first one in
    drawing order is visible or tappable; tapping that spot selects one
    specific tenant, never the mall itself. This spreads such a group into a
    small grid, sized to stay inside the parent's own polygon when it has one.
    """
    areas_by_id = {a["id"]: a for a in doc["areas"]}
    groups: dict[tuple, list[int]] = {}
    for i, p in enumerate(doc["pois"]):
        key = (p.get("parent"), tuple(p["coord"]))
        groups.setdefault(key, []).append(i)

    moved = 0
    for (parent, coord), idxs in groups.items():
        if len(idxs) < 2 or parent is None:
            continue
        area = areas_by_id.get(parent)
        # Fit the grid inside the parent's own footprint when we have one, so
        # spread-out pins never drift outside the shape they belong to.
        half_w_m, half_h_m = 28.0, 20.0
        if area and area.get("geometry"):
            x0, y0, x1, y1 = bbox_of_rings(rings_of(area["geometry"]))
            kx = 111320 * math.cos(math.radians(coord[1]))
            half_w_m = min(half_w_m, (x1 - x0) * kx / 2 * 0.7)
            half_h_m = min(half_h_m, (y1 - y0) * 110540 / 2 * 0.7)

        n = len(idxs)
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        kx = 111320 * math.cos(math.radians(coord[1]))
        for k, i in enumerate(idxs):
            col, row = k % cols, k // cols
            # Centre the grid on the original point rather than growing from a corner.
            fx = (col - (cols - 1) / 2) / max(cols - 1, 1) if cols > 1 else 0
            fy = (row - (rows - 1) / 2) / max(rows - 1, 1) if rows > 1 else 0
            dx_m, dy_m = fx * half_w_m, fy * half_h_m
            doc["pois"][i]["coord"] = [
                round(coord[0] + dx_m / kx, 6),
                round(coord[1] + dy_m / 110540, 6),
            ]
        moved += n
    if moved:
        print(f"  spread {moved} coincident point(s) apart under their shared parent(s)",
              file=sys.stderr)


def assign_parent(pt, areas):
    """The innermost area containing the point, or None."""
    containing = []
    for a in areas:
        if a.get("kind") != "mall" or not a.get("geometry"):
            continue
        rings = rings_of(a["geometry"])
        if any(point_in_ring(pt, r) for r in rings):
            containing.append((min(ring_area(r) for r in rings), a["id"]))
    if containing:
        return min(containing)[1]  # smallest polygon wins = innermost

    best, best_d = None, float("inf")
    for a in areas:
        if a.get("kind") != "arcade" or not a.get("geometry"):
            continue
        limit = a.get("width_m", 14) / 2 + ARCADE_MARGIN_M
        d = dist_to_lines_m(pt, a["geometry"])
        if d <= limit and d < best_d:
            best, best_d = a["id"], d
    return best


def centroid_of(geom):
    pts = []

    def walk(node):
        if isinstance(node, list):
            if node and isinstance(node[0], (int, float)):
                pts.append(node)
            else:
                for n in node:
                    walk(n)

    walk(geom["coordinates"])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [round((min(xs) + max(xs)) / 2, 6), round((min(ys) + max(ys)) / 2, 6)]


def osm_index(city: str) -> dict[str, list[float]]:
    """Centroid of every fetched OSM element, keyed by "way/123"."""
    index: dict[str, list[float]] = {}
    for name in (f"{city}_basemap.json", f"{city}_areas.osm.json"):
        path = DATA_DIR / name
        if not path.exists():
            continue
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            osm = f["properties"].get("osm")
            if osm and osm not in index:
                index[osm] = centroid_of(f["geometry"])
    return index


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    city, src = sys.argv[1], sys.argv[2]

    city_path = DATA_DIR / f"{city}.json"
    if not city_path.exists():
        print(f"missing {city_path}; run make_areas.py first", file=sys.stderr)
        return 2
    doc = json.loads(city_path.read_text(encoding="utf-8"))

    raw = sys.stdin.read() if src == "-" else pathlib.Path(src).read_text(encoding="utf-8")
    incoming = json.loads(raw)
    if isinstance(incoming, dict):
        incoming = incoming.get("pois", [])

    index = osm_index(city)
    by_id = {p["id"]: i for i, p in enumerate(doc.get("pois", []))}
    doc.setdefault("pois", [])
    added = updated = skipped = 0

    for i, item in enumerate(incoming):
        coord = item.get("coord")
        if not coord and item.get("osm"):
            coord = index.get(item["osm"])
            if not coord:
                print(f"  SKIP {item.get('name_ja') or item.get('name_zh')}: "
                      f"{item['osm']} not in fetched data", file=sys.stderr)
                skipped += 1
                continue
        if not coord:
            print(f"  SKIP {item.get('name_zh')}: no coord and no osm id", file=sys.stderr)
            skipped += 1
            continue

        rec = {k: v for k, v in item.items() if k != "osm"}
        rec["coord"] = [round(coord[0], 6), round(coord[1], 6)]
        rec.setdefault("id", f"P{i + 1:03d}")
        rec.setdefault("cat", "other")
        if "parent" not in rec:
            rec["parent"] = assign_parent(rec["coord"], doc["areas"])
        if item.get("osm"):
            rec["source"] = item["osm"]

        if rec["id"] in by_id:
            doc["pois"][by_id[rec["id"]]] = rec
            updated += 1
        else:
            by_id[rec["id"]] = len(doc["pois"])
            doc["pois"].append(rec)
            added += 1

        names = {a["id"]: a.get("name_zh") or a.get("name_ja") for a in doc["areas"]}
        where = names.get(rec["parent"], "（獨立）")
        print(f"  {rec['id']} {rec.get('name_zh') or rec.get('name_ja'):<22} → {where}",
              file=sys.stderr)

    spread_coincident_pois(doc)

    city_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {city_path}: +{added} added, {updated} updated, {skipped} skipped, "
          f"{len(doc['pois'])} total", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
