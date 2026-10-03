CREATE TABLE llm_rate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    created_at REAL NOT NULL,
    tokens INTEGER NOT NULL
);

CREATE INDEX idx_llm_rate_provider_time ON llm_rate_events(provider, created_at);

CREATE TABLE llm_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    event TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    waited REAL NOT NULL DEFAULT 0,
    detail TEXT
);

CREATE INDEX idx_llm_usage_provider_event ON llm_usage_events(provider, event);

CREATE INDEX idx_llm_usage_created ON llm_usage_events(created_at);
