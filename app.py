import os
import asyncio
import json
import logging
import base64
import wave
import io
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, UTC
import traceback
import pytz
import numpy

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Form
from fastapi.responses import JSONResponse, Response
from starlette.websockets import WebSocketState
from dotenv import load_dotenv

from config import ConfigManager
from zipcode_service import ZipcodeService
from surname_verifier import find_surname_candidates, generate_llm_prompt
from cost_tracker import get_cost_tracker

from functools import lru_cache
from time import time

# Azure Voice Live SDK imports
from azure.core.credentials import AzureKeyCredential
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    RequestSession,
    AzureSemanticVad,
    AudioNoiseReduction,
    AudioEchoCancellation,
    AudioInputTranscriptionOptions,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    ServerEventType,
    FunctionTool
)

# ------------------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("voice_bridge")

# ------------------------------------------------------------------------------
# ENV & CONFIG
# ------------------------------------------------------------------------------
load_dotenv()

AZURE_AI_ENDPOINT = os.getenv("AZURE_AI_ENDPOINT", "").strip()
AZURE_AI_KEY = os.getenv("AZURE_AI_KEY", "").strip()
AZURE_AI_MODEL = os.getenv("AZURE_AI_MODEL", "gpt-realtime-mini").strip()

SAVE_RECORDINGS = os.getenv("SAVE_RECORDINGS", "true").lower() == "true"
SAVE_TRANSCRIPTS = os.getenv("SAVE_TRANSCRIPTS", "true").lower() == "true"

config_manager = ConfigManager()
zipcode_service = ZipcodeService()
cost_tracker = get_cost_tracker(config_manager)

# ------------------------------------------------------------------------------
# CONFIGURATION CACHE (5-minute TTL)
# ------------------------------------------------------------------------------
@lru_cache(maxsize=128)
def _get_company_config_cached(company_id: str, cache_key: int):
    """Internal cached config getter with time-based key"""
    return config_manager.get_company_config(company_id)

