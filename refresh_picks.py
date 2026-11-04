"""Refresh the "Picks for Dylan" rows from Dylan's Stremio watch history.

1. Pulls the Stremio library (everything played, how far, marked watched, in library).
2. Drops current picks that were played or have been showing for a week or more.
3. Builds a candidate pool from Cinemeta (popular, new, featured movies and series),
   leaving out anything already played or shown before.
4. Asks Claude (headless `claude -p`) to choose from the pool, plus a few older films it knows,
   guided by taste.org and the history.
5. Keeps only titles whose IMDb ID checks out on Cinemeta and that have a cached 1080p
   Real-Debrid stream (Torrentio), so every pick plays instantly. Fills to 10 movies, 5 series.
6. Writes picks.json, rebuilds docs/, commits and pushes.

Wanted-list picks (source "wanted", added by watch_wanted.py) stay at the top until played.

Secrets: the Stremio auth key comes from the Keychain (service "stremio", account "auth-key"),
falling back to the Stremio Mac app's cache; the Real-Debrid token from the Keychain
(service "real-debrid", account "api-token"). Neither is written to this public repo.

State: ~/.local/state/stremio-picks/shown.json (when each pick first showed).
Usage: python3 refresh_picks.py [--dry-run]
"""
import datetime
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).parent
STATE = pathlib.Path.home() / ".local/state/stremio-picks"
SHOWN = STATE / "shown.json"
TASTE = pathlib.Path.home() / "dev/life/personal/movies/taste.org"
APP_CACHE = pathlib.Path.home() / "Library/Containers/com.stremio.pal/Data/Library/Caches/com.stremio.pal"
N_MOVIES, N_SERIES = 10, 5
STALE_DAYS = 7
TORRENTIO_OPTS = ("qualityfilter=brremux,hdrall,dolbyvision,dolbyvisionwithhdr,"
                  "threed,4k,720p,480p,other,scr,cam,unknown|sizefilter=10GB|"
                  "debridoptions=nodownloadlinks,nocatalog")
UA = {"User-Agent": "Mozilla/5.0"}
TODAY = datetime.date.today()


def log(*a):
    print(datetime.datetime.now().isoformat(timespec="minutes"), *a, flush=True)


def get_json(url, data=None, timeout=30):
    headers = dict(UA)
    if data is not None:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
        return json.load(r)


def keychain(service, account):
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def stremio_key():
    key = keychain("stremio", "auth-key")
    if key:
        return key
    for f in ("Cache.db-wal", "Cache.db"):
        p = APP_CACHE / f
        if p.exists():
            m = re.search(rb'"authKey"\s*:\s*"([^"]+)"', p.read_bytes())
            if m:
                return m.group(1).decode()
    sys.exit("No Stremio auth key: add it to the Keychain (service stremio, account auth-key).")


def history(auth):
    items = get_json("https://api.strem.io/api/datastoreGet",
                     {"authKey": auth, "collection": "libraryItem", "all": True})["result"]
    out = []
    for x in items:
        s = x.get("state") or {}
        dur = s.get("duration") or 0
        out.append({
            "id": x["_id"], "type": x["type"], "name": x["name"],
            "last": (s.get("lastWatched") or "")[:10],
            "finished": bool(s.get("timesWatched") or s.get("flaggedWatched")),
            "episodes_watched": s.get("timesWatched", 0) if x["type"] == "series" else None,
            "progress": round(100 * s.get("timeOffset", 0) / dur) if dur else None,
            "in_library": not x.get("removed"),
        })
    out.sort(key=lambda h: h["last"], reverse=True)
    return out


def label(h):
    if h["type"] == "series":
        return f"{h['episodes_watched']} episodes watched" if h["episodes_watched"] else "opened"
    if h["finished"]:
        return "finished"
    if h["progress"] is not None and h["progress"] < 15:
        return f"stopped early ({h['progress']}%)"
    return f"partway ({h['progress']}%)" if h["progress"] else "opened, not played"


def cinemeta_pool():
    base = "https://v3-cinemeta.strem.io/catalog"
    urls = []
    for t in ("movie", "series"):
        urls += [f"{base}/{t}/top.json", f"{base}/{t}/imdbRating.json"]
        urls += [f"{base}/{t}/year/genre={y}.json" for y in (TODAY.year, TODAY.year - 1)]
    pool = {}
    for u in urls:
        t = u.split("/catalog/")[1].split("/")[0]
        try:
            metas = get_json(u).get("metas", [])
        except Exception as e:
            log("pool fetch failed", u, e)
            continue
        for m in metas:
            if m.get("id", "").startswith("tt"):
                pool.setdefault(m["id"], {
                    "id": m["id"], "type": t, "name": m.get("name"),
                    "year": m.get("releaseInfo") or m.get("year"),
                    "genres": m.get("genres", [])[:4], "imdb": m.get("imdbRating"),
                    "about": (m.get("description") or "")[:220],
                })
    return list(pool.values())


def meta(type_, imdb_id):
    try:
        return get_json(f"https://v3-cinemeta.strem.io/meta/{type_}/{imdb_id}.json").get("meta")
    except Exception:
        return None


def playable(type_, imdb_id, rd_token):
    path = f"{imdb_id}.json" if type_ == "movie" else f"{imdb_id}:1:1.json"
    opts = urllib.parse.quote(f"{TORRENTIO_OPTS}|realdebrid={rd_token}", safe="=,")
    try:
        streams = get_json(f"https://torrentio.strem.fun/{opts}/stream/{type_}/{path}").get("streams", [])
    except Exception as e:
        log("torrentio failed", imdb_id, e)
        return False
    return any("RD+" in s.get("name", "") for s in streams)


