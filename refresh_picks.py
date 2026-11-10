"""Refresh the "Picks for Dylan" rows from Dylan's Stremio watch history.

1. Pulls the Stremio library (everything played, how far, marked watched, in library).
2. Drops current picks that were played or have been showing for a week or more.
3. Builds a candidate pool from Cinemeta (popular, new, featured movies and series),
   leaving out anything already played or shown before.
4. Asks Claude (headless `claude -p`) to choose from the pool, plus a few older films it knows,
   guided by taste.org and the history.
5. Keeps only titles whose IMDb ID checks out on Cinemeta and that have a cached 1080p
   Real-Debrid stream (Torrentio), so every pick plays instantly. Fills each row in rows.py.
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
import time
import urllib.error
import urllib.parse
import urllib.request

from rows import ROWS
from watch_wanted import BAD, wanted

ROOT = pathlib.Path(__file__).parent
STATE = pathlib.Path.home() / ".local/state/stremio-picks"
SHOWN = STATE / "shown.json"
TASTE = pathlib.Path.home() / "dev/life/personal/movies/taste.org"
APP_CACHE = pathlib.Path.home() / "Library/Containers/com.stremio.pal/Data/Library/Caches/com.stremio.pal"
STALE_DAYS = 7
TORRENTIO_OPTS = ("qualityfilter=brremux,hdrall,dolbyvision,dolbyvisionwithhdr,"
                  "threed,4k,720p,480p,other,scr,cam,unknown|sizefilter=10GB|"
                  "debridoptions=nodownloadlinks,nocatalog")
UA = {"User-Agent": "Mozilla/5.0"}
TODAY = datetime.date.today()


def log(*a):
    print(datetime.datetime.now().isoformat(timespec="minutes"), *a, flush=True)


def get_json(url, data=None, timeout=30, tries=4):
    headers = dict(UA)
    if data is not None:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429:
                raise
            if i == tries - 1:
                raise
            time.sleep(5 * 2 ** i)


def wait_for_network(minutes=20):
    """launchd runs a missed 5:00 job right at wake, before Wi-Fi is back. Wait for it."""
    for _ in range(minutes * 4):
        try:
            urllib.request.urlopen("https://api.strem.io", timeout=10)
            return
        except urllib.error.HTTPError:
            return  # got an answer, so the network is up
        except Exception:
            time.sleep(15)
    sys.exit("No network after waiting; giving up until tomorrow.")


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
    # Torrentio's quality filter misses some theater copies (AUDIONEW, HC, TS in the name)
    return any("RD+" in s.get("name", "") and not BAD.search(f"{s.get('name', '')} {s.get('title', '')}")
               for s in streams)


def ask_claude(taste, hist, keep, pool, avoid_names, needs):
    hist_lines = "\n".join(f"- {h['name']} ({h['type']}): {label(h)}, last {h['last']}"
                           + (", saved to library" if h["in_library"] else "") for h in hist[:60])
    rows_text = "\n".join(
        f'- "{r["key"]}" ({r["type"]}, "{r["name"]}"): {r["brief"]} Give {needs[r["key"]] * 2 + 4}, ranked.'
        for r in ROWS if needs[r["key"]] > 0)
    keys = ", ".join(f'"{r["key"]}": [...]' for r in ROWS if needs[r["key"]] > 0)
    prompt = f"""You choose films and series for Dylan's rows in Stremio.
Today is {TODAY}. Pick what he will actually want to watch, judged by what he rated and
finished, not by prestige.

His taste notes (the summary at the top is the best guide):
{taste}

His Stremio history, newest first. "finished" and many episodes usually mean liked, but his
taste notes override that (he finishes some films he finds meh). "stopped early" = not for him;
avoid things like it. Never pick anything in this list or any title named in his taste notes.
{hist_lines}

Already in the rows, keep as is and don't repeat: {', '.join(p['name'] for p in keep) or 'none'}
Shown before and ignored or watched, never pick again: {', '.join(sorted(avoid_names)) or 'none'}

Candidate pool (current popular, new and featured titles on Cinemeta, with real IMDb IDs):
{json.dumps(pool, ensure_ascii=False)}

Rows to fill:
{rows_text}

Titles outside the pool are fine (and needed for Deep Cuts), but only if you are sure of the
exact IMDb ID. Never put the same title in two rows. Each "why" is one or two sentences: what
the film is and why it fits. The rows are public, so don't name titles from his history and
don't mention his viewing. Describe the film, not him: never "he tends to" or "you usually".

