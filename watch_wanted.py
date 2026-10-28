"""Check the wanted list for proper (non-CAM) releases.

Reads the "Waiting for a proper release" section of watchlist.org. For each unchecked
movie with an IMDb ID, asks Torrentio for streams. When a WEB-DL, WEBRip or BluRay shows up,
the movie goes to the top of picks.json, the add-on is rebuilt and pushed, and an iMessage
goes to the number in ~/.config/stremio-picks/phone. Each movie is announced once; the
record lives in ~/.local/state/stremio-picks/announced.json.

Usage: python3 watch_wanted.py [--dry-run]
"""
import datetime
import json
import pathlib
import re
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).parent
WATCHLIST = pathlib.Path.home() / "dev/life/personal/movies/watchlist.org"
PHONE_FILE = pathlib.Path.home() / ".config/stremio-picks/phone"
STATE_FILE = pathlib.Path.home() / ".local/state/stremio-picks/announced.json"
SECTION = "** Waiting for a proper release"

GOOD = re.compile(r"WEB[-. ]?DL|WEB[-. ]?Rip|\bWEB\b|Blu[-. ]?Ray|BDRip|BRRip|REMUX", re.I)
BAD = re.compile(
    r"\b(HD)?CAM(Rip)?\b|\bHQCAM\b|\b(HD)?TS\b|TELESYNC|\bTC\b|TELECINE|\bSCR\b|SCREENER"
    r"|AUDIONEW|NEW[-. ]?AUDIO|\bHC\b",
    re.I,
)


def wanted():
    """Unchecked movies in the wanted section, as (imdb_id, title, year)."""
    items, inside = [], False
    for line in WATCHLIST.read_text().splitlines():
        if line.startswith("*"):
            inside = line.startswith(SECTION)
            continue
        m = re.match(r"- \[ \] (.+?) \((\d{4}).*?IMDb (tt\d+)", line)
        if inside and m:
            items.append((m.group(3), m.group(1), int(m.group(2))))
    return items


def proper_release(imdb_id):
    """Name of the best non-CAM release Torrentio lists, or None."""
    req = urllib.request.Request(
        f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        streams = json.load(r).get("streams", [])
    for s in streams:  # Torrentio sorts best first
        text = f"{s.get('name', '')} {s.get('title', '')}"
        release = s.get("title", "").split("\n")[0]
        if GOOD.search(text) and not BAD.search(text):
            return release
    return None


def add_pick(imdb_id, title, year, release):
    path = ROOT / "picks.json"
    data = json.loads(path.read_text())
    data["picks"] = [p for p in data["picks"] if p["id"] != imdb_id]
    data["picks"].insert(0, {
        "id": imdb_id,
        "name": title,
        "year": year,
        "why": f"From your wanted list: now out in proper quality ({release}).",
    })
    path.write_text(json.dumps(data, indent=2) + "\n")
    subprocess.run([sys.executable, str(ROOT / "build.py")], check=True)
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "picks.json", "docs"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", f"Add {title}: proper release is out"], check=True)
    subprocess.run(git + ["push", "-q"], check=True)


def imessage(text):
    phone = PHONE_FILE.read_text().strip()
    script = (
        'on run {who, msg}\n'
        '  tell application "Messages" to send msg to participant who of '
        '(1st account whose service type = iMessage)\n'
        'end run'
    )
    subprocess.run(["osascript", "-e", script, phone, text], check=True)


def main():
    dry = "--dry-run" in sys.argv
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    announced = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    stamp = datetime.datetime.now().isoformat(timespec="minutes")
    for imdb_id, title, year in wanted():
        if imdb_id in announced:
            continue
        try:
            release = proper_release(imdb_id)
        except Exception as e:
            print(f"{stamp} {title}: check failed ({e})")
            continue
        print(f"{stamp} {title}: {release or 'not out yet'}")
        if not release or dry:
            continue
        add_pick(imdb_id, title, year, release)
        imessage(f"🎬 {title} is out in proper quality. It's at the top of Picks for Dylan in Stremio.")
        announced[imdb_id] = {"title": title, "release": release, "date": stamp}
        STATE_FILE.write_text(json.dumps(announced, indent=2))


if __name__ == "__main__":
    main()
