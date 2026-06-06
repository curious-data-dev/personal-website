"""Text chunking for LLM summarization.

Uses langchain's RecursiveCharacterTextSplitter to split at natural
boundaries (paragraphs → sentences → words) with configurable overlap
to preserve semantic continuity between chunks.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings


def create_splitter(
    chunk_size: int | None = None, overlap: int | None = None
) -> RecursiveCharacterTextSplitter:
    """Create a text splitter with the configured chunk size and overlap."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=overlap or settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        length_function=len,
    )


def chunk_article(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split an article into semantically coherent, overlapping chunks.

    Args:
        text: The full article text.
        chunk_size: Max characters per chunk. Defaults to settings.chunk_size.
        overlap: Overlap between chunks. Defaults to settings.chunk_overlap.

    Returns:
        List of chunk strings.
    """
    if not text or len(text) < 200:
        return [text] if text else []

    splitter = create_splitter(chunk_size, overlap)
    chunks = splitter.split_text(text)

    # Filter out very small chunks (likely just leftover whitespace)
    chunks = [c for c in chunks if len(c.strip()) > 50]

    return chunks
