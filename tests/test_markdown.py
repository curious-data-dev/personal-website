"""Unit tests for markdown rendering: _make_anchor and render_markdown."""

import pytest
from app.web.routes import _make_anchor, render_markdown


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
