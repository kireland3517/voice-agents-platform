"""
Call Session Model
Tracks call state, transcripts, and recordings
"""
import logging
from datetime import datetime, UTC
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class CallSession:
    """Represents an active call session"""

    def __init__(self, company_id: str, call_id: Optional[str] = None):
        self.company_id = company_id
        self.call_id = call_id or f"call-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        self.start_time = datetime.now(UTC)
        self.end_time: Optional[datetime] = None

        # Transcript tracking
        self.transcript: List[Dict] = []
        self.assistant_partial = ""

        # Audio recording buffers
        self.caller_audio_chunks: List[bytes] = []
        self.assistant_audio_chunks: List[bytes] = []

        # Information collection tracking
        self.collected_info = {
            'first_name': None,
            'last_name': None,
            'last_name_verified': False,
            'phone': None,
            'email': None,
            'zipcode': None,
            'city': None,
            'state': None,
            'address': None,
            'dob': None
        }

        # Session state
        self.is_active = True

        logger.info(f"✅ Call session created: {self.call_id}")

    def add_transcript(self, role: str, text: str):
        """Add a completed transcript entry"""
        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'role': role,
            'text': text
        }
        self.transcript.append(entry)

    def add_assistant_partial(self, partial: str):
        """Add partial assistant text (for streaming)"""
        self.assistant_partial += partial

    def get_transcript_json(self) -> dict:
        """Get transcript in JSON format for storage"""
        return {
            'call_id': self.call_id,
            'company_id': self.company_id,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': (self.end_time - self.start_time).total_seconds() if self.end_time else None,
            'transcript': self.transcript,
            'collected_info': self.collected_info
        }

    def end_session(self):
        """Mark session as ended"""
        self.end_time = datetime.now(UTC)
        self.is_active = False
        logger.info(f"📴 Call session ended: {self.call_id} (duration: {(self.end_time - self.start_time).total_seconds():.1f}s)")
