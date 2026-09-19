"""Document loading and chunking.

Chunking is where most RAG systems are won or lost, and it gets less attention
than the vector store choice — which matters far less.

Strategy here: split on Markdown H2 boundaries, because these policy documents
are written as self-contained numbered clauses and a clause is the natural unit
of retrieval. Long clauses are then split on paragraph boundaries with overlap.

Every chunk carries its document title and section heading into the embedded
text. That is deliberate: a clause that reads "the cap rises to 15 percent" is
meaningless on its own, and prefixing it with "Goodwill Credit and Escalation
Matrix > Goodwill ceilings" makes it both retrievable and citable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import CHUNK_OVERLAP_CHARS, MAX_CHUNK_CHARS

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
H1 = re.compile(r"^#\s+(.*)$", re.MULTILINE)
H2_SPLIT = re.compile(r"^##\s+", re.MULTILINE)


@dataclass
class Chunk:
    """One retrievable unit, plus everything needed to cite it."""

    chunk_id: str
    text: str                       # what gets embedded and shown to the model
    body: str                       # the clause without the context prefix
    doc_id: str
    doc_title: str
    section: str
    source_file: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_chroma_metadata(self) -> dict[str, str]:
        """Chroma metadata values must be str, int, float or bool — not lists."""
        return {
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "section": self.section,
            "source_file": self.source_file,
            **{k: str(v) for k, v in self.metadata.items()},
        }


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, raw[match.end():]


def _split_long_section(text: str) -> list[str]:
    """Split an oversized section on paragraph boundaries, with overlap.

    Overlap exists so that a sentence straddling a split is still fully present
    in at least one chunk. Without it you get chunks that retrieve well and then
    answer half a question.
    """
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    parts: list[str] = []
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > MAX_CHUNK_CHARS:
            parts.append(current)
            tail = current[-CHUNK_OVERLAP_CHARS:]
            # Resume from a sentence boundary inside the overlap where possible,
            # so the next chunk does not open mid-clause.
            boundary = tail.find(". ")
            current = (tail[boundary + 2:] if boundary != -1 else tail) + "\n\n" + para
        else:
            current = f"{current}\n\n{para}".strip()

    if current:
        parts.append(current)
    return parts


def load_and_chunk(kb_dir: Path) -> list[Chunk]:
    """Load every Markdown file in kb_dir and return heading-aware chunks."""
    chunks: list[Chunk] = []

    for path in sorted(kb_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)

        doc_id = meta.get("doc_id", path.stem.upper())
        h1_match = H1.search(body)
        doc_title = meta.get("title") or (h1_match.group(1) if h1_match else path.stem)

        # Everything before the first H2 is preamble; the sections follow.
        sections = H2_SPLIT.split(body)[1:]

        for section_index, section in enumerate(sections, start=1):
            heading, _, section_body = section.partition("\n")
            heading = heading.strip()
            section_body = section_body.strip()
            if not section_body:
                continue

            for part_index, part in enumerate(_split_long_section(section_body), start=1):
                chunk_id = f"{doc_id}#S{section_index:02d}.{part_index}"
                # The context prefix is what makes a clause self-describing.
                contextual = f"{doc_title} > {heading}\n\n{part}"
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        text=contextual,
                        body=part,
                        doc_id=doc_id,
                        doc_title=doc_title,
                        section=heading,
                        source_file=path.name,
                        metadata={
                            "owner": meta.get("owner", ""),
                            "version": meta.get("version", ""),
                            "effective_from": meta.get("effective_from", ""),
                        },
                    )
                )

    return chunks


def tokenize(text: str) -> list[str]:
    """Tokeniser for BM25.

    Lowercase, keep alphanumerics and intra-word hyphens so that SKU codes and
    document IDs survive as single tokens. This matters more than it looks:
    exact-identifier matching is the main thing BM25 contributes to the hybrid,
    and a tokeniser that shreds `AUR-DIFF-CER-01` throws that advantage away.
    """
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
