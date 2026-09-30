"""Build the searchable index over Meridian's policy documents.

Run once, standalone, before using v5Agent:

    python v5Agent/build_index.py

It extracts each PDF page by page, chunks on section headings, marks
superseded content, embeds every chunk, and writes one readable JSON file.
No vector database: participants must be able to open index.json and see
exactly what got indexed.

The documents hold what the database structurally cannot -- the rules, the
specifications, the contract terms and the memory of past incidents. The
database says what happened; these say what should have happened.

Requires: pypdf, pdfplumber (table fallback), pypdfium2 (OCR fallback),
numpy, google-genai.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import dotenv

    dotenv.load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # optional -- the environment may already be populated
    pass

from pypdf import PdfReader

# --------------------------------------------------------------------------
# paths and document registry
# --------------------------------------------------------------------------

BUILD_DIR = Path(__file__).resolve().parent
DAY5 = BUILD_DIR.parent

# The source PDFs. Note the directory name is spelled "EnterpriseKnoweledge"
# on disk; that is deliberate, not a typo here.
PDF_DIR = DAY5 / "data" / "EnterpriseKnoweledge"
INDEX_PATH = PDF_DIR / "index.json"

EMBED_MODEL = "gemini-embedding-001"
EMBED_BATCH = 16

# OCR fallback for pages with no text layer. "Microsoft: Print To PDF" draws
# every glyph as a vector outline, so pypdf returns nothing; those pages are
# rendered to an image and transcribed by a multimodal model instead. Each
# transcription is cached as a readable .md file so reruns are free and the
# OCR output can be inspected (and hand-corrected) like the index itself.
OCR_MODEL = "gemini-2.5-flash"
OCR_DIR = PDF_DIR / ".ocr"
OCR_SCALE = 2.0  # render at ~144 dpi; enough for small table text
OCR_PROMPT = """Transcribe this document page to plain text, exactly as written.
Rules:
- Keep every section heading on its own line with its number, e.g. "7.3 Company-attributable root cause uplift" or "Appendix B Superseded remedy bands".
- Render every table as a markdown table with its header row.
- Keep document codes (e.g. MR-CC-POL-004), numbers, currency and dates verbatim.
- Do not summarise, translate, add commentary or wrap the output in code fences."""

# Words per chunk. MIN_WORDS is advisory -- a section shorter than it stays
# its own chunk rather than being merged into a neighbour (see chunk_document).
# Over-long sections are split at line boundaries, never mid-table.
MIN_WORDS = 400
MAX_WORDS = 900

# Fallback mapping when a document's own reference code cannot be read out of
# its text. Keyed on the leading number in the filename, because the files are
# named "01 customer care remedy policy.pdf" rather than by document code.
FALLBACK_DOC_ID = {
    "01": "MR-CC-POL-004",
    "02": "MR-QA-STD-002",
    "03": "MR-PROC-HB-003",
    "04": "MR-OPS-PM-ARCHIVE",
}

# Everything the retrieval layer needs to cite a passage precisely. Kept here
# rather than read from ontology.yaml so build_index.py runs standalone.
DOC_REGISTRY: dict[str, dict[str, str]] = {
    "MR-CC-POL-004": {
        "doc_title": "Customer Care Remedy & Goodwill Policy",
        "doc_version": "4.0",
        "effective_date": "2025-11-01",
        "owner": "Director of Customer Experience",
    },
    "MR-QA-STD-002": {
        "doc_title": "Green Coffee Quality Standards & Roasting QA Manual",
        "doc_version": "2.3",
        "effective_date": "2025-09-01",
        "owner": "Head of Quality",
    },
    "MR-PROC-HB-003": {
        "doc_title": "Supplier Agreements & Procurement Handbook",
        "doc_version": "3.0",
        "effective_date": "2025-07-01",
        "owner": "Head of Procurement",
    },
    "MR-OPS-PM-ARCHIVE": {
        "doc_title": "Incident Post-Mortem Archive",
        "doc_version": "",
        "effective_date": "",
        "owner": "Operations",
    },
}

DOC_CODE_RE = re.compile(r"\bMR-[A-Z]{2,4}-[A-Z0-9-]{2,}\b")

# A heading looks like "7.3 Company-attributable root cause uplift",
# "Appendix B -- Superseded remedy bands" or, in the post-mortem archive,
# "INC-2025-04 — Decaf mislabelling". Section ids are how these documents
# cross-reference each other, so they are what we chunk on. The title must
# start with a capital: a wrapped line such as "90 parcels, 71 customers."
# is body text, not section 90.
HEADING_RE = re.compile(
    r"^\s*(?:§\s*)?("
    r"\d+(?:\.\d+)*"            # 7 or 7.3 or 7.3.1
    r"|Appendix\s+[A-Z]"        # Appendix B
    r"|INC-\d{4}-\d+"           # INC-2025-04
    r")[.)]?\s+(?:[—–-]+\s+)?([A-Z]\S*.*?)\s*$"
)

# Any one of these in a chunk means the content describes a rule that is no
# longer in force. Such chunks stay in the index but are excluded from
# retrieval by default: deleting them loses the lesson, returning them by
# default produces confidently wrong caps.
SUPERSEDED_MARKERS = (
    "superseded",
    "no longer in force",
    "retained for audit",
    "previous version",
    "replaced by",
)
REVISION_HISTORY_RE = re.compile(
    r"revision\s+history|version\s+history|change\s+log", re.I
)


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


class ExtractionError(RuntimeError):
    """Raised when a PDF yields no usable text."""


@dataclass
class Page:
    number: int
    text: str


def _tables_as_markdown(pdf_path: Path, page_number: int) -> str:
    """Serialise a page's tables as markdown, for pages pypdf flattens badly.

    A cap table that extracts as a column of bare numbers is worthless and
    would silently produce wrong remedy amounts, so tables are pulled out
    separately and laid out explicitly.
    """
    try:
        import pdfplumber
    except ImportError:
        return ""

    blocks: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            page = pdf.pages[page_number - 1]
            for table in page.extract_tables() or []:
                rows = [
                    [(cell or "").replace("\n", " ").strip() for cell in row]
                    for row in table
                    if any((cell or "").strip() for cell in row)
                ]
                if len(rows) < 2:
                    continue
                header, *body = rows
                width = max(len(r) for r in rows)
                header += [""] * (width - len(header))
                lines = [
                    "| " + " | ".join(header) + " |",
                    "|" + "---|" * width,
                ]
                for row in body:
                    row = row + [""] * (width - len(row))
                    lines.append("| " + " | ".join(row) + " |")
                blocks.append("\n".join(lines))
    except Exception as exc:  # pdfplumber is a best-effort fallback
        print(f"    (pdfplumber failed on page {page_number}: {exc})")
    return "\n\n".join(blocks)


def _ocr_page(pdf_path: Path, page_number: int) -> str:
    """Transcribe one page image with Gemini, caching the result on disk."""
    cache = OCR_DIR / f"{pdf_path.stem}.p{page_number:02d}.md"
    if cache.exists():
        return cache.read_text()

    import io

    import pypdfium2
    from google.genai import types

    pdf = pypdfium2.PdfDocument(str(pdf_path))
    try:
        image = pdf[page_number - 1].render(scale=OCR_SCALE).to_pil()
    finally:
        pdf.close()
    png = io.BytesIO()
    image.save(png, format="PNG")

    client = _client()  # keep a reference: a temporary client closes mid-request
    response = client.models.generate_content(
        model=OCR_MODEL,
        contents=[
            types.Part.from_bytes(data=png.getvalue(), mime_type="image/png"),
            OCR_PROMPT,
        ],
        config=types.GenerateContentConfig(temperature=0),
    )
    text = (response.text or "").strip()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text)
    return text


def extract_pages(pdf_path: Path, ocr: bool = True) -> list[Page]:
    """Extract text per page, keeping the page number on everything.

    Pages with no text layer fall back to OCR (see _ocr_page) when ``ocr``
    is true.

    Raises:
        ExtractionError: if the PDF still yields no text at all. These files
            have been seen with every glyph drawn as vector outlines, which
            yields zero characters rather than mangled ones -- indexing that
            silently would make every later retrieval return nothing.
    """
    reader = PdfReader(str(pdf_path))
    pages: list[Page] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text and ocr:
            print(f"    page {i}: no text layer, OCR via {OCR_MODEL}", flush=True)
            pages.append(Page(number=i, text=_ocr_page(pdf_path, i)))
            continue
        tables = _tables_as_markdown(pdf_path, i)
        if tables:
            text = f"{text}\n\n{tables}" if text else tables
        pages.append(Page(number=i, text=text))

    if not any(p.text.strip() for p in pages):
        raise ExtractionError(
            f"{pdf_path.name}: no extractable text on any of {len(pages)} pages.\n"
            "        The PDF has no text layer -- its glyphs are drawn as vector\n"
            "        outlines or scanned images, so pypdf and pdfplumber both\n"
            "        return nothing. Re-export the document with a real text\n"
            "        layer (print-to-PDF from the source, not an image export),\n"
            "        or OCR it (drop --no-ocr). Indexing it as-is would produce empty\n"
            "        chunks and make every retrieval silently return nothing."
        )
    return pages


def detect_doc_id(pages: Iterable[Page], filename: str) -> str:
    """Find the document's own reference code, falling back to the filename."""
    for page in list(pages)[:2]:
        for code in DOC_CODE_RE.findall(page.text):
            if code in DOC_REGISTRY:
                return code
    leading = re.match(r"\s*(\d{2})", filename)
    if leading and leading.group(1) in FALLBACK_DOC_ID:
        return FALLBACK_DOC_ID[leading.group(1)]
    raise ExtractionError(
        f"{filename}: could not determine a document id. Expected a code like "
        f"MR-CC-POL-004 in the text, or a leading number matching "
        f"{sorted(FALLBACK_DOC_ID)}."
    )


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------


