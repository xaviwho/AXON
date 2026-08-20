"""Run every benchmark, then compile REPORT.md summarizing outputs.

Usage:
  uv run python -m benchmarks.run_all
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH_MODULES = [
    ("bench_dispatch_latency", ["--count", "60"]),
    ("bench_phase_timeline",   ["--count", "40"]),
    ("bench_chaos",            []),
    ("bench_signing",          []),
    ("bench_fusion_gating",    []),
    ("bench_rag_retrieval",    []),
]

RESULTS_DIR = Path(__file__).parent / "results"


def run_one(module: str, extra: list[str]) -> str:
    print(f"\n=== running {module} ===")
    cmd = [sys.executable, "-m", f"benchmarks.{module}", *extra]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"!! {module} FAILED:\n{proc.stderr}")
    else:
        print(proc.stdout.strip().splitlines()[-1])
    return proc.stdout


def load_json(name: str):
    p = RESULTS_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt(v, prec: int = 1) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{prec}f}"
    return str(v)


def write_report() -> Path:
    disp = load_json("dispatch_latency.json") or {}
    phase = load_json("phase_timeline.json") or {}
    chaos = load_json("chaos_matrix.json") or []
    sign = load_json("signing_overhead.json") or {}
    gate = load_json("fusion_gating.json") or []
    rag = load_json("rag_retrieval.json") or {}

    lines: list[str] = []
    lines.append("# AXON Benchmark Report")
    lines.append(f"_generated {datetime.now(timezone.utc).isoformat()}_")
    lines.append("")
    lines.append("In-process reproduction of every result claim the paper "
                 "makes. No Docker, no Redis: benchmarks instantiate the "
                 "real services (`ActionDispatcher`, `FusionEngine` rule "
                 "evaluator, `KnowledgeBase`) and drive them through ASGI-"
                 "mounted mocks for the actuator / slice endpoints. "
                 "Reproduce with `python -m benchmarks.run_all`.")
    lines.append("")

    # 1. dispatch latency
    lines.append("## 1. Phase-1 dispatch latency by network mode")
    lines.append("| mode | n | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) | actions/trigger |")
    lines.append("|------|---:|---------:|---------:|---------:|----------:|----------------:|")
    for m in ("urllc", "wifi", "wifi_heavy"):
        s = disp.get(m, {})
        lines.append(
            f"| `{m}` | {s.get('n','—')} "
            f"| {_fmt(s.get('p50'))} | {_fmt(s.get('p95'))} "
            f"| {_fmt(s.get('p99'))} | {_fmt(s.get('mean'))} "
            f"| {_fmt(s.get('actions_per_trigger'), 2)} |"
        )
    lines.append("")
    lines.append("![dispatch_latency](dispatch_latency.png)")
    lines.append("")

    # 2. phase timeline
    lines.append("## 2. Phase-1 vs Phase-2 completion timing")
    lines.append(f"n={phase.get('n', '—')} triggers, deliberative stage simulated "
                 f"per the projection in Sec. `sec:res-projection`.")
    lines.append("")
    lines.append("| stage | p50 (ms) | p95 (ms) | mean audits/trigger |")
    lines.append("|-------|---------:|---------:|--------------------:|")
    lines.append(f"| Phase 1 (Π_g) completion | {_fmt(phase.get('phase1_p50_ms'))} "
                 f"| {_fmt(phase.get('phase1_p95_ms'))} "
                 f"| {_fmt(phase.get('phase1_audit_count_mean'), 2)} |")
    lines.append(f"| Phase 2 (Π_d delta) completion | "
                 f"{_fmt(phase.get('phase2_completion_p50_ms'))} "
                 f"| {_fmt(phase.get('phase2_completion_p95_ms'))} "
                 f"| {_fmt(phase.get('phase2_audit_count_mean'), 2)} |")
    ratio = phase.get('ratio_p50_p2_over_p1')
    if ratio is not None:
        lines.append(f"\n**Phase-2 arrives ~{ratio:.0f}× later than Phase-1 completes "
                     "— confirming Π_d is off the critical path.**")
    lines.append("")
    lines.append("![phase_timeline](phase_timeline.png)")
    lines.append("")

    # 3. chaos
    lines.append("## 3. Chaos / fault-injection matrix")
    lines.append("Empirical companion to the fail-safe claims around Prop. 1. Each "
                 "scenario runs a 6-action plan under a specific fault and asserts "
                 "the expected `ActionEffect` per action.")
    lines.append("")
    lines.append("| scenario | matches | dispatch time (ms) | audit_intact |")
    lines.append("|----------|--------:|-------------------:|:------------:|")
    for r in chaos:
        lines.append(
            f"| `{r['name']}` | {r['matches']}/{r['of']} "
            f"| {_fmt(r['elapsed_ms'])} "
            f"| {'✅' if r.get('audit_intact') else '❌'} |"
        )
    total_m = sum(r['matches'] for r in chaos)
    total_o = sum(r['of'] for r in chaos)
    if total_o:
        lines.append(f"\n**Overall: {total_m}/{total_o} expected-effect matches "
                     f"({100.0 * total_m / total_o:.1f}%).**")
    lines.append("")
    lines.append("![chaos_matrix](chaos_matrix.png)")
    lines.append("")

    # 4. signing
    lines.append("## 4. HMAC audit-signing overhead")
    lines.append("Per-op micro-benchmark. Signing runs on the dispatcher hot "
                 "path; verify runs on the persister hot path.")
    lines.append("")
    su = sign.get("sign_us", {})
    vu = sign.get("verify_us", {})
    lines.append("| operation | p50 (μs) | p95 (μs) | p99 (μs) | mean (μs) |")
    lines.append("|-----------|---------:|---------:|---------:|----------:|")
    lines.append(f"| sign    | {_fmt(su.get('p50'), 2)} | {_fmt(su.get('p95'), 2)} "
                 f"| {_fmt(su.get('p99'), 2)} | {_fmt(su.get('mean'), 2)} |")
    lines.append(f"| verify  | {_fmt(vu.get('p50'), 2)} | {_fmt(vu.get('p95'), 2)} "
                 f"| {_fmt(vu.get('p99'), 2)} | {_fmt(vu.get('mean'), 2)} |")
    rt = sign.get("round_trip_p50_us")
    if rt is not None:
        lines.append(f"\n**Sign + verify round-trip at p50: {rt:.1f} μs = "
                     f"~{rt / 1000.0:.4f} ms — negligible vs any per-action "
                     "handler latency.**")
    lines.append("")
    lines.append("![signing_overhead](signing_overhead.png)")
    lines.append("")

    # 5. fusion gating
    lines.append("## 5. Fusion activation ratio $\\bar g$ vs cooldown")
    lines.append("Sweep of the emission cooldown $\\tau_{cd}$ against a 60 s / "
                 "10 Hz synthetic workload with a HIGH reading injected every 5 s. "
                 "$\\bar g$ is the Eq. (6) activation ratio.")
    lines.append("")
    lines.append("| cooldown (s) | evaluations | over-threshold | activations | over-threshold ratio | $\\bar g$ |")
    lines.append("|-------------:|------------:|---------------:|------------:|---------------------:|---------:|")
    for r in gate:
        lines.append(
            f"| {r['cooldown_s']} | {r['evaluations']} | {r['over_threshold']} "
            f"| {r['activations']} | {_fmt(r['over_threshold_ratio'], 3)} "
            f"| {_fmt(r['gate_ratio'], 3)} |"
        )
    lines.append("")
    lines.append("![fusion_gating](fusion_gating.png)")
    lines.append("")

    # 6. RAG
    lines.append("## 6. RAG retrieval: semantic vs keyword")
    lines.append("Paraphrase queries (queries share zero keywords with the KB "
                 "sections they target) evaluated on `shared/knowledge_base/`.")
    lines.append("")
    sem = rag.get("semantic", {})
    kw = rag.get("keyword", {})
    lines.append("| backend | hit@3 | latency p50 (ms) | latency p95 (ms) | mean (ms) |")
    lines.append("|---------|:-----:|-----------------:|-----------------:|----------:|")
    lines.append(
        f"| semantic (MiniLM+FAISS) | {sem.get('hits_at_3', '—')}/"
        f"{rag.get('n_queries', '—')} "
        f"| {_fmt(sem.get('latency_ms', {}).get('p50'), 3)} "
        f"| {_fmt(sem.get('latency_ms', {}).get('p95'), 3)} "
        f"| {_fmt(sem.get('latency_ms', {}).get('mean'), 3)} |"
    )
    lines.append(
        f"| keyword | {kw.get('hits_at_3', '—')}/"
        f"{rag.get('n_queries', '—')} "
        f"| {_fmt(kw.get('latency_ms', {}).get('p50'), 4)} "
        f"| {_fmt(kw.get('latency_ms', {}).get('p95'), 4)} "
        f"| {_fmt(kw.get('latency_ms', {}).get('mean'), 4)} |"
    )
    lines.append("")
    lines.append("![rag_retrieval](rag_retrieval.png)")
    lines.append("")

    lines.append("## Reproduction")
    lines.append("```bash")
    lines.append("uv sync --extra dev")
    lines.append("uv run python -m benchmarks.run_all")
    lines.append("```")
    lines.append("Each script is independent and writes its own CSV + PNG + "
                 "JSON to `benchmarks/results/`. All benches use a fixed HMAC "
                 "signing key (`AXON_AUDIT_SIGNING_KEY=bb..bb`, 64 chars) so "
                 "signing overhead is reproducible across machines.")

    out = RESULTS_DIR / "REPORT.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> None:
    for mod, extra in BENCH_MODULES:
        run_one(mod, extra)
    report = write_report()
    print(f"\n=== summary written to {report} ===")


if __name__ == "__main__":
    main()
