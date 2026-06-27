CREATE TABLE backfill_state (
    operation TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);
