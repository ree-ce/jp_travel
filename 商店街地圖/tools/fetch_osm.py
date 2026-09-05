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

# The public mirrors rate-limit by *request*, not by result size: after the
# first query or two they start returning 90s read timeouts regardless of how
# trivial the query is. So we make as few round trips as possible -- a couple
# of unioned queries -- and sort the results into layers locally.
ROAD_KINDS = "motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|pedestrian|footway"

QUERIES: list[tuple[str, list[str]]] = [
    (
        "roads",
        [f'way["highway"~"^({ROAD_KINDS})$"]'],
    ),
    (
        "features",
        [
            'way["natural"="coastline"]',
            'way["natural"="water"]',
            'way["waterway"~"^(river|stream|canal|riverbank)$"]',
            'way["railway"~"^(rail|light_rail|tram)$"]',
            'way["leisure"~"^(park|garden)$"]',
            'way["building"]["name"]',
            'way["shop"~"^(mall|department_store|supermarket)$"]',
            'node["railway"="station"]',
        ],
    ),
]

# Layers already fetched by the older per-layer queries; still read from cache
# so an existing checkout does not have to re-download them.
LEGACY_CACHE = ["arcade", "arcade_open", "mall"]


def classify(tags: dict) -> str | None:
    """Sort one OSM element into the layer the renderer draws it on."""
    hw = tags.get("highway")
    if hw in ("motorway", "trunk", "primary"):
        return "road_major"
    if hw in ("secondary", "tertiary"):
        return "road_mid"
    if hw in ("residential", "unclassified", "living_street"):
        return "road_minor"
    if hw in ("pedestrian", "footway"):
        return "footway"
    if tags.get("natural") == "coastline":
        return "coastline"
    if tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
        return "water"
    if tags.get("waterway") in ("river", "stream", "canal"):
        return "stream"
    if tags.get("railway") in ("rail", "light_rail", "tram"):
        return "rail"
    if tags.get("leisure") in ("park", "garden"):
        return "green"
    if tags.get("railway") == "station":
        return "station"
    if tags.get("building"):
        return "building"
    return None


def is_area_candidate(tags: dict) -> bool:
    """Whether an element is a shopping arcade or a mall outline.

    Arcades are covered `highway=pedestrian` *lines*; malls are polygons. Any
    named pedestrian way is kept too, since some arcades lack `covered`.
    """
    if tags.get("highway") == "pedestrian" and (tags.get("covered") or tags.get("name")):
        return True
    return tags.get("shop") in ("mall", "department_store", "supermarket") or (
        tags.get("building") == "retail" and tags.get("name")
    )


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


def to_features(payload: dict, layer: str | None = None) -> list[dict]:
    """Convert an Overpass `out geom` payload into GeoJSON features.

    Ways whose first and last node coincide become Polygons, everything else a
    LineString. Relations are flattened to their member ways -- good enough for
    the water bodies and mall outlines we care about.
    """
    feats: list[dict] = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        assigned = layer or classify(tags)
        if assigned is None:
            continue
        base = {
            "layer": assigned,
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


def raw_elements(city: str, bbox) -> list[dict]:
    """Every OSM element we need, from cache where possible."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    elements: list[dict] = []

    for name, selectors in QUERIES:
        cache = CACHE_DIR / f"{city}_{name}.json"
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            print(f"  · {name}: {len(payload.get('elements', []))} elements (cached)",
                  file=sys.stderr, flush=True)
        else:
            print(f"  · {name} ...", file=sys.stderr, flush=True)
            payload = overpass(build_query(selectors, bbox, True))
            cache.write_text(json.dumps(payload), encoding="utf-8")
            print(f"    {len(payload.get('elements', []))} elements",
                  file=sys.stderr, flush=True)
            time.sleep(1.0)  # be polite to the public mirror
        elements.extend(payload.get("elements", []))

    for name in LEGACY_CACHE:
        cache = CACHE_DIR / f"{city}_{name}.json"
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            print(f"  · {name}: {len(payload.get('elements', []))} elements (legacy cache)",
                  file=sys.stderr, flush=True)
            elements.extend(payload.get("elements", []))

    seen, unique = set(), []
    for el in elements:
        key = (el["type"], el["id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(el)
    print(f"  {len(unique)} unique elements", file=sys.stderr, flush=True)
    return unique


def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "takamatsu"
    if city not in CITIES:
        print(f"unknown city {city!r}; known: {', '.join(CITIES)}", file=sys.stderr)
        return 2
    cfg = CITIES[city]
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"fetching {city} {cfg['bbox']}", file=sys.stderr)
    elements = raw_elements(city, cfg["bbox"])

    basemap = {
        "type": "FeatureCollection",
        "meta": {
            "city": city,
            "bbox": list(cfg["bbox"]),
            "center": cfg["center"],
            "attribution": "© OpenStreetMap contributors (ODbL)",
        },
        "features": to_features({"elements": elements}),
    }
    path = DATA_DIR / f"{city}_basemap.json"
    path.write_text(json.dumps(basemap, ensure_ascii=False), encoding="utf-8")
    counts: dict[str, int] = {}
    for f in basemap["features"]:
        counts[f["properties"]["layer"]] = counts.get(f["properties"]["layer"], 0) + 1
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)
    for k in sorted(counts, key=lambda k: -counts[k]):
        print(f"    {k:<12} {counts[k]}", file=sys.stderr)

    area_els = [el for el in elements if is_area_candidate(el.get("tags", {}))]
    areas = {
        "type": "FeatureCollection",
        "meta": {"city": city, "note": "seed for hand-curated <city>.json"},
        "features": to_features({"elements": area_els}, layer="candidate"),
    }
    path = DATA_DIR / f"{city}_areas.osm.json"
    path.write_text(json.dumps(areas, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB, "
          f"{len(areas['features'])} candidates)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
