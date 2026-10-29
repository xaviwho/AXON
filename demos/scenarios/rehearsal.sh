#!/usr/bin/env bash
# `make rehearsal` without make (Windows Git Bash, or any box lacking make).
# Runs medical_emergency, fire_ignition, wifi_vs_5g back-to-back with a
# settle gap, then writes demos/scenarios/reports/REHEARSAL.md.
#
#   bash demos/scenarios/rehearsal.sh            # all three
#   bash demos/scenarios/rehearsal.sh fire_ignition
set -u
cd "$(dirname "$0")/../.."

export PYTHONIOENCODING=utf-8    # Windows console can't print "→" otherwise
GAP_SECONDS="${REHEARSAL_GAP_SECONDS:-30}"
SCENARIOS=("${@:-medical_emergency fire_ignition wifi_vs_5g}")
read -r -a SCENARIOS <<< "${SCENARIOS[*]}"

run_one() {
    local scen="$1" yaml="$1"
    [ "$scen" = "wifi_vs_5g" ] && yaml=fire_ignition
    echo "--- bringing up stack with SCENARIO=$yaml ---"
    SCENARIO=$yaml docker compose up -d redis mosquitto slice_control_mock actuators_mock
    SCENARIO=$yaml docker compose up -d --force-recreate \
        sensing vision fusion vlm agent action console_api
    echo "--- waiting 8 s for services to settle ---"
    sleep 8
    uv run python -m "demos.scenarios.$scen"
}

start=$(date +%s)
rc=0
last="${SCENARIOS[${#SCENARIOS[@]}-1]}"
for scen in "${SCENARIOS[@]}"; do
    echo ""; echo "==============================="
    echo "  rehearsal: $scen"
    echo "==============================="
    if ! run_one "$scen"; then rc=1; echo "!!! $scen FAILED"; fi
    if [ "$scen" != "$last" ]; then
        echo "--- ${GAP_SECONDS} s settle gap ---"; sleep "$GAP_SECONDS"
    fi
done
uv run python -m demos.scenarios.rehearsal_summary --since "$start" || rc=1
echo ""; echo "Rehearsal finished in $(( $(date +%s) - start ))s (rc=$rc)"
exit $rc
