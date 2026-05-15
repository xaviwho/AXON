#!/usr/bin/env bash
# Auto-record the three demo scenarios into demos/recordings/*.webm.
#
# Assumes the AXON stack is up + the Vite dev server is serving the
# dashboard on http://localhost:5173 (per the runbook). Each scenario
# is recorded inside a Playwright container (chromium + system libs
# preinstalled) using --network host so it can reach localhost:5173;
# the scenario itself fires from this shell.

set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root

RECORDINGS_DIR="$(pwd)/demos/recordings"
mkdir -p "$RECORDINGS_DIR"

PW_IMAGE="${PW_IMAGE:-mcr.microsoft.com/playwright/python:v1.59.0-noble}"
WIDTH="${WIDTH:-1600}"
HEIGHT="${HEIGHT:-900}"

# Per-scenario recording duration. Each is the orchestrator's wallclock
# (rough) + pre/post-roll. Tune if the scenario takes longer locally.
declare -A DURATIONS=(
    [medical_emergency]=60
    [fire_ignition]=30
    [wifi_vs_5g]=80
)

# Make sure dashboard + console_api are answering before we start.
if ! curl -sf http://127.0.0.1:5173/ > /dev/null; then
    echo "dashboard not reachable at http://localhost:5173 — start `npm run dev` first" >&2
    exit 2
fi
if ! curl -sf http://127.0.0.1:8008/health > /dev/null; then
    echo "console_api not reachable at :8008 — bring the stack up first" >&2
    exit 2
fi

for scen in medical_emergency fire_ignition wifi_vs_5g; do
    dur="${DURATIONS[$scen]}"
    out="${RECORDINGS_DIR}/${scen}.webm"
    echo
    echo "=============================="
    echo "  recording: $scen  (~${dur}s)"
    echo "=============================="

    cname="axon-recorder-$scen"
    docker rm -f "$cname" >/dev/null 2>&1 || true
    # The official playwright image ships browsers under /ms-playwright but
    # NOT the Python module — we pip-install it on first use (~10s; cached
    # in /ms-playwright after that). Browser download is skipped because
    # PLAYWRIGHT_BROWSERS_PATH already points at the bundled binaries.
    docker run -d --rm \
        --name "$cname" \
        --network host \
        -v "$RECORDINGS_DIR:/recordings:rw" \
        -v "$(pwd)/demos/recordings/record_dashboard.py:/record_dashboard.py:ro" \
        -e DASHBOARD_URL=http://host.docker.internal:5173 \
        -e DURATION_S="$dur" \
        -e OUTPUT_FILE="/recordings/${scen}.webm" \
        -e WIDTH="$WIDTH" \
        -e HEIGHT="$HEIGHT" \
        -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
        "$PW_IMAGE" \
        bash -c "pip install --quiet --break-system-packages playwright==1.59.0 \
                 && python /record_dashboard.py"

    # Let Chromium load the dashboard before we kick off the scenario.
    sleep 4

    if [[ "$scen" == "wifi_vs_5g" ]]; then
        # ratio comparison takes ~55s; recording is 80s
        uv run python -m demos.scenarios.wifi_vs_5g || \
            echo "(scenario $scen returned non-zero — continuing recording anyway)"
    else
        uv run python -m demos.scenarios."$scen" || \
            echo "(scenario $scen returned non-zero — continuing recording anyway)"
    fi

    # Wait for the recorder to finish + flush
    docker wait "$cname" >/dev/null
    docker logs "$cname" 2>&1 | tail -3 || true

    # gap so fusion's 10s cooldown is clear before the next scenario
    if [[ "$scen" != "wifi_vs_5g" ]]; then
        sleep 12
    fi
done

echo
echo "Recordings:"
ls -lh "$RECORDINGS_DIR"/*.webm 2>/dev/null || echo "(none?)"
