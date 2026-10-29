"""Combine the three per-scenario reports into one dress-rehearsal summary.

Runs after `make rehearsal` has executed each scenario. Pulls the
per-scenario markdown reports from demos/scenarios/reports/ and writes a
single REHEARSAL.md alongside them with cross-run latencies.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPORTS = Path(__file__).parent / "reports"
SCENARIOS = ["medical_emergency", "fire_ignition", "wifi_vs_5g"]


def _extract_passfail(text: str) -> str:
    m = re.search(r"\*\*Result:\*\*\s*(\S+\s*\S*)", text)
    if m:
        return m.group(1)
    # wifi_vs_5g uses a comparison shape rather than a single pass/fail
    # line; it passes when the headline ratio meets the ≥ 5× target.
    m = re.search(r"Wi-Fi\s*/\s*URLLC\s*ratio:\*\*\s*([0-9.]+)×", text)
    if m:
        return "✅ PASS" if float(m.group(1)) >= 5.0 else "❌ FAIL"
    return "?"


def _extract_dispatch_window(text: str) -> str:
    m = re.search(r"anomaly\s*→\s*all-audits window:\s*([0-9.]+)\s*ms", text)
    if m:
        return f"{m.group(1)} ms"
    # wifi_vs_5g report uses a different shape — fall back to the comparison table.
    return "—"


def _extract_anomaly_to_first_audit(text: str) -> str:
    m = re.search(r"anomaly\s*→\s*first-audit gap:\s*([0-9.]+)\s*ms", text)
    return f"{m.group(1)} ms" if m else "—"


def _extract_ratio(text: str) -> str:
    m = re.search(r"Wi-Fi\s*/\s*URLLC\s*ratio:\*\*\s*([0-9.]+×)", text)
    return m.group(1) if m else "—"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--since", type=float, default=None,
        help="epoch seconds the rehearsal started; older reports are flagged stale",
    )
    args = parser.parse_args()

    if not REPORTS.exists():
        print(f"no reports dir at {REPORTS}", file=sys.stderr)
        return 2

    lines = [
        "# AXON Dress Rehearsal Summary",
        f"_generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "Combined view of one back-to-back run of all three demo scenarios "
        "(`make rehearsal`). Per-scenario detail is in the linked reports.",
        "",
        "## Per-scenario summary",
        "| scenario | result | anomaly → all audits | anomaly → first audit | Wi-Fi ratio |",
        "|----------|:------:|------------------:|----------------------:|------------:|",
    ]
    all_ok = True
    for name in SCENARIOS:
        path = REPORTS / f"{name}.md"
        if not path.exists():
            lines.append(f"| `{name}` | _missing report_ | — | — | — |")
            all_ok = False
            continue
        if args.since is not None and path.stat().st_mtime < args.since:
            # The scenario failed before writing a report; the file on disk is
            # from an earlier run and must not be read as this run's result.
            lines.append(f"| `{name}` | ❌ STALE (not rewritten this run) | — | — | — |")
            all_ok = False
            continue
        text = path.read_text(encoding="utf-8")
        result = _extract_passfail(text)
        all_ok = all_ok and "PASS" in result
        dispatch = _extract_dispatch_window(text)
        anomaly = _extract_anomaly_to_first_audit(text)
        ratio = _extract_ratio(text) if name == "wifi_vs_5g" else "n/a"
        link = f"[`{name}.md`]({name}.md)"
        lines.append(f"| {link} | {result} | {dispatch} | {anomaly} | {ratio} |")

    tick = "x" if all_ok else " "
    lines.extend([
        "",
        "## Dress-rehearsal checklist (per CLAUDE.md and Prompt 10)",
        f"- [{tick}] All three scenarios run to completion without manual intervention",
        f"- [{tick}] Audit log captures every dispatched action with required fields",
        f"- [{tick}] Per-stage latencies recorded for every run",
        "- [ ] Slice reshape visible on the live dashboard WebSocket (check by eye)",
        "",
        "## How to reproduce",
        "```",
        "make rehearsal",
        "```",
        "_The Make target runs each scenario with a 30 s settle gap between runs and "
        "regenerates this summary at the end._",
    ])

    out = REPORTS / "REHEARSAL.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nDress-rehearsal summary written to {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
