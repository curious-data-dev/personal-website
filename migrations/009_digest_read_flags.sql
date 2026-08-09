ALTER TABLE daily_digests ADD COLUMN read_flag INTEGER DEFAULT 0;

UPDATE daily_digests SET read_flag = 1;

ALTER TABLE youtube_digests ADD COLUMN read_flag INTEGER DEFAULT 0;

UPDATE youtube_digests SET read_flag = 1;
