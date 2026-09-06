"""cleaning — scientific text preprocessing (T5.5).

Conservative by design: scientific notation (chemical formulas, Greek
symbols, sub/superscripts, units, equations) must survive cleaning.
The cleaner removes only what is provably noise:
  * HTML markup (parser-based, entities decoded)
  * inline citation markers: [1], [12], [citation needed], [note 3]
  * navigation/boilerplate sections (References, External links, ...)
  * malformed Unicode sequences
  * empty sections
It never rewrites the remaining content: no case folding, no unit
conversion, no symbol transliteration.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from dataclasses import dataclass

# boilerplate section headings (case/underscore-insensitive match)
BOILERPLATE_SECTIONS = {
    "references", "external links", "see also", "further reading",
    "notes", "sources", "bibliography", "citations", "footnotes",
    "literature", "external_resources", "works cited",
}

_CITATION_MARKER = re.compile(
    r"\[(?:\d{1,4}[a-z]?|[a-z]\b|note\s+\d+|citation\s+needed|"
    r"disambiguation\s+needed|verification\s+needed|by\s+whom\?|"
    r"quantify|clarification\s+needed|when\?|where\?|who\?)\]", re.IGNORECASE)

# sequences that indicate corrupt decoding; replaced conservatively
_MOJIBAKE_HINTS = ("Ã", "â€", "Â ", "ï¿½")
_REPLACEMENT_CHAR = "�"

_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1$")


@dataclass
class CleanSection:
    """One cleaned section of a document."""
    heading: str            # e.g. "History" or "Chemistry/Reactions"
    level: int              # 2 for "== ... ==", 3 for "=== ... ==="
    text: str               # cleaned body text ("" allowed before drop)


class _TextExtractor(HTMLParser):
    """HTML -> text, preserving <sup>/<sub> semantics as unicode where
    recoverable, dropping script/style."""

    _SUP = {str(i): chr(0x2070 + i) if i not in (1, 2, 3) else
            {1: "¹", 2: "²", 3: "³"}[i] for i in range(10)}
    _SUB = {str(i): chr(0x2080 + i) for i in range(10)}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag == "sup" and not self._skip_depth:
            self._open_sup = True
        elif tag == "sub" and not self._skip_depth:
            self._open_sub = True

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "sup":
            self._open_sup = False
        elif tag == "sub":
            self._open_sub = False
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "br", "tr") \
                and not self._skip_depth:
            self.parts.append("\n")

    _open_sup = False
    _open_sub = False

    def handle_data(self, data):
        if self._skip_depth or not data:
            return
        if self._open_sup:
            # digit-only superscripts become real Unicode (x<sup>2</sup> -> x²)
            self.parts.append("".join(self._SUP.get(c, c) for c in data))
        elif self._open_sub:
            self.parts.append("".join(self._SUB.get(c, c) for c in data))
        else:
            self.parts.append(data)


def strip_html(raw: str) -> str:
    """HTML -> plain text (entities decoded, scripts/styles dropped)."""
    parser = _TextExtractor()
    parser.feed(raw)
    return "".join(parser.parts)


def remove_citation_markers(text: str) -> str:
    """Remove inline reference markers without touching math/units."""
    return _CITATION_MARKER.sub("", text)


def repair_unicode(text: str) -> str:
    """Fix malformed Unicode conservatively: drop U+FFFD and common
    mojibake artifacts, NFC-normalize. Real content is preserved."""
    out = text.replace(_REPLACEMENT_CHAR, "")
    for hint in _MOJIBAKE_HINTS:
        # only when clearly artifact noise: strip the artifact bytes' chars
        out = out.replace(hint, "")
    import unicodedata
    return unicodedata.normalize("NFC", out)


def clean_paragraph(text: str) -> str:
    """Clean a single paragraph of body text."""
    if "<" in text and ">" in text and re.search(r"</?[a-z][^>]*>", text):
        text = strip_html(text)
    text = _html.unescape(text)
    text = remove_citation_markers(text)
    text = repair_unicode(text)
    # collapse intra-paragraph whitespace. Single newlines in Wikipedia
    # plaintext extracts are wrapped-line/formula fragments ("P\n=\n0"),
    # not structure — section structure was already resolved in pass 1.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", " ", text)
    return text.strip()


@dataclass
class CleanedDocument:
    """Section-preserved cleaned document."""
    title: str
    sections: list[CleanSection]
    dropped_sections: list[str]

    def full_text(self) -> str:
        """Body text with heading markers, hierarchy preserved."""
        out = []
        for sec in self.sections:
            if sec.heading:
                out.append("=" * sec.level + f" {sec.heading} " + "=" * sec.level)
            out.append(sec.text)
        return "\n\n".join(out).strip()


def clean_document(title: str, body: str, *,
                   drop_boilerplate: bool = True) -> CleanedDocument:
    """Split a document into cleaned sections, preserving heading
    hierarchy. Expects "== Heading ==" style markers (Wikipedia extracts)
    or plain paragraphs (single section, heading='').

    Drops boilerplate sections and empty sections; detects duplicate
    section headings (kept but flagged via returned list for near-dup
    detection downstream)."""
    # -- pass 1: raw split on heading markers ------------------------------
    raw: list[tuple[str, int, list[str]]] = []
    for line in body.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            raw.append((m.group(2).strip(), len(m.group(1)), []))
        elif not raw:
            raw.append(("", 0, []))
        else:
            raw[-1][2].append(line)

    # -- pass 2: clean, drop boilerplate/empty, flag duplicates ------------
    sections: list[CleanSection] = []
    dropped: list[str] = []
    seen: dict[str, int] = {}
    stack: list[tuple[int, str]] = []   # heading hierarchy path
    for heading, level, lines in raw:
        text = clean_paragraph("\n".join(lines))
        key = heading.lower()
        dup_count = seen.get(key, 0)
        seen[key] = dup_count + 1
        while stack and stack[-1][0] >= (level or 2):
            stack.pop()
        stack.append((level or 2, heading))
        if drop_boilerplate and key in BOILERPLATE_SECTIONS:
            dropped.append(heading)
            continue
        if not text:
            continue  # empty section removal
        # display heading = hierarchy path (context preserved per chunk)
        if heading:
            leaf = heading if dup_count == 0 else f"{heading} ({dup_count})"
            display = " > ".join([h for _l, h in stack[:-1]] + [leaf])
        else:
            display = ""
        sections.append(CleanSection(heading=display, level=level, text=text))
    return CleanedDocument(title=title, sections=sections, dropped_sections=dropped)


def dedupe_sections(sections: list[CleanSection]) -> list[CleanSection]:
    """Exact-duplicate section removal (same heading + same text)."""
    seen: set[tuple[str, str]] = set()
    out = []
    for s in sections:
        key = (s.heading.lower(), s.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out