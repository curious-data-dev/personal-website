"""Tests for summarization resilience: requeue on rate-limit and the digest
pipeline reading full article summaries (no condense step)."""

import pytest

import app.summarizer.service as service
from app.summarizer import llm


def _insert_article(conn, source_id, title="Title", raw_len=2000, published_at="2026-08-05T02:00:00+00:00", status="raw"):
    return conn.execute(
        """INSERT INTO articles(source_id, url, title, snippet, raw_text,
                                published_at, published_date_ist, status)
           VALUES (?, ?, ?, '', ?, ?, '2026-08-05', ?)""",
        (source_id, title, title, "x" * raw_len, published_at, status),
    ).lastrowid


def _source(conn, name="Src", source_type="rss"):
    cur = conn.execute(
        "INSERT INTO sources(name, feed_url, source_type) VALUES (?, ?, ?)",
        (name, f"http://{name}", source_type),
    )
    return cur.lastrowid


def test_rate_limited_article_is_requeued_not_failed(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    source_id = _source(conn)
    article_id = _insert_article(conn, source_id)
    conn.commit(); conn.close()

    monkeypatch.setattr(
        service,
        "_summarize_article",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("429 RESOURCE_EXHAUSTED rate limit")),
    )

    stats = service.run_summarization(source_types={"rss"})

    assert stats["articles_rate_limited"] == 1
    assert stats["articles_failed"] == 0
    conn = isolated_db.get_db()
    try:
        row = conn.execute("SELECT status, error_message FROM articles WHERE id=?", (article_id,)).fetchone()
        assert row["status"] == "raw"  # requeued for the next run
    finally:
        conn.close()


def test_non_rate_limit_error_marks_article_failed(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    source_id = _source(conn)
    article_id = _insert_article(conn, source_id)
    conn.commit(); conn.close()

    monkeypatch.setattr(
        service,
        "_summarize_article",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("model returned empty response")),
    )

    stats = service.run_summarization(source_types={"rss"})

    assert stats["articles_failed"] == 1
    assert stats["articles_rate_limited"] == 0
    conn = isolated_db.get_db()
    try:
        row = conn.execute("SELECT status FROM articles WHERE id=?", (article_id,)).fetchone()
        assert row["status"] == "failed"
    finally:
        conn.close()


def test_digest_uses_full_summaries(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    source_id = _source(conn)
    long_summary = "d" * 5000
    article_id = _insert_article(conn, source_id, status="summarized")
    conn.execute(
        "UPDATE articles SET summary_text=? WHERE id=?",
        (long_summary, article_id),
    )
    conn.commit(); conn.close()

    prompts = []

    def fake_call_llm(prompt, **kwargs):
        prompts.append(prompt)
        if "STORY BULLETS" in prompt:
            return "- **Story** — What happened: key facts. [1]"
        return "DIGEST OUTPUT"

    monkeypatch.setattr(service, "call_llm", fake_call_llm)
    monkeypatch.setattr(llm, "call_llm", fake_call_llm)

    conn = isolated_db.get_db()
    try:
        service._generate_daily_digest(conn, "2026-08-05")
        conn.commit()
    finally:
        conn.close()

    # There is no condensation call any more.
    assert not any("CONDENSED SUMMARY" in p for p in prompts)
    # The per-article extract prompt embeds the full stored summary.
    extract_prompt = [p for p in prompts if "STORY BLOCKS" in p or "STORY BULLETS" in p]
    assert extract_prompt and long_summary in extract_prompt[0]
    # The merge pass must receive the extracted story bullets.
    merge_prompt = [p for p in prompts if "DAILY DIGEST" in p]
    assert merge_prompt and "DIGEST OUTPUT" in merge_prompt[0]

    # condensed_summary is no longer written.
    conn = isolated_db.get_db()
    try:
        cached = conn.execute(
            "SELECT condensed_summary FROM articles WHERE id=?", (article_id,)
        ).fetchone()["condensed_summary"]
        assert cached is None
    finally:
        conn.close()


def test_digest_makes_only_extract_and_merge_calls(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    source_id = _source(conn)
    article_id = _insert_article(conn, source_id, status="summarized")
    conn.execute(
        "UPDATE articles SET summary_text=? WHERE id=?",
        ("short summary", article_id),
    )
    conn.commit(); conn.close()

    calls = {"n": 0}
    monkeypatch.setattr(
        service, "call_llm", lambda prompt, **kw: (calls.__setitem__("n", calls["n"] + 1) or "DIGEST")
    )
    monkeypatch.setattr(
        llm, "call_llm", lambda prompt, **kw: (calls.__setitem__("n", calls["n"] + 1) or "DIGEST")
    )

    conn = isolated_db.get_db()
    try:
        service._generate_daily_digest(conn, "2026-08-05")
    finally:
        conn.close()

    # Story extract + merge only (no condensation call).
    assert calls["n"] == 2


def test_summarize_article_is_single_pass_and_truncates(monkeypatch):
    """One call per article, truncated at max_article_chars, with the article
    output cap — no chunk/reduce calls."""

    calls = []

    def fake_call_llm(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return "summary"

    monkeypatch.setattr(service, "call_llm", fake_call_llm)
    monkeypatch.setattr(service.settings, "max_article_chars", 1000)
    monkeypatch.setattr(service.settings, "article_max_output_tokens", 6144)

    text = "y" * 5000
    summary, chunk_count, _provider = service._summarize_article(text)

    assert summary == "summary"
    assert chunk_count == 1
    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert "y" * 1000 in prompt
    assert "y" * 1001 not in prompt
    assert kwargs["max_tokens"] == 6144



def test_strip_placeholder_sections_heading():
    text = (
        "## Today's Highlights\n\nHi.\n\n## Sections\n\n"
        "## ⚖️ Politics\n\nBody.\n\n## 💡 Key Takeaway\n- x"
    )
    out = service._strip_placeholder_sections(text)
    assert "## Sections" not in out
    assert "## ⚖️ Politics" in out
    assert "Body." in out


def test_strip_placeholder_sections_promotes_nested_headings():
    out = service._strip_placeholder_sections("## Sections\n### ⚖️ Politics\nBody")
    assert out.splitlines()[0] == "## ⚖️ Politics"


def test_strip_placeholder_sections_leaves_normal_digest_untouched():
    text = "## Today's Highlights\nHi.\n\n## 💡 Key Takeaway\n- x"
    assert service._strip_placeholder_sections(text) == text


def test_digest_output_has_no_placeholder_sections(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    source_id = _source(conn)
    article_id = _insert_article(conn, source_id, status="summarized")
    conn.execute("UPDATE articles SET summary_text='facts' WHERE id=?", (article_id,))
    conn.commit(); conn.close()

    digest_text = (
        "## Today's Highlights\nHi.\n\n## Sections\n\n"
        "## ⚖️ Politics\n\nBody.\n\n## 💡 Key Takeaway\n- **X:** y [1]"
    )

    def fake_call_llm(prompt, **kwargs):
        if "STORY BULLETS" in prompt:
            return "- **Story** — What happened. [1]"
        return digest_text

    monkeypatch.setattr(service, "call_llm", fake_call_llm)
    monkeypatch.setattr(llm, "call_llm", fake_call_llm)

    conn = isolated_db.get_db()
    try:
        service._generate_daily_digest(conn, "2026-08-05")
        conn.commit()
        saved = conn.execute(
            "SELECT summary_text FROM daily_digests WHERE date='2026-08-05'"
        ).fetchone()["summary_text"]
    finally:
        conn.close()

    assert "## Sections" not in saved
    assert "## ⚖️ Politics" in saved
    assert "Body." in saved
