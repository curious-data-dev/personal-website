"""Unit tests for markdown rendering: _make_anchor and render_markdown."""

import pytest
from app.web.routes import (
    _make_anchor,
    render_markdown,
    extract_toc,
    extract_citations,
    _resolve_source_titles,
    TocEntry,
    SourceEntry,
)


# ---------------------------------------------------------------------------
# _make_anchor
# ---------------------------------------------------------------------------

class TestMakeAnchor:
    """URL-safe anchor ID generation from heading text."""

    def test_plain_text(self):
        """Plain text becomes lowercase hyphenated anchor."""
        assert _make_anchor("Hello World") == "hello-world"

    def test_bold_text_stripped(self):
        """**text** tokens are stripped before building anchor."""
        assert _make_anchor("**Hello** World") == "hello-world"

    def test_italic_text_stripped(self):
        """*text* tokens are stripped before building anchor."""
        assert _make_anchor("*Hello* World") == "hello-world"

    def test_link_stripped(self):
        """[text](url) links are reduced to just the link text."""
        assert _make_anchor("[Hello](url) World") == "hello-world"

    def test_mixed_inline_tokens(self):
        """Multiple inline markdown tokens are all stripped."""
        assert _make_anchor("**Bold** and *italic* text") == "bold-and-italic-text"

    def test_empty_string(self):
        """Empty string should produce an empty anchor."""
        assert _make_anchor("") == ""

    def test_special_chars_become_hyphens(self):
        """Non-alphanumeric characters are replaced with hyphens."""
        assert _make_anchor("What is happening? ") == "what-is-happening"

    def test_multiple_spaces_and_hyphens(self):
        """Multiple spaces/punctuation collapse into a single hyphen."""
        assert _make_anchor("foo   bar---baz") == "foo-bar-baz"

    def test_leading_trailing_special(self):
        """Leading and trailing hyphens from special chars are stripped."""
        assert _make_anchor("  !!hello!!  ") == "hello"

    def test_double_underscore_bold(self):
        """__text__ tokens are stripped before building anchor."""
        assert _make_anchor("__Bold__ heading") == "bold-heading"


# ---------------------------------------------------------------------------
# render_markdown heading IDs
# ---------------------------------------------------------------------------

class TestRenderMarkdownHeadings:
    """Heading output includes id attributes based on _make_anchor."""

    def test_h2_from_double_hash(self):
        """## headings produce <h2> with an id attribute."""
        html = render_markdown("## Hello World")
        assert '<h2 id="hello-world">' in html
        assert 'Hello World</h2>' in html

    def test_h2_from_single_hash(self):
        """# headings also produce <h2> with an id attribute."""
        html = render_markdown("# Hello World")
        assert '<h2 id="hello-world">' in html
        assert 'Hello World</h2>' in html

    def test_h3_from_triple_hash(self):
        """### headings produce <h3> with an id attribute."""
        html = render_markdown("### Hello World")
        assert '<h3 id="hello-world">' in html
        assert 'Hello World</h3>' in html

    def test_heading_with_bold_has_clean_id(self):
        """Bold markdown in heading is stripped from id but rendered in content."""
        html = render_markdown("## **Bold** heading")
        assert '<h2 id="bold-heading">' in html
        assert '<strong>Bold</strong> heading</h2>' in html

    def test_heading_with_link_has_clean_id(self):
        """Link markdown in heading is stripped from id but rendered in content."""
        html = render_markdown("## [Click](https://example.com) here")
        assert '<h2 id="click-here">' in html
        assert '<a href="https://example.com"' in html
        assert 'Click</a> here</h2>' in html

    def test_heading_with_mixed_formatting(self):
        """Mixed bold + italic + link in heading — id is clean, content formatted."""
        html = render_markdown("## **Hello** and *world* with [link](url)")
        assert '<h2 id="hello-and-world-with-link">' in html
        assert '<strong>Hello</strong>' in html
        assert '<em>' not in html  # *italic* is not implemented in _render_inline
        assert '<a href="url"' in html

    def test_multi_word_heading(self):
        """Multi-word heading produces a hyphenated id."""
        html = render_markdown("## My heading with spaces")
        assert 'id="my-heading-with-spaces"' in html


