"""Durable YouTube transcript provider chain and job processing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    outcome: str
    text: str = ""
    retry_after: int | None = None
    error: str = ""


class TranscriptProvider:
    def __init__(self, name: str, api_key: str, limit: int):
        self.name, self.api_key, self.limit = name, api_key, limit

    def fetch(self, video_id: str) -> TranscriptResult:
        try:
            if self.name == "supadata":
                response = requests.get(
                    "https://api.supadata.ai/v1/transcript",
                    params={"url": f"https://youtu.be/{video_id}", "mode": "native", "text": "true"},
                    headers={"x-api-key": self.api_key}, timeout=45,
                )
            elif self.name == "scribetube":
                response = requests.get(
                    "https://api.scribetube.app/v1/transcript",
                    params={"id": video_id, "lang": "en"},
                    headers={"Authorization": f"Bearer {self.api_key}"}, timeout=45,
                )
            else:
                response = requests.get(
                    "https://api.transcriptapi.io/transcript",
                    params={"video_id": video_id, "language": "en"},
                    headers={"Authorization": f"Bearer {self.api_key}"}, timeout=45,
                )
            if response.status_code == 202 and self.name == "supadata":
                job_id = response.json().get("jobId")
                if not job_id:
                    return TranscriptResult("temporary_failure", error="Provider returned no job ID")
                for _ in range(15):
                    import time
                    time.sleep(2)
                    response = requests.get(
                        f"https://api.supadata.ai/v1/transcript/{job_id}",
                        headers={"x-api-key": self.api_key}, timeout=20,
                    )
                    if response.status_code != 202:
                        break
            if response.status_code in (401, 403):
                return TranscriptResult("authentication_failure", error="Provider authentication failed")
            if response.status_code == 402:
                return TranscriptResult("quota_exhausted", error="Provider quota exhausted")
            if response.status_code == 429:
                retry = response.headers.get("Retry-After")
                return TranscriptResult("rate_limited", retry_after=int(retry) if retry and retry.isdigit() else None)
            if response.status_code in (404, 422):
                return TranscriptResult("no_captions")
            if response.status_code >= 500:
                return TranscriptResult("temporary_failure", error=f"HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("source", "")).lower() == "asr":
                return TranscriptResult("no_captions", error="Provider returned generated ASR")
            text = payload.get("content") or payload.get("segments") or payload.get("transcript") or payload.get("text") or ""
            if isinstance(text, list):
                text = " ".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in text)
            return TranscriptResult("success", text=text.strip()) if text.strip() else TranscriptResult("no_captions")
        except requests.Timeout:
            return TranscriptResult("temporary_failure", error="Provider request timed out")
        except Exception as exc:
            return TranscriptResult("temporary_failure", error=str(exc)[:300])


class DirectTranscriptProvider:
    """Local-development adapter; may be blocked from datacenter/VPS IPs."""

    name = "direct"
    limit = 1_000_000
    api_key = ""

    def fetch(self, video_id: str) -> TranscriptResult:
        from app.scraper.youtube.service import _fetch_transcript
        text = _fetch_transcript(video_id)
        return TranscriptResult("success", text=text) if text else TranscriptResult("no_captions")


def _providers() -> list[TranscriptProvider]:
    configured = {
        "supadata": (settings.supadata_api_key, settings.supadata_monthly_limit),
        "scribetube": (settings.scribetube_api_key, settings.scribetube_monthly_limit),
        "transcriptapi_io": (settings.transcriptapi_io_api_key, settings.transcriptapi_io_monthly_limit),
    }
    result = []
    for name in settings.youtube_transcript_providers.split(","):
        name = name.strip()
        if name == "direct":
            result.append(DirectTranscriptProvider())
            continue
        key, limit = configured.get(name, ("", 0))
        if key:
            result.append(TranscriptProvider(name, key, limit))
    return result


def process_pending_transcripts(run_id: int | None = None) -> dict:
    """Process eligible jobs serially; state is committed after every provider call."""
    conn = get_db()
    stats = {"completed": 0, "unavailable": 0, "failed": 0, "retry": 0}
    try:
        if run_id is None:
            jobs = conn.execute(
                """SELECT * FROM transcript_jobs WHERE status='pending'
                   OR (status='retry' AND next_attempt_at <= CURRENT_TIMESTAMP) ORDER BY id"""
            ).fetchall()
        else:
            jobs = conn.execute(
                """SELECT tj.* FROM transcript_jobs tj JOIN run_items ri ON ri.article_id=tj.article_id
                   WHERE ri.run_id=? AND (tj.status='pending' OR
                   (tj.status='retry' AND tj.next_attempt_at <= CURRENT_TIMESTAMP)) ORDER BY tj.id""",
                (run_id,),
            ).fetchall()
        providers = _providers()
        for raw_job in jobs:
            job = dict(raw_job)
            attempts = json.loads(job["provider_attempts"] or "[]")
            success = False
            no_caption_count = 0
            for provider in providers:
                period = datetime.now(timezone.utc).strftime("%Y-%m")
                usage = conn.execute(
                    "SELECT request_count FROM transcript_provider_usage WHERE provider=? AND period=?",
                    (provider.name, period),
                ).fetchone()
                if usage and usage["request_count"] >= provider.limit:
                    continue
                conn.execute(
                    """INSERT INTO transcript_provider_usage(provider, period, request_count, configured_limit)
                       VALUES (?, ?, 1, ?) ON CONFLICT(provider, period) DO UPDATE SET
                       request_count=request_count+1, configured_limit=excluded.configured_limit""",
                    (provider.name, period, provider.limit),
                )
                result = provider.fetch(job["video_id"])
                attempts.append({"provider": provider.name, "outcome": result.outcome})
                if result.outcome == "success":
                    conn.execute(
                        """UPDATE articles SET raw_text=?, status='raw', transcript_provider=?, error_message=NULL
                           WHERE id=?""",
                        (result.text, provider.name, job["article_id"]),
                    )
                    conn.execute(
                        """UPDATE transcript_jobs SET status='completed', provider=?, provider_attempts=?,
                           attempt_count=attempt_count+1, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (provider.name, json.dumps(attempts), job["id"]),
                    )
                    stats["completed"] += 1
                    success = True
                    break
                if result.outcome == "no_captions":
                    no_caption_count += 1
                    if no_caption_count >= 2:
                        break
            if not success:
                next_attempt = job["attempt_count"] + 1
                terminal = "unavailable" if no_caption_count else (
                    "retry" if next_attempt < settings.youtube_job_max_attempts else "failed"
                )
                article_status = "transcript_unavailable" if no_caption_count else (
                    "pending_transcript" if terminal == "retry" else "failed"
                )
                conn.execute("UPDATE articles SET status=?, error_message=? WHERE id=?", (article_status, "No usable transcript" if no_caption_count else "Transcript providers unavailable", job["article_id"]))
                conn.execute(
                    """UPDATE transcript_jobs SET status=?, provider_attempts=?, attempt_count=attempt_count+1,
                       next_attempt_at=CASE WHEN ?='retry' THEN datetime('now', '+' || MIN(3600, 60 * (1 << attempt_count)) || ' seconds') ELSE NULL END,
                       last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (terminal, json.dumps(attempts), terminal, "No usable transcript" if no_caption_count else "No configured provider succeeded", job["id"]),
                )
                stats[terminal] += 1
            conn.commit()
        return stats
    finally:
        conn.close()
