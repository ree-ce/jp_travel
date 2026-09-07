#!/usr/bin/env python3
"""Export data/<city>.json (areas + pois) to a KML file for Google My Maps.

Google My Maps happily imports KML: top-level <Folder> elements become
toggle-able layers (limit 10 per map), so this puts every arcade/mall
polygon in one "範圍" layer and buckets points one layer per category.

Usage:
    python3 tools/export_kml.py takamatsu
    python3 tools/export_kml.py takamatsu -o takamatsu_map.kml
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from xml.sax.saxutils import escape

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# zh label + accent colour, matching src/app.template.html's CATEGORIES/AREA_KIND
# so the KML export looks like the same map, not a re-skin of it.
CATEGORIES = {
    "restaurant": ("餐廳", "e0642f"),
    "cafe":       ("咖啡", "9a6b43"),
    "shop":       ("商店", "2f74c9"),
    "sight":      ("景點", "3f9a5c"),
    "view":       ("展望台", "1e9c96"),
    "hotel":      ("住宿", "8256c4"),
    "transit":    ("交通", "6a7078"),
    "other":      ("其他", "8a8177"),
}
AREA_KIND_LABEL = {"arcade": "商店街", "mall": "商場", "group": "商店街群"}
AREA_COLORS = {"arcade": "d9622f", "mall": "2f74c9", "group": "7a4fbf"}


def kml_color(hex_rgb: str, alpha: str = "ff") -> str:
    """Web #RRGGBB -> KML's aabbggrr channel order."""
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"{alpha}{b}{g}{r}"


def name_of(o: dict) -> str:
    return o.get("name_zh") or o.get("name_ja") or o.get("id", "")


def coord_str(lon: float, lat: float) -> str:
    return f"{lon},{lat},0"


def rings_of(geom: dict) -> list:
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


def area_placemark(a: dict) -> str:
    geom = a.get("geometry")
    if not geom:
        return ""
    kind = a.get("kind", "arcade")
    bits = [AREA_KIND_LABEL.get(kind, kind)]
    if a.get("note"):
        bits.append(a["note"])
    desc = escape("\n".join(bits))
    name = escape(name_of(a))

    rings = rings_of(geom)
    is_poly = geom["type"] in ("Polygon", "MultiPolygon")
    parts = []
    for ring in rings:
        coords = " ".join(coord_str(lo, la) for lo, la in ring)
        if is_poly:
            parts.append(
                f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}"
                f"</coordinates></LinearRing></outerBoundaryIs></Polygon>"
            )
        else:
            parts.append(f"<LineString><coordinates>{coords}</coordinates></LineString>")
    geom_xml = parts[0] if len(parts) == 1 else f"<MultiGeometry>{''.join(parts)}</MultiGeometry>"

    return (
        f"<Placemark><name>{name}</name><styleUrl>#area-{kind}</styleUrl>"
        f"<description>{desc}</description>{geom_xml}</Placemark>"
    )


def poi_placemark(p: dict) -> str:
    lon, lat = p["coord"]
    cat = p.get("cat", "other")
    bits = []
    if p.get("floor"):
        bits.append(p["floor"])
    if p.get("note"):
        bits.append(p["note"])
    if p.get("hours"):
        bits.append("營業時間：" + p["hours"])
    if p.get("url"):
        bits.append(p["url"])
    if p.get("source"):
        bits.append("來源：" + p["source"])
    desc = escape("\n".join(bits))
    name = escape(name_of(p))
    return (
        f"<Placemark><name>{name}</name><styleUrl>#poi-{cat}</styleUrl>"
        f"<description>{desc}</description>"
        f"<Point><coordinates>{coord_str(lon, lat)}</coordinates></Point></Placemark>"
    )


def build_kml(doc: dict, title: str) -> str:
    areas = doc.get("areas", [])
    pois = doc.get("pois", [])

    styles = []
    for kind, hexcol in AREA_COLORS.items():
        styles.append(
            f'<Style id="area-{kind}">'
            f"<LineStyle><color>{kml_color(hexcol)}</color><width>3</width></LineStyle>"
            f'<PolyStyle><color>{kml_color(hexcol, "50")}</color></PolyStyle>'
            f"</Style>"
        )
    for cat, (_, hexcol) in CATEGORIES.items():
        styles.append(
            f'<Style id="poi-{cat}">'
            f"<IconStyle><color>{kml_color(hexcol)}</color><scale>1.1</scale>"
            f'<Icon><href>http://maps.google.com/mapfiles/kml/paddle/wht-blank.png</href></Icon>'
            f"</IconStyle></Style>"
        )

    area_placemarks = "\n".join(p for a in areas if (p := area_placemark(a)))

    by_cat: dict[str, list] = {}
    for p in pois:
        by_cat.setdefault(p.get("cat", "other"), []).append(p)

    cat_folders = []
    # Stable order (CATEGORIES' own order) rather than whatever order cats
    # first appear in the data, so re-exports don't reshuffle the layer list.
    for cat in list(CATEGORIES) + [k for k in by_cat if k not in CATEGORIES]:
        plist = by_cat.get(cat)
        if not plist:
            continue
        label = CATEGORIES.get(cat, (cat,))[0]
        placemarks = "\n".join(poi_placemark(p) for p in plist)
        cat_folders.append(f"<Folder><name>{escape(label)}（{len(plist)}）</name>{placemarks}</Folder>")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
        f"<name>{escape(title)}</name>\n"
        + "".join(styles)
        + f"<Folder><name>範圍（商店街／商場，{sum(1 for a in areas if a.get('geometry'))}）</name>{area_placemarks}</Folder>\n"
        + "\n".join(cat_folders)
        + "\n</Document>\n</kml>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("city")
    ap.add_argument("-o", "--out", help="output path (default: <city>_map.kml)")
    args = ap.parse_args()

    path = DATA_DIR / f"{args.city}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    title = doc.get("meta", {}).get("name_zh") or args.city
    kml = build_kml(doc, f"{title} 商店街地圖")

    out = pathlib.Path(args.out) if args.out else DATA_DIR.parent / f"{args.city}_map.kml"
    out.write_text(kml, encoding="utf-8")
    n_areas = sum(1 for a in doc.get("areas", []) if a.get("geometry"))
    n_pois = len(doc.get("pois", []))
    print(f"wrote {out} — {n_areas} area shapes, {n_pois} points", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