def get_cached_config(company_id: str):
    """Get company config with 5-minute cache"""
    cache_key = int(time() // 300)  # Cache expires every 5 minutes
    return _get_company_config_cached(company_id, cache_key)

# ------------------------------------------------------------------------------
# FUNCTION FEEDBACK MESSAGES (Pre-function verbal feedback)
# ------------------------------------------------------------------------------
FUNCTION_FEEDBACK = {
    "transfer_window_check": "One moment checking availability."
}

if not (AZURE_AI_ENDPOINT and AZURE_AI_KEY):
    logger.error("Missing required environment variables")
    raise ValueError("AZURE_AI_ENDPOINT and AZURE_AI_KEY are required")

logger.info("=" * 80)
logger.info("??? VOICE AGENT - AZURE VOICE LIVE API")
logger.info("=" * 80)
logger.info(f"Azure Endpoint: {AZURE_AI_ENDPOINT}")
logger.info(f"Model: {AZURE_AI_MODEL}")
logger.info(f"Audio Format: PCM16 24kHz passthrough")
logger.info(f"Voices: 600+ Azure TTS voices (friendly names OR direct Azure voice names)")
logger.info(f"Save Recordings: {SAVE_RECORDINGS}")
logger.info(f"Save Transcripts: {SAVE_TRANSCRIPTS}")
logger.info("=" * 80)

# ------------------------------------------------------------------------------
# VOICE MAP - OpenAI voice names to Azure TTS voices
# ------------------------------------------------------------------------------
VOICE_MAP = {
    'alloy': 'alloy',
    'shimmer': 'shimmer',
    'echo': 'echo',
    'ash': 'ash',
    'ballad': 'ballad',
    'coral': 'coral',
    'sage': 'sage',
    'verse': 'verse',
    'cedar': 'cedar',
    'luna': 'luna',
}

# Azure TTS voice mappings for Voice Live API (600+ voices supported)
# Companies can use friendly names (alloy, cedar, etc.) OR direct Azure voice names
# Full list: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts
AZURE_VOICE_MAP = {
    # Friendly names mapped to Azure voices
    'alloy': 'en-US-AndrewNeural',           # Warm, friendly male voice
    'shimmer': 'en-US-JennyNeural',          # Friendly, warm female voice
    'echo': 'en-US-GuyNeural',               # Professional male voice
    'ash': 'en-US-EmmaNeural',               # Clear, articulate female voice
    'ballad': 'en-US-DavisNeural',           # Conversational male voice
    'coral': 'en-US-Ava:DragonHDLatestNeural',  # HD quality warm, professional female voice
    'sage': 'en-US-BrianNeural',             # Clear, professional male voice
    'verse': 'en-US-AriaNeural',             # Friendly, expressive female voice
    'cedar': 'en-US-Andrew:DragonHDLatestNeural',  # HD quality warm, natural male voice with temperature support
    'luna': 'en-US-LunaNeural',              # Conversational female voice

    # Additional popular voices for quick access
    'jenny-multilingual': 'en-US-JennyMultilingualNeural',
    'ryan-multilingual': 'en-US-RyanMultilingualNeural',
    'aria-multilingual': 'en-US-AriaMultilingualNeural',
}

# ------------------------------------------------------------------------------
# CALLER ID NORMALIZATION
# ------------------------------------------------------------------------------
def normalize_caller_id(caller: Optional[str]) -> Optional[str]:
    """
    Extract E.164 phone number from various SIP URI formats.

    Handles formats like:
    - "tel:+1234567890"
    - "sip:+1234567890@domain"
    - "<sip:+1234567890@domain>"
    - "+1234567890"
    - Plain numbers: "1234567890"

    Returns normalized E.164 format or None if invalid.
    """
    if not caller:
        return None

    import re

    # Extract phone number from SIP URI formats
    # Match: optional tel:/sip: prefix, optional +, then 10-15 digits
    match = re.search(r'(?:tel:|sip:)?(\+?\d{10,15})', caller)

    if match:
        number = match.group(1)
        # Ensure it starts with + for E.164 format
        if not number.startswith('+'):
            # Assume US/Canada if no country code (you may need to adjust this)
            number = '+1' + number if len(number) == 10 else '+' + number
        return number

    return caller  # Return as-is if we can't parse it

# ------------------------------------------------------------------------------
# CALL SESSION (SIMPLIFIED - NO BARGE-IN STATE)
# ------------------------------------------------------------------------------
class CallSession:
    def __init__(self, company_id: str, call_sid: str):
        self.company_id = company_id
        self.call_sid = call_sid
        self.start_time = datetime.now(UTC)
        self.end_time: Optional[datetime] = None

        # Audio recording buffers
        self.caller_audio_chunks: List[bytes] = []
        self.ai_audio_chunks: List[bytes] = []
        self.transcript: List[Dict[str, Any]] = []

        # Barge-in state tracking (v17.6)
        self.agent_is_speaking = False  # Track if Sarah is actively speaking

    def add_caller_audio(self, audio_base64: str):
        try:
            self.caller_audio_chunks.append(base64.b64decode(audio_base64))
        except Exception as e:
            logger.error(f"Error adding caller audio: {e}")

    def add_ai_audio(self, audio_base64: str):
        try:
            self.ai_audio_chunks.append(base64.b64decode(audio_base64))
        except Exception as e:
            logger.error(f"Error adding AI audio: {e}")

    def add_transcript_entry(self, speaker: str, text: str, timestamp: Optional[datetime] = None):
        timestamp = timestamp or datetime.now(UTC)
        self.transcript.append({
            "timestamp": timestamp.isoformat(),
            "speaker": speaker,
            "text": text
        })

    def finalize(self):
        self.end_time = datetime.now(UTC)
        dur = (self.end_time - self.start_time).total_seconds()
        logger.info(f"Call finalized. Duration: {dur:.2f} seconds")

    def _to_wav(self, chunks: List[bytes]) -> Optional[bytes]:
        if not chunks:
            return None
        try:
            pcm = b"".join(chunks)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            buf.seek(0)
            return buf.read()
        except Exception as e:
            logger.error(f"Error creating WAV: {e}")
            return None

    def _create_merged_stereo_wav(self, caller_chunks: List[bytes], ai_chunks: List[bytes]) -> Optional[bytes]:
        """
        Create a stereo WAV file with caller audio in left channel and AI audio in right channel.
        Both streams are PCM16 @ 24kHz mono, we merge them into stereo.
        """
        try:
            # Join chunks into continuous streams
            caller_data = b''.join(caller_chunks) if caller_chunks else b''
            ai_data = b''.join(ai_chunks) if ai_chunks else b''

            # Pad shorter stream with silence to match lengths
            max_len = max(len(caller_data), len(ai_data))
            caller_data = caller_data.ljust(max_len, b'\x00')
            ai_data = ai_data.ljust(max_len, b'\x00')

            # Convert bytes to numpy arrays (PCM16 = 16-bit signed integers)
            caller_samples = numpy.frombuffer(caller_data, dtype=numpy.int16)
            ai_samples = numpy.frombuffer(ai_data, dtype=numpy.int16)

            # Interleave samples to create stereo: [L, R, L, R, L, R, ...]
            stereo_samples = numpy.empty((caller_samples.size + ai_samples.size,), dtype=numpy.int16)
            stereo_samples[0::2] = caller_samples  # Left channel (caller)
            stereo_samples[1::2] = ai_samples      # Right channel (AI)

            # Create stereo WAV file
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(2)  # Stereo
                w.setsampwidth(2)  # 16-bit
                w.setframerate(24000)  # 24kHz
                w.writeframes(stereo_samples.tobytes())
            buf.seek(0)
            return buf.read()
        except Exception as e:
            logger.error(f"Error creating merged stereo WAV: {e}")
            return None

    async def save_to_storage(self):
        try:
            if SAVE_TRANSCRIPTS and self.transcript:
                doc = {
                    "call_sid": self.call_sid,
                    "company_id": self.company_id,
                    "start_time": self.start_time.isoformat(),
                    "end_time": self.end_time.isoformat() if self.end_time else None,
                    "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.end_time else None,
                    "transcript": self.transcript,
                }
                config_manager.save_call_transcript(self.company_id, self.call_sid, doc)

            if SAVE_RECORDINGS:
                # Create merged stereo recording (caller=left, AI=right)
                merged_wav = self._create_merged_stereo_wav(self.caller_audio_chunks, self.ai_audio_chunks)
                if merged_wav:
                    config_manager.save_call_recording(self.company_id, self.call_sid, merged_wav, "wav")
                    logger.info(f"? Saved merged stereo recording: {self.call_sid}.wav")

                # Also save separate mono files (for debugging/backup)
                if self.caller_audio_chunks:
                    caller_wav = self._to_wav(self.caller_audio_chunks)
                    if caller_wav:
                        config_manager.save_call_recording(self.company_id, f"{self.call_sid}-caller", caller_wav, "wav")

                if self.ai_audio_chunks:
                    ai_wav = self._to_wav(self.ai_audio_chunks)
                    if ai_wav:
                        config_manager.save_call_recording(self.company_id, f"{self.call_sid}-ai", ai_wav, "wav")

            logger.info(f"Successfully saved call session data for {self.call_sid}")
        except Exception as e:
            logger.error(f"Error saving call session: {e}")
            logger.error(traceback.format_exc())

# ------------------------------------------------------------------------------
# SESSION MONITORING AND METRICS
# ------------------------------------------------------------------------------
class SessionMonitor:
    """Monitor and track Voice Live session metrics"""

    def __init__(self, company_id: str):
        self.company_id = company_id
        self.start_time = datetime.now(UTC)
        self.token_count = 0
        self.audio_duration_ms = 0
        self.turn_count = 0
        self.function_calls = []
        self.vad_triggers = 0
        self.errors = []
        self.last_token_warning = 0
        self.invalid_token_count = 0
        self.barge_in_count = 0

    def add_tokens(self, input_tokens: int, output_tokens: int):
        self.token_count += (input_tokens + output_tokens)
        # Audio uses ~800 tokens/minute per research
        estimated_minutes = self.token_count / 800
        remaining_minutes = max(0, 15 - estimated_minutes)  # 15 min session limit

        # Warn at thresholds
        if self.token_count > 100000 and self.last_token_warning < 100000:
            logger.warning(f"?? HIGH TOKEN USAGE: {self.token_count:,}/128,000 ({self.token_count/128000:.1%})")
            self.last_token_warning = 100000
        elif self.token_count > 64000 and self.last_token_warning < 64000:
            logger.info(f"?? Token usage at {self.token_count/128000:.1%} of limit")
            self.last_token_warning = 64000

        if remaining_minutes < 2:
            logger.warning(f"? Session approaching 15-minute limit: {remaining_minutes:.1f} min remaining")

    def add_turn(self):
        self.turn_count += 1
        if self.turn_count == 10:
            logger.info(f"?? Consider text conversion after {self.turn_count} turns to save tokens")

    def add_function_call(self, function_name: str):
        self.function_calls.append({
            'name': function_name,
            'timestamp': datetime.now(UTC).isoformat()
        })

    def add_vad_trigger(self):
        self.vad_triggers += 1

    def add_error(self, error: str):
        self.errors.append({
            'error': error,
            'timestamp': datetime.now(UTC).isoformat()
        })

    def add_invalid_token(self):
        self.invalid_token_count += 1

    def add_barge_in(self):
        self.barge_in_count += 1

    def log_summary(self):
        duration = (datetime.now(UTC) - self.start_time).total_seconds()
        logger.info(f"""
?? SESSION SUMMARY for {self.company_id}:
   Duration: {duration:.1f}s
   Turns: {self.turn_count}
   Tokens: {self.token_count:,} (~{self.token_count/128000:.1%} of limit)
   VAD Triggers: {self.vad_triggers}
   Function Calls: {len(self.function_calls)}
   Barge-ins: {self.barge_in_count}
   Invalid Tokens: {self.invalid_token_count}
   Errors: {len(self.errors)}
   Avg Turn Time: {duration/max(1, self.turn_count):.1f}s
        """)

# ------------------------------------------------------------------------------
# PROMPT BUILDER (Simplified - Instructions from Blob Storage)
# ------------------------------------------------------------------------------
def extract_prompt_version(instructions):
    """
    Extract version metadata from prompt instructions.
    Looks for YAML-style header with Version, Last Updated, Changes, and Git Commit.

    Expected format:
    ---
    PROMPT METADATA
    Version: 13
    Last Updated: 2025-11-08
    Changes: Context injection timing fix (Ch81)...
    Git Commit: e06c07b
    Previous Versions: v12 (2025-11-07 caller ID format)...
    ---
    """
    import re

    # Extract version number
    version_match = re.search(r'Version:\s*(\d+)', instructions)
    version = version_match.group(1) if version_match else "Unknown"

    # Extract last updated date
    date_match = re.search(r'Last Updated:\s*([^\n]+)', instructions)
    last_updated = date_match.group(1).strip() if date_match else "Unknown"

    # Extract git commit
    commit_match = re.search(r'Git Commit:\s*([a-f0-9]{7})', instructions)
    git_commit = commit_match.group(1) if commit_match else "Unknown"

    # Extract changes summary (first 100 chars)
    changes_match = re.search(r'Changes:\s*([^\n]+)', instructions)
    changes = changes_match.group(1).strip()[:100] if changes_match else "No change log"

    return {
        'version': version,
        'last_updated': last_updated,
        'git_commit': git_commit,
        'changes': changes
    }

def build_company_instructions(company_config):
    """
    Load company instructions from Blob Storage.
    All instruction logic (greeting, tools, business rules, etc.) should be in Blob Storage.
    This function only extracts voice configuration and provides minimal fallback.
    """
    company_name = company_config.get('company-name', 'Unknown Company')
    greeting = company_config.get('greeting', f'Thank you for calling {company_name}')

    voice_config = company_config.get('voice-config', {})
    voice_style = voice_config.get('voice-style', 'alloy')
    # Pass through voice_style directly - will be mapped to Azure voice in create_voicelive_connection
    openai_voice = voice_style

    detailed_instructions = company_config.get('detailed-instructions')

    if detailed_instructions:
        # Use instructions from Blob Storage (recommended)
        instructions = detailed_instructions

        # Extract and log version metadata
        version_info = extract_prompt_version(instructions)
        logger.info(f"? Loaded instructions from Blob Storage ({len(detailed_instructions)} characters)")
        logger.info(f"?? Prompt Version: {version_info['version']} (updated: {version_info['last_updated']}, commit: {version_info['git_commit']})")
        logger.info(f"?? Changes: {version_info['changes']}")
    else:
        # Minimal fallback if Blob Storage file missing
        logger.warning(f"?? No Blob Storage instructions found for {company_name}, using minimal fallback")
        instructions = f"""You are a professional phone agent for {company_name}.

Start every call with: {greeting}

AVAILABLE TOOLS:
- verify_surname: Verify customer surname spelling
- lookup_zipcode: Get city/state from ZIP code

Answer questions professionally and be helpful. Keep responses concise.
"""

    return instructions, openai_voice, greeting

# ------------------------------------------------------------------------------
# AZURE VOICE LIVE API CONNECTION
# ------------------------------------------------------------------------------
async def create_voicelive_connection(company_instructions, voice_name, audio_settings):
    """
    Create Voice Live API connection with PRODUCTION-GRADE configuration.
    All research-backed features enabled by default for demo mode.

    Features:
    - Semantic VAD: 40-60% better turn detection
    - Deep noise suppression: 60% noise reduction
    - Echo cancellation: Feedback prevention
    - Whisper transcription: Better accuracy
    - Filler word removal: Auto-remove "uh", "um"
    """
    logger.info("=" * 80)
    logger.info("?? Connecting to Azure Voice Live API with production optimizations")
    logger.info(f"Endpoint: {AZURE_AI_ENDPOINT}")
    logger.info(f"Model: {AZURE_AI_MODEL}")

    try:
        # Connect using Voice Live SDK - returns context manager
        connection = connect(
            endpoint=AZURE_AI_ENDPOINT,
            credential=AzureKeyCredential(AZURE_AI_KEY),
            model=AZURE_AI_MODEL,
        )  # Returns context manager (not awaitable)

        logger.info("? Voice Live connection established")

        # Feature flags (all TRUE by default in demo mode)
        use_noise_suppression = audio_settings.get('enable-noise-suppression', True)
        use_echo_cancellation = audio_settings.get('enable-echo-cancellation', True)
        use_transcription = audio_settings.get('enable-audio-transcription', True)

        # Configure Azure TTS voice based on company configuration
        # Support both friendly names (cedar, alloy) and direct Azure voice names
        if voice_name in AZURE_VOICE_MAP:
            # Use friendly name mapping
            azure_voice_name = AZURE_VOICE_MAP[voice_name]
            logger.info(f"? Azure TTS Voice configured: {azure_voice_name} (mapped from friendly name: {voice_name})")
        elif voice_name and ("-" in voice_name and "Neural" in voice_name):
            # Looks like a direct Azure voice name (e.g., "en-US-AriaNeural", "es-MX-DaliaNeural")
            azure_voice_name = voice_name
            logger.info(f"? Azure TTS Voice configured: {azure_voice_name} (direct Azure voice name)")
        else:
            # Fallback to default
            azure_voice_name = "en-US-FableTurboMultilingualNeural"
            logger.warning(f"?? Voice '{voice_name}' not recognized, using default: {azure_voice_name}")

        # Configure Azure TTS voice using settings from Azure App Configuration
        # HD voices (DragonHDLatestNeural) support ONLY temperature and rate parameters
        # Standard neural voices support rate, pitch, volume, and style parameters
        # Source: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-how-to

        is_hd_voice = ":DragonHD" in azure_voice_name

        if is_hd_voice:
            # HD voices: Only temperature and rate supported (per Voice Live API docs Oct 31, 2025)
            voice_temperature = float(audio_settings.get('voice-temperature', 0.8))
            voice_rate = audio_settings.get('voice-rate', '1.0')

            voice_config = AzureStandardVoice(
                name=azure_voice_name,
                type="azure-standard",
                temperature=voice_temperature,
                rate=voice_rate
            )
            logger.info(f"   HD Voice Config: temperature={voice_temperature}, rate={voice_rate}")
            logger.info(f"   Note: pitch, volume, and style are NOT supported for HD voices")
        else:
            # Standard voices: Full parameter support
            voice_rate = audio_settings.get('voice-rate', '1.0')
            voice_pitch = audio_settings.get('voice-pitch', '+0%')
            voice_volume = audio_settings.get('voice-volume', '+10%')
            voice_style = audio_settings.get('voice-style', 'friendly')

            voice_config = AzureStandardVoice(
                name=azure_voice_name,
                type="azure-standard",
                rate=voice_rate,
                pitch=voice_pitch,
                volume=voice_volume,
                style=voice_style
            )
            logger.info(f"   Standard Voice Config: rate={voice_rate}, pitch={voice_pitch}, volume={voice_volume}, style={voice_style}")

        # Configure Semantic VAD using settings from Azure App Configuration
        enable_barge_in = audio_settings.get('enable-barge-in', True)
        vad_threshold = audio_settings.get('vad-threshold', 0.3)
        vad_prefix_padding_ms = audio_settings.get('vad-prefix-padding-ms', 300)
        vad_silence_duration_ms = audio_settings.get('vad-silence-duration-ms', 500)
        remove_filler_words = audio_settings.get('remove-filler-words', False)

        if enable_barge_in:
            turn_detection_config = AzureSemanticVad(
                threshold=vad_threshold,
                prefix_padding_ms=vad_prefix_padding_ms,
                silence_duration_ms=vad_silence_duration_ms,
                remove_filler_words=remove_filler_words,
                interrupt_response=True,  # CRITICAL: Allow user to interrupt AI
                auto_truncate=True  # CRITICAL: Cut off AI speech on interrupt
                # NOTE: end_of_utterance_detection is NOT supported by AzureSemanticVad
            )
            logger.info(f"? Barge-in ENABLED - Semantic VAD (threshold={vad_threshold}, prefix_padding={vad_prefix_padding_ms}ms, silence={vad_silence_duration_ms}ms, remove_fillers={remove_filler_words}, interrupt=True, auto_truncate=True)")
        else:
            turn_detection_config = None
            logger.info(f"?? Barge-in DISABLED - Callers cannot interrupt agent")

        # Configure noise suppression
        noise_reduction = None
        if use_noise_suppression:
            noise_reduction = AudioNoiseReduction(type="azure_deep_noise_suppression")
            logger.info("? Deep Noise Suppression ENABLED")

        # Configure echo cancellation
        echo_cancellation = None
        if use_echo_cancellation:
            echo_cancellation = AudioEchoCancellation(type="server_echo_cancellation")
            logger.info("? Echo Cancellation ENABLED")

        # Configure audio transcription
        transcription = None
        if use_transcription:
            # Create transcription options with only supported parameters
            # Note: temperature, phrase_list, and prompt are NOT supported by Voice Live SDK
            transcription = AudioInputTranscriptionOptions(
                model="whisper-1",
                language="en"
            )

            logger.info("? Whisper Transcription ENABLED")

            # Add a warning if the config key still exists
            transcription_prompt_setting = audio_settings.get('transcription-prompt', None)
            if transcription_prompt_setting:
                logger.warning(f"?? 'transcription-prompt' is set in config, but this SDK version does not support it. Ignoring setting.")

        # ----------------------------------------------------------------------
        # FUNCTION CALLING CONFIGURATION
        # ----------------------------------------------------------------------
        logger.info("?? Configuring function calling tools...")

        # Define tools using FunctionTool SDK class (compliance-optimized)
        tools = [
            FunctionTool(
                name="lookup_zipcode",
                description="Look up city and state from ZIP code. Use this when the customer provides their ZIP code to verify their location.",
                parameters={
                    "type": "object",
                    "properties": {
                        "zipcode": {
                            "type": "string",
                            "description": "US ZIP or ZIP+4 (digits, optional dash/spaces). Will be normalized to 5 digits.",
                            "pattern": "^[0-9\\s-]{5,10}$"  # Relaxed: accept ZIP+4, spaces, dashes
                        }
                    },
                    "required": ["zipcode"]
                }
            ),
            FunctionTool(
                name="transfer_window_check",
                description="Check if live agent transfers are currently available based on business hours. Transfer window: Monday-Saturday, 8:00 AM - 2:00 AM Eastern Time. Use this to determine if you should offer transfer or schedule a callback.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            )
        ]
        logger.info(f"? Configured {len(tools)} function calling tools: {[t.name for t in tools]}")

        # Create session configuration using SDK typed models
        session_config = RequestSession(
            model="gpt-realtime-mini",  # Explicit model selection for Voice Live API
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=company_instructions,
            voice=voice_config,
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            turn_detection=turn_detection_config,
            input_audio_noise_reduction=noise_reduction,
            input_audio_echo_cancellation=echo_cancellation,
            input_audio_transcription=transcription,
            temperature=float(audio_settings.get("temperature", 0.7)),  # Model temperature (different from voice temp)
            max_response_output_tokens=int(audio_settings.get("max-response-tokens", 200)),  # Concise responses
            tools=tools,
            tool_choice="auto"
        )

        # Log configuration (session will be updated after entering context)
        logger.info("=" * 80)
        logger.info("? PRODUCTION-GRADE Voice Live API Ready (Elderly-Optimized)")
        logger.info(f"   Voice: {azure_voice_name}")
        if enable_barge_in:
            logger.info(f"   Barge-in: ENABLED - VAD (threshold={vad_threshold}, prefix_padding={vad_prefix_padding_ms}ms, silence={vad_silence_duration_ms}ms, remove_fillers={remove_filler_words})")
        else:
            logger.info(f"   Barge-in: DISABLED - Agent completes responses without interruption")
        logger.info(f"   LLM: temp={audio_settings.get('temperature', 0.7)}, max_tokens={audio_settings.get('max-response-tokens', 200)}")
        logger.info(f"   Features: Noise={use_noise_suppression}, Echo={use_echo_cancellation}, Transcription={use_transcription}")
        logger.info("=" * 80)

        # Return both the context manager and session config
        # Caller must enter context before calling session.update()
        return (connection, session_config)

    except Exception as e:
        logger.error(f"? Failed to create Voice Live connection: {e}")
        logger.error(traceback.format_exc())
        raise

# ------------------------------------------------------------------------------
# CONNECTION RESILIENCE: RETRY LOGIC AND HEARTBEAT
# ------------------------------------------------------------------------------
async def create_voicelive_connection_with_retry(company_instructions, voice_name, audio_settings, max_retries=3):
    """Create Voice Live connection with exponential backoff retry logic"""
    last_error = None
    retry_count = audio_settings.get('connection-retry-attempts', max_retries)

    for attempt in range(retry_count):
        try:
            logger.info(f"?? Connection attempt {attempt + 1}/{retry_count}")
            connection = await create_voicelive_connection(
                company_instructions, voice_name, audio_settings
            )

            logger.info("? Connection established with retry logic")
            return connection

        except Exception as e:
            last_error = e
            if attempt == retry_count - 1:
                logger.error(f"? All connection attempts failed after {retry_count} tries: {e}")
                raise

            # Exponential backoff: 2, 4, 8... seconds, max 30
            wait_time = min(2 ** (attempt + 1), 30)
            logger.warning(f"?? Attempt {attempt + 1} failed: {e}")
            logger.info(f"? Retrying in {wait_time} seconds...")
            await asyncio.sleep(wait_time)

    raise last_error or Exception("Connection failed")

async def heartbeat_loop(connection, monitor: SessionMonitor, interval: int = 30):
    """Keep connection alive with periodic heartbeat"""
    try:
        while True:
            await asyncio.sleep(interval)
            # Connection stays alive through regular event processing
            logger.debug(f"?? Connection heartbeat ({interval}s interval)")

    except asyncio.CancelledError:
        logger.info("?? Heartbeat task cancelled")
    except Exception as e:
        logger.error(f"?? Heartbeat error: {e}")
        monitor.add_error(f"Heartbeat failed: {e}")

# ------------------------------------------------------------------------------
# FUNCTION EXECUTION HANDLER
# ------------------------------------------------------------------------------
async def execute_function(function_name: str, arguments: dict) -> dict:
    """Execute tool functions and return results"""
    logger.info(f"?? Executing function: {function_name} with args: {arguments}")

    try:
        if function_name == "lookup_zipcode":
            raw_zipcode = arguments.get("zipcode", "") or ""

            # Normalize: extract only digits, take first 5
            digits = "".join(ch for ch in raw_zipcode if ch.isdigit())
            zipcode5 = digits[:5] if len(digits) >= 5 else ""

            logger.info(f"   ZIP tool: normalized '{raw_zipcode}' -> '{zipcode5}'")

            if not zipcode5:
                return {
                    "found": False,
                    "zipcode": raw_zipcode,
                    "message": "Invalid ZIP. Please ask for five digits."
                }

            # Use existing zipcode service (includes zipcode_spoken for clear pronunciation)
            result = zipcode_service.lookup(zipcode5)

            if result:
                logger.info(f"   ZIP lookup success: {result['city']}, {result['state']}")
                return {
                    "found": True,
                    "zipcode": zipcode5,
                    "zipcode_spoken": result.get('zipcode_spoken', zipcode5),  # Speech-formatted ZIP
                    "city": result['city'],
                    "state": result['state'],
                    "message": f"{result['city']}, {result['state']}"
                }
            else:
                logger.warning(f"   ZIP code {zipcode5} not found")
                return {
                    "found": False,
                    "zipcode": zipcode5,
                    "message": "ZIP code not found. Please verify."
                }

        elif function_name == "transfer_window_check":
            # Check if live agent transfers are available
            # Transfer window: Monday-Saturday, 8:00 AM - 2:00 AM Eastern Time

            # Get current time in Eastern timezone
            eastern_tz = pytz.timezone('US/Eastern')
            now_eastern = datetime.now(UTC).astimezone(eastern_tz)

            current_day = now_eastern.weekday()  # 0=Monday, 6=Sunday
            current_hour = now_eastern.hour
            current_minute = now_eastern.minute
            current_time_minutes = current_hour * 60 + current_minute

            # Transfer window: Monday (0) - Saturday (5), 8:00 AM - 2:00 AM (next day)
            # 8:00 AM = 480 minutes, 2:00 AM = 120 minutes
            transfer_start = 8 * 60  # 8:00 AM = 480 minutes
            transfer_end = 2 * 60    # 2:00 AM = 120 minutes

            # Since window spans midnight (8am-2am next day), we need to check two scenarios
            transfers_available = False

            # Scenario 1: Current time is after 8:00 AM on a valid day (Mon-Sat)
            if current_day in [0, 1, 2, 3, 4, 5] and current_time_minutes >= transfer_start:
                transfers_available = True

            # Scenario 2: Current time is before 2:00 AM and YESTERDAY was a valid day
            # (e.g., it's 1:00 AM Sunday, which is still Saturday's transfer window)
            elif current_time_minutes < transfer_end:
                previous_day = (current_day - 1) % 7
                if previous_day in [0, 1, 2, 3, 4, 5]:
                    transfers_available = True

            logger.info(f"   Transfer window check: {now_eastern.strftime('%A %I:%M %p %Z')} - Available: {transfers_available}")

            return {
                "available": transfers_available,
                "current_time": now_eastern.strftime('%I:%M %p %Z'),
                "current_day": now_eastern.strftime('%A'),
                "transfer_window": "Monday-Saturday, 8:00 AM - 2:00 AM Eastern",
                "message": "Transfers available now" if transfers_available else "Transfers not available - will schedule callback"
            }

        else:
            return {"error": f"Unknown function: {function_name}"}

    except Exception as e:
        logger.error(f"? Error executing function {function_name}: {e}")
        logger.error(traceback.format_exc())
        return {"error": f"Function execution failed: {str(e)}"}

# ------------------------------------------------------------------------------
# FASTAPI APP
# ------------------------------------------------------------------------------
app = FastAPI(title="Voice Agent Bridge")

@app.get("/")
def root():
    return {
        "ok": True,
        "service": "Voice Agent Bridge",
        "version": "28.0 - HD voice + JSON voice properties (no inline SSML)",
        "api": "Azure Voice Live API",
        "model": AZURE_AI_MODEL,
        "voices": "Per-company Azure TTS voices (600+ voices supported)",
        "voice_options": {
            "friendly_names": list(AZURE_VOICE_MAP.keys()),
            "direct_azure_voices": "Any Azure Neural voice (e.g., en-US-AriaNeural, es-MX-DaliaNeural, fr-FR-DeniseNeural)",
            "full_list": "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts"
        },
        "audio_format": "PCM16 24kHz passthrough",
        "features": [
            "Function calling (ZIP lookup, transfer window)",
            "Grace period to prevent race conditions (500ms transcript wait)",
            "Per-company Azure TTS voice selection (600+ voices)",
            "Friendly names OR direct Azure voice names",
            "Semantic VAD with filler removal",
            "Deep noise suppression",
            "Echo cancellation",
            "Whisper transcription",
            "Native audio streaming",
            "Natural conversation flow",
            "Call recordings & transcripts" if SAVE_RECORDINGS or SAVE_TRANSCRIPTS else None
        ],
        "functions": [
            {"name": "lookup_zipcode", "description": "Get city and state from ZIP code"},
            {"name": "transfer_window_check", "description": "Check if live agent transfers are available (Mon-Sat 8AM-2AM Eastern)"}
        ]
    }

# ------------------------------------------------------------------------------
# CALLER ID CACHE (for cXML webhook integration)
# ------------------------------------------------------------------------------
# Store caller ID from initial webhook, retrieved later during WebSocket connection
call_metadata_cache: Dict[str, Dict[str, Any]] = {}

def cache_call_metadata(call_sid: str, metadata: Dict[str, Any], ttl_seconds: int = 300):
    """Cache call metadata with automatic expiration"""
    import time
    call_metadata_cache[call_sid] = {
        **metadata,
        "_expires_at": time.time() + ttl_seconds
    }
    logger.info(f"?? Cached metadata for call {call_sid}: {metadata}")

def get_cached_call_metadata(call_sid: str) -> Optional[Dict[str, Any]]:
    """Retrieve cached call metadata if not expired"""
    import time
    if call_sid in call_metadata_cache:
        metadata = call_metadata_cache[call_sid]
        if time.time() < metadata.get("_expires_at", 0):
            return {k: v for k, v in metadata.items() if not k.startswith("_")}
        else:
            del call_metadata_cache[call_sid]  # Expired, remove it
    return None

@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True, "status": "healthy"})

