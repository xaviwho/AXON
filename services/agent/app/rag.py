"""RAG retrieval over the markdown knowledge base.

Two backends, selected at `KnowledgeBase.load` time:

  * ``semantic`` (default) — encodes each KB section with the
    sentence-transformers MiniLM model and builds a FAISS ``IndexFlatIP``
    over L2-normalized embeddings so ``retrieve`` returns the sections
    with the highest cosine similarity to the query. This is the
    production path and lets the agent match semantically related
    sections even when the terms in the trigger do not literally appear
    in the KB text.
  * ``keyword`` — the legacy substring baseline (case-insensitive hit
    count, ties broken by source-file order). Kept for offline tests and
    as an escape hatch for environments where the model cannot load.

Sections are split by H2 (``##``) headings, exactly as before. Sentence
embeddings are computed once at load time and reused across every
``retrieve`` call. The model is cached module-globally so multiple
``KnowledgeBase`` instances share a single copy in memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class KBSection:
    source_file: str
    heading: str
    body: str

    def __str__(self) -> str:
        return f"### [{self.source_file}] {self.heading}\n{self.body.strip()}"


_H2 = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _split_sections(path: Path) -> list[KBSection]:
    text = path.read_text(encoding="utf-8")
    out: list[KBSection] = []
    matches = list(_H2.finditer(text))
    if not matches:
        return [KBSection(source_file=path.name, heading=path.stem, body=text)]
    preamble = text[: matches[0].start()].strip()
    if preamble:
        out.append(KBSection(source_file=path.name, heading="(preamble)", body=preamble))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        out.append(KBSection(source_file=path.name, heading=heading, body=body))
    return out


@lru_cache(maxsize=4)
def _load_model(name: str) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


class KnowledgeBase:
    def __init__(
        self,
        sections: list[KBSection],
        *,
        backend: str = "semantic",
        model: Any | None = None,
        index: Any | None = None,
    ) -> None:
        self._sections = sections
        self._backend = backend
        self._model = model
        self._index = index

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        backend: str = "semantic",
        model_name: str = _DEFAULT_MODEL,
    ) -> "KnowledgeBase":
        sections: list[KBSection] = []
        if root.exists():
            for md in sorted(root.glob("*.md")):
                sections.extend(_split_sections(md))

        if backend != "semantic" or not sections:
            return cls(sections, backend=backend if backend == "keyword" else "semantic")

        import faiss    # noqa: PLC0415 — local import keeps keyword-only paths lightweight

        model = _load_model(model_name)
        vecs = model.encode(
            [f"{s.heading}\n{s.body}" for s in sections],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")
        index = faiss.IndexFlatIP(vecs.shape[1])
        index.add(vecs)
        return cls(sections, backend="semantic", model=model, index=index)

    def __len__(self) -> int:
        return len(self._sections)

    @property
    def backend(self) -> str:
        return self._backend

    def retrieve(self, terms: list[str], *, limit: int = 6) -> list[KBSection]:
        """Return up to ``limit`` KB sections most relevant to the query terms.

        Semantic backend: cosine-similarity ranking over section embeddings.
        Keyword backend: case-insensitive substring hit-count ranking.
        Empty ``terms`` returns nothing under either backend.
        """
        norm_terms = [t.strip() for t in terms if t and t.strip()]
        if not norm_terms or not self._sections:
            return []
        if self._backend == "semantic":
            return self._retrieve_semantic(norm_terms, limit)
        return self._retrieve_keyword(norm_terms, limit)

    def _retrieve_semantic(self, terms: list[str], limit: int) -> list[KBSection]:
        query = " ".join(terms)
        qvec = self._model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True,
        ).astype("float32")
        k = min(limit, len(self._sections))
        _, idxs = self._index.search(qvec, k)
        return [self._sections[i] for i in idxs[0] if i >= 0]

    def _retrieve_keyword(self, terms: list[str], limit: int) -> list[KBSection]:
        norm = [t.lower() for t in terms]
        scored: list[tuple[int, int, KBSection]] = []
        for i, sec in enumerate(self._sections):
            hay = (sec.heading + "\n" + sec.body).lower()
            hits = sum(1 for t in norm if t in hay)
            if hits > 0:
                scored.append((-hits, i, sec))
        scored.sort()
        return [s[2] for s in scored[:limit]]
