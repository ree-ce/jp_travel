#!/usr/bin/env python3
"""Fetch OpenStreetMap geometry for a city and write the map app's data files.

Produces two GeoJSON-ish JSON files per city under ``data/``:

* ``<city>_basemap.json`` -- the drawable background (coastline, water, rail,
  roads, parks, station buildings). Rendered as plain vector, never as tiles,
  so the app stays offline-capable and free of commercial clutter.
* ``<city>_areas.osm.json`` -- raw candidates for the translucent overlays
  (shopping arcades as lines, malls/department stores as polygons). This is a
  *seed*; the curated file that the app actually ships is
  ``<city>_areas.json``, which is hand-checked on top of this.

Usage:
    python3 tools/fetch_osm.py takamatsu

OSM data (c) OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Mirrors are tried in order. overpass-api.de tends to reset the connection
# outright from sandboxed networks, and kumi rate-limits into 90s timeouts
# after a few queries, so the smaller community mirror leads.
ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
# Raw Overpass responses, one per layer. The public mirrors are slow and
# flaky enough that a whole-city fetch rarely survives in one go, so each
# layer is cached and a re-run resumes instead of starting over.
CACHE_DIR = DATA_DIR / ".cache"

CITIES = {
    # bbox = (south, west, north, east)
    "takamatsu": {
        "name_ja": "高松",
        "bbox": (34.3255, 134.0330, 34.3600, 134.0700),
        "center": [134.0497, 34.3430],
    },
    "marugame": {
        "name_ja": "丸亀",
        "bbox": (34.2740, 133.7700, 34.3050, 133.8080),
        "center": [133.7885, 34.2890],
    },
}

# Each entry: (layer name, overpass selector list). Selectors are kept
# tag-indexed -- `name~"..."` regex scans time out on the public instances.
BASEMAP_LAYERS: list[tuple[str, list[str]]] = [
    ("coastline", ['way["natural"="coastline"]']),
    ("water", ['way["natural"="water"]']),
    ("moat", ['way["waterway"="riverbank"]']),
    ("stream", ['way["waterway"~"^(river|stream|canal)$"]']),
    ("rail", ['way["railway"~"^(rail|light_rail|tram)$"]']),
    ("green", ['way["leisure"="park"]']),
    ("garden", ['way["leisure"="garden"]']),
    ("road_major", ['way["highway"~"^(motorway|trunk|primary)$"]']),
    ("road_mid", ['way["highway"~"^(secondary|tertiary)$"]']),
    (
        "road_minor",
        [
            'way["highway"~"^(residential|unclassified|living_street)$"]',
        ],
    ),
    ("footway", ['way["highway"~"^(pedestrian|footway)$"]']),
    ("building", ['way["building"]["name"]']),
    ("station", ['node["railway"="station"]', 'node["public_transport"="station"]']),
]

AREA_LAYERS: list[tuple[str, list[str]]] = [
    # Shopping arcades: OSM models these as covered pedestrian *ways*, not
    # polygons. The app widens them into ribbons at draw time.
    ("arcade", ['way["highway"="pedestrian"]["covered"~"^(arcade|yes)$"]']),
    ("arcade_open", ['way["highway"="pedestrian"]["name"]']),
    # Kept as several narrow queries: combining them into one selector list
    # makes the public mirrors return 504 on this bbox.
    ("mall", ['way["shop"="mall"]']),
    ("mall_dept", ['way["shop"="department_store"]']),
    ("mall_retail", ['way["building"="retail"]["name"]']),
    ("mall_super", ['way["shop"="supermarket"]']),
]


def overpass(query: str, timeout: int = 90) -> dict:
    """POST an Overpass QL query, walking the mirror list and retrying."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last: Exception | None = None
    for attempt in range(2):
        for url in ENDPOINTS:
            host = url.split("/")[2]
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    url, data=body, headers={"User-Agent": "jp-travel-map/1.0"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode())
                print(f"    via {host} in {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
                return payload
            except Exception as exc:  # noqa: BLE001 - mirrors fail in many ways
                last = exc
                print(f"    ! {host} after {time.time() - t0:.0f}s: {exc}",
                      file=sys.stderr, flush=True)
        if attempt == 0:
            print("    retrying in 5s ...", file=sys.stderr, flush=True)
            time.sleep(5)
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def build_query(selectors: list[str], bbox: tuple[float, ...], geom: bool) -> str:
    box = ",".join(f"{v:.5f}" for v in bbox)
    parts = "".join(f"{s}({box});" for s in selectors)
    tail = "out geom;" if geom else "out tags center;"
    return f"[out:json][timeout:85];({parts});{tail}"


def to_features(payload: dict, layer: str) -> list[dict]:
    """Convert an Overpass `out geom` payload into GeoJSON features.

    Ways whose first and last node coincide become Polygons, everything else a
    LineString. Relations are flattened to their member ways -- good enough for
    the water bodies and mall outlines we care about.
    """
    feats: list[dict] = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        base = {
            "layer": layer,
            "osm": f"{el['type']}/{el['id']}",
            "name": tags.get("name"),
            "name_en": tags.get("name:en"),
        }
        base.update(
            {k: tags[k] for k in ("shop", "building", "covered", "highway") if k in tags}
        )
        base = {k: v for k, v in base.items() if v is not None}

        if el["type"] == "node":
            geom = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif "geometry" in el:
            coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
            if len(coords) < 2:
                continue
            closed = coords[0] == coords[-1] and len(coords) >= 4
            geom = (
                {"type": "Polygon", "coordinates": [coords]}
                if closed
                else {"type": "LineString", "coordinates": coords}
            )
        elif el["type"] == "relation" and "members" in el:
            rings = [
                [[p["lon"], p["lat"]] for p in m["geometry"]]
                for m in el["members"]
                if m.get("geometry")
            ]
            rings = [r for r in rings if len(r) >= 2]
            if not rings:
                continue
            geom = {"type": "MultiLineString", "coordinates": rings}
        else:
            continue
        feats.append({"type": "Feature", "properties": base, "geometry": geom})
    return feats


def fetch_group(city: str, layers, bbox, geom=True) -> list[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for layer, selectors in layers:
        cache = CACHE_DIR / f"{city}_{layer}.json"
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            feats = to_features(payload, layer)
            print(f"  · {layer}: {len(feats)} features (cached)", file=sys.stderr, flush=True)
            out.extend(feats)
            continue
        print(f"  · {layer} ...", file=sys.stderr, flush=True)
        try:
            payload = overpass(build_query(selectors, bbox, geom))
        except RuntimeError as exc:
            # One dead layer should not cost us the eleven that worked; the
            # next run picks it up from cache-miss and leaves the rest alone.
            print(f"    SKIPPED {layer}: {exc}", file=sys.stderr, flush=True)
            continue
        cache.write_text(json.dumps(payload), encoding="utf-8")
        feats = to_features(payload, layer)
        print(f"    {len(feats)} features", file=sys.stderr, flush=True)
        out.extend(feats)
        time.sleep(1.0)  # be polite to the public mirror
    return out


def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "takamatsu"
    if city not in CITIES:
        print(f"unknown city {city!r}; known: {', '.join(CITIES)}", file=sys.stderr)
        return 2
    cfg = CITIES[city]
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Areas first: the arcades are the point of the app, the basemap is context.
    print(f"area candidates for {city} {cfg['bbox']}", file=sys.stderr)
    areas = {
        "type": "FeatureCollection",
        "meta": {"city": city, "note": "seed for hand-curated <city>_areas.json"},
        "features": fetch_group(city, AREA_LAYERS, cfg["bbox"]),
    }
    path = DATA_DIR / f"{city}_areas.osm.json"
    path.write_text(json.dumps(areas, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)

    print("basemap", file=sys.stderr)
    basemap = {
        "type": "FeatureCollection",
        "meta": {
            "city": city,
            "bbox": list(cfg["bbox"]),
            "center": cfg["center"],
            "attribution": "© OpenStreetMap contributors (ODbL)",
        },
        "features": fetch_group(city, BASEMAP_LAYERS, cfg["bbox"]),
    }
    path = DATA_DIR / f"{city}_basemap.json"
    path.write_text(json.dumps(basemap, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
