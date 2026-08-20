"""Semantic RAG backend — embedding + FAISS path.

These tests exercise the real MiniLM + FAISS retriever. Skipped if
sentence-transformers is not importable (offline install).
"""

from pathlib import Path

import pytest

pytest.importorskip("sentence_transformers")
pytest.importorskip("faiss")

from services.agent.app.rag import KnowledgeBase    # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "shared" / "knowledge_base"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load(KB_DIR, backend="semantic")


def test_kb_uses_semantic_backend(kb):
    assert kb.backend == "semantic"
    assert len(kb) > 0


def test_semantic_retrieves_medical_from_paraphrase(kb):
    """A query that never mentions 'medical' or 'prone' must still surface it.

    The safety_protocols.md medical section talks about door_unlock, EHS,
    responder video. Query with unrelated phrasing that a keyword grep
    would miss but sentence embeddings will connect.
    """
    secs = kb.retrieve(["person collapsed unconscious"], limit=3)
    assert secs, "semantic backend must return at least one section"
    joined = " ".join((s.heading + " " + s.body).lower() for s in secs)
    # At least one of the top-3 must reference the medical response.
    assert (
        "medical" in joined
        or "door_unlock" in joined
        or "person down" in joined
        or "responder" in joined
    ), f"expected medical section in top-3; got headings={[s.heading for s in secs]}"


def test_semantic_retrieves_fire_from_paraphrase(kb):
    """Query 'combustion in workshop' should surface the fire protocol."""
    secs = kb.retrieve(["combustion in workshop"], limit=3)
    assert secs
    joined = " ".join((s.heading + " " + s.body).lower() for s in secs)
    assert (
        "fire" in joined
        or "thermal" in joined
        or "hvac" in joined
        or "power_cutoff" in joined
    )


def test_semantic_respects_limit(kb):
    for k in (1, 2, 4):
        secs = kb.retrieve(["fire hazard response"], limit=k)
        assert len(secs) <= k


def test_semantic_empty_terms_returns_nothing(kb):
    assert kb.retrieve([]) == []
    assert kb.retrieve([""]) == []
    assert kb.retrieve(["   "]) == []
