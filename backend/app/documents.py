"""Reference documents (spec PJ-11): a project's PDF, DOCX, TXT or MD files, their text extracted on upload into
passages (technical design section 4) that search_project scores by meaning. A passage says where it is: a page
(PDF) or the heading it is under (DOCX, MD). Passages are whole paragraphs up to PASSAGE_CHARS (the reranker reads
512 tokens of each), a longer paragraph split at its sentences."""

from __future__ import annotations

import io
import zipfile

import pypdfium2 as pdfium
from lxml import etree

PASSAGE_CHARS = 1200
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
KINDS = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md", ".markdown": "md"}


class Unreadable(Exception):
    pass


def kind_of(name: str, raw: bytes) -> str:
    """pdf | docx | txt | md, by the file's content first (its name only tells text from Markdown)."""
    if raw.startswith(b"%PDF"):
        return "pdf"
    if raw.startswith(b"PK"):
        try:
            infos = zipfile.ZipFile(io.BytesIO(raw)).infolist()
        except zipfile.BadZipFile:
            infos = []
        if "word/document.xml" in {i.filename for i in infos}:
            # what it unpacks to, before anything is read (security review M3: a 60 KB file unpacked to 60 MB, read
            # whole into memory): the limits a deck upload has (docengine/files.py)
            from .docengine import files

            unpacked = sum(i.file_size for i in infos)
            if len(infos) > files.MAX_ENTRIES or unpacked > files.MAX_UNCOMPRESSED or unpacked > files.MAX_RATIO * len(raw):
                raise Unreadable("This document unpacks to far more data than a Word document holds.")
            return "docx"
        raise Unreadable("Only PDF, Word (.docx), text and Markdown documents can be added.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Unreadable("Only PDF, Word (.docx), text and Markdown documents can be added.") from None
    # bytes that decode are not yet text: a binary file can (measured: three control bytes were taken as a document)
    odd = sum(1 for c in text if not (c.isprintable() or c in "\n\r\t"))
    if "\x00" in text or odd > max(len(text) * 0.05, 0):
        raise Unreadable("This file is not text: only PDF, Word (.docx), text and Markdown documents can be added.")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return "md" if KINDS.get(ext) == "md" else "txt"


def passages(kind: str, raw: bytes) -> list[dict]:
    """[{where, text}] in reading order."""
    if kind == "pdf":
        sections = _pdf(raw)
    elif kind == "docx":
        sections = _docx(raw)
    else:
        sections = _text(raw.decode("utf-8"), markdown=kind == "md")
    out = []
    for where, paragraphs in sections:
        for text in _pack(paragraphs):
            out.append({"where": where, "text": text})
    return out


def _pdf(raw: bytes) -> list[tuple[str, list[str]]]:
    try:
        doc = pdfium.PdfDocument(raw)
    except pdfium.PdfiumError:
        raise Unreadable("This PDF could not be read (damaged, or protected by a password).") from None
    out = []
    for i, page in enumerate(doc):
        text = page.get_textpage().get_text_range()
        paragraphs = [" ".join(p.split()) for p in text.replace("\r\n", "\n").split("\n\n")]
        paragraphs = [p for p in paragraphs if p]
        if paragraphs:
            out.append((f"p. {i + 1}", paragraphs))
    return out


def _docx(raw: bytes) -> list[tuple[str, list[str]]]:
    # no entities expanded, nothing fetched; a damaged file is said, not a server error (security review M3)
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml")
        body = etree.fromstring(xml, parser).find(f"{W}body")
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError):
        raise Unreadable("This Word document could not be read: it may be damaged.") from None
    out: list[tuple[str, list[str]]] = []
    heading, current = "", []
    for el in body if body is not None else []:
        if el.tag == f"{W}p":
            text = "".join(t.text or "" for t in el.iter(f"{W}t")).strip()
            style = el.find(f"{W}pPr/{W}pStyle")
            sid = (style.get(f"{W}val") or "").lower() if style is not None else ""
            # a heading: Word's style ids, in English and Portuguese installations ("Heading1", "Ttulo1", "Title")
            if text and sid.startswith(("heading", "ttulo", "titulo", "title")):
                if current:
                    out.append((heading, current))
                heading, current = text, []
            elif text:
                current.append(text)
        elif el.tag == f"{W}tbl":
            for row in el.iter(f"{W}tr"):
                cells = ["".join(t.text or "" for t in cell.iter(f"{W}t")).strip() for cell in row.iter(f"{W}tc")]
                if any(cells):
                    current.append(" | ".join(cells))
    if current:
        out.append((heading, current))
    return out


def _text(text: str, markdown: bool) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    heading, current, para = "", [], []

    def close_paragraph():
        if para:
            current.append(" ".join(" ".join(para).split()))
            para.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if markdown and stripped.startswith("#"):
            close_paragraph()
            if current:
                out.append((heading, list(current)))
                current.clear()
            heading = stripped.lstrip("#").strip()
        elif not stripped:
            close_paragraph()
        else:
            para.append(stripped)
    close_paragraph()
    if current:
        out.append((heading, current))
    return out


def _pack(paragraphs: list[str]) -> list[str]:
    """Whole paragraphs into passages of at most PASSAGE_CHARS; a longer paragraph split at its sentences (and a
    sentence longer still, at a space)."""
    pieces = []
    for p in paragraphs:
        if len(p) <= PASSAGE_CHARS:
            pieces.append(p)
            continue
        sentence = ""
        for word in p.split(" "):
            candidate = f"{sentence} {word}".strip()
            if len(candidate) > PASSAGE_CHARS and sentence:
                pieces.append(sentence)
                sentence = word
            else:
                sentence = candidate
            if sentence.endswith((".", "!", "?")) and len(sentence) > PASSAGE_CHARS * 0.6:
                pieces.append(sentence)
                sentence = ""
        if sentence:
            pieces.append(sentence)
    out, current = [], ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > PASSAGE_CHARS:
            out.append(current)
            current = piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        out.append(current)
    return out
