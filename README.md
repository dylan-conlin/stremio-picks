# stremio-picks

A static Stremio add-on that shows a "Picks for Dylan" row. Each pick uses its IMDb ID, so
Torrentio still adds Real-Debrid (RD+) streams.

- `picks.json`: the current picks, each with a reason. An agent or a person edits this.
- `build.py`: writes the add-on into `docs/` (`manifest.json` plus the catalog).
- Test locally: `python3 build.py && python3 -m http.server 7001 -d docs`, then install
  `http://127.0.0.1:7001/manifest.json` in Stremio on the Mac.
- Hosted on GitHub Pages from `docs/` on main. To update: edit picks.json, run build.py, commit, push.
- Install URL: https://dylan-conlin.github.io/stremio-picks/manifest.json

Taste notes and watch history live in `~/dev/life/personal/movies/`. Trakt user: dylan_conlin_ok.

## Wanted-list checker

`watch_wanted.py` runs twice a day (9:00 and 18:00) from launchd
(`com.dylanconlin.wanted-check.plist`, installed in `~/Library/LaunchAgents`). It reads the
"Waiting for a proper release" section of `~/dev/life/personal/movies/watchlist.org`. When a movie
there has a WEB-DL, WEBRip or BluRay on Torrentio (never CAM, TS, screener or AUDIONEW), it adds the
movie to the top of the picks row, pushes, and sends an iMessage.

- Phone number: `~/.config/stremio-picks/phone` (kept out of this public repo).
- Already-announced movies and the log: `~/.local/state/stremio-picks/`.
- Check by hand: `python3 watch_wanted.py --dry-run`.
