"""The rows shown in Stremio. Each row is a key in picks.json and a catalog in the manifest.

To add, remove or reorder a row, edit this list, then run refresh_picks.py (it fills the row
and rebuilds). Stremio shows rows in this order. The "picks" and "series" rows keep the
catalog id "dylan-picks" that the add-on started with.
"""

ROWS = [
    {"key": "picks", "type": "movie", "catalog": "dylan-picks", "name": "Picks for Dylan", "size": 10,
     "brief": "The best fits for tonight, any year or style."},
    {"key": "new", "type": "movie", "catalog": "dylan-new", "name": "New for Dylan", "size": 10,
     "brief": "Movies released in the last 12 months that fit his taste. Mostly from the pool."},
    {"key": "dread", "type": "movie", "catalog": "dylan-dread", "name": "Controlled Dread", "size": 10,
     "brief": "Tense, precise thrillers and horror: cruel, director-controlled, escalating, with an "
              "ending that lands. Any year."},
    {"key": "deadpan", "type": "movie", "catalog": "dylan-deadpan", "name": "Dark & Deadpan", "size": 10,
     "brief": "Dark comedies and satires played completely straight: people calmly going along with "
              "something awful. Never campy or wacky. Any year."},
    {"key": "deepcuts", "type": "movie", "catalog": "dylan-deepcuts", "name": "Deep Cuts", "size": 10,
     "brief": "Lesser-known films, from before 2023 and from any country, in the same vein. Skip anything "
              "famous: no mainstream hits or best-of-decade staples."},
    {"key": "series", "type": "series", "catalog": "dylan-picks", "name": "Picks for Dylan", "size": 8,
     "brief": "Series he'll want to binge: same taste, with momentum from episode to episode."},
]
