"""Periodic cleanup for expired transcript and summary content."""
from datetime import datetime, timezone

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import CallSummary, TranscriptMessage


def purge_expired_content() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        transcript_count = db.execute(delete(TranscriptMessage).where(TranscriptMessage.expires_at <= now)).rowcount or 0
        summary_count = db.execute(delete(CallSummary).where(CallSummary.expires_at <= now)).rowcount or 0
        db.commit()
    return transcript_count, summary_count


if __name__ == "__main__":
    deleted_transcripts, deleted_summaries = purge_expired_content()
    # Counts are safe aggregate maintenance output; no record content or IDs.
    print(f"Expired content removed: {deleted_transcripts} transcript segments, {deleted_summaries} summaries.")
