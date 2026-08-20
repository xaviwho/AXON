"""Benchmark 3 — chaos / fault-injection outcome matrix.

Each row of the matrix is a fault scenario. Under the fault we dispatch a
6-action plan and record: (a) whether each action was rescued to a
well-formed audit record with the correct ``ActionEffect``, and (b) the
end-to-end dispatch time.

The output is the empirical companion to Proposition 1's surrounding
fail-safe prose in the paper.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass

import httpx
import matplotlib.pyplot as plt
import numpy as np

from benchmarks._common import (
    COLORS,
    NOW,
    RESULTS_DIR,
    MemoryBus,
    dump_json,
    savefig,
)


class ChaosTransport(httpx.AsyncBaseTransport):
    def __init__(self, rules):
        self._rules = rules

    async def handle_async_request(self, request):
        url = str(request.url)
        for needle, mode in self._rules:
            if needle in url:
                if mode == "500":
                    return httpx.Response(500, text="chaos: forced 500", request=request)
                if mode == "timeout":
                    raise httpx.TimeoutException("chaos: forced timeout", request=request)
                if mode == "exception":
                    raise httpx.ConnectError("chaos: forced connect error", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)


@dataclass
class ChaosScenario:
    name: str
    faults: list[tuple[str, str]]
    expected: dict[str, str]    # action_id → expected effect ("success"/"failure"/"timeout")


SCENARIOS = [
    ChaosScenario(
        name="baseline_no_fault",
        faults=[],
        expected={"power_cutoff": "success", "hvac_isolate": "success",
                  "slice_reshape": "success", "notify_responders": "success",
                  "display_alert": "success"},
    ),
    ChaosScenario(
        name="actuator_500",
        faults=[("/equipment/power_cutoff", "500")],
        expected={"power_cutoff": "failure", "hvac_isolate": "success",
                  "slice_reshape": "success", "notify_responders": "success",
                  "display_alert": "success"},
    ),
    ChaosScenario(
        name="actuator_timeout",
        faults=[("/hvac/isolate", "timeout")],
        expected={"power_cutoff": "success", "hvac_isolate": "timeout",
                  "slice_reshape": "success", "notify_responders": "success",
                  "display_alert": "success"},
    ),
    ChaosScenario(
        name="slice_controller_500",
        faults=[("/slices/", "500")],
        expected={"power_cutoff": "success", "hvac_isolate": "success",
                  "slice_reshape": "failure", "notify_responders": "success",
                  "display_alert": "success"},
    ),
    ChaosScenario(
        name="actuator_connect_error",
        faults=[("/equipment/", "exception")],
        expected={"power_cutoff": "failure", "hvac_isolate": "success",
                  "slice_reshape": "success", "notify_responders": "success",
                  "display_alert": "success"},
    ),
    ChaosScenario(
        name="everything_500",
        faults=[("/equipment/", "500"), ("/hvac/", "500"),
                ("/slices/", "500"), ("/door/", "500")],
        expected={"power_cutoff": "failure", "hvac_isolate": "failure",
                  "slice_reshape": "failure", "notify_responders": "success",
                  "display_alert": "success"},
    ),
]


async def run_scenario(scenario: ChaosScenario) -> dict:
    from services.action.app.dispatcher import ActionDispatcher, NetworkMode
    from services.action.app.telemetry import ActionTelemetry
    from shared.action_library import ActionLibrary
    from shared.schemas.actions import ActionInvocation, ActionPlan
    from shared.schemas.enums import ActionEffect

    http = httpx.AsyncClient(transport=ChaosTransport(scenario.faults), timeout=1.0)
    bus = MemoryBus()
    d = ActionDispatcher(
        bus=bus, http=http, telemetry=ActionTelemetry(),
        library=ActionLibrary.load(),
        actuators_url="http://actuators-mock:8000",
        slice_control_url="http://slice-control-mock:8000",
        timeout_seconds=0.5, max_concurrent_plans=8,
        network=NetworkMode(),
    )
    plan = ActionPlan(
        severity=4,
        actions=[
            ActionInvocation(action_id="power_cutoff",
                             parameters={"zone_id": "lab-A"}, requested_latency_ms=80),
            ActionInvocation(action_id="hvac_isolate",
                             parameters={"zone_id": "lab-A"}, requested_latency_ms=80),
            ActionInvocation(action_id="slice_reshape",
                             parameters={"slices": [{"slice_id": "URLLC", "priority": 9}]},
                             requested_latency_ms=60),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@x"], "severity": 4,
                                         "message": "chaos"},
                             requested_latency_ms=200),
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 4, "message": "chaos"},
                             requested_latency_ms=200),
        ],
        rationale="chaos scenario",
        audit_metadata={"layer_d_trace": "chaos"},
        confidence=1.0, trigger_id=f"chaos-{scenario.name}", timestamp=NOW,
    )
    try:
        t0 = time.monotonic()
        outcomes = await d.dispatch_plan(plan)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
    finally:
        await http.aclose()

    by_action = {o.invocation.action_id: o.effect.value for o in outcomes}
    matches = sum(
        1 for aid, exp in scenario.expected.items() if by_action.get(aid) == exp
    )
    audit_intact = len(bus.audits) == len(outcomes)
    return {
        "name": scenario.name,
        "elapsed_ms": elapsed_ms,
        "by_action": by_action,
        "expected": scenario.expected,
        "matches": matches,
        "of": len(scenario.expected),
        "audit_intact": audit_intact,
        "dispatched_count": len(outcomes),
    }


def render(rows: list[dict]) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    ax = axes[0]
    n = len(rows)
    ys = np.arange(n)
    match_rates = [100.0 * r["matches"] / r["of"] for r in rows]
    ax.barh(ys, match_rates, color=COLORS["success"], edgecolor="white")
    ax.set_yticks(ys)
    ax.set_yticklabels([r["name"] for r in rows])
    ax.set_xlabel("expected-effect match rate (%)")
    ax.set_xlim(0, 105)
    for i, r in enumerate(rows):
        ax.text(match_rates[i] + 1, i,
                f"{r['matches']}/{r['of']}", va="center", fontsize=9)
    ax.set_title("Chaos-scenario expected-effect match rate")
    ax.grid(True, axis="x", alpha=0.25)
    ax.invert_yaxis()

    ax = axes[1]
    times = [r["elapsed_ms"] for r in rows]
    ax.barh(ys, times, color=COLORS["phase1"], edgecolor="white")
    ax.set_yticks(ys)
    ax.set_yticklabels([r["name"] for r in rows])
    ax.set_xlabel("plan dispatch time (ms, under fault)")
    for i, t in enumerate(times):
        ax.text(t + max(times) * 0.01, i, f"{t:.0f}", va="center", fontsize=9)
    ax.set_title("Dispatch completion time under each fault")
    ax.grid(True, axis="x", alpha=0.25)
    ax.invert_yaxis()

    plt.tight_layout()
    return fig


def main() -> None:
    from benchmarks._common import run

    rows = [run(run_scenario(s)) for s in SCENARIOS]

    csv_path = RESULTS_DIR / "chaos_matrix.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scenario", "matches", "of", "audit_intact",
                    "dispatched_count", "elapsed_ms", "outcomes_json"])
        import json
        for r in rows:
            w.writerow([r["name"], r["matches"], r["of"],
                        int(r["audit_intact"]), r["dispatched_count"],
                        f"{r['elapsed_ms']:.3f}", json.dumps(r["by_action"])])

    fig = render(rows)
    savefig(fig, "chaos_matrix.png")

    dump_json("chaos_matrix.json", rows)
    total_matches = sum(r["matches"] for r in rows)
    total_expected = sum(r["of"] for r in rows)
    print(f"[chaos] wrote csv+png+json  "
          f"overall matches={total_matches}/{total_expected} "
          f"({100.0 * total_matches / total_expected:.1f}%)")
    for r in rows:
        print(f"  {r['name']:28s} {r['matches']}/{r['of']} "
              f"({r['elapsed_ms']:6.1f}ms)")


if __name__ == "__main__":
    main()
