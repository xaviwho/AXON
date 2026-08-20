"""Markdown KB retrieval tests."""

from pathlib import Path

import pytest

from services.agent.app.rag import KnowledgeBase

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "shared" / "knowledge_base"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    # Legacy keyword backend — kept for portability and to lock in the
    # substring-ranking contract. The semantic backend is exercised in
    # test_rag_semantic.py.
    return KnowledgeBase.load(KB_DIR, backend="keyword")


def test_kb_loads_real_sections(kb):
    assert len(kb) > 0


def test_retrieve_by_location_finds_lab_profile(kb):
    secs = kb.retrieve(["lab-A"], limit=8)
    # Retrieval is case-insensitive; assert against lowercased body+heading.
    assert any("lab-a" in (s.heading + s.body).lower() for s in secs)


def test_retrieve_by_hazard_finds_safety_protocols(kb):
    fire = kb.retrieve(["fire"], limit=8)
    assert any("fire" in (s.heading + s.body).lower() for s in fire)
    gas = kb.retrieve(["gas"], limit=8)
    assert any("gas" in (s.heading + s.body).lower() for s in gas)


def test_retrieve_with_empty_terms_returns_nothing(kb):
    assert kb.retrieve([]) == []
    assert kb.retrieve([""]) == []


def test_retrieve_ranks_by_hit_count(kb):
    """Sections matching more terms must come first."""
    # "person" + "prone" both appear in safety_protocols.md medical section;
    # asking for both should rank that section ahead of single-term hits.
    secs = kb.retrieve(["person", "prone", "medical"], limit=3)
    assert secs, "expected at least one hit"
    # Top result must contain at least 2 of the terms.
    top = (secs[0].heading + "\n" + secs[0].body).lower()
    hits = sum(1 for t in ("person", "prone", "medical") if t in top)
    assert hits >= 2


def test_retrieve_limit_respected(kb):
    secs = kb.retrieve(["lab", "fire", "gas", "ppe"], limit=2)
    assert len(secs) <= 2
