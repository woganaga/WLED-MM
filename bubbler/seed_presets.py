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
MOTOR_PRESET_ID = 250       # quickload toggle for the bubble motor (MultiRelay 0 = GPIO6)
CYCLE_PRESET_ID = 249       # quickload toggle for motor duty-cycle mode (20s on / 2min, see cfg)
STOP_PRESET_ID = 248        # quickload: stop the running playlist, keep current effect


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


def upload_presets_file(data: bytes):
    boundary = "----bubblerseed"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="data"; filename="/presets.json"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=10):
        pass


def reset_presets_file():
    """Start from an empty presets.json. Re-saving an existing preset id goes
    through WLED's in-place file patcher, which corrupts the file when many
    ids are replaced in a row (keys blanked, stale bodies left behind);
    appends to a fresh file are reliable. NOTE: wipes ALL presets on device."""
    upload_presets_file(b'{"0":{}}')
    print("presets.json reset")


def add_motor_toggle_preset():
    """Command-only preset ("o":true saves the API call itself, not a light
    state snapshot) so tapping it just toggles the motor relay."""
    post_state({"psave": MOTOR_PRESET_ID, "n": "Bubbles (toggle)", "ql": "BUB",
                "o": True, "MultiRelay": {"relay": 0, "on": "t"}})
    print(f"preset {MOTOR_PRESET_ID}  Bubbles (toggle)  [quickload BUB]")
    time.sleep(1.0)
    # duty-cycle mode: on cycle-for-s every cycle-every-s (bubbler fork of
    # the MultiRelay usermod; times configurable in usermod settings)
    post_state({"psave": CYCLE_PRESET_ID, "n": "Bubbles auto (20s/2min)", "ql": "B2",
                "o": True, "MultiRelay": {"relay": 0, "cycle": "t"}})
    print(f"preset {CYCLE_PRESET_ID}  Bubbles auto  [quickload B2]")


def main():
    cfg = json.loads((Path(__file__).parent / "groups.json").read_text())
    groups = cfg["groups"]

    reset_presets_file()
    time.sleep(1)

    effects = api("/json/eff")
    # device names carry trailing audio-reactive glyphs (e.g. "GEQ ♫") - match on ASCII only
    def norm(name):
        return "".join(c for c in name.split("@")[0] if ord(c) < 128).strip()
    fx_ids = {norm(name): i for i, name in enumerate(effects)}

    # ambient group first so it lands on playlist preset id 1
    ordered = sorted(groups, key=lambda g: g != cfg.get("ambient_group"))

    next_id = FIRST_EFFECT_PRESET
    playlists = {}  # group -> [preset ids]
    bubbler_ids = {}  # preset id -> motor on/off (groups that drive the bubbler)
    missing = []

    for group in ordered:
        ids = []
        entries = [e for e in groups[group] if e["fx"] in fx_ids]
        group_has_bubbler = any(e.get("bubbler") for e in entries)
        for entry in groups[group]:
            fx = entry["fx"]
            if fx not in fx_ids:
                missing.append(fx)
                continue
            seg = {"id": 0, "fx": fx_ids[fx], "sx": entry.get("sx", 128),
                   "ix": entry.get("ix", 128)}
            if "pal" in entry:
                seg["pal"] = entry["pal"]
            if entry.get("mi"):
                # mirror: directional effects (one end feeds, far end dark)
                # look better symmetric on the totem's ring row
                seg["mi"] = True
            # ib False: don't store brightness in effect presets, so the
            # global brightness survives effect changes during the show
            post_state({"on": True, "mainseg": 0, "seg": [seg],
                        "psave": next_id, "n": f"{group}: {fx}",
                        "ib": False, "sb": True})
            print(f"preset {next_id:3d}  {group}: {fx}")
            if group_has_bubbler:
                # in a bubbler-driving group every preset sets the motor, so
                # it turns off again when a non-bubbler effect comes up
                bubbler_ids[next_id] = bool(entry.get("bubbler"))
            ids.append(next_id)
            next_id += 1
            time.sleep(1.0)  # rapid psave calls corrupt presets.json (in-place patcher race)
        playlists[group] = ids

    for pl_id, group in enumerate(ordered, start=1):
        ids = playlists[group]
        if not ids:
            print(f"!! group {group} has no valid presets, skipping playlist")
            continue
        dur = cfg.get("group_dur", {}).get(group, PLAYLIST_DUR_TENTHS)
        post_state({
            "playlist": {
                "ps": ids,
                "dur": [dur] * len(ids),
                "transition": [PLAYLIST_TRANSITION] * len(ids),
                "repeat": 0,
                "end": 0,
                "r": True,
            },
            # "o" marks this as a playlist/API preset: without it psave
            # snapshots the current light state instead of the playlist
            "psave": pl_id, "n": group, "on": True, "o": True,
        })
        print(f"playlist {pl_id}  {group}  -> presets {ids}")
        time.sleep(1.0)

    time.sleep(1)  # let the last psave finish writing presets.json
    add_motor_toggle_preset()

    # final direct patch of presets.json: things psave can't express.
    # - bubbler on/off embedded in effect presets (psave snapshots only
    #   relay *state*, which is ignored on apply)
    # - the Stop Playlist button: psave with a "playlist" key saves the
    #   currently loaded playlist, not the posted one, so an empty-playlist
    #   command preset has to be written into the file directly
    time.sleep(1)
    presets = api("/presets.json")
    for pid, on in bubbler_ids.items():
        presets[str(pid)]["MultiRelay"] = {"relay": 0, "on": on}
    presets[str(STOP_PRESET_ID)] = {
        "n": "Stop Playlist", "ql": "STP",
        # empty playlist = unload current one, keep the running effect
        "playlist": {"ps": []},
    }
    upload_presets_file(json.dumps(presets).encode())
    if bubbler_ids:
        on_ids = [p for p, on in bubbler_ids.items() if on]
        print(f"bubbler ON during presets {on_ids}, off for the rest of their group")
    print(f"preset {STOP_PRESET_ID}  Stop Playlist  [quickload STP]")

    if missing:
        print("\nWARNING - effect names not found on device:", ", ".join(missing))
        print("Fix groups.json (names must match /json/eff) and re-run.")


if __name__ == "__main__":
    main()