@app.post("/webhook/call/{company_id}")
async def signalwire_call_webhook(company_id: str, request: Request):
    """
    Webhook endpoint for SignalWire to send call information before streaming.

    This endpoint receives the initial call parameters (From, To, CallSid, etc.)
    and caches them so they're available when the WebSocket connects.

    Returns cXML that initiates the media stream.
    """
    try:
        # Parse form data from SignalWire webhook
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")

        logger.info(f"?? Webhook received: CallSid={call_sid}, From={from_number}, To={to_number}")

        # Cache the call metadata
        if call_sid and from_number:
            cache_call_metadata(call_sid, {
                "from": from_number,
                "to": to_number,
                "call_sid": call_sid
            })

        # Return cXML to start streaming
        stream_url = f"wss://voice-agents-bridge.victoriouswave-f95f67ff.eastus2.azurecontainerapps.io/voice/{company_id}"

        cxml_response = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}?call_sid={call_sid}"
            codec="L16@24000h" />
  </Connect>
</Response>'''

        return Response(content=cxml_response, media_type="application/xml")

    except Exception as e:
        logger.error(f"? Webhook error: {e}")
        logger.error(traceback.format_exc())
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
                       media_type="application/xml")

@app.get("/companies/{company_id}/config")
def get_company_config(company_id: str):
    try:
        config = get_cached_config(company_id)
        if not config or not config.get('company-name'):
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        return {"company_id": company_id, "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/companies/{company_id}/audio-settings")
def get_company_audio_settings(company_id: str):
    try:
        settings = config_manager.get_audio_settings(company_id)
        return {"company_id": company_id, "audio_settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------------------------
# COST MONITORING API ENDPOINTS
# ------------------------------------------------------------------------------

@app.get("/costs/daily")
def get_daily_costs(date: Optional[str] = None):
    """Get daily cost summary

    Args:
        date: Date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        Daily cost summary with breakdown
    """
    try:
        summary = cost_tracker.get_daily_summary(date)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/costs/call/{call_sid}")
def get_call_costs(call_sid: str):
    """Get cost breakdown for a specific call

    Args:
        call_sid: Call identifier

    Returns:
        Detailed cost breakdown for the call
    """
    try:
        if call_sid not in cost_tracker.call_costs:
            raise HTTPException(status_code=404, detail=f"Call {call_sid} not found in cost tracker")

        from dataclasses import asdict
        cost_data = asdict(cost_tracker.call_costs[call_sid])
        return cost_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/costs/pricing")
def get_pricing_info():
    """Get current pricing configuration

    Returns:
        Current pricing rates per component
    """
    return {
        "currency": "USD",
        "pricing_version": "2024-11",
        "components": {
            "openai_realtime_api": {
                "input_audio_per_million_tokens": cost_tracker.PRICE_INPUT_AUDIO_PER_MILLION,
                "output_audio_per_million_tokens": cost_tracker.PRICE_OUTPUT_AUDIO_PER_MILLION,
                "input_text_per_million_tokens": cost_tracker.PRICE_INPUT_TEXT_PER_MILLION,
                "output_text_per_million_tokens": cost_tracker.PRICE_OUTPUT_TEXT_PER_MILLION
            },
            "signalwire": {
                "inbound_per_minute": cost_tracker.PRICE_SIGNALWIRE_PER_MINUTE
            },
            "azure_infrastructure": {
                "container_apps_per_minute": cost_tracker.PRICE_CONTAINER_APPS_PER_MINUTE,
                "storage_per_call": cost_tracker.PRICE_STORAGE_PER_CALL
            }
        },
        "estimated_cost_per_minute": {
            "min": 0.015,
            "max": 0.017,
            "description": "Estimated total cost per minute of conversation"
        }
    }

# ------------------------------------------------------------------------------
# MAIN WEBSOCKET BRIDGE
# ------------------------------------------------------------------------------
@app.websocket("/voice/{company_id}")
async def voice_bridge(company_id: str, signalwire_ws: WebSocket):
    await signalwire_ws.accept()

    # Extract caller ID from query parameters and call metadata cache
    query_params = dict(signalwire_ws.query_params)

    # DEBUG: Log all query parameters
    if query_params:
        logger.info(f"?? Query parameters received: {query_params}")
    else:
        logger.info(f"?? No query parameters in WebSocket URL")

    # Try to get caller ID from:
    # 1. Query parameters (direct pass-through)
    # 2. Call metadata cache (webhook-based approach)
    query_caller_id = query_params.get("caller_id") or query_params.get("from")

    # If call_sid is in query params, look up cached metadata
    call_sid_param = query_params.get("call_sid")
    if call_sid_param and not query_caller_id:
        cached_metadata = get_cached_call_metadata(call_sid_param)
        if cached_metadata:
            query_caller_id = cached_metadata.get("from")
            logger.info(f"? Retrieved caller ID from cache: {query_caller_id}")

    if query_caller_id:
        logger.info(f"? SignalWire connection accepted for company: {company_id} (Caller ID: {query_caller_id})")
    else:
        logger.info(f"? SignalWire connection accepted for company: {company_id}")

    try:
        company_config = get_cached_config(company_id)
        if not company_config or not company_config.get('company-name'):
            msg = f"Company '{company_id}' not found in configuration"
            logger.error(msg)
            await signalwire_ws.send_text(json.dumps({"type": "error", "source": "config", "detail": msg}))
            await signalwire_ws.close(code=1008)
            return
        
        company_name = company_config['company-name']
        audio_settings = company_config.get('audio-settings', {})
        logger.info(f"? Loaded config for {company_name}")
    except Exception as e:
        msg = f"Failed to load company configuration: {e}"
        logger.error(msg)
        await signalwire_ws.send_text(json.dumps({"type": "error", "source": "config", "detail": msg}))
        await signalwire_ws.close(code=1011)
        return

    shared_state: Dict[str, Any] = {
        "call_session": None,
        "stream_sid": None,
        "monitor": SessionMonitor(company_id),  # Add session monitor
        "query_caller_id": query_caller_id,  # Caller ID from URL query parameters
        "greeting_done": False,  # Track when greeting completes (prevents race condition)
        "company_id": company_id  # Add company_id for conditional logic
    }
    voicelive_connection = None
    heartbeat_task = None

    try:
        instructions, voice_name, greeting_text = build_company_instructions(company_config)

        # Get heartbeat interval from config
        heartbeat_interval = audio_settings.get('heartbeat-interval-seconds', 30)

        # Get connection manager and session config from retry helper
        connection_manager, session_config = await create_voicelive_connection_with_retry(
            instructions, voice_name, audio_settings
        )

        # Use async context manager to ensure proper connection cleanup
        async with connection_manager as voicelive_connection:

            # Configure session AFTER entering context (when .session is available)
            await voicelive_connection.session.update(session=session_config)
            logger.info("? Voice Live session configured successfully with function calling")

            # Log connection lifecycle for monitoring
            call_start = datetime.now(UTC)
            logger.info(
                "?? Voice Live connection opened",
                extra={
                    "call_sid": call_sid_param or "pending",  # Use query param or "pending" (stream not started yet)
                    "company_id": company_id,
                    "timestamp": call_start.isoformat()
                }
            )

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(
                heartbeat_loop(voicelive_connection, shared_state["monitor"], heartbeat_interval)
            )

            logger.info(f"? Voice Live API connected with monitoring for {company_name}")

            # Start bidirectional audio forwarding
            audio_sender_task = asyncio.create_task(
                send_signalwire_audio_to_voicelive(signalwire_ws, voicelive_connection, company_id, company_name, shared_state, greeting_text)
            )
            logger.info(f"??? {company_name} agent ready for calls!")

            try:
                # Process events from Voice Live API
                async for event in voicelive_connection:
                    try:
                        call_session = shared_state.get("call_session")
                        stream_sid = shared_state.get("stream_sid")
                        monitor = shared_state.get("monitor")

                        # Pass monitor and shared_state to event handler
                        await handle_voicelive_event(
                            event, signalwire_ws, voicelive_connection,
                            company_name, stream_sid, call_session,
                            monitor,  # Add monitor parameter
                            shared_state  # Add shared_state for context injection
                        )
                    except Exception as e:
                        logger.error(f"Error handling Voice Live event: {e}")
                        monitor = shared_state.get("monitor")
                        if monitor:
                            monitor.add_error(str(e))
                        logger.error(traceback.format_exc())
            except Exception as e:
                logger.info(f"Voice Live connection closed for {company_name}: {e}")
            finally:
                # Cancel audio sender task
                audio_sender_task.cancel()
                try:
                    await audio_sender_task
                except asyncio.CancelledError:
                    pass

                # Clean up heartbeat task with timeout
                if heartbeat_task:
                    heartbeat_task.cancel()
                    try:
                        await asyncio.wait_for(heartbeat_task, timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

                # Log session summary (protected - won't swallow exceptions)
                try:
                    monitor = shared_state.get("monitor")
                    if monitor:
                        monitor.log_summary()
                except Exception as e:
                    logger.warning(f"Failed to log session summary: {e}")

                # Log connection close for monitoring
                call_duration = (datetime.now(UTC) - call_start).total_seconds()

                # Get call_sid from session if available, otherwise from query param
                call_session = shared_state.get("call_session")
                session_call_sid = call_session.call_sid if call_session else None

                logger.info(
                    "?? Voice Live connection closed",
                    extra={
                        "call_sid": session_call_sid or call_sid_param or "unknown",
                        "company_id": company_id,
                        "duration_seconds": call_duration,
                        "timestamp": datetime.now(UTC).isoformat()
                    }
                )

            # Connection automatically closed when exiting async with block

    except Exception as e:
        msg = f"Voice Live connection failed: {e}"
        logger.error(msg)
        logger.error(traceback.format_exc())
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({"type": "error", "source": "voicelive", "detail": str(e)}))
            await signalwire_ws.close(code=1011)

# ------------------------------------------------------------------------------
# VOICE LIVE ? SIGNALWIRE EVENT HANDLER
# ------------------------------------------------------------------------------

# Response tracking to detect and suppress audio-only responses (prevents <|audio_text|> token)
INVALID_TOKEN_LITERALS = {"<|audio_text|>", "<|text_hbr_audio|>", "<|end_of_text|>"}
AUDIO_VALIDATION_HOLD_SECONDS = 2.0  # Max time to buffer audio while waiting for safe transcript - increased for safety
AUDIO_BUFFER_MAX_CHUNKS = 48  # Safety cap to avoid unbounded buffering


class ResponseTracker:
    """Track whether current response has text to prevent audio-only responses"""
    def __init__(self):
        self.current_response_has_text = False
        self.suppressed_audio_count = 0
        self.has_invalid_token = False  # Track if response contains invalid token
        self.transcript_buffer = ""  # Buffer to accumulate transcript deltas
        self.recovery_attempted = False  # Prevent double recovery after invalid token suppression
        self.suppress_next_audio_chunk = False  # Suppress only the chunk tied to invalid token
        self.chunks_to_suppress = 0  # Counter for multiple chunk suppression (audio arrives before transcript)
        self.awaiting_assistant_text = True  # Gate audio streaming until we have safe assistant text
        self.audio_buffer: List[bytes] = []  # Buffer of audio chunks waiting for validation
        self.audio_hold_started_at: Optional[float] = None

    def start_response(self):
        """Reset for new response"""
        self.current_response_has_text = False
        self.suppressed_audio_count = 0
        self.has_invalid_token = False
        self.transcript_buffer = ""  # Reset buffer
        self.recovery_attempted = False  # Reset recovery flag
        self.suppress_next_audio_chunk = False  # Reset per-chunk suppression flag
        self.chunks_to_suppress = 0  # Reset chunk counter
        self.awaiting_assistant_text = True
        self.audio_buffer = []
        self.audio_hold_started_at = time()

    def add_transcript_delta(self, delta_text: str):
        """Add transcript delta and check for invalid tokens"""
        self.transcript_buffer += delta_text

        # Check if the accumulated buffer contains specific invalid tokens
        # Using explicit list instead of broad regex to avoid false positives
        if any(token in self.transcript_buffer for token in INVALID_TOKEN_LITERALS):
            logger.error(f"dYs? INVALID TOKEN DETECTED IN TRANSCRIPT BUFFER: '{self.transcript_buffer}'")
            self.has_invalid_token = True
            self.suppress_next_audio_chunk = True
            self.chunks_to_suppress = 5  # Suppress multiple chunks since audio arrives before transcript
            self.drop_audio_buffer()
            return True  # Signal that invalid token was found
        return False

    def mark_text_received(self, from_assistant: bool = True) -> bool:
        """Mark that assistant text was received; returns True if this is the first assistant text chunk"""
        if not from_assistant:
            return False
        first_text = not self.current_response_has_text
        self.current_response_has_text = True
        if first_text:
            self.awaiting_assistant_text = False
        return first_text

    def mark_invalid_token(self):
        """Mark that response contains invalid token (suppresses next audio chunks)"""
        self.has_invalid_token = True
        self.suppress_next_audio_chunk = True
        self.chunks_to_suppress = 5  # Suppress multiple chunks to catch bad audio
        self.awaiting_assistant_text = False
        self.drop_audio_buffer()

    def should_forward_audio(self) -> bool:
        """Return True if audio should be forwarded (has text and no invalid tokens)"""
        return self.current_response_has_text and not self.has_invalid_token

    def should_buffer_audio(self) -> bool:
        """Return True if audio should stay buffered until assistant text is validated

        Note: This is a pure query method - call check_buffer_timeout() separately
        to handle timeout side effects.
        """
        return self.awaiting_assistant_text

    def check_buffer_timeout(self) -> bool:
        """Check if buffer timeout exceeded and update state if needed

        Returns:
            bool: True if timeout was just exceeded and buffer should be flushed
        """
        if not self.awaiting_assistant_text:
            return False
        if self.audio_hold_started_at and (time() - self.audio_hold_started_at) > AUDIO_VALIDATION_HOLD_SECONDS:
            logger.warning("dYs? Audio hold exceeded 750ms while waiting for transcript - releasing buffer to avoid long silence")
            self.awaiting_assistant_text = False
            return True  # Timeout exceeded - caller should flush
        return False

    def buffer_audio_chunk(self, chunk: bytes) -> bool:
        """Store audio chunks until we confirm the transcript is safe

        Returns:
            bool: True if buffer cap was just reached and should be flushed immediately
        """
        self.audio_buffer.append(chunk)
        if len(self.audio_buffer) >= AUDIO_BUFFER_MAX_CHUNKS:
            logger.warning("⚠️ Audio buffer reached safety cap before transcript validation - forcing release")
            self.awaiting_assistant_text = False
            return True  # Cap reached - caller should flush immediately
        return False

    def drain_audio_buffer(self) -> List[bytes]:
        """Return buffered chunks and clear the buffer"""
        if not self.audio_buffer:
            return []
        buffered = self.audio_buffer[:]
        self.audio_buffer.clear()
        return buffered

    def drop_audio_buffer(self):
        """Discard buffered chunks (used when invalid tokens are detected)"""
        if self.audio_buffer:
            logger.warning(f"dYs? Dropping {len(self.audio_buffer)} buffered audio chunk(s) due to invalid token detection")
        self.audio_buffer.clear()

    def should_suppress_next_chunk(self) -> bool:
        """Return True if the next audio chunk should be suppressed"""
        # Check counter first (handles multiple chunks)
        if self.chunks_to_suppress > 0:
            self.chunks_to_suppress -= 1
            return True
        return self.suppress_next_audio_chunk

    def clear_chunk_suppression(self):
        """Clear per-chunk suppression flag after suppressing"""
        self.suppress_next_audio_chunk = False

    def suppress_audio(self):
        """Count a suppressed audio chunk"""
        self.suppressed_audio_count += 1

    def log_suppression(self):
        """Log if audio was suppressed"""
        if self.has_invalid_token and self.suppressed_audio_count > 0:
            logger.warning(f"?s??,? Suppressed {self.suppressed_audio_count} audio chunks containing invalid <|audio_text|> token")
        elif not self.current_response_has_text and self.suppressed_audio_count > 0:
            logger.warning(f"?s??,? Suppressed {self.suppressed_audio_count} audio-only chunks (no text)")
# Global response tracker instance
response_tracker = ResponseTracker()


async def _forward_audio_chunk(
    audio_bytes: bytes,
    signalwire_ws: WebSocket,
    stream_sid: Optional[str],
    call_session: Optional[CallSession]
):
    """Encode audio chunk to base64, optionally save it, and forward to SignalWire"""
    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

    if call_session and SAVE_RECORDINGS:
        try:
            call_session.add_ai_audio(audio_b64)
        except Exception:
            pass

    logger.debug("dY\"S Forwarding audio to SignalWire")
    await signalwire_ws.send_text(json.dumps({
        "event": "media",
        "streamSid": stream_sid or "",
        "media": {"payload": audio_b64}
    }))


async def _flush_buffered_audio(
    tracker: ResponseTracker,
    signalwire_ws: WebSocket,
    stream_sid: Optional[str],
    call_session: Optional[CallSession]
):
    """Flush any buffered audio chunks now that transcript validation succeeded"""
    buffered_chunks = tracker.drain_audio_buffer()
    if not buffered_chunks:
        return

    logger.debug(f"dY\"S Releasing {len(buffered_chunks)} buffered audio chunk(s) after transcript validation")
    for chunk in buffered_chunks:
        await _forward_audio_chunk(chunk, signalwire_ws, stream_sid, call_session)


async def handle_voicelive_event(
    event,  # Voice Live SDK event object
    signalwire_ws: WebSocket,
    voicelive_connection,
    company_name: str,
    stream_sid: Optional[str],
    call_session: Optional[CallSession],
    monitor: Optional[SessionMonitor] = None,  # Add monitor parameter
    shared_state: Optional[Dict[str, Any]] = None  # Add shared_state for context injection
):
    """Handle events from Voice Live API and forward to SignalWire"""
    logger.debug(f"?? Voice Live event: {event.type}")

    # ----------------------------------------------------------------------
    # COMPANY-SPECIFIC BEHAVIOR CONTROL
    # ----------------------------------------------------------------------
    # Determine if using minimal mode (test-basic company)
    company_id = shared_state.get("company_id") if shared_state else None
    is_minimal = (company_id == "test-basic")

    if is_minimal:
        logger.debug("?? Minimal mode active - bypassing complex logic")

    # ----------------------------------------------------------------------
    # TRANSCRIPT LOGGING
    # ----------------------------------------------------------------------
    # Log user speech transcripts
    event_type_str = str(event.type)
    event_type_lower = event_type_str.lower()

    # Special handling for response.audio_transcript.delta - strip invalid tokens
    # ONLY for non-minimal mode (test-basic skips this complexity)
    if not is_minimal:
        if event_type_str == 'ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA' or 'audio_transcript.delta' in event_type_lower:
            if hasattr(event, 'delta') and event.delta:
                delta_text = str(event.delta)

                # Strip denylisted literals from the delta before buffering
                stripped_delta = delta_text
                for literal in INVALID_TOKEN_LITERALS:
                    if literal in stripped_delta:
                        stripped_delta = stripped_delta.replace(literal, "")
                        logger.debug(f"?? Stripped denylisted literal '{literal}' from transcript delta")

                # If nothing remains after stripping, skip buffering
                if not stripped_delta.strip():
                    if delta_text.strip():  # Only log if there was content before stripping
                        logger.debug(f"?? Skipping transcript delta after stripping denylisted literals: '{delta_text}'")
                    return

                # Add to buffer and check for invalid tokens
                if response_tracker.add_transcript_delta(stripped_delta):
                    # Invalid token detected! Suppress audio and log
                    logger.error("🚨 INVALID TOKEN IN DELTA - Audio will be suppressed")
                    monitor.add_invalid_token()  # Track for metrics
                    return

                # Mark that we received clean assistant text and flush buffered audio
                first_text = response_tracker.mark_text_received(from_assistant=True)
                if first_text:
                    await _flush_buffered_audio(response_tracker, signalwire_ws, stream_sid, call_session)

                # Don't log individual delta characters/words - too noisy
                return  # Skip further processing for delta events

    if 'transcription' in event_type_lower or 'transcript' in event_type_lower:
        transcript_text = None
        if hasattr(event, 'transcript'):
            transcript_text = event.transcript
        elif hasattr(event, 'text'):
            transcript_text = event.text
        elif hasattr(event, 'content'):
            transcript_text = event.content

        if transcript_text:
            # Filter out invalid tokens from transcript (ONLY in non-minimal mode)
            if not is_minimal:
                INVALID_TOKENS = {"null", ""}
                transcript_str = str(transcript_text)
                matched_tokens = [token for token in INVALID_TOKEN_LITERALS if token in transcript_str]
                cleaned_transcript = transcript_str

                # Strip matched tokens from transcript
                for token in matched_tokens:
                    cleaned_transcript = cleaned_transcript.replace(token, " ")

                cleaned_transcript = cleaned_transcript.strip()

                if matched_tokens:
                    if cleaned_transcript:
                        logger.info(f"?? Stripped invalid token(s) {matched_tokens} from transcript")
                    else:
                        logger.warning(f"?? Dropped transcript containing only invalid token(s) {matched_tokens}")
                        response_tracker.mark_invalid_token()
                        return

                if cleaned_transcript and cleaned_transcript not in INVALID_TOKENS:
                    # Note: This could be user OR assistant transcript depending on event type
                    logger.info(f"?? TRANSCRIPT: {cleaned_transcript}")
                    is_assistant_transcript = "response" in event_type_lower
                    if is_assistant_transcript:
                        first_assistant_text = response_tracker.mark_text_received(from_assistant=True)
                        if first_assistant_text:
                            await _flush_buffered_audio(response_tracker, signalwire_ws, stream_sid, call_session)

                    # Save transcript to session
                    if call_session:
                        # Determine speaker based on event type
                        speaker = "assistant" if is_assistant_transcript else "user"
                        call_session.add_transcript_entry(speaker, cleaned_transcript)
                else:
                    logger.warning(f"?? FILTERED INVALID TRANSCRIPT CONTENT: '{transcript_text}'")
            else:
                # Minimal mode: just log and save transcript, no filtering
                logger.info(f"?? TRANSCRIPT: {transcript_text}")
                if call_session:
                    speaker = "assistant" if "response" in event_type_lower else "user"
                    call_session.add_transcript_entry(speaker, transcript_text)

    # Log AI response text and filter invalid tokens (ONLY in non-minimal mode)
    if not is_minimal:
        if 'text' in event_type_lower and 'delta' in event_type_lower:
            response_text = None
            if hasattr(event, 'delta'):
                response_text = event.delta
            elif hasattr(event, 'text'):
                response_text = event.text

            if response_text and isinstance(response_text, str):
                INVALID_TOKENS = {"null", ""}
                delta_str = response_text
                matched_tokens = [token for token in INVALID_TOKEN_LITERALS if token in delta_str]
                cleaned_response = delta_str

                # Strip matched tokens from response text
                for token in matched_tokens:
                    cleaned_response = cleaned_response.replace(token, " ")

                cleaned_response = cleaned_response.strip()
                delta_is_token_only = False

                if matched_tokens:
                    if cleaned_response:
                        logger.info(f"?? Stripped invalid token(s) {matched_tokens} from text delta")
                    else:
                        delta_is_token_only = True
                        logger.warning(f"?? Dropped invalid token-only text delta: {matched_tokens}")

                if cleaned_response and cleaned_response not in INVALID_TOKENS:
                    logger.info(f"?? AI RESPONSE TEXT: {cleaned_response}")
                    # Mark that valid text was received for this response
                    first_text_chunk = response_tracker.mark_text_received(from_assistant=True)
                    if first_text_chunk:
                        await _flush_buffered_audio(response_tracker, signalwire_ws, stream_sid, call_session)
                elif cleaned_response in INVALID_TOKENS:
                    logger.warning(f"?? Dropped empty/invalid text delta: '{response_text}'")
                    response_tracker.mark_invalid_token()

                if delta_is_token_only:
                    response_tracker.mark_invalid_token()

    # Log content parts (might contain text)
    if 'content_part' in event_type_lower or 'output_item' in event_type_lower:
        if hasattr(event, 'part') and hasattr(event.part, 'text'):
            logger.info(f"?? AI RESPONSE: {event.part.text}")
        elif hasattr(event, 'item'):
            if hasattr(event.item, 'content') and isinstance(event.item.content, list):
                for content in event.item.content:
                    if hasattr(content, 'text'):
                        logger.info(f"?? AI RESPONSE: {content.text}")

    # ----------------------------------------------------------------------
    # TOKEN USAGE AND RATE LIMIT MONITORING
    # ----------------------------------------------------------------------
    # Monitor token usage
    if hasattr(event, 'usage') or 'usage' in str(event.type).lower():
        if monitor and hasattr(event, 'usage'):
            usage = event.usage
            if hasattr(usage, 'input_tokens') and hasattr(usage, 'output_tokens'):
                input_tokens = usage.input_tokens
                output_tokens = usage.output_tokens
                total_tokens = input_tokens + output_tokens

                logger.info(f"?? Token usage - Input: {input_tokens:,}, Output: {output_tokens:,}, Total: {total_tokens:,}")
                monitor.add_tokens(input_tokens, output_tokens)

    # Track rate limits
    if hasattr(event, 'rate_limits') or 'rate_limit' in str(event.type).lower():
        if hasattr(event, 'rate_limits'):
            rate_limits = event.rate_limits
            if hasattr(rate_limits, 'remaining_tokens'):
                remaining = rate_limits.remaining_tokens
                if remaining < 10000:
                    logger.warning(f"?? Rate limit warning: {remaining:,} tokens remaining")

    # Track VAD events for monitoring
    if monitor:
        if event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            monitor.add_vad_trigger()
            monitor.add_turn()  # New turn started

        elif event.type == ServerEventType.ERROR:
            error_msg = getattr(event, 'error', {}).get('message', 'Unknown error') if hasattr(event, 'error') else 'Unknown error'
            monitor.add_error(error_msg)

    # ----------------------------------------------------------------------
    # STANDARD EVENT HANDLING
    # ----------------------------------------------------------------------
    if event.type == ServerEventType.SESSION_UPDATED:
        logger.info(f"? {company_name} Voice Live session ready")

    elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
        # BARGE-IN HANDLING: Only for non-minimal mode
        if not is_minimal:
            # v17.6: Check if this is REAL barge-in or normal turn-taking
            if call_session and call_session.agent_is_speaking:
                logger.info("?? REAL BARGE-IN: Caller interrupting Sarah - executing cancellation")
                monitor.add_barge_in()  # Track barge-in for metrics

                # ------------------------------------------------------------------
                # TRIPLE-ACTION BARGE-IN PATTERN (Distributed Cancellation)
                # ------------------------------------------------------------------

                # ACTION 1: Clear SignalWire audio buffer (stops playback immediately)
                if stream_sid and signalwire_ws.application_state == WebSocketState.CONNECTED:
                    try:
                        await signalwire_ws.send_json({
                            "event": "clear",
                            "streamSid": stream_sid
                        })
                        logger.info("?? ACTION 1: Sent CLEAR to SignalWire - flushed audio buffer")
                    except Exception as e:
                        logger.warning(f"Failed to clear SignalWire buffer: {e}")

                # ACTION 2: Cancel Azure response generation
                try:
                    await voicelive_connection.response.cancel()
                    logger.info("?? ACTION 2: Sent response.cancel to Azure")
                except Exception as e:
                    logger.warning(f"Failed to cancel response: {e}")

                # ACTION 3: Inject context system message for conversational recovery
                # Use SDK's send method directly (same pattern as function calling)
                try:
                    raw_message = {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "system",
                            "content": [{"type": "input_text", "text": "SYSTEM: User interrupted. Respond verbally with a brief acknowledgment and listen for their input."}]
                        }
                    }

                    # Use SDK's send method (send dict, not JSON string)
                    if hasattr(voicelive_connection, 'send'):
                        await voicelive_connection.send(raw_message)
                        logger.info("?? ACTION 3: Injected interruption context via connection.send()")
                    elif hasattr(voicelive_connection, '_connection') and hasattr(voicelive_connection._connection, 'send'):
                        await voicelive_connection._connection.send(raw_message)
                        logger.info("?? ACTION 3: Injected interruption context via _connection.send()")
                    else:
                        logger.warning("?? Could not access send method for context injection")
                except Exception as e:
                    logger.warning(f"Failed to inject context: {e}")

                # Clear flag immediately (response was cancelled)
                call_session.agent_is_speaking = False
                logger.debug("?? Agent speaking flag CLEARED (interrupted)")

            else:
                # Normal turn-taking: Sarah finished, user responding naturally
                logger.info("?? User started speaking (normal turn-taking, no interruption)")
        else:
            # Minimal mode: just log that user started speaking
            logger.info("?? User started speaking (minimal mode - no barge-in logic)")

    elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
        logger.info("?? Caller stopped speaking")

        # GRACE PERIOD: Only in non-minimal mode
        if not is_minimal:
            # Wait 500ms for transcript to arrive before AI responds
            # This prevents race condition where AI responds before hearing the transcript
            # Evidence from production: transcript takes ~360ms to arrive after VAD stops
            logger.info("? Waiting 500ms grace period for transcript...")
            await asyncio.sleep(0.5)
            logger.info("? Grace period complete, transcript should be available")

    elif event.type == ServerEventType.RESPONSE_CREATED:
        logger.info(f"?? {company_name} AI responding")

        # Reset response tracker for new response (ONLY in non-minimal mode)
        if not is_minimal:
            response_tracker.start_response()

            # Mark agent as speaking (v17.6 - for barge-in detection)
            if call_session:
                call_session.agent_is_speaking = True
                logger.debug("?? Agent speaking flag SET")

    elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
        if signalwire_ws.application_state != WebSocketState.CONNECTED:
            return

        # Voice Live SDK returns audio as bytes in event.delta
        audio_bytes = event.delta
        if not audio_bytes:
            return

        # CRITICAL: Audio suppression & buffering (ONLY in non-minimal mode)
        if not is_minimal:
            # Additional safety check: string data likely means malformed token payload
            if isinstance(audio_bytes, str):
                logger.warning(f"?? SUPPRESSING STRING AUDIO DATA: '{audio_bytes}' (expected bytes)")
                response_tracker.mark_invalid_token()
                response_tracker.suppress_audio()
                response_tracker.clear_chunk_suppression()
                return

            # Suppress only the chunk tied to the invalid token, then resume
            if response_tracker.should_suppress_next_chunk():
                response_tracker.suppress_audio()
                response_tracker.clear_chunk_suppression()
                logger.warning("?? SUPPRESSING AUDIO CHUNK - Invalid token detected (preventing 'audio underscore text' speech)")
                return

            # Buffer audio until we have validated assistant text to avoid leaking control tokens
            if response_tracker.should_buffer_audio():
                # Check timeout first before buffering
                timeout_exceeded = response_tracker.check_buffer_timeout()
                if timeout_exceeded:
                    # Timeout exceeded - flush immediately
                    await _flush_buffered_audio(response_tracker, signalwire_ws, stream_sid, call_session)
                    logger.debug("?? Buffer timeout exceeded - flushed all buffered audio")
                else:
                    # Buffer this chunk and check if cap reached
                    cap_reached = response_tracker.buffer_audio_chunk(audio_bytes)
                    if cap_reached:
                        # Buffer cap reached - flush immediately
                        await _flush_buffered_audio(response_tracker, signalwire_ws, stream_sid, call_session)
                        logger.debug("?? Buffer cap reached - flushed all buffered audio")
                    else:
                        logger.debug("?? Buffering audio chunk while waiting for transcript validation")
                return

            # Flush any buffered audio now that transcript validation has passed
            await _flush_buffered_audio(response_tracker, signalwire_ws, stream_sid, call_session)

        # Forward audio to SignalWire (minimal mode streams immediately)
        await _forward_audio_chunk(audio_bytes, signalwire_ws, stream_sid, call_session)

    elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
        logger.info(f"?? {company_name} finished speaking")
        # Log if we suppressed audio-only chunks (ONLY in non-minimal mode)
        if not is_minimal:
            response_tracker.log_suppression()

    elif event.type == ServerEventType.RESPONSE_DONE:
        # Check if response was cancelled or completed normally
        response_status = getattr(event, 'response', None)
        if response_status and hasattr(response_status, 'status'):
            if response_status.status == "cancelled":
                logger.info("? Response cancelled successfully (barge-in)")
            else:
                logger.info(f"? Response complete (status: {response_status.status})")
        else:
            logger.info("? Response complete")

        # Mark agent as not speaking and log suppression (ONLY in non-minimal mode)
        if not is_minimal:
            # Mark agent as not speaking (v17.6 - for barge-in detection)
            if call_session:
                call_session.agent_is_speaking = False
                logger.debug("?? Agent speaking flag CLEARED")

            # Log if we suppressed audio-only chunks
            response_tracker.log_suppression()

        # Context is now injected WITH greeting (single response.create call)
        # No separate context injection needed here

    elif event.type == ServerEventType.ERROR:
        error_msg = getattr(event, 'error', {}).get('message', 'Unknown error') if hasattr(event, 'error') else 'Unknown error'
        logger.error(f"? Voice Live error: {error_msg}")
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({
                "type": "error",
                "source": "voicelive",
                "detail": error_msg
            }))

    # ----------------------------------------------------------------------
    # FUNCTION CALLING EVENT HANDLING
    # ----------------------------------------------------------------------
    # Try to detect function call events - SDK may use different event types
    event_type_str = str(event.type) if hasattr(event, 'type') else None

    # Method 1: Check if this is a function call event
    if event_type_str and 'function_call' in event_type_str.lower():
        logger.info(f"?? Function call event detected: {event_type_str}")

        # Try to extract function call details
        function_name = None
        arguments = None
        call_id = None

        # Try SDK parsed attributes
        if hasattr(event, 'name'):
            function_name = event.name
        if hasattr(event, 'arguments'):
            try:
                arguments = json.loads(event.arguments) if isinstance(event.arguments, str) else event.arguments
            except:
                arguments = event.arguments
        if hasattr(event, 'call_id'):
            call_id = event.call_id

        logger.info(f"   Function: {function_name}, Args: {arguments}, CallID: {call_id}")

        if function_name and arguments:
            # Track function call
            if monitor:
                monitor.add_function_call(function_name)

            # NEW: Send pre-function feedback message
            if function_name in FUNCTION_FEEDBACK:
                try:
                    feedback_msg = FUNCTION_FEEDBACK[function_name]
                    await voicelive_connection.send_text(feedback_msg)
                    logger.info(f"?? Pre-function feedback: '{feedback_msg}'")
                except Exception as e:
                    logger.warning(f"Failed to send pre-function feedback: {e}")

            # Execute the function
            result = await execute_function(function_name, arguments)
            logger.info(f"   Function result: {result}")

            # Use raw WebSocket bypass (SDK conversation.item.create doesn't work)
            result_json = json.dumps(result)

            try:
                # Build the raw message format (bypassing SDK)
                raw_message = {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result_json
                    }
                }

                logger.info("?? Sending function result via SDK send method...")

                # Use the SDK's send method directly (send dict, not JSON string)
                if hasattr(voicelive_connection, 'send'):
                    await voicelive_connection.send(raw_message)
                    logger.info("? Function result sent via connection.send()")
                elif hasattr(voicelive_connection, '_connection') and hasattr(voicelive_connection._connection, 'send'):
                    await voicelive_connection._connection.send(raw_message)
                    logger.info("? Function result sent via _connection.send()")
                else:
                    # Log available attributes for debugging
                    attrs = [a for a in dir(voicelive_connection) if not a.startswith('__')]
                    logger.error(f"?? No send method found. Available: {attrs[:15]}")
                    raise AttributeError("Cannot access send method on connection")

                # Trigger the next response so AI can speak the result
                if hasattr(voicelive_connection, 'response'):
                    await voicelive_connection.response.create()
                    logger.info("? Triggered response.create() to continue conversation")

            except Exception as e:
                # WebSocket bypass failed
                logger.error(f"? WebSocket bypass failed: {e}")
                logger.error(traceback.format_exc())

                try:
                    # Build context-appropriate recovery message
                    if function_name == "lookup_zipcode":
                        recovery_prompt = (
                            f"IMPORTANT: Your tool call for '{function_name}' just failed. "
                            "Do not mention the tool or the error. "
                            "Simply ask the caller: 'Could you let me know your city and state?'"
                        )
                    else:
                        recovery_prompt = (
                            f"IMPORTANT: Your tool call for '{function_name}' just failed. "
                            "Do not mention the tool or the error. "
                            "Gracefully ask the user to provide the information manually."
                        )

                    # Use the SDK's *supported* response.create method
                    # to force the AI to speak again with new instructions
                    if hasattr(voicelive_connection, 'response'):
                        await voicelive_connection.response.create(
                            additional_instructions=recovery_prompt
                        )
                        logger.info("? Triggered SDK response.create() for graceful tool failure recovery.")
                except Exception as recovery_e:
                    logger.critical(f"? TOTAL FAILURE: Could not send function result AND could not trigger recovery response: {recovery_e}")
                    logger.error(traceback.format_exc())

    # Method 2: Check raw event data for function calls
    elif hasattr(event, '_raw') or hasattr(event, 'data'):
        raw_data = getattr(event, '_raw', None) or getattr(event, 'data', None)
        if raw_data and isinstance(raw_data, str):
            try:
                parsed = json.loads(raw_data)
                if parsed.get('type') == 'response.function_call_arguments.done':
                    logger.info("?? Function call detected in raw event data")
                    function_name = parsed.get('name')
                    arguments = json.loads(parsed.get('arguments', '{}'))
                    call_id = parsed.get('call_id')

                    if function_name:
                        # Track function call
                        if monitor:
                            monitor.add_function_call(function_name)

                        # NEW: Send pre-function feedback message
                        if function_name in FUNCTION_FEEDBACK:
                            try:
                                feedback_msg = FUNCTION_FEEDBACK[function_name]
                                await voicelive_connection.send_text(feedback_msg)
                                logger.info(f"?? Pre-function feedback: '{feedback_msg}' (Method 2)")
                            except Exception as e:
                                logger.warning(f"Failed to send pre-function feedback (Method 2): {e}")

                        result = await execute_function(function_name, arguments)
                        logger.info(f"   Function result: {result}")

                        # Use raw WebSocket bypass (SDK conversation.item.create doesn't work)
                        result_json = json.dumps(result)

                        try:
                            # Build the raw message format (bypassing SDK)
                            raw_message = {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": result_json
                                }
                            }

                            logger.info("?? Sending function result via SDK send method (Method 2)...")

                            # Use the SDK's send method directly (send dict, not JSON string)
                            if hasattr(voicelive_connection, 'send'):
                                await voicelive_connection.send(raw_message)
                                logger.info("? Function result sent via connection.send() (Method 2)")
                            elif hasattr(voicelive_connection, '_connection') and hasattr(voicelive_connection._connection, 'send'):
                                await voicelive_connection._connection.send(raw_message)
                                logger.info("? Function result sent via _connection.send() (Method 2)")
                            else:
                                # Log available attributes for debugging
                                attrs = [a for a in dir(voicelive_connection) if not a.startswith('__')]
                                logger.error(f"?? No send method found. Available: {attrs[:15]}")
                                raise AttributeError("Cannot access send method on connection")

                            # Trigger the next response so AI can speak the result
                            if hasattr(voicelive_connection, 'response'):
                                await voicelive_connection.response.create()
                                logger.info("? Triggered response.create() to continue conversation (Method 2)")

                        except Exception as e:
                            # WebSocket bypass failed
                            logger.error(f"? WebSocket bypass failed (Method 2): {e}")
                            logger.error(traceback.format_exc())

                            try:
                                # Build context-appropriate recovery message
                                if function_name == "lookup_zipcode":
                                    recovery_prompt = (
                                        f"IMPORTANT: Your tool call for '{function_name}' just failed. "
                                        "Do not mention the tool or the error. "
                                        "Simply ask the caller: 'Could you let me know your city and state?'"
                                    )
                                else:
                                    recovery_prompt = (
                                        f"IMPORTANT: Your tool call for '{function_name}' just failed. "
                                        "Do not mention the tool or the error. "
                                        "Gracefully ask the user to provide the information manually."
                                    )

                                # Use the SDK's *supported* response.create method
                                # to force the AI to speak again with new instructions
                                if hasattr(voicelive_connection, 'response'):
                                    await voicelive_connection.response.create(
                                        additional_instructions=recovery_prompt
                                    )
                                    logger.info("? Triggered SDK response.create() for graceful tool failure recovery (Method 2).")
                            except Exception as recovery_e:
                                logger.critical(f"? TOTAL FAILURE (Method 2): Could not send function result AND could not trigger recovery response: {recovery_e}")
                                logger.error(traceback.format_exc())
            except:
                pass  # Not a function call event

    # ----------------------------------------------------------------------
    # DEBUG: Log all event types to discover what we're missing
    # ----------------------------------------------------------------------
    # Log event details for debugging (helps find transcript events)
    event_type_str = str(event.type)
    if event_type_str not in [
        str(ServerEventType.RESPONSE_AUDIO_DELTA),  # Too verbose
        str(ServerEventType.SESSION_UPDATED),
        str(ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED),
        str(ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED),
        str(ServerEventType.RESPONSE_CREATED),
        str(ServerEventType.RESPONSE_AUDIO_DONE),
        str(ServerEventType.RESPONSE_DONE),
        str(ServerEventType.ERROR)
    ]:
        # Log unhandled events to discover new event types
        event_attrs = {k: v for k, v in event.__dict__.items() if not k.startswith('_')}
        logger.info(f"?? Event type: {event_type_str}")
        if event_attrs:
            logger.info(f"   Attributes: {event_attrs}")

# ------------------------------------------------------------------------------
# SIGNALWIRE ? VOICE LIVE AUDIO FORWARDER
# ------------------------------------------------------------------------------
async def send_signalwire_audio_to_voicelive(
    signalwire_ws: WebSocket,
    voicelive_connection,
    company_id: str,
    company_name: str,
    shared_state: Dict[str, Any],
    greeting_text: str
):
    logger.info(f"?? Audio forwarding started for {company_name}")

    stream_sid: Optional[str] = None
    call_session: Optional[CallSession] = None

    try:
        while True:
            msg = await signalwire_ws.receive()

            if msg["type"] == "websocket.disconnect":
                logger.info(f"?? SignalWire disconnected for {company_name}")
                break

            if "text" in msg and msg["text"] is not None:
                try:
                    data = json.loads(msg["text"])
                    event_name = data.get("event")

                    if event_name == "connected":
                        logger.info(f"?? SignalWire connected for {company_name}")

                    elif event_name == "start":
                        stream_sid = (data.get("start") or {}).get("streamSid")
                        start_data = data.get("start") or {}
                        media_format = start_data.get("mediaFormat", {})

                        # DEBUG: Log the full start event data
                        logger.info(f"?? Start event data: streamSid={stream_sid}, from={start_data.get('from')}, customParameters={start_data.get('customParameters')}")

                        # Extract caller ID with priority:
                        # 1. Query parameters (for cXML compatibility: ?caller_id=xxx or ?from=xxx)
                        # 2. customParameters.caller_id (from SWML custom_parameters)
                        # 3. customParameters.original_caller (P-Asserted-Identity from SIP headers)
                        # 4. start.from (basic SignalWire caller ID)
                        query_caller = shared_state.get("query_caller_id")
                        custom_params = start_data.get("customParameters", {})
                        raw_caller = (
                            query_caller or
                            custom_params.get("caller_id") or
                            custom_params.get("original_caller") or
                            start_data.get("from")
                        )

                        # Normalize caller ID to E.164 format
                        caller_phone = normalize_caller_id(raw_caller)

                        logger.info(f"?? Raw caller ID: {raw_caller}")
                        if query_caller:
                            logger.info(f"?? Caller ID source: URL query parameter")
                        elif custom_params.get("caller_id"):
                            logger.info(f"?? Caller ID source: SWML customParameters")
                        else:
                            logger.info(f"?? Caller ID source: SignalWire start.from")
                        logger.info(f"?? Normalized caller ID: {caller_phone}")

                        # Create call session
                        call_session = CallSession(company_id, stream_sid or "unknown")
                        shared_state["call_session"] = call_session
                        shared_state["stream_sid"] = stream_sid

                        # Start cost tracking
                        cost_tracker.start_call_tracking(stream_sid or "unknown", company_id)

                        logger.info(f"?? Call started for {company_name}")
                        logger.info(f"?? Caller ID: {caller_phone}")
                        logger.info(f"?? Audio format: {media_format}")

                        # Add business context
                        # Get business hours configuration for this company
                        company_config = get_cached_config(company_id)
                        business_hours_config = company_config.get('business-hours', {})
                        timezone_str = business_hours_config.get('timezone', 'US/Eastern')
                        business_days = business_hours_config.get('days', [0, 1, 2, 3, 4])  # 0=Monday, 6=Sunday
                        open_time_str = business_hours_config.get('open-time', '08:30')
                        close_time_str = business_hours_config.get('close-time', '17:00')

                        logger.info(f"?? Business hours config: timezone={timezone_str}, days={business_days}, open={open_time_str}, close={close_time_str}")

                        # Get current time in company's timezone (convert from UTC for reliability)
                        company_tz = pytz.timezone(timezone_str)
                        now_utc = datetime.now(UTC)
                        now_local = now_utc.astimezone(company_tz)

                        logger.info(f"?? Current time - UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}, Local: {now_local.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")

                        # Parse open and close times
                        open_hour, open_minute = map(int, open_time_str.split(':'))
                        close_hour, close_minute = map(int, close_time_str.split(':'))

                        current_time_minutes = now_local.hour * 60 + now_local.minute
                        open_time_minutes = open_hour * 60 + open_minute
                        close_time_minutes = close_hour * 60 + close_minute

                        # Check if hours span midnight (overnight, e.g., 8am-2am)
                        is_overnight = close_time_minutes < open_time_minutes

                        # Determine if currently in business hours
                        current_day = now_local.weekday()
                        previous_day = (current_day - 1) % 7

                        if is_overnight:
                            # Overnight hours (e.g., Mon 8am - Tue 2am)
                            # Two scenarios:
                            # 1. Current time is after open time on a business day (Mon 8am - Mon 11:59pm)
                            # 2. Current time is before close time and YESTERDAY was a business day (Tue 12am - Tue 2am)
                            in_hours_today = current_day in business_days and current_time_minutes >= open_time_minutes
                            in_hours_from_yesterday = previous_day in business_days and current_time_minutes < close_time_minutes
                            is_business_hours = in_hours_today or in_hours_from_yesterday

                            logger.info(f"?? Overnight hours detected: open={open_time_str}, close={close_time_str}")
                            logger.info(f"?? Business hours check: Day={now_local.strftime('%A')} ({current_day}), Time={now_local.strftime('%H:%M')}, in_hours_today={in_hours_today}, in_hours_from_yesterday={in_hours_from_yesterday}, is_business_hours={is_business_hours}")
                        else:
                            # Standard hours (e.g., Mon 8am - Mon 5pm)
                            is_business_day = current_day in business_days
                            is_within_hours = open_time_minutes <= current_time_minutes < close_time_minutes
                            is_business_hours = is_business_day and is_within_hours

                            logger.info(f"?? Standard hours: Day={now_local.strftime('%A')} ({current_day}), Time={now_local.strftime('%H:%M')}, is_business_day={is_business_day}, is_within_hours={is_within_hours}, is_business_hours={is_business_hours}")
                        
                        formatted_phone = caller_phone or "Unknown"
                        if caller_phone and len(caller_phone) == 12 and caller_phone.startswith('+1'):
                            # Strip the +1 country code - just send the 10 digits for easy reading
                            formatted_phone = caller_phone[2:]

                        logger.info(f"?? DEBUG FORMATTING: caller_phone='{caller_phone}', len={len(caller_phone) if caller_phone else 0}, formatted_phone='{formatted_phone}'")

                        # Get timezone abbreviation for display (e.g., "EST", "PDT")
                        tz_abbrev = now_local.strftime('%Z')

                        context_text = (
                            f"Current date: {now_local.strftime('%B %d, %Y')}\n"
                            f"Current day: {now_local.strftime('%A')}\n"
                            f"Current time: {now_local.strftime('%I:%M %p')} {tz_abbrev}\n"
                            f"Transfer window: Monday-Saturday, 8:00 AM - 2:00 AM Eastern\n"
                            f"Caller ID: {formatted_phone}"
                        )

                        # Prepare call context to inject into session instructions
                        # Using session.update() is cleaner than additional_instructions per Azure best practices
                        enhanced_context = f"""=== CALL CONTEXT (For This Call Only) ===

TRANSFER CONTEXT (Internal Use Only):
Date: {now_local.strftime('%B %d, %Y')}
Day: {now_local.strftime('%A')}
Time: {now_local.strftime('%I:%M %p')} {tz_abbrev}
Transfer Window: Monday-Saturday, 8:00 AM - 2:00 AM Eastern

CALLER INFORMATION:
Phone Number: {formatted_phone}

Use the provided context as instructed in your main prompt.
Follow all tool usage rules and call flow procedures exactly as specified."""

                        logger.info(f"?? Call context prepared")
                        logger.info(f"?? DEBUG FULL CONTEXT:\n{enhanced_context}")

                        # Update session instructions with caller context using session.update()
                        # This is cleaner and more explicit than using additional_instructions
                        updated_instructions = f"""{company_config.get('detailed-instructions', '')}

{enhanced_context}"""

                        session_config = RequestSession(instructions=updated_instructions)
                        await voicelive_connection.session.update(session=session_config)
                        logger.info("? Updated session with caller context via session.update()")

                        # Wait for audio stream to fully establish before greeting
                        await asyncio.sleep(1.5)

                        # Trigger greeting WITHOUT additional_instructions (context already in session)
                        await voicelive_connection.response.create()
                        shared_state["greeting_done"] = True  # Mark as done immediately
                        logger.info("? Triggered greeting (context injected via session.update)")

                    elif event_name == "media":
                        if not call_session:
                            continue

                        payload = (data.get("media") or {}).get("payload")
                        if not payload:
                            continue

                        # Save raw audio for recording
                        if SAVE_RECORDINGS:
                            call_session.add_caller_audio(payload)

                        # Direct forward - Voice Live API handles optimal chunking
                        try:
                            await voicelive_connection.input_audio_buffer.append(audio=payload)
                            logger.debug("?? Forwarded audio")
                        except Exception as e:
                            logger.error(f"Audio forward error: {e}")

                    elif event_name == "stop":
                        logger.info(f"?? Call ended for {company_name}")
                        if call_session:
                            try:
                                call_session.finalize()
                                await call_session.save_to_storage()
                                logger.info("? Call session saved successfully")

                                # Finalize and save cost tracking
                                if stream_sid:
                                    cost_breakdown = cost_tracker.finalize_call_costs(stream_sid)
                                    if cost_breakdown:
                                        await cost_tracker.save_call_costs(stream_sid)

                            except Exception as e:
                                logger.error(f"Failed to save call session: {e}")
                                logger.error(traceback.format_exc())
                        break

                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                except Exception as e:
                    logger.error(f"Error processing SignalWire message: {e}")
                    logger.error(traceback.format_exc())

    except asyncio.CancelledError:
        logger.info(f"?? Audio forwarding cancelled for {company_name}")
    except WebSocketDisconnect:
        logger.info(f"?? WebSocket disconnected for {company_name}")
    except Exception as e:
        logger.error(f"? Error in audio forwarding for {company_name}: {e}")
        logger.error(traceback.format_exc())
    finally:
        logger.info(f"?? Audio forwarding stopped for {company_name}")

# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)




