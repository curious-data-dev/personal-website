-- Reset YouTube video summaries from the last 3 IST calendar days to 'raw'
-- so they regenerate with the new youtube_summary prompt on the next scrape cycle.

UPDATE articles
SET status = 'raw', summary_text = ''
WHERE status = 'summarized'
  AND published_date_ist IN (
    SELECT DISTINCT a.published_date_ist
    FROM articles a
    JOIN sources s ON s.id = a.source_id
    WHERE s.source_type = 'youtube'
      AND a.status = 'summarized'
      AND a.published_date_ist >= date('now', '-3 days')
  )
  AND source_id IN (SELECT id FROM sources WHERE source_type = 'youtube');