# ---------------------------------------------------------------------------
# render_markdown non-heading content (regression guards)
# ---------------------------------------------------------------------------

class TestRenderMarkdownNonHeading:
    """Paragraphs and bullet lists must not be affected by heading-id changes."""

    def test_plain_paragraph(self):
        """Plain text should render as <p> without an id."""
        html = render_markdown("Just a paragraph of text.")
        assert "<p>" in html
        assert "Just a paragraph of text." in html
        assert 'id=' not in html

    def test_bullet_list(self):
        """Bullet lists should render as <ul> without ids."""
        html = render_markdown("- item one\n- item two\n- item three")
        assert "<ul>" in html
        assert "<li>" in html
        assert 'id=' not in html

    def test_asterisk_bullet_list(self):
        """Asterisk-prefixed bullet lists should render correctly."""
        html = render_markdown("* item a\n* item b")
        assert "<ul>" in html
        assert "<li>item a</li>" in html
        assert "<li>item b</li>" in html
        assert 'id=' not in html

    def test_empty_input(self):
        """Empty or whitespace-only input produces empty string."""
        assert render_markdown("") == ""
        assert render_markdown("   ") == ""

    def test_multiple_paragraphs(self):
        """Multiple paragraphs should each be wrapped in <p> tags."""
        html = render_markdown("First paragraph.\n\nSecond paragraph.")
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html
        assert 'id=' not in html

    def test_heading_and_paragraph_mixed(self):
        """A heading followed by a paragraph; only the heading gets an id."""
        html = render_markdown("## A heading\n\nA paragraph follows.")
        assert '<h2 id="a-heading">' in html
        assert "<p>A paragraph follows.</p>" in html

    def test_heading_with_trailing_bullets(self):
        """Heading paragraph with trailing bullet lines renders heading + list."""
        html = render_markdown("## Heading\n- item 1\n- item 2")
        assert '<h2 id="heading">' in html
        assert "<ul>" in html
        assert "<li>item 1</li>" in html
        assert "<li>item 2</li>" in html


# ---------------------------------------------------------------------------
# extract_toc
# ---------------------------------------------------------------------------