@dataclass
class Chunk:
    text: str
    doc_id: str
    doc_title: str
    doc_version: str
    effective_date: str
    section: str
    section_title: str
    page: int
    superseded: bool
    owner: str
    embedding: list[float] = field(default_factory=list)


def _looks_superseded(text: str, section: str, section_title: str) -> bool:
    """Whether a chunk describes a rule that is no longer in force."""
    haystack = f"{section_title}\n{text}".lower()
    if any(marker in haystack for marker in SUPERSEDED_MARKERS):
        return True
    if REVISION_HISTORY_RE.search(f"{section_title} {text}"):
        return True
    return False


def _split_long(body: list[tuple[str, str, int]]) -> list[list[tuple[str, str, int]]]:
    """Split an over-long section into pieces at line boundaries.

    Never splits inside a markdown table: a table broken across two chunks
    loses its header and becomes a column of bare numbers.
    """
    groups: list[list[tuple[str, str, int]]] = [[]]
    words = 0
    in_table = False
    for line, kind, page in body:
        is_table_row = line.lstrip().startswith("|")
        if is_table_row and not in_table:
            in_table = True
        elif in_table and not is_table_row and line.strip():
            in_table = False

        line_words = len(line.split())
        if words + line_words > MAX_WORDS and groups[-1] and not in_table:
            groups.append([])
            words = 0
        groups[-1].append((line, kind, page))
        words += line_words
    return [g for g in groups if g]