Reply with JSON only, no prose and no code fences, using these keys:
{{{keys}}}
where each item is {{"id": "tt...", "name": "...", "year": 2026, "why": "..."}}"""
    r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", "opus"],
                       input=prompt, capture_output=True, text=True, timeout=1200,
                       cwd=str(STATE))
    if r.returncode != 0:
        sys.exit(f"claude failed: {r.stderr[-500:]}")
    text = json.loads(r.stdout)["result"]
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def in_rows_list(keep):
    return [p for ps in keep.values() for p in ps]


def main():
    dry = "--dry-run" in sys.argv
    wait_for_network()
    STATE.mkdir(parents=True, exist_ok=True)
    shown = json.loads(SHOWN.read_text()) if SHOWN.exists() else {}
    picks_path = ROOT / "picks.json"
    data = json.loads(picks_path.read_text())
    old = [p for r in ROWS for p in data.get(r["key"], [])]
    for p in old:  # picks from before this script count as shown on their generated date
        shown.setdefault(p["id"], {"name": p["name"], "first": data.get("generated", str(TODAY))})

    auth = stremio_key()
    rd = keychain("real-debrid", "api-token") or sys.exit("No Real-Debrid token in Keychain.")
    hist = history(auth)
    played = {h["id"] for h in hist}
    played |= set(re.findall(r"\btt\d{6,}\b", TASTE.read_text()))  # seen outside Stremio
    waiting = {w[0] for w in wanted()}  # watch_wanted.py adds these once a proper release is out

    def stays(p):
        if p["id"] in played:
            return False
        if p.get("source") == "wanted":
            return True
        if p["id"] in waiting:
            return False
        first = datetime.date.fromisoformat(shown.get(p["id"], {}).get("first", str(TODAY)))
        return (TODAY - first).days < STALE_DAYS

    keep = {r["key"]: [p for p in data.get(r["key"], []) if stays(p)] for r in ROWS}
    in_rows = {p["id"] for ps in keep.values() for p in ps}
    excluded = played | set(shown) | waiting
    pool = [c for c in cinemeta_pool() if c["id"] not in excluded]
    needs = {r["key"]: r["size"] - len(keep[r["key"]]) for r in ROWS}
    log(f"history {len(hist)}, pool {len(pool)}, need", needs)

    if any(n > 0 for n in needs.values()):
        avoid = {v["name"] for k, v in shown.items() if k not in in_rows}
        kept = [p for ps in keep.values() for p in ps]
        got = ask_claude(TASTE.read_text(), hist, kept, pool, avoid, needs)
        for r in ROWS:
            need, row = needs[r["key"]], keep[r["key"]]
            for c in got.get(r["key"], []):
                if need <= 0:
                    break
                cid = c.get("id", "")
                if not re.fullmatch(r"tt\d+", cid) or cid in excluded or cid in in_rows:
                    continue
                m = meta(r["type"], cid)
                if not m or m.get("name", "").lower()[:12] != c["name"].lower()[:12]:
                    log(f"skip {c['name']}: IMDb ID {cid} doesn't match ({m and m.get('name')})")
                    continue
                if not playable(r["type"], cid, rd):
                    log(f"skip {c['name']}: no cached 1080p")
                    continue
                year = str(m.get("releaseInfo") or c.get("year", ""))
                row.append({"id": cid, "name": m["name"], "year": year, "why": c["why"]})
                in_rows.add(cid)
                need -= 1
            log(f"{r['name']} ({r['type']}): {len(row)}/{r['size']}")

    for p in in_rows_list(keep):
        shown.setdefault(p["id"], {"name": p["name"], "first": str(TODAY)})
    new = {"generated": str(TODAY),
           "note": "Built by refresh_picks.py from Stremio history and taste.org. Rows: rows.py."}
    for r in ROWS:
        new[r["key"]] = keep[r["key"]]
        for p in keep[r["key"]]:
            log(f"{r['key']:8}", p["name"], p["year"], "|", p["why"])
    if dry:
        return
    picks_path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    SHOWN.write_text(json.dumps(shown, indent=2))
    subprocess.run([sys.executable, str(ROOT / "build.py")], check=True)
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "picks.json", "docs", "rows.py"], check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode:
        subprocess.run(git + ["commit", "-q", "-m", f"Refresh picks {TODAY}"], check=True)
        subprocess.run(git + ["push", "-q"], check=True)
        log("pushed")


if __name__ == "__main__":
    main()
