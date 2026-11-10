# stremio-picks

A static Stremio add-on that shows a "Picks for Dylan" row. Each pick uses its IMDb ID, so
Torrentio still adds Real-Debrid (RD+) streams.

- `rows.py`: the rows (Picks for Dylan, New for Dylan, Controlled Dread, Dark & Deadpan, Deep Cuts,
  series), each with a size and a brief for the picker. Edit it to add, drop or reorder rows.
- `picks.json`: the current picks, one key per row, each with a reason.
- `refresh_picks.py`: rebuilds the rows daily at 5:00 (`com.dylanconlin.picks-refresh.plist`).
  It reads Stremio watch history (finished = liked, stopped under 15% = not for Dylan), drops
  picks that were played or have shown for 7 days, has `claude -p` choose from Cinemeta's popular,
  new and featured titles plus `taste.org`, keeps only titles with a cached 1080p Real-Debrid stream that isn't a theater copy,
  skips titles on the wanted list (the checker below adds those),
  and pushes. Wanted-list picks stay until played. Log: `~/.local/state/stremio-picks/refresh.log`.
  Try it: `python3 refresh_picks.py --dry-run`. The Stremio auth key comes from the Keychain
  (service `stremio`, account `auth-key`), falling back to the Stremio Mac app's cache.
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
