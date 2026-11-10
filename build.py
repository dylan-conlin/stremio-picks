"""Build a static Stremio add-on from picks.json into docs/ (served by GitHub Pages)."""
import json
import pathlib

from rows import ROWS

ROOT = pathlib.Path(__file__).parent
DIST = ROOT / "docs"
CATALOG_ID = "dylan-picks"

picks = json.loads((ROOT / "picks.json").read_text())

manifest = {
    "id": "com.dylanconlin.picks",
    "version": "0.3.0",
    "name": "Dylan's Picks",
    "description": "Movies and series picked for Dylan from his Stremio history, refreshed daily.",
    "resources": ["catalog"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [{"type": r["type"], "id": r["catalog"], "name": r["name"]} for r in ROWS],
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
for r in ROWS:
    rows = metas(picks.get(r["key"], []), r["type"])
    (DIST / "catalog" / r["type"]).mkdir(parents=True, exist_ok=True)
    (DIST / "catalog" / r["type"] / f"{r['catalog']}.json").write_text(
        json.dumps({"metas": rows}, indent=2, ensure_ascii=False))
    print(f"Built {len(rows)} picks for {r['name']} ({r['type']})")
