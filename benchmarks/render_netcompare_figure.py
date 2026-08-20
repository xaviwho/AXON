"""One-shot: render paper/figures/netcompare.png from the wifi_vs_5g report.

Replaces Table 3 (`tab:netcompare`) in paper/results.tex with a paired
bar chart. Numbers come directly from
``demos/scenarios/reports/wifi_vs_5g.md`` — hardcoded here because the
report is markdown, not JSON, and the values only change when the
scenario is re-run.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import numpy as np   # noqa: E402


# From demos/scenarios/reports/wifi_vs_5g.md, 2026-08-20 run
FIRST_AUDIT = {"URLLC": 16.0, "Wi-Fi": 239.0}
ALL_AUDITS  = {"URLLC": 16.8, "Wi-Fi": 240.6}
PER_ACTION  = {"URLLC": 16.5, "Wi-Fi": 240.0}

URLLC_BLUE = "#1e3a8a"
WIFI_RED   = "#dc2626"
OUT = Path(__file__).resolve().parents[1] / "paper" / "figures" / "netcompare.png"


def main() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.1))

    groups = ["plan → first-audit", "plan → all-audits", "per-action p50"]
    urllc_vals = [FIRST_AUDIT["URLLC"], ALL_AUDITS["URLLC"], PER_ACTION["URLLC"]]
    wifi_vals  = [FIRST_AUDIT["Wi-Fi"], ALL_AUDITS["Wi-Fi"], PER_ACTION["Wi-Fi"]]

    x = np.arange(len(groups))
    w = 0.36

    b1 = ax.bar(x - w/2, urllc_vals, w, label="URLLC", color=URLLC_BLUE)
    b2 = ax.bar(x + w/2, wifi_vals,  w, label="Wi-Fi",  color=WIFI_RED)

    for bar in list(b1) + list(b2):
        v = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, v + 5,
                f"{v:.1f}", ha="center", va="bottom", fontsize=9)

    for i, (u, w_v) in enumerate(zip(urllc_vals, wifi_vals)):
        ratio = w_v / u if u else 0
        ax.text(x[i], max(u, w_v) + 25,
                f"{ratio:.1f}×", ha="center", va="bottom", fontsize=10,
                color="#111", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(groups)
    ax.set_ylabel("latency (ms)")
    ax.set_title("Paired fire_ignition run: identical plan, network mode switched")
    ax.set_ylim(0, max(wifi_vals) * 1.35)
    ax.legend(loc="upper right", framealpha=0.95)
    ax.grid(True, axis="y", alpha=0.25)

    plt.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