def chunk_document(pages: list[Page], doc_id: str) -> list[Chunk]:
    """Chunk on section headings rather than a fixed character count."""
    meta = DOC_REGISTRY[doc_id]

    # Flatten to (line, page) so a chunk can report the page it started on.
    lines: list[tuple[str, int]] = []
    for page in pages:
        for line in page.text.splitlines():
            lines.append((line, page.number))

    # Group lines under the most recent heading.
    sections: list[dict[str, Any]] = []
    current = {"section": "", "section_title": "Front matter", "body": []}
    for line, page_number in lines:
        match = HEADING_RE.match(line)
        # A heading line is short; a sentence that happens to start with a
        # number is not a heading.
        if match and len(line.split()) <= 12:
            if current["body"]:
                sections.append(current)
            current = {
                "section": match.group(1).strip(),
                "section_title": match.group(2).strip(),
                "body": [],
            }
        else:
            current["body"].append((line, "text", page_number))
    if current["body"]:
        sections.append(current)

    # Sections are NEVER merged across a heading boundary. Merging was tried
    # and rejected: it destroyed the section id (which is how these documents
    # address each other) and, worse, let Appendix B's superseded flag leak
    # onto the live section it was merged with -- which would have hidden the
    # 7.3 uplift rule from every default search. A short section is better as
    # a short, correctly-addressed chunk.
    #
    # The one exception is front matter before the first heading, which has no
    # id of its own and belongs with the document's opening section.
    merged: list[dict[str, Any]] = []
    for section in sections:
        is_front = not section["section"] and section["section_title"] == "Front matter"
        if is_front and len(sections) > 1:
            follower = sections[sections.index(section) + 1] if sections.index(section) + 1 < len(sections) else None
            if follower is not None:
                follower["body"] = section["body"] + follower["body"]
                continue
        merged.append(section)

    chunks: list[Chunk] = []
    for section in merged:
        for group in _split_long(section["body"]):
            text = "\n".join(l for l, _, _ in group).strip()
            if not text:
                continue
            page = group[0][2]
            title = section["section_title"]
            heading = f"{section['section']} {section['section_title']}".strip()
            chunks.append(
                Chunk(
                    # Prefix the heading so the section id is searchable in the
                    # chunk text itself -- people type "§7.3".
                    text=f"[{doc_id} §{section['section']}] {heading}\n\n{text}"
                    if section["section"]
                    else f"[{doc_id}] {heading}\n\n{text}",
                    doc_id=doc_id,
                    doc_title=meta["doc_title"],
                    doc_version=meta["doc_version"],
                    effective_date=meta["effective_date"],
                    section=section["section"],
                    section_title=title,
                    page=page,
                    superseded=_looks_superseded(text, section["section"], title),
                    owner=meta["owner"],
                )
            )
    return chunks


