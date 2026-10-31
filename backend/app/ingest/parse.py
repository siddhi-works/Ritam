"""Turn raw bytes into pages of text with stable character offsets.

`doc_text` = pages joined by PAGE_SEP; each page's `char_start` is its offset in `doc_text`, so
a quote found anywhere maps back to (page_no, char_start, char_end) for highlighting.
"""

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

log = logging.getLogger(__name__)

PAGE_SEP = "\n\n"
DocType = Literal["pdf", "html", "text"]


class ParseError(Exception):
    pass


@dataclass
class Page:
    page_no: int  # 1-based
    text: str
    char_start: int


@dataclass
class ParsedDoc:
    doc_type: DocType
    pages: list[Page]
    title: str | None = None
    html: str | None = None  # kept for date extraction from meta tags
    pdf_dates: dict[str, datetime] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return PAGE_SEP.join(p.text for p in self.pages)


_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})
_SPACES = re.compile(r"[ \t  -​ 　]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Display-safe cleanup that keeps line structure. Not NFKC: that would turn '½' into '1⁄2'
    and change visible text; the quote matcher applies its own heavier normalisation."""
    text = unicodedata.normalize("NFC", text).translate(_LIGATURES)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def sniff(body: bytes, content_type: str = "", filename: str = "") -> DocType:
    head = body[:1024].lstrip()
    is_pdf = b"%PDF-" in body[:1024]  # the spec allows junk bytes before the header
    if is_pdf:
        return "pdf"
    if "pdf" in content_type or filename.lower().endswith(".pdf"):
        raise ParseError("declared as PDF but the file is not a PDF")
    lowered = head[:512].lower()
    if b"<html" in lowered or b"<!doctype html" in lowered or "html" in content_type:
        return "html"
    return "text"


def _pages(texts: list[str]) -> list[Page]:
    pages, offset = [], 0
    for i, t in enumerate(texts, start=1):
        pages.append(Page(page_no=i, text=t, char_start=offset))
        offset += len(t) + len(PAGE_SEP)
    return pages


def parse_pdf(body: bytes, *, max_pages: int = 80) -> ParsedDoc:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("PDF is password-protected")
        n = len(reader.pages)
    except PdfReadError as exc:
        raise ParseError(f"unreadable PDF: {exc}") from exc
    if n > max_pages:
        raise ParseError(f"PDF has {n} pages; the limit is {max_pages}")

    warnings: list[str] = []
    texts: list[str] = []
    empty: list[int] = []
    for i, page in enumerate(reader.pages):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill the document
            warnings.append(f"page {i + 1}: pypdf failed ({type(exc).__name__})")
            raw = ""
        if not raw.strip():
            empty.append(i)
        texts.append(clean_text(raw))

    if empty:  # pdfplumber copes better with some table-heavy layouts
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(body)) as pdf:
                for i in empty:
                    texts[i] = clean_text(pdf.pages[i].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pdfplumber fallback failed ({type(exc).__name__})")
        still_empty = [i + 1 for i, t in enumerate(texts) if not t]
        if still_empty:
            warnings.append(
                f"no text layer on pages {still_empty} (scanned image?); those pages were skipped"
            )
    if not any(texts):
        raise ParseError("PDF has no extractable text (scanned image). OCR is not supported yet.")

    meta = reader.metadata
    dates: dict[str, datetime] = {}
    if meta is not None:
        for key, attr in (("created", "creation_date"), ("modified", "modification_date")):
            try:
                value = getattr(meta, attr)
            except Exception:  # noqa: BLE001 - malformed metadata dates are common
                value = None
            if isinstance(value, datetime):
                dates[key] = value
    title = str(meta.title).strip() if meta is not None and meta.title else None
    return ParsedDoc("pdf", _pages(texts), title=title, pdf_dates=dates, warnings=warnings)


def parse_html(body: bytes, url: str | None = None) -> ParsedDoc:
    import trafilatura

    html = body.decode("utf-8", "replace")
    extracted = trafilatura.extract(
        html,
        url=url,
        include_tables=True,
        include_comments=False,
        favor_recall=True,
        output_format="txt",
    )
    warnings: list[str] = []
    if not extracted or len(extracted) < 200:
        # Fallback: visible text of the whole page (bank pages often hide terms in accordions).
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html)
        for bad in tree.xpath("//script|//style|//noscript|//svg"):
            bad.drop_tree()
        extracted = tree.text_content()
        warnings.append("main-content extraction was thin; used full visible text")
    text = clean_text(extracted)
    if not text:
        raise ParseError("page has no readable text")
    # Prefer the page's own <title> (bank pages put the product name there); trafilatura's
    # metadata often picks the first <h1>, e.g. "Fees and charges".
    title = _html_title(html)
    if title is None:
        meta = trafilatura.extract_metadata(html)
        title = meta.title if meta is not None and meta.title else None
    return ParsedDoc("html", _pages([text]), title=title, html=html, warnings=warnings)


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _html_title(html: str) -> str | None:
    import html as html_lib

    m = _TITLE.search(html[:200_000])
    title = clean_text(html_lib.unescape(m.group(1))) if m else ""
    return title[:500] or None


def parse_text(body: bytes | str) -> ParsedDoc:
    text = body if isinstance(body, str) else body.decode("utf-8", "replace")
    text = clean_text(text)
    if not text:
        raise ParseError("text is empty")
    # Remotely rendered pages (Jina Reader) arrive as Markdown starting with "# <page title>".
    first = text.split("\n", 1)[0]
    title = first[2:].strip()[:500] if first.startswith("# ") else None
    return ParsedDoc("text", _pages([text]), title=title or None)


def parse(
    body: bytes, *, content_type: str = "", filename: str = "", url: str | None = None
) -> ParsedDoc:
    kind = sniff(body, content_type, filename)
    if kind == "pdf":
        return parse_pdf(body)
    if kind == "html":
        return parse_html(body, url)
    return parse_text(body)
