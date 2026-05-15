"""RAG retrieval over the markdown knowledge base.

MVP implementation: read every `*.md` once at startup, split by H2 (`##`)
headings, return sections whose heading OR body mentions any of the
caller's query terms.

Production swap path documented in services/agent/README.md: replace this
module with a FAISS index over BGE-large embeddings while keeping the
`retrieve(...)` signature stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


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
    # Optional preamble (everything before first H2)
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


class KnowledgeBase:
    def __init__(self, sections: list[KBSection]) -> None:
        self._sections = sections

    @classmethod
    def load(cls, root: Path) -> "KnowledgeBase":
        sections: list[KBSection] = []
        if not root.exists():
            return cls(sections)
        for md in sorted(root.glob("*.md")):
            sections.extend(_split_sections(md))
        return cls(sections)

    def __len__(self) -> int:
        return len(self._sections)

    def retrieve(self, terms: list[str], *, limit: int = 6) -> list[KBSection]:
        """Return up to `limit` sections that mention any of `terms`, ranked by hit count.

        Case-insensitive substring match; ties broken by source-file order.
        Empty `terms` returns nothing — the agent should always pass at least
        the location, trigger reason, or hazard types.
        """
        norm_terms = [t.lower().strip() for t in terms if t and t.strip()]
        if not norm_terms:
            return []
        scored: list[tuple[int, int, KBSection]] = []
        for i, sec in enumerate(self._sections):
            hay = (sec.heading + "\n" + sec.body).lower()
            hits = sum(1 for t in norm_terms if t in hay)
            if hits > 0:
                scored.append((-hits, i, sec))
        scored.sort()
        return [s[2] for s in scored[:limit]]