# --------------------------------------------------------------------------
# embedding
# --------------------------------------------------------------------------


def _client():
    """A google-genai client, via Vertex or an API key, whichever is set."""
    from google import genai

    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in ("1", "TRUE"):
        return genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1",
        )
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "Set GOOGLE_API_KEY, or GOOGLE_GENAI_USE_VERTEXAI=TRUE with "
            "GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION."
        )
    return genai.Client(api_key=key)


def embed_chunks(chunks: list[Chunk]) -> None:
    """Embed every chunk in batches, writing the vector back onto the chunk."""
    client = _client()
    done = 0
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        response = client.models.embed_content(
            model=EMBED_MODEL,
            contents=[c.text for c in batch],
        )
        for chunk, embedding in zip(batch, response.embeddings):
            chunk.embedding = list(embedding.values)
        done += len(batch)
        print(f"    embedded {done}/{len(chunks)}", end="\r", flush=True)
    print(f"    embedded {done}/{len(chunks)}    ")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build(pdf_dir: Path = PDF_DIR, index_path: Path = INDEX_PATH,
          embed: bool = True, ocr: bool = True) -> list[Chunk]:
    """Extract, chunk, embed and write the index. Returns the chunks."""
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {pdf_dir}")

    all_chunks: list[Chunk] = []
    per_doc: Counter = Counter()
    superseded_per_doc: Counter = Counter()

    for pdf in pdfs:
        print(f"  {pdf.name}")
        pages = extract_pages(pdf, ocr=ocr)
        doc_id = detect_doc_id(pages, pdf.name)
        chunks = chunk_document(pages, doc_id)
        print(f"    {len(pages)} pages -> {len(chunks)} chunks  [{doc_id}]")
        per_doc[doc_id] = len(chunks)
        superseded_per_doc[doc_id] = sum(1 for c in chunks if c.superseded)
        all_chunks.extend(chunks)

    if embed:
        print("\n  embedding...")
        embed_chunks(all_chunks)

    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "embed_model": EMBED_MODEL if embed else None,
        "documents": DOC_REGISTRY,
        "chunks": [asdict(c) for c in all_chunks],
    }
    index_path.write_text(json.dumps(payload, indent=2))

    total_words = sum(len(c.text.split()) for c in all_chunks)
    print("\n" + "=" * 62)
    print(f"  {'document':<22} {'chunks':>7} {'superseded':>11}")
    for doc_id in per_doc:
        print(f"  {doc_id:<22} {per_doc[doc_id]:>7} {superseded_per_doc[doc_id]:>11}")
    print("  " + "-" * 44)
    print(f"  {'TOTAL':<22} {sum(per_doc.values()):>7} {sum(superseded_per_doc.values()):>11}")
    print(f"\n  ~{total_words:,} words  (~{int(total_words / 0.75):,} tokens)")
    print(f"  written to {index_path}")
    print("=" * 62)
    return all_chunks


if __name__ == "__main__":
    print(f"Building index from {PDF_DIR}\n")
    try:
        build(embed="--no-embed" not in sys.argv, ocr="--no-ocr" not in sys.argv)
    except ExtractionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(2)
