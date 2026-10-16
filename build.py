"""Build a static Stremio add-on from picks.json into docs/ (served by GitHub Pages)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).parent
DIST = ROOT / "docs"
CATALOG_ID = "dylan-picks"

picks = json.loads((ROOT / "picks.json").read_text())

manifest = {
    "id": "com.dylanconlin.picks",
    "version": "0.1.0",
    "name": "Dylan's Picks",
    "description": "A weekly row of movies picked for Dylan, each with a reason.",
    "resources": ["catalog"],
    "types": ["movie"],
    "idPrefixes": ["tt"],
    "catalogs": [{"type": "movie", "id": CATALOG_ID, "name": "Picks for Dylan"}],
}

metas = [
    {
        "id": p["id"],
        "type": "movie",
        "name": p["name"],
        "releaseInfo": str(p["year"]),
        "poster": f"https://images.metahub.space/poster/medium/{p['id']}/img",
        "description": p["why"],
    }
    for p in picks["picks"]
]

(DIST / "catalog" / "movie").mkdir(parents=True, exist_ok=True)
(DIST / "manifest.json").write_text(json.dumps(manifest, indent=2))
(DIST / "catalog" / "movie" / f"{CATALOG_ID}.json").write_text(json.dumps({"metas": metas}, indent=2))
print(f"Built {len(metas)} picks into {DIST}")
