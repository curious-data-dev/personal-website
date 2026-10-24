"""PromptManager — loads prompt templates from the repository `prompts/` folder.

Layout (see prompts/README.md):

    prompts/article/   per-article / per-video summarization (map-reduce)
    prompts/digest/    digest condensation + two-phase digest generation
    prompts/_legacy/   archived prompts that no code path uses

Resolution is a direct file lookup: the logical name *is* the path inside
`prompts/` (e.g. "article/rss_summary" -> prompts/article/rss_summary.md).

A missing prompt raises `PromptNotFoundError` on purpose. Silently substituting
a built-in fallback used to change digest quality with no visible signal.

Templates are cached in memory after the first read, so editing a .md file
requires an app/worker restart to take effect. That is intentional (production
behaviour stays predictable); use `PROMPTS_DIR` to point at a different folder.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# repo_root/prompts  (app/prompts/manager.py -> app/prompts -> app -> repo root)
DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# Logical prompt names referenced by the pipeline. Keep in sync with
# prompts/README.md — `tests/test_prompts.py` asserts each of these exists.
RSS_SUMMARY = "article/rss_summary"
YOUTUBE_SUMMARY = "article/youtube_summary"
RSS_STORY_EXTRACT = "digest/rss_story_extract"
YOUTUBE_STORY_EXTRACT = "digest/youtube_story_extract"
DIGEST_MERGE = "digest/merge"

ACTIVE_PROMPTS = (
    RSS_SUMMARY,
    YOUTUBE_SUMMARY,
    RSS_STORY_EXTRACT,
    YOUTUBE_STORY_EXTRACT,
    DIGEST_MERGE,
)


class PromptNotFoundError(FileNotFoundError):
    """Raised when a prompt template is missing from the prompts folder."""


def _default_prompts_dir() -> Path:
    """Resolve the prompts directory, honouring the PROMPTS_DIR override."""
    override = os.environ.get("PROMPTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_PROMPTS_DIR


class PromptManager:
    """Loads prompt templates from `prompts/` with caching."""

    def __init__(self, prompts_dir: str | Path | None = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else _default_prompts_dir()

    def template_path(self, name: str) -> Path:
        """Return the .md path for a logical name, refusing path escapes."""
        if not name or name.startswith("/") or ".." in Path(name).parts:
            raise PromptNotFoundError(f"Invalid prompt name: {name!r}")
        return self.prompts_dir / f"{name}.md"

    @lru_cache(maxsize=64)
    def get_prompt(self, name: str) -> str:
        """Return the prompt template for a logical name, raising if missing.

        Args:
            name: Logical name without the .md suffix, e.g. "digest/merge".

        Returns:
            The template string, with {placeholders} for the caller to .format().

        Raises:
            PromptNotFoundError: if the template file does not exist.
        """
        path = self.template_path(name)
        if not path.is_file():
            raise PromptNotFoundError(
                f"Prompt '{name}' not found at {path}. "
                f"Expected one of: {', '.join(ACTIVE_PROMPTS)}"
            )
        logger.debug("Loading prompt from %s", path)
        return path.read_text(encoding="utf-8").strip()

    def list_available_prompts(self) -> list[str]:
        """List active prompt names (relative to prompts/, excluding _legacy)."""
        if not self.prompts_dir.exists():
            return []
        names = []
        for path in self.prompts_dir.rglob("*.md"):
            rel = path.relative_to(self.prompts_dir)
            # Prompts live in a stage subfolder (article/, digest/); skip README.md
            # and anything archived under _legacy/.
            if len(rel.parts) < 2 or "_legacy" in rel.parts:
                continue
            names.append(str(rel.with_suffix("")))
        return sorted(names)


# Singleton instance
prompt_manager = PromptManager()
