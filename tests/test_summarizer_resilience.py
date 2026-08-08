"""Tests for summarization resilience: requeue on rate-limit, digest condensation,
and grouped reduce that keeps requests under the token budget."""

import pytest

import app.summarizer.service as service
from app.summarizer import llm
from app.summarizer.llm import TokenRateLimiter


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


def test_digest_uses_condensed_summaries_and_caches_them(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    source_id = _source(conn)
    article_id = _insert_article(conn, source_id, status="summarized")
    conn.execute(
        "UPDATE articles SET summary_text=? WHERE id=?",
        ("d" * 2000, article_id),
    )
    conn.commit(); conn.close()

    prompts = []

    def fake_call_llm(prompt, **kwargs):
        prompts.append(prompt)
        if "CONDENSED SUMMARY" in prompt:
            return "Condensed: key facts preserved."
        return "DIGEST OUTPUT"

    monkeypatch.setattr(service, "call_llm", fake_call_llm)
    monkeypatch.setattr(llm, "call_llm", fake_call_llm)

    conn = isolated_db.get_db()
    try:
        service._generate_daily_digest(conn, "2026-08-05")
        conn.commit()
    finally:
        conn.close()

    # Condensation call happened before the digest call.
    assert any("CONDENSED SUMMARY" in p for p in prompts)
    # The digest prompt must embed the condensed text, not the 2000-char summary.
    digest_prompt = [p for p in prompts if "DAILY DIGEST" in p]
    assert digest_prompt and "Condensed: key facts preserved." in digest_prompt[0]
    assert "d" * 2000 not in digest_prompt[0]

    # Condensed summary cached on the article row for reuse.
    conn = isolated_db.get_db()
    try:
        cached = conn.execute(
            "SELECT condensed_summary FROM articles WHERE id=?", (article_id,)
        ).fetchone()["condensed_summary"]
        assert cached == "Condensed: key facts preserved."
    finally:
        conn.close()


def test_short_summaries_skip_condensation_call(isolated_db, monkeypatch):
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

    assert calls["n"] == 1  # only the digest call, no condensation call


def test_reduce_groups_subsummaries_under_token_budget(monkeypatch):
    """Long articles whose combined sub-summaries exceed the budget must be
    reduced in multiple passes so no single request exceeds the TPM limit."""

    class FakeSettings:
        chunk_size = 1000
        chunk_overlap = 0
        max_article_chars = 10000
        llm_input_tokens_per_min = 500  # deliberately tiny budget
        rate_limit_window_seconds = 60

    monkeypatch.setattr(service.settings, "chunk_size", FakeSettings.chunk_size)
    monkeypatch.setattr(service.settings, "chunk_overlap", FakeSettings.chunk_overlap)
    monkeypatch.setattr(service.settings, "max_article_chars", FakeSettings.max_article_chars)
    monkeypatch.setattr(service.settings, "llm_input_tokens_per_min", 500)
    monkeypatch.setattr(service.settings, "rate_limit_window_seconds", 60)
    # Patch the module-global limiter so the reduce isn't actually paced in-test.
    monkeypatch.setattr(llm, "_rate_limiter", TokenRateLimiter(10**9, 60))

    reduce_calls = {"n": 0, "inputs": []}

    def fake_call_llm(prompt, **kwargs):
        if "SUB-SUMMARIES:" in prompt:  # reduce_synthesis prompt
            reduce_calls["n"] += 1
            reduce_calls["inputs"].append(len(prompt))
            return "reduced"
        return "chunk summary " + "x" * 1200  # ~300-token chunk summaries

    monkeypatch.setattr(service, "call_llm", fake_call_llm)
    monkeypatch.setattr(llm, "call_llm", fake_call_llm)

    text = "y" * 3500  # → ~4 chunks of 1000 chars
    summary, chunk_count, provider = service._summarize_article(text)

    assert chunk_count == 4
    # With ~300-token sub-summaries and a 500-token budget, more than one
    # reduce pass (group + merge) is required.
    assert reduce_calls["n"] >= 2
    # No single reduce input may exceed the configured per-minute budget.
    for inp in reduce_calls["inputs"]:
        assert inp // 4 <= 500
