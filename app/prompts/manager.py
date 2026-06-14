"""PromptManager — loads prompt templates from .md files.

Prompts are stored as Markdown files in Main Architechture/prompts/
and cached in memory after first load.

Resolution order (first match wins):
1. {prompts_dir}/{creator}/{detail_level}/{template_name}.md
2. {prompts_dir}/{creator}/{template_name}.md
3. {prompts_dir}/{detail_level}/{template_name}.md
4. {prompts_dir}/{template_name}.md
5. Built-in fallback
"""

import logging
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "Main Architechture" / "prompts"

FALLBACK_PROMPTS = {
    "single_summary": (
        "Summarize the following article concisely, preserving all key facts, "
        "names, numbers, and dates:\n\n{text}"
    ),
    "chunk_summary": (
        "Summarize this excerpt from a longer article. "
        "Capture every key fact, name, number, and date:\n\n{text}"
    ),
    "reduce_synthesis": (
        "Synthesize these sub-summaries into one cohesive summary. "
        "Preserve all unique details:\n\n{sub_summaries}"
    ),
    "daily_digest": (
        "Create a daily digest for {date} from the following article summaries. "
        "Tag each paragraph with its source reference number:\n\n{article_summaries}"
    ),
}


class PromptManager:
    """Manages prompt templates loaded from .md files with caching."""

    def __init__(self, prompts_dir: str | Path | None = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else PROMPTS_DIR

    @lru_cache(maxsize=64)
    def get_prompt(
        self,
        template_name: str,
        detail_level: str = "detailed",
        creator: str | None = None,
    ) -> str:
        """Get a prompt template by name.

        Resolution order (first match wins):
        1. {prompts_dir}/{creator}/{detail_level}/{template_name}.md
        2. {prompts_dir}/{creator}/{template_name}.md
        3. {prompts_dir}/{detail_level}/{template_name}.md
        4. {prompts_dir}/{template_name}.md
        5. Built-in fallback

        Args:
            template_name: e.g. "single_summary", "chunk_summary", "daily_digest"
            detail_level: "high-level" or "detailed" (default: "detailed")
            creator: Optional creator/channel name for per-creator override

        Returns:
            The prompt template string, with {placeholders} for caller to .format()
        """
        candidates: list[Path] = []

        if creator:
            candidates.append(
                self.prompts_dir / creator / detail_level / f"{template_name}.md"
            )
            candidates.append(
                self.prompts_dir / creator / f"{template_name}.md"
            )

        candidates.append(
            self.prompts_dir / detail_level / f"{template_name}.md"
        )
        candidates.append(
            self.prompts_dir / f"{template_name}.md"
        )

        for path in candidates:
            if path.exists():
                logger.debug("Loading prompt from %s", path)
                return path.read_text(encoding="utf-8").strip()

        logger.warning(
            "Prompt '%s' not found in %s, using fallback",
            template_name,
            self.prompts_dir,
        )
        return FALLBACK_PROMPTS.get(template_name, "")

    def list_available_prompts(self) -> list[str]:
        """List all available .md prompt template names."""
        if not self.prompts_dir.exists():
            return []
        return sorted(p.stem for p in self.prompts_dir.glob("**/*.md"))


# Singleton instance
prompt_manager = PromptManager()
