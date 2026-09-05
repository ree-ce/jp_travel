#!/usr/bin/env python3
"""Turn OSM coastlines into a fillable sea polygon.

OSM ships the coast as open ``natural=coastline`` ways, so a renderer that
just strokes them leaves the Seto Inland Sea the same colour as the land.
This script clips each coastline to the city bbox and closes it along the
bbox edge, picking whichever of the two possible closures does *not* contain
the city centre -- that one is the water.

Idempotent: it strips any previously derived ``sea`` features first, so it can
be re-run after every fetch.

Usage:
    python3 tools/derive_sea.py takamatsu
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def clip_to_bbox(coords, bbox):
    """Split a polyline into the runs that lie inside the bbox.

    Segments crossing an edge are cut at the intersection so every returned
    run starts and ends either inside the box or exactly on its boundary.
    """
    south, west, north, east = bbox

    def inside(p):
        return west <= p[0] <= east and south <= p[1] <= north

    def lerp(a, b, t):
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]

    def cut(p_in, p_out):
        """The boundary point on the segment from an inside to an outside point."""
        lo, hi = 0.0, 1.0  # lo stays inside, hi stays outside
        for _ in range(50):  # bisection is plenty at these scales
            mid = (lo + hi) / 2
            if inside(lerp(p_in, p_out, mid)):
                lo = mid
            else:
                hi = mid
        return lerp(p_in, p_out, lo)

    # A single long segment can span the whole bbox with both ends outside;
    # densifying first guarantees such a crossing has interior samples.
    step = min(east - west, north - south) / 20.0
    dense = [coords[0]]
    for i in range(1, len(coords)):
        a, b = coords[i - 1], coords[i]
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / step)
        for k in range(1, n):
            dense.append(lerp(a, b, k / n))
        dense.append(b)

    runs, cur = [], []
    for i, p in enumerate(dense):
        if inside(p):
            if not cur and i > 0:
                cur.append(cut(p, dense[i - 1]))  # entering: add the crossing
            cur.append(p)
        elif cur:
            cur.append(cut(dense[i - 1], p))  # leaving
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def perimeter_param(p, bbox, eps=1e-7):
    """Position of a boundary point along the bbox perimeter, in [0, 4)."""
    south, west, north, east = bbox
    w, h = east - west, north - south
    if abs(p[1] - south) < eps * max(1.0, h):
        return 0.0 + (p[0] - west) / w
    if abs(p[0] - east) < eps * max(1.0, w):
        return 1.0 + (p[1] - south) / h
    if abs(p[1] - north) < eps * max(1.0, h):
        return 2.0 + (east - p[0]) / w
    if abs(p[0] - west) < eps * max(1.0, w):
        return 3.0 + (north - p[1]) / h
    return None


def perimeter_point(t, bbox):
    south, west, north, east = bbox
    t %= 4.0
    if t < 1:
        return [west + (east - west) * t, south]
    if t < 2:
        return [east, south + (north - south) * (t - 1)]
    if t < 3:
        return [east - (east - west) * (t - 2), north]
    return [west, north - (north - south) * (t - 3)]


def walk_boundary(t_from, t_to, bbox, forward):
    """The bbox corners passed when travelling t_from -> t_to along the edge.

    Perimeter params 0, 1, 2, 3 are exactly the four corners, so the corners in
    between are just the integers inside the travelled span.
    """
    span = (t_to - t_from) % 4.0 if forward else (t_from - t_to) % 4.0
    pts = []
    for k in range(1, 5):  # at most four corners on one lap
        offset = math.ceil(t_from + 1e-9) + (k - 1) if forward else \
            math.floor(t_from - 1e-9) - (k - 1)
        travelled = (offset - t_from) if forward else (t_from - offset)
        if travelled <= 0 or travelled >= span:
            break
        pts.append(perimeter_point(float(offset), bbox))
    return pts


def contains(ring, pt):
    inside = False
    n = len(ring)
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[(i - 1) % n]
        if (yi > pt[1]) != (yj > pt[1]):
            if pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi:
                inside = not inside
    return inside


def close_run(run, bbox, center):
    """Close a clipped coastline run into a polygon covering the water side."""
    t_end = perimeter_param(run[-1], bbox)
    t_start = perimeter_param(run[0], bbox)
    if t_end is None or t_start is None:
        return None  # run does not touch the boundary; likely an island
    candidates = []
    for forward in (True, False):
        ring = list(run) + walk_boundary(t_end, t_start, bbox, forward) + [run[0]]
        candidates.append(ring)
    for ring in candidates:
        if not contains(ring, center):
            return ring
    return None


def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "takamatsu"
    path = DATA_DIR / f"{city}_basemap.json"
    if not path.exists():
        print(f"missing {path}; run fetch_osm.py first", file=sys.stderr)
        return 2
    doc = json.loads(path.read_text(encoding="utf-8"))
    bbox = doc["meta"]["bbox"]  # south, west, north, east
    center = doc["meta"]["center"]  # [lon, lat]

    feats = [f for f in doc["features"] if f["properties"].get("layer") != "sea"]
    coastlines = [f for f in feats if f["properties"].get("layer") == "coastline"]

    made = 0
    for f in coastlines:
        geom = f["geometry"]
        lines = ([geom["coordinates"]] if geom["type"] == "LineString"
                 else geom["coordinates"] if geom["type"] == "MultiLineString" else [])
        for line in lines:
            for run in clip_to_bbox(line, bbox):
                ring = close_run(run, bbox, center)
                if ring and len(ring) >= 4:
                    feats.append({
                        "type": "Feature",
                        "properties": {"layer": "sea", "osm": f["properties"].get("osm")},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    })
                    made += 1

    doc["features"] = feats
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"derived {made} sea polygon(s) from {len(coastlines)} coastline way(s)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
