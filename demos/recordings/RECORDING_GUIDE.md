# Pre-recorded demo videos — recording guide

The contest brief requires a pre-recorded `.mp4` for each of the three
scenarios as a fail-safe in case the live demo can't run. Aim for **under
90 seconds each** with a title card, live dashboard footage, and a
latency overlay.

This file is the operator recipe. The actual `.mp4` files are stored
alongside it and are **not** in git (added to `.gitignore`).

## Target files

```
demos/recordings/
├── medical_emergency.mp4    # ≤ 90 s
├── fire_ignition.mp4        # ≤ 90 s
├── wifi_vs_5g.mp4           # ≤ 90 s
└── RECORDING_GUIDE.md       # this file
```

## What each clip must contain

Per Prompt 9 each report calls out a "Screenshot or video reference".
A clean clip includes, in order:

1. **Title card** (5 s) — scenario name, AXON logo, navy `#1E3A8A` background.
2. **Live dashboard** with the trigger firing — anomaly gauge + slice
   chart + recent-actions stream all visible. Browser at
   `http://localhost:5173`, full-screen.
3. **Latency overlay** — small bottom-right ticker showing the
   per-stage latency numbers from the orchestrator output (or just the
   dashboard's "Live latency budget" tile if it's legible at the
   recording's resolution).
4. **End card** (3 s) — "End of `<scenario>` — see [report](…) and
   [audit log](http://localhost:5173/audit)."

## Recording recipes

### Linux (most reproducible)

```bash
# 1. Bring up the stack
SCENARIO=fire_ignition docker compose up -d \
    redis mosquitto sensing vision fusion vlm agent \
    slice_control_mock actuators_mock action console_api

# 2. Start the dashboard at a fixed resolution
cd frontend && npm run dev -- --host 0.0.0.0 --port 5173 &
# Open Chromium/Firefox in a 1920×1080 borderless window pointed at http://localhost:5173

# 3. Start ffmpeg recording the dashboard window
#    (replace :0.0 with the right display if multi-monitor)
ffmpeg -f x11grab -video_size 1920x1080 -framerate 30 -i :0.0+0,0 \
       -c:v libx264 -preset veryfast -pix_fmt yuv420p \
       demos/recordings/fire_ignition.mp4 &
FFMPEG_PID=$!

# 4. In another terminal, run the scenario
make demo SCENARIO=fire_ignition

# 5. Stop the recording
kill -INT $FFMPEG_PID
```

Repeat for each of the three scenarios.

### macOS / Windows

Either OBS Studio (free) or QuickTime / Windows Game Bar. Output at
1920×1080 30 fps, H.264, then trim to ≤90 s with the same tool's
built-in editor or `ffmpeg -ss <start> -to <end> -c copy out.mp4`.

## Latency overlay — three options

1. **Easiest:** the dashboard's existing "Live latency budget" tile is
   on every frame — no overlay needed.
2. **From the orchestrator log:** the script's `tail -3` includes
   `latency=...ms`, `latency_from_anomaly=...ms`, `latency_from_scene=...ms`,
   `all_audits_within=...ms`. Drop these as a ticker in the editor.
3. **Programmatic overlay** — `ffmpeg drawtext` can stamp text from a
   sidecar file:
   ```bash
   ffmpeg -i fire_ignition.mp4 -vf "drawtext=fontfile=/usr/share/fonts/.../Inter-Bold.otf:\
   textfile=overlay.txt:reload=1:fontcolor=white:x=20:y=H-th-20" -c:a copy out.mp4
   ```

## Trim + title cards

```bash
# Concatenate a title card + main clip + end card
ffmpeg -f lavfi -i color=c=#1e3a8a:s=1920x1080:d=5 \
       -vf "drawtext=fontfile=/usr/share/fonts/.../Inter-Bold.otf:\
       text='AXON — Fire Ignition Scenario':fontcolor=white:\
       fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2" \
       title.mp4

ffmpeg -i title.mp4 -i main.mp4 -i end.mp4 -filter_complex \
       "[0:v][1:v][2:v]concat=n=3:v=1[outv]" -map "[outv]" \
       demos/recordings/fire_ignition.mp4
```

## Storage

The `.mp4` files are intentionally **not** committed. They live on:

- the demo laptop's local disk (the master copy)
- a USB stick taken to the contest as a fail-safe
- a Google Drive / S3 bucket if the team needs to share before the event

Keep this guide in sync if the dashboard layout changes — the framing
of the screen-grab assumes the Dashboard at `/` with the standard
12-column grid.
