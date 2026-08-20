"""Benchmark 6 — RAG retrieval: semantic (MiniLM + FAISS) vs keyword.

Measures per-query latency of the two backends and a small precision
proxy: for a paraphrase query, does the top-k contain the section the
paraphrase is about? Keyword typically misses (no lexical overlap);
semantic typically hits.
"""

from __future__ import annotations

import csv
import statistics
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from benchmarks._common import COLORS, RESULTS_DIR, dump_json, savefig
from services.agent.app.rag import KnowledgeBase

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = REPO_ROOT / "shared" / "knowledge_base"


# (query, expected substring appearing somewhere in one of the retrieved
# sections' heading+body — lowercased). The queries deliberately paraphrase.
QUERIES = [
    ("person collapsed unconscious",     "medical"),
    ("combustion in workshop",           "fire"),
    ("toxic gas leak in the lab",        "gas"),
    ("worker not wearing hard hat",      "ppe"),
    ("chemical splash on the floor",     "chemical"),
    ("smoke pouring out of enclosure",   "smoke"),
    ("power tool in operation",          "equipment"),
    ("responder needs to enter zone",    "unlock"),
]


def _time(fn, n: int) -> list[float]:
    for _ in range(3):
        fn()
    xs = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        fn()
        xs.append((time.perf_counter_ns() - t0) / 1e6)   # milliseconds
    return xs


def evaluate(kb: KnowledgeBase, queries):
    hits = 0
    times = []
    for q, expected in queries:
        secs = kb.retrieve([q], limit=3)
        joined = " ".join((s.heading + " " + s.body).lower() for s in secs)
        if expected.lower() in joined:
            hits += 1
        # Time this one query 20x for the per-query latency distribution
        times.extend(_time(lambda: kb.retrieve([q], limit=3), 20))
    return hits, times


def render(sem_times, kw_times, sem_hits, kw_hits, n_queries) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    bins = np.linspace(0, max(max(sem_times), max(kw_times)) * 1.05, 40)
    ax.hist(kw_times, bins=bins, alpha=0.65, label="keyword",
            color=COLORS["keyword"], edgecolor="white")
    ax.hist(sem_times, bins=bins, alpha=0.65, label="semantic (MiniLM+FAISS)",
            color=COLORS["semantic"], edgecolor="white")
    ax.set_xlabel("query latency (ms)")
    ax.set_ylabel("count")
    ax.set_title("RAG per-query retrieval latency")
    ax.legend()
    ax.grid(True, alpha=0.25)

    ax = axes[1]
    xs = np.arange(2)
    vals = [100.0 * kw_hits / n_queries, 100.0 * sem_hits / n_queries]
    bars = ax.bar(xs, vals,
                  color=[COLORS["keyword"], COLORS["semantic"]], width=0.55)
    ax.set_xticks(xs)
    ax.set_xticklabels(["keyword", "semantic"])
    ax.set_ylabel("paraphrase hit@3 (%)")
    ax.set_ylim(0, 105)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 1, f"{v:.0f}%",
                ha="center", va="bottom", fontsize=10)
    ax.set_title(f"Paraphrase retrieval recall (n={n_queries})")
    ax.grid(True, axis="y", alpha=0.25)

    plt.tight_layout()
    return fig


def main() -> None:
    sem_kb = KnowledgeBase.load(KB_DIR, backend="semantic")
    kw_kb = KnowledgeBase.load(KB_DIR, backend="keyword")
    print(f"[rag] KB sections: {len(sem_kb)}  queries: {len(QUERIES)}")

    sem_hits, sem_times = evaluate(sem_kb, QUERIES)
    kw_hits, kw_times = evaluate(kw_kb, QUERIES)

    csv_path = RESULTS_DIR / "rag_retrieval.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["backend", "iteration", "query_ms"])
        for i, x in enumerate(sem_times):
            w.writerow(["semantic", i, f"{x:.3f}"])
        for i, x in enumerate(kw_times):
            w.writerow(["keyword", i, f"{x:.3f}"])

    fig = render(sem_times, kw_times, sem_hits, kw_hits, len(QUERIES))
    savefig(fig, "rag_retrieval.png")

    summary = {
        "n_queries": len(QUERIES),
        "sections": len(sem_kb),
        "semantic": {
            "hits_at_3": sem_hits,
            "hit_rate": sem_hits / len(QUERIES),
            "latency_ms": {
                "p50": float(np.percentile(sem_times, 50)),
                "p95": float(np.percentile(sem_times, 95)),
                "mean": statistics.mean(sem_times),
            },
        },
        "keyword": {
            "hits_at_3": kw_hits,
            "hit_rate": kw_hits / len(QUERIES),
            "latency_ms": {
                "p50": float(np.percentile(kw_times, 50)),
                "p95": float(np.percentile(kw_times, 95)),
                "mean": statistics.mean(kw_times),
            },
        },
    }
    dump_json("rag_retrieval.json", summary)
    print(f"[rag] wrote csv+png+json")
    print(f"  semantic hits@3={sem_hits}/{len(QUERIES)}  "
          f"p50={summary['semantic']['latency_ms']['p50']:.2f}ms")
    print(f"  keyword  hits@3={kw_hits}/{len(QUERIES)}  "
          f"p50={summary['keyword']['latency_ms']['p50']:.3f}ms")


if __name__ == "__main__":
    main()