class TestExtractToc:
    """TOC extraction from markdown heading lines."""

    def test_empty_input(self):
        """Empty input returns an empty list."""
        assert extract_toc("") == []

    def test_none_text_safe(self):
        """Falsy input (None, empty) returns empty list."""
        assert extract_toc(None) == []

    def test_only_h2_headings(self):
        """## headings produce TocEntry with level=2."""
        entries = extract_toc("## Introduction\n## Conclusion")
        assert len(entries) == 2
        assert all(e.level == 2 for e in entries)
        assert entries[0].text == "Introduction"
        assert entries[1].text == "Conclusion"

    def test_only_h3_headings(self):
        """### headings produce TocEntry with level=3."""
        entries = extract_toc("### Details\n### More Details")
        assert len(entries) == 2
        assert all(e.level == 3 for e in entries)
        assert entries[0].text == "Details"

    def test_mixed_levels(self):
        """Mixed ## and ### headings return entries in order."""
        entries = extract_toc("## Overview\n### Detail A\n### Detail B\n## Summary")
        assert len(entries) == 4
        assert [e.level for e in entries] == [2, 3, 3, 2]
        assert [e.text for e in entries] == ["Overview", "Detail A", "Detail B", "Summary"]

    def test_no_headings(self):
        """Text with no markdown headings returns empty list."""
        entries = extract_toc("Just a plain paragraph.\nNo headings here.")
        assert entries == []

    def test_bold_text_in_heading(self):
        """**bold** in heading: anchor strips tokens, text preserves them."""
        entries = extract_toc("## **Bold** heading")
        assert len(entries) == 1
        assert entries[0].text == "**Bold** heading"
        assert entries[0].anchor == _make_anchor("**Bold** heading")
        assert entries[0].anchor == "bold-heading"

    def test_link_in_heading(self):
        """[text](url) in heading: anchor strips markdown, text preserved."""
        entries = extract_toc("## Click [here](https://example.com) now")
        assert len(entries) == 1
        assert entries[0].text == "Click [here](https://example.com) now"
        assert entries[0].anchor == _make_anchor("Click [here](https://example.com) now")
        assert entries[0].anchor == "click-here-now"

    def test_mixed_inline_in_heading(self):
        """Mixed **bold** and [link](url): anchors use _make_anchor for clean ID."""
        entries = extract_toc("## **Start** with [a link](http://x.com) here")
        assert len(entries) == 1
        assert entries[0].text == "**Start** with [a link](http://x.com) here"
        assert entries[0].anchor == _make_anchor(entries[0].text)
        assert entries[0].anchor == "start-with-a-link-here"

    def test_heading_with_trailing_whitespace(self):
        """Heading text is stripped of leading/trailing whitespace."""
        entries = extract_toc("##   padded heading   ")
        assert len(entries) == 1
        assert entries[0].text == "padded heading"
        assert entries[0].anchor == "padded-heading"

    def test_h1_not_extracted(self):
        """Single # h1 headings are NOT extracted (only ## and ###)."""
        entries = extract_toc("# Main Title")
        assert entries == []

    def test_h4_not_extracted(self):
        """#### h4 headings are NOT extracted."""
        entries = extract_toc("#### Sub sub heading")
        assert entries == []

    def test_ignores_non_heading_hashes(self):
        """Hashes in the middle of a line (not at start) are ignored."""
        entries = extract_toc("Not a ## heading here")
        assert entries == []

    def test_heading_followed_by_content(self):
        """Headings followed by paragraph text are still extracted."""
        text = "## The Topic\n\nSome paragraph content.\n\n### Subtopic\nMore text."
        entries = extract_toc(text)
        assert len(entries) == 2
        assert entries[0].text == "The Topic"
        assert entries[1].text == "Subtopic"


# ---------------------------------------------------------------------------
# extract_citations
# ---------------------------------------------------------------------------

class TestExtractCitations:
    """Citation extraction from [[N]](url) links in digest text."""

    def test_empty_input(self):
        """Empty input returns an empty list."""
        assert extract_citations("") == []

    def test_none_text_safe(self):
        """Falsy input (None) returns empty list."""
        assert extract_citations(None) == []

    def test_single_citation(self):
        """Single [[N]](url) extracted correctly."""
        entries = extract_citations("See [[1]](https://example.com) for details.")
        assert len(entries) == 1
        assert entries[0].number == 1
        assert entries[0].url == "https://example.com"
        assert entries[0].title == ""

    def test_multiple_citations(self):
        """Multiple citations are all extracted."""
        text = "[[1]](https://a.com) and [[2]](https://b.com) and [[3]](https://c.com)"
        entries = extract_citations(text)
        assert len(entries) == 3
        assert [e.number for e in entries] == [1, 2, 3]
        assert [e.url for e in entries] == ["https://a.com", "https://b.com", "https://c.com"]

    def test_deduplication(self):
        """Same citation number twice returns one entry."""
        text = "First [[1]](https://a.com) and again [[1]](https://a.com)"
        entries = extract_citations(text)
        assert len(entries) == 1
        assert entries[0].number == 1

    def test_sort_order(self):
        """Unsorted input is returned sorted by number."""
        text = "[[3]](https://c.com) [[1]](https://a.com) [[2]](https://b.com)"
        entries = extract_citations(text)
        assert [e.number for e in entries] == [1, 2, 3]

    def test_no_citations(self):
        """Text with no [[N]](url) patterns returns empty list."""
        entries = extract_citations("Just plain text [link](url) with regular links.")
        assert entries == []

    def test_bracket_links_not_matched(self):
        """Regular [text](url) links are not treated as citations."""
        entries = extract_citations("See [Wikipedia](https://en.wikipedia.org) for more.")
        assert entries == []

    def test_citation_with_complex_url(self):
        """Citations with URLs containing query strings and fragments."""
        text = "Source [[1]](https://example.com/path?q=1&b=2#frag)"
        entries = extract_citations(text)
        assert len(entries) == 1
        assert entries[0].url == "https://example.com/path?q=1&b=2#frag"

    def test_dedup_keeps_first_url(self):
        """When same number appears with different URLs, first encountered is kept."""
        text = "[[1]](https://first.com) [[1]](https://second.com)"
        entries = extract_citations(text)
        assert len(entries) == 1
        assert entries[0].url == "https://first.com"


