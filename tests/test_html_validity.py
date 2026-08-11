"""Structural validation of the one HTML document in the repository.

The earlier checks counted tags with regexes, which cannot tell
``<p><span></p></span>`` from correctly nested markup. This parses the
document properly and enforces the handful of machine-checkable rules that
actually apply to a single, self-contained, unindexed page.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPORT = Path(__file__).resolve().parent.parent / "docs" / "audit-report.html"

#: Elements with no closing tag.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

#: Googlebot truncates HTML past ~15 MB; browsers slow long before that.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


class StructureChecker(HTMLParser):
    """Verifies tags nest and close correctly, and attributes are sane."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.duplicate_attrs: list[str] = []
        self.elements: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.elements.append(tag)
        names = [name for name, _ in attrs]
        if len(names) != len(set(names)):
            self.duplicate_attrs.append(f"<{tag}> at line {self.getpos()[0]}")
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            self.errors.append(f"</{tag}> closes a void element (line {self.getpos()[0]})")
            return
        if not self.stack:
            self.errors.append(f"</{tag}> with nothing open (line {self.getpos()[0]})")
            return
        open_tag, open_line = self.stack.pop()
        if open_tag != tag:
            self.errors.append(
                f"</{tag}> at line {self.getpos()[0]} closes <{open_tag}> opened at line {open_line}"
            )


@pytest.fixture(scope="module")
def html() -> str:
    return REPORT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(html) -> StructureChecker:
    checker = StructureChecker()
    checker.feed(html)
    checker.close()
    return checker


class TestWellFormed:
    def test_tags_nest_and_close_correctly(self, parsed) -> None:
        assert parsed.errors == []

    def test_nothing_is_left_open(self, parsed) -> None:
        assert parsed.stack == [], f"unclosed: {[t for t, _ in parsed.stack]}"

    def test_no_duplicate_attributes(self, parsed) -> None:
        assert parsed.duplicate_attrs == []

    def test_no_deprecated_presentational_elements(self, parsed) -> None:
        banned = {"font", "center", "marquee", "blink", "big", "strike", "tt", "frame"}
        assert not (set(parsed.elements) & banned)

    def test_the_document_is_html5(self, html) -> None:
        assert html.lstrip().lower().startswith("<!doctype html>")
        # No XHTML leftovers that would conflict with the HTML5 parser.
        assert "xml:lang" not in html
        assert not re.search(r"<(?:meta|br|hr|img|link)[^>]*/>", html)


class TestCrawlableStructure:
    """The subset of the SEO checklist that applies to a single static file
    with no site around it."""

    def test_it_stays_under_document_size_limits(self, html) -> None:
        assert len(html.encode("utf-8")) < MAX_DOCUMENT_BYTES

    def test_it_has_exactly_one_title_and_it_is_not_empty(self, html) -> None:
        titles = re.findall(r"<title>(.*?)</title>", html, re.S)
        assert len(titles) == 1
        assert titles[0].strip()

    def test_it_declares_a_favicon(self, html) -> None:
        assert re.search(r'<link[^>]+rel="icon"', html)

    def test_it_has_a_meta_description(self, html) -> None:
        description = re.search(r'<meta name="description" content="([^"]+)"', html)
        assert description
        assert 50 < len(description.group(1)) < 320

    def test_every_link_is_syntactically_valid(self, html) -> None:
        """No empty, placeholder, or javascript: hrefs."""
        for href in re.findall(r'href="([^"]*)"', html):
            assert href.strip(), "empty href"
            assert not href.lower().startswith("javascript:")
            assert href not in {"#", "undefined", "null"}

    def test_no_insecure_http_references(self, html) -> None:
        """An https document must not pull or link to http resources."""
        insecure = [
            url for url in re.findall(r'(?:href|src)="(http://[^"]+)"', html)
            if not url.startswith("http://www.w3.org/")  # XML namespace, not fetched
        ]
        assert insecure == []

    def test_the_content_is_substantial(self, html) -> None:
        """Thin content is a real signal; this should never be a stub."""
        text = re.sub(r"<[^>]+>", " ", html.split("</style>")[-1])
        assert len(text.split()) > 500
