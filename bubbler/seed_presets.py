#!/usr/bin/env python3
"""Seed the totem's presets + group playlists from groups.json over the WLED JSON API.

One preset per effect entry (named "<Group>: <Effect>"), then one playlist
preset per group (named "<Group>") that shuffles its effect presets every
~12s. The AutoPlaylist usermod (anyPlaylist + beatQuantize enabled) adopts
whichever group playlist is selected and re-times the switches to beat onsets.

Preset id layout: effect presets from 10 up, group playlists at 1..N in
groups.json order (ambient group first is conventional: AutoPlaylist's
ambientPlaylist default is 1, musicPlaylist 2).

Usage: python seed_presets.py [host]   (default 192.168.1.108)
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.108"
BASE = f"http://{HOST}"

FIRST_EFFECT_PRESET = 10
PLAYLIST_DUR_TENTHS = 120   # 12s per entry if the usermod is off/suspended
PLAYLIST_TRANSITION = 7     # 0.7s crossfade


def api(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.load(r)


def post_state(state):
    req = urllib.request.Request(
        f"{BASE}/json/state",
        data=json.dumps(state).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    cfg = json.loads((Path(__file__).parent / "groups.json").read_text())
    groups = cfg["groups"]

    effects = api("/json/eff")
    fx_ids = {name.split("@")[0].strip(): i for i, name in enumerate(effects)}

    # ambient group first so it lands on playlist preset id 1
    ordered = sorted(groups, key=lambda g: g != cfg.get("ambient_group"))

    next_id = FIRST_EFFECT_PRESET
    playlists = {}  # group -> [preset ids]
    missing = []

    for group in ordered:
        ids = []
        for entry in groups[group]:
            fx = entry["fx"]
            if fx not in fx_ids:
                missing.append(fx)
                continue
            seg = {"id": 0, "fx": fx_ids[fx], "sx": entry.get("sx", 128),
                   "ix": entry.get("ix", 128)}
            if "pal" in entry:
                seg["pal"] = entry["pal"]
            post_state({"on": True, "mainseg": 0, "seg": [seg],
                        "psave": next_id, "n": f"{group}: {fx}",
                        "ib": True, "sb": True})
            print(f"preset {next_id:3d}  {group}: {fx}")
            ids.append(next_id)
            next_id += 1
            time.sleep(0.3)  # let FS writes settle
        playlists[group] = ids

    for pl_id, group in enumerate(ordered, start=1):
        ids = playlists[group]
        if not ids:
            print(f"!! group {group} has no valid presets, skipping playlist")
            continue
        post_state({
            "playlist": {
                "ps": ids,
                "dur": [PLAYLIST_DUR_TENTHS] * len(ids),
                "transition": [PLAYLIST_TRANSITION] * len(ids),
                "repeat": 0,
                "end": 0,
                "r": True,
            },
            "psave": pl_id, "n": group, "on": True,
        })
        print(f"playlist {pl_id}  {group}  -> presets {ids}")
        time.sleep(0.3)

    if missing:
        print("\nWARNING - effect names not found on device:", ", ".join(missing))
        print("Fix groups.json (names must match /json/eff) and re-run.")


if __name__ == "__main__":
    main()
