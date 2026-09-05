#!/usr/bin/env python3
"""Bake the map data into the app template, producing self-contained HTML.

Two outputs, because the two places this app runs want different wrappers:

* ``<city>_map.html``          -- a complete document (doctype, head, viewport)
                                  for opening straight off the filesystem or
                                  serving from GitHub Pages.
* ``<city>_map.artifact.html`` -- body-only fragment, which is what the Claude
                                  Artifact publisher expects (it supplies the
                                  doctype and head itself).

Both are fully offline: no external script, style, font or tile is referenced.

Usage:
    python3 tools/build.py takamatsu
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATE = ROOT / "src" / "app.template.html"

FULL_HEAD = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, \
maximum-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#f4f1ea" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1b1e23" media="(prefers-color-scheme: dark)">
<style>html,body{margin:0;padding:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head>
<body>
"""
FULL_TAIL = "\n</body>\n</html>\n"


def minify_geojson(doc: dict, precision: int = 6) -> dict:
    """Round coordinates. At 1e-6 degrees (~0.1 m) nothing visible is lost,
    and it typically takes a third off the file size."""

    def rnd(node):
        if isinstance(node, list):
            if node and isinstance(node[0], (int, float)):
                return [round(v, precision) for v in node]
            return [rnd(v) for v in node]
        return node

    for f in doc.get("features", []):
        g = f.get("geometry")
        if g and "coordinates" in g:
            g["coordinates"] = rnd(g["coordinates"])
    for a in doc.get("areas", []):
        g = a.get("geometry")
        if g and "coordinates" in g:
            g["coordinates"] = rnd(g["coordinates"])
    return doc


def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "takamatsu"
    basemap_path = DATA_DIR / f"{city}_basemap.json"
    city_path = DATA_DIR / f"{city}.json"
    for p in (TEMPLATE, basemap_path, city_path):
        if not p.exists():
            print(f"missing {p}", file=sys.stderr)
            return 2

    basemap = minify_geojson(json.loads(basemap_path.read_text(encoding="utf-8")))
    citydoc = minify_geojson(json.loads(city_path.read_text(encoding="utf-8")))
    title = f"{citydoc['meta'].get('name_zh', city)}商店街地圖"

    def embed(obj: dict) -> str:
        # `</script>` inside a JSON string would end the host script tag early.
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace(
            "</", "<\\/"
        )

    body = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__TITLE__", title)
        .replace("__BASEMAP_JSON__", embed(basemap))
        .replace("__CITY_JSON__", embed(citydoc))
    )

    full = ROOT / f"{city}_map.html"
    full.write_text(FULL_HEAD + body + FULL_TAIL, encoding="utf-8")
    frag = ROOT / f"{city}_map.artifact.html"
    frag.write_text(body, encoding="utf-8")

    for p in (full, frag):
        print(f"wrote {p.relative_to(ROOT)}  {p.stat().st_size / 1024:.0f} KB",
              file=sys.stderr)
    print(f"  {len(citydoc['areas'])} areas, {len(citydoc['pois'])} points, "
          f"{len(basemap['features'])} basemap features", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
