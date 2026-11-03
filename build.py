"""Build a static Stremio add-on from picks.json into docs/ (served by GitHub Pages)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).parent
DIST = ROOT / "docs"
CATALOG_ID = "dylan-picks"

picks = json.loads((ROOT / "picks.json").read_text())

manifest = {
    "id": "com.dylanconlin.picks",
    "version": "0.2.0",
    "name": "Dylan's Picks",
    "description": "Movies and series picked for Dylan from his Stremio history, refreshed daily.",
    "resources": ["catalog"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [
        {"type": "movie", "id": CATALOG_ID, "name": "Picks for Dylan"},
        {"type": "series", "id": CATALOG_ID, "name": "Picks for Dylan"},
    ],
}

def metas(items, type_):
    return [
    {
        "id": p["id"],
        "type": type_,
        "name": p["name"],
        "releaseInfo": str(p["year"]),
        "poster": f"https://images.metahub.space/poster/medium/{p['id']}/img",
        "description": p["why"],
    }
    for p in items
    ]


(DIST / "manifest.json").write_text(json.dumps(manifest, indent=2))
for type_, key in (("movie", "picks"), ("series", "series")):
    rows = metas(picks.get(key, []), type_)
    (DIST / "catalog" / type_).mkdir(parents=True, exist_ok=True)
    (DIST / "catalog" / type_ / f"{CATALOG_ID}.json").write_text(
        json.dumps({"metas": rows}, indent=2, ensure_ascii=False))
    print(f"Built {len(rows)} {type_} picks into {DIST}")
