# BubblerTotem on WLED

This branch adapts stock WLED for the BubblerTotem: a battery-powered bubble
machine / LED totem — 6 rings of 27 WS2811 pixels (GRB) on an ESP32-S3
DevKitC-1 N8 (8MB flash, no PSRAM), with an INMP441 I2S microphone for sound
reactivity.

All customization lives in low-collision surfaces so upstream WLED merges
stay painless: this folder, `platformio_override.ini` (local, gitignored),
usermods, and `-D WLED_DISABLE_*` build flags — no core-source surgery.

## Building

1. Copy `platformio_bubbler.sample.ini` to `../platformio_override.ini` and
   fill in WiFi credentials.
2. `pio run` (env `bubbler_totem`). Requires Node.js (WLED generates its web
   UI headers at build time).

## Hardware map

| Function | GPIO |
|---|---|
| LED chain A (rings 3,2,1 — 81 px) | 4 |
| LED chain B (rings 4,5,6 — 81 px) | 5 |
| INMP441 SCK / WS / SD | 44 / 7 / 8 |
| Bubble motor (planned usermod) | 15 |
| RS485 command receiver (planned usermod) | 1, 2, 42 |

## LED layout

WLED sees the totem as a 27x6 2D matrix (x = position around a ring, y =
ring 1..6). `generate_ledmap.py` produces `ledmap.json`, which translates
that logical grid to the physical chain order above — upload it to the
device via `http://<ip>/edit` (filename must be `/ledmap.json`), and set up
the 2D matrix in LED Preferences as a single 27x6 panel.

## Roadmap (planned usermods)

- Beat-quantized preset cycling: randomly switch effects every 10-15s within
  a user-chosen category (playlist), transitioning on beat onsets from the
  audioreactive usermod
- Bubble motor control (GPIO15)
- RS485 remote commands: effect/palette/intensity/audio-sync
- BLE control interface (battery life: WiFi radio off unless needed —
  biggest open item, mainline WLED has no BLE)
- Simplified UI
