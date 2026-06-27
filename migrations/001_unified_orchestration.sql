ALTER TABLE sources ADD COLUMN source_type TEXT NOT NULL DEFAULT 'rss';
ALTER TABLE sources ADD COLUMN archived_at TIMESTAMP;
ALTER TABLE sources ADD COLUMN last_fetch_status TEXT;
ALTER TABLE sources ADD COLUMN last_fetch_error TEXT;

UPDATE sources SET source_type = 'youtube' WHERE category = 'youtube';

ALTER TABLE articles ADD COLUMN published_date_ist DATE;
ALTER TABLE articles ADD COLUMN transcript_provider TEXT;
ALTER TABLE articles ADD COLUMN excluded_at TIMESTAMP;

UPDATE articles
SET published_date_ist = date(published_at, '+5 hours', '+30 minutes')
WHERE published_at IS NOT NULL AND published_date_ist IS NULL;

CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('manual', 'scheduled', 'backfill')),
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    start_date DATE,
    end_date DATE,
    counters_json TEXT NOT NULL DEFAULT '{}',
    errors_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    lease_owner TEXT,
    lease_expires_at TIMESTAMP
);

CREATE TABLE run_sources (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (run_id, source_id)
);

CREATE TABLE run_items (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    discovered INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT,
    PRIMARY KEY (run_id, article_id)
);

CREATE TABLE run_affected_dates (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    digest_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    digest_id INTEGER,
    error_message TEXT,
    PRIMARY KEY (run_id, source_type, digest_date)
);

CREATE TABLE transcript_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    provider TEXT,
    provider_attempts TEXT NOT NULL DEFAULT '[]',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP,
    lease_owner TEXT,
    lease_expires_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transcript_provider_usage (
    provider TEXT NOT NULL,
    period TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    configured_limit INTEGER NOT NULL,
    exhausted_at TIMESTAMP,
    PRIMARY KEY (provider, period)
);

CREATE INDEX idx_sources_type_state ON sources(source_type, archived_at, is_active);
CREATE INDEX idx_articles_published_date_ist ON articles(published_date_ist);
CREATE INDEX idx_runs_status_created ON runs(status, created_at);
CREATE INDEX idx_transcript_jobs_claim ON transcript_jobs(status, next_attempt_at, lease_expires_at);
