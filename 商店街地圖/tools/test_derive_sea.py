#!/usr/bin/env python3
"""Checks for the coastline-to-sea-polygon closure.

The rule under test: a coastline clipped to the bbox can be closed along the
boundary in two directions; the correct one is whichever polygon excludes the
city centre. Run with:

    python3 tools/test_derive_sea.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import derive_sea as ds  # noqa: E402

BBOX = [0.0, 0.0, 1.0, 1.0]  # south, west, north, east

CASES = [
    # name,           centre,      coastline,                              sea probe,  land probe
    ("sea north",     [0.5, 0.2], [[-0.2, 0.6], [0.5, 0.55], [1.2, 0.6]], [0.5, 0.9], [0.5, 0.2]),
    ("sea south",     [0.5, 0.8], [[-0.2, 0.4], [0.5, 0.45], [1.2, 0.4]], [0.5, 0.1], [0.5, 0.8]),
    ("sea west",      [0.8, 0.5], [[0.4, -0.2], [0.35, 0.5], [0.4, 1.2]], [0.1, 0.5], [0.8, 0.5]),
    # A diagonal coast: closing it has to round two corners of the bbox.
    ("sea NE corner", [0.2, 0.2], [[-0.2, 0.8], [0.8, -0.2]],             [0.9, 0.9], [0.2, 0.2]),
    # No interior vertices at all -- relies on densifying before clipping.
    ("span, no verts", [0.5, 0.1], [[-0.5, 0.5], [1.5, 0.5]],             [0.5, 0.9], [0.5, 0.1]),
]


def main() -> int:
    failures = 0
    for name, centre, line, sea_probe, land_probe in CASES:
        runs = ds.clip_to_bbox(line, BBOX)
        ring = ds.close_run(runs[0], BBOX, centre) if runs else None
        ok = bool(ring) and ds.contains(ring, sea_probe) and not ds.contains(ring, land_probe)
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        failures += not ok

    # An island fully inside the bbox touches no edge and must be skipped
    # rather than closed into a bogus polygon.
    island = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.4]]
    ok = ds.close_run(ds.clip_to_bbox(island, BBOX)[0], BBOX, [0.1, 0.1]) is None
    print(f"{'PASS' if ok else 'FAIL'}  interior ring is skipped")
    failures += not ok

    print("ALL PASS" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
