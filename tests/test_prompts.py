"""Guards for the prompt registry in `prompts/`.

These tests make the prompt folder a hard contract: a renamed, deleted, or
brace-broken template fails here instead of silently degrading a digest.
"""

import pytest

from app.prompts import manager as prompt_registry
from app.prompts.manager import (
    ACTIVE_PROMPTS,
    DEFAULT_PROMPTS_DIR,
    PromptManager,
    PromptNotFoundError,
    prompt_manager,
)

REQUIRED_PLACEHOLDERS = {
    "article/rss_summary": {"text"},
    "article/youtube_summary": {"text"},
    "digest/rss_story_extract": {"ref_num", "summary"},
    "digest/youtube_story_extract": {"ref_num", "summary"},
    "digest/merge": {"date", "story_bullets"},
}

RENDER_VALUES = {
    "text": "<<TEXT>>",
    "sub_summaries": "<<SUB_SUMMARIES>>",
    "ref_num": "1",
    "summary": "<<SUMMARY>>",
    "date": "2026-08-22",
    "story_bullets": "<<STORY_BULLETS>>",
}


def test_active_prompts_are_fully_declared():
    assert set(REQUIRED_PLACEHOLDERS) == set(ACTIVE_PROMPTS)


def test_prompts_dir_is_repo_root_prompts():
    assert DEFAULT_PROMPTS_DIR.name == "prompts"
    assert DEFAULT_PROMPTS_DIR.is_dir()


@pytest.mark.parametrize("name", ACTIVE_PROMPTS)
def test_active_prompt_file_exists(name):
    assert (DEFAULT_PROMPTS_DIR / f"{name}.md").is_file()


@pytest.mark.parametrize("name", ACTIVE_PROMPTS)
def test_active_prompt_has_placeholders_and_renders(name):
    template = prompt_manager.get_prompt(name)
    for placeholder in REQUIRED_PLACEHOLDERS[name]:
        assert "{" + placeholder + "}" in template, f"{name} is missing {{{placeholder}}}"
    # Any other literal brace would make str.format() raise at runtime.
    rendered = template.format(**RENDER_VALUES)
    assert rendered.strip()


def test_active_prompts_match_files_on_disk():
    assert set(prompt_manager.list_available_prompts()) == set(ACTIVE_PROMPTS)


def test_legacy_prompts_are_archived_not_active():
    assert not any("_legacy" in name for name in ACTIVE_PROMPTS)
    listed = prompt_manager.list_available_prompts()
    assert not any(name.startswith("_legacy") for name in listed)
    for archived in (
        "daily_digest",
        "youtube_digest",
        "podcast_summary",
        "rss_chunk",
        "rss_reduce",
        "youtube_reduce",
        "condense",
    ):
        assert (DEFAULT_PROMPTS_DIR / "_legacy" / f"{archived}.md").is_file()


def test_missing_prompt_raises_instead_of_falling_back():
    with pytest.raises(PromptNotFoundError):
        prompt_manager.get_prompt("digest/does_not_exist")


def test_prompt_name_cannot_escape_prompts_dir():
    for bad_name in ("../secrets", "/etc/passwd", ""):
        with pytest.raises(PromptNotFoundError):
            prompt_manager.get_prompt(bad_name)


def test_prompts_dir_override(tmp_path):
    (tmp_path / "article").mkdir()
    (tmp_path / "article" / "rss_summary.md").write_text("Custom {text}", encoding="utf-8")
    manager = PromptManager(tmp_path)
    assert manager.get_prompt("article/rss_summary") == "Custom {text}"


def test_manager_reads_default_dir_when_no_override(monkeypatch):
    monkeypatch.delenv("PROMPTS_DIR", raising=False)
    manager = PromptManager()
    assert manager.prompts_dir == prompt_registry.DEFAULT_PROMPTS_DIR