def ask_claude(taste, hist, keep, pool, avoid_names):
    hist_lines = "\n".join(f"- {h['name']} ({h['type']}): {label(h)}, last {h['last']}"
                           + (", saved to library" if h["in_library"] else "") for h in hist[:60])
    prompt = f"""You choose films and series for Dylan's "Picks for Dylan" rows in Stremio.
Today is {TODAY}. Pick what he will actually want to watch tonight, judged by what he really
finishes, not by prestige.

His taste notes:
{taste}

His Stremio history, newest first. "finished" and many episodes usually mean liked, but his taste notes override that (he finishes some films he finds meh). "stopped early" = not
for him; avoid things like it. Never pick anything in this list.
{hist_lines}

Already in the row, keep as is: {', '.join(p['name'] for p in keep) or 'none'}
Shown before and ignored or watched, never pick again: {', '.join(sorted(avoid_names)) or 'none'}

Candidate pool (current popular, new and featured titles on Cinemeta):
{json.dumps(pool, ensure_ascii=False)}

Return 20 movies and 10 series, ranked best first. Mostly from the pool. You may add up to 5
older movies and 2 older series that are not in the pool, if you are sure of their exact IMDb ID.
Each "why" is one or two sentences: what the film is and why it fits his taste. This row is
public, so don't name titles from his history or mention his viewing; describe the fit instead
(e.g. "slow-burn horror centered on a teen outsider"). Describe the film, not him: never "he tends to" or "you usually".

Reply with JSON only, no prose and no code fences:
{{"movies": [{{"id": "tt...", "name": "...", "year": 2026, "why": "..."}}],
  "series": [{{"id": "tt...", "name": "...", "year": 2026, "why": "..."}}]}}"""
    r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", "opus"],
                       input=prompt, capture_output=True, text=True, timeout=900,
                       cwd=str(STATE))
    if r.returncode != 0:
        sys.exit(f"claude failed: {r.stderr[-500:]}")
    text = json.loads(r.stdout)["result"]
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def main():
    dry = "--dry-run" in sys.argv
    STATE.mkdir(parents=True, exist_ok=True)
    shown = json.loads(SHOWN.read_text()) if SHOWN.exists() else {}
    picks_path = ROOT / "picks.json"
    data = json.loads(picks_path.read_text())
    old = data.get("picks", []) + data.get("series", [])
    for p in old:  # picks from before this script count as shown on their generated date
        shown.setdefault(p["id"], {"name": p["name"], "first": data.get("generated", str(TODAY))})

    auth = stremio_key()
    rd = keychain("real-debrid", "api-token") or sys.exit("No Real-Debrid token in Keychain.")
    hist = history(auth)
    played = {h["id"] for h in hist}

    def stays(p):
        if p["id"] in played:
            return False
        if p.get("source") == "wanted":
            return True
        first = datetime.date.fromisoformat(shown.get(p["id"], {}).get("first", str(TODAY)))
        return (TODAY - first).days < STALE_DAYS

    keep_m = [p for p in data.get("picks", []) if stays(p)]
    keep_s = [p for p in data.get("series", []) if stays(p)]
    excluded = played | set(shown)
    pool = [c for c in cinemeta_pool() if c["id"] not in excluded]
    log(f"history {len(hist)}, keeping {len(keep_m)} movies {len(keep_s)} series, pool {len(pool)}")

    need_m, need_s = N_MOVIES - len(keep_m), N_SERIES - len(keep_s)
    if need_m > 0 or need_s > 0:
        avoid = {v["name"] for k, v in shown.items() if k not in {p["id"] for p in keep_m + keep_s}}
        got = ask_claude(TASTE.read_text(), hist, keep_m + keep_s, pool, avoid)
        for kind, keep, need in (("movie", keep_m, need_m), ("series", keep_s, need_s)):
            ids = {p["id"] for p in keep}
            for c in got["movies" if kind == "movie" else "series"]:
                if need <= 0:
                    break
                cid = c.get("id", "")
                if not re.fullmatch(r"tt\d+", cid) or cid in excluded or cid in ids:
                    continue
                m = meta(kind, cid)
                if not m or m.get("name", "").lower()[:12] != c["name"].lower()[:12]:
                    log(f"skip {c['name']}: IMDb ID {cid} doesn't match ({m and m.get('name')})")
                    continue
                if not playable(kind, cid, rd):
                    log(f"skip {c['name']}: no cached 1080p")
                    continue
                year = str(m.get("releaseInfo") or c.get("year", ""))
                keep.append({"id": cid, "name": m["name"], "year": year, "why": c["why"]})
                ids.add(cid)
                need -= 1
            log(f"{kind}: {len(keep)} in row")

    for p in keep_m + keep_s:
        shown.setdefault(p["id"], {"name": p["name"], "first": str(TODAY)})
    new = {"generated": str(TODAY),
           "note": "Built by refresh_picks.py from Stremio history and taste.org.",
           "picks": keep_m, "series": keep_s}
    for p in keep_m:
        log("movie ", p["name"], p["year"], "|", p["why"])
    for p in keep_s:
        log("series", p["name"], p["year"], "|", p["why"])
    if dry:
        return
    picks_path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    SHOWN.write_text(json.dumps(shown, indent=2))
    subprocess.run([sys.executable, str(ROOT / "build.py")], check=True)
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "picks.json", "docs"], check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode:
        subprocess.run(git + ["commit", "-q", "-m", f"Refresh picks {TODAY}"], check=True)
        subprocess.run(git + ["push", "-q"], check=True)
        log("pushed")


if __name__ == "__main__":
    main()
