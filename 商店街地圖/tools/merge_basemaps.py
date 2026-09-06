#!/usr/bin/env python3
"""Merge per-city basemap files into one combined basemap for the app.

fetch_osm.py/derive_sea.py write one basemap per city (takamatsu_basemap.json,
marugame_basemap.json, ...), but the app embeds a single basemap file and
build.py only ever loaded `<city>_basemap.json` for the one city named on the
command line -- so a second city's data sat on disk, fetched and derived,
but never actually reaching the page. Points in that city rendered on a blank
background with no streets, indistinguishable from a wrong coordinate.

This writes `<primary>_basemap.json` (the file build.py reads) as the union
of every listed city's basemap, deduped by OSM id, keeping `<primary>`'s own
meta (bbox/center used for the default view).

Usage:
    python3 tools/merge_basemaps.py takamatsu takamatsu marugame
"""

from __future__ import annotations

import json
import pathlib
import sys

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    primary, *cities = sys.argv[1:]

    meta = None
    bbox = None  # union of every city's bbox: south, west, north, east
    seen: set[str] = set()
    features: list[dict] = []
    for city in cities:
        path = DATA_DIR / f"{city}_basemap.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        if city == primary:
            meta = doc["meta"]
        b = doc["meta"]["bbox"]
        bbox = b if bbox is None else [
            min(bbox[0], b[0]), min(bbox[1], b[1]),
            max(bbox[2], b[2]), max(bbox[3], b[3]),
        ]
        added = 0
        for f in doc["features"]:
            osm = f["properties"].get("osm")
            key = osm or json.dumps(f["geometry"])  # sea polygons lack an osm id
            if key in seen:
                continue
            seen.add(key)
            features.append(f)
            added += 1
        print(f"  {city}: +{added} features ({len(doc['features'])} total in file)",
              file=sys.stderr)

    # clampView() on the client uses this bbox as the pan boundary; if it only
    # covered the primary city, panning toward a second city snapped straight
    # back -- which silently mis-rendered every point out there (rather than
    # erroring), since screen position is computed relative to the clamped
    # view centre.
    meta = dict(meta, bbox=bbox)
    out = {"type": "FeatureCollection", "meta": meta, "features": features}
    out_path = DATA_DIR / f"{primary}_basemap.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path} -- {len(features)} features from {len(cities)} cities "
          f"({out_path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
