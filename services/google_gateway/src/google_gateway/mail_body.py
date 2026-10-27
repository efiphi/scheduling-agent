"""Plain text out of a Gmail message payload. No HTML, no attachments (T2).

The agent gets text only. HTML carries scripts, remote images (tracking pixels) and
styling that can hide text from a human reader; as plain text, hidden text is just text,
and everything stays untrusted data either way (invariant 2). Prefer the sender's own
text/plain part; otherwise strip tags from text/html with the standard library's parser.
"""

import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

Decoder = Callable[[str], bytes]


def text_from_payload(payload: dict[str, Any], decode: Decoder) -> str:
    plain = _first_part(payload, "text/plain")
    if plain is not None:
        return _part_text(plain, decode)
    html = _first_part(payload, "text/html")
    if html is not None:
        return html_to_text(_part_text(html, decode))
    return ""


def _first_part(part: dict[str, Any], mime_type: str) -> dict[str, Any] | None:
    # Attachments have a filename; their content is never read.
    if part.get("mimeType") == mime_type and not part.get("filename"):
        return part
    for child in part.get("parts", []):
        found = _first_part(child, mime_type)
        if found is not None:
            return found
    return None


def _part_text(part: dict[str, Any], decode: Decoder) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    return decode(data).decode("utf-8", errors="replace")


class _TextCollector(HTMLParser):
    _SKIP = frozenset({"script", "style", "head", "title"})
    _BREAKS = frozenset({"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAKS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.chunks.append(data)


def html_to_text(html: str) -> str:
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    lines = (" ".join(line.split()) for line in "".join(collector.chunks).splitlines())
    return "\n".join(line for line in lines if line)


# Where a reply's quoted history begins. Gmail, Outlook and Apple Mail, English and Hebrew.
# Bidi marks (U+200E/U+200F) are stripped first: Gmail wraps Hebrew reply headers in them.
_QUOTE_START = re.compile(
    r"^(On .{5,200} wrote:"
    r"|בתאריך .{5,200}(כתב|כתבה|מאת .{3,200}):"
    r"|-{2,}\s*(Original Message|Forwarded message|הודעה מקורית|הודעה שהועברה)\s*-{2,}"
    r"|(From|מאת): .+)$",
    re.I,
)
_BIDI_MARKS = str.maketrans("", "", "\u200e\u200f\u202a\u202b\u202c\u202d\u202e")


def strip_quoted(text: str) -> str:
    """The new part of a reply: everything before the quoted history, minus "> " lines."""
    kept: list[str] = []
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = raw.translate(_BIDI_MARKS).strip()
        # Gmail sometimes breaks "On <date> <name> wrote:" over two lines.
        joined = (
            f"{line} {lines[i + 1].translate(_BIDI_MARKS).strip()}" if i + 1 < len(lines) else line
        )
        if _QUOTE_START.match(line) or (line.startswith("On ") and _QUOTE_START.match(joined)):
            break
        if not line.startswith(">"):
            kept.append(raw)
    return "\n".join(kept).strip()