# ---------------------------------------------------------------------------
# _resolve_source_titles
# ---------------------------------------------------------------------------

class TestResolveSourceTitles:
    """Resolve citation titles from digest articles or fall back to domain."""

    def _make_citation(self, number=1, url="https://example.com/article"):
        """Helper to create a SourceEntry with a given number and URL."""
        return SourceEntry(number=number, url=url, title="")

    def test_url_in_map_with_title(self):
        """URL in url_map with a title uses that title."""
        citations = [self._make_citation(url="https://example.com/a")]
        digest_articles = [{"url": "https://example.com/a", "title": "Article A"}]
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "Article A"

    def test_url_not_in_map_falls_back_to_domain(self):
        """URL not in url_map: use domain name as title."""
        citations = [self._make_citation(url="https://news.ycombinator.com/item?id=1")]
        digest_articles = []
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "news.ycombinator.com"

    def test_bad_url_uses_raw_url(self):
        """Non-matching URL pattern uses the raw URL as title."""
        citations = [self._make_citation(url="not-a-valid-url")]
        digest_articles = []
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "not-a-valid-url"

    def test_url_in_map_with_empty_title_preserves_existing(self):
        """When url_map has the URL but title is empty, preserve existing (don't fall to domain)."""
        citations = [self._make_citation(url="https://example.com/b")]
        digest_articles = [{"url": "https://example.com/b", "title": ""}]
        resolved = _resolve_source_titles(citations, digest_articles)
        # URL was found in map (even though title was empty), so it should
        # NOT fall through to domain extraction; title stays empty.
        assert resolved[0].title == ""

    def test_url_in_map_with_empty_title_uses_existing_nonempty(self):
        """If s.title already has a value and url_map has empty, keep existing."""
        citations = [SourceEntry(number=1, url="https://example.com/c", title="Already Set")]
        digest_articles = [{"url": "https://example.com/c", "title": ""}]
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "Already Set"

    def test_multiple_keys_in_digest_articles(self):
        """url_map collects from url, article_url, and source_url keys."""
        citations = [
            self._make_citation(url="https://a.com/1"),
            self._make_citation(url="https://b.com/2"),
            self._make_citation(url="https://c.com/3"),
        ]
        digest_articles = [
            {"url": "https://a.com/1", "title": "From URL"},
            {"article_url": "https://b.com/2", "title": "From Article URL"},
            {"source_url": "https://c.com/3", "title": "From Source URL"},
        ]
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "From URL"
        assert resolved[1].title == "From Article URL"
        assert resolved[2].title == "From Source URL"

    def test_mixed_found_and_not_found(self):
        """Some citations found in articles, others get domain fallback."""
        citations = [
            self._make_citation(1, "https://known.com/x"),
            self._make_citation(2, "https://unknown.net/y"),
        ]
        digest_articles = [{"url": "https://known.com/x", "title": "Known Article"}]
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "Known Article"
        assert resolved[1].title == "unknown.net"

    def test_article_url_key_used(self):
        """article_url key in digest_article is checked for URL match."""
        citations = [self._make_citation(url="https://myblog.com/post/1")]
        digest_articles = [
            {"article_url": "https://myblog.com/post/1", "title": "My Blog Post"}
        ]
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "My Blog Post"

    def test_source_url_key_used(self):
        """source_url key in digest_article is checked for URL match."""
        citations = [self._make_citation(url="https://source.org/doc")]
        digest_articles = [
            {"source_url": "https://source.org/doc", "title": "Source Doc"}
        ]
        resolved = _resolve_source_titles(citations, digest_articles)
        assert resolved[0].title == "Source Doc"
