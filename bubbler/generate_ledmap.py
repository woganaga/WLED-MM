"""Generate ledmap.json for the BubblerTotem: 6 rings x 27 LEDs on two pins.

Physical chain order (matches the retired Bubbler-pio firmware's Rings.cpp):
  bus A on GPIO4, 81 LEDs: ring 3 (phys 0-26), ring 2 (27-53), ring 1 (54-80)
  bus B on GPIO5, 81 LEDs: ring 4 (81-107), ring 5 (108-134), ring 6 (135-161)

Logical layout for WLED's 2D matrix model: 27 wide (position around the
ring) x 6 high (ring 1 = row 0 ... ring 6 = row 5) - the same unrolled
cylinder the old xLights-derived effects used. The ledmap translates
logical (row-major) index -> physical chain index.

Usage: py generate_ledmap.py > ledmap.json, then upload to the device via
http://<wled-ip>/edit (file must be named /ledmap.json).
"""

import json

WIDTH, HEIGHT = 27, 6
# physical index of position 0 for logical row y (y=0 is ring 1)
RING_START = [54, 27, 0, 81, 108, 135]

ledmap = {
    "n": "BubblerTotem 27x6 rings",
    "w": WIDTH,
    "h": HEIGHT,
    "map": [RING_START[y] + x for y in range(HEIGHT) for x in range(WIDTH)],
}

print(json.dumps(ledmap))
