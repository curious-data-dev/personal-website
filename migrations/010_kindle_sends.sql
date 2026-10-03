CREATE TABLE kindle_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_type TEXT NOT NULL CHECK(digest_type IN ('rss', 'youtube')),
    digest_date DATE NOT NULL,
    content_hash TEXT NOT NULL,
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(digest_type, digest_date)
);

CREATE INDEX idx_kindle_sends_date ON kindle_sends(digest_date);
