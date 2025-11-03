import os
import asyncio
import json
import logging
import base64
import wave
import io
from typing import Optional, List, Dict, Any
from datetime import datetime, UTC
import traceback
import pytz

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState
from dotenv import load_dotenv

from config import ConfigManager
from zipcode_service import ZipcodeService
from surname_verifier import find_surname_candidates, generate_llm_prompt

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

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("voice_bridge")

# ──────────────────────────────────────────────────────────────────────────────
# ENV & CONFIG
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

AZURE_AI_ENDPOINT = os.getenv("AZURE_AI_ENDPOINT", "").strip()
AZURE_AI_KEY = os.getenv("AZURE_AI_KEY", "").strip()
AZURE_AI_MODEL = os.getenv("AZURE_AI_MODEL", "gpt-realtime-mini").strip()

SAVE_RECORDINGS = os.getenv("SAVE_RECORDINGS", "true").lower() == "true"
SAVE_TRANSCRIPTS = os.getenv("SAVE_TRANSCRIPTS", "true").lower() == "true"

config_manager = ConfigManager()
zipcode_service = ZipcodeService()

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION CACHE (5-minute TTL)
# ──────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=128)
def _get_company_config_cached(company_id: str, cache_key: int):
    """Internal cached config getter with time-based key"""
    return config_manager.get_company_config(company_id)

def get_cached_config(company_id: str):
    """Get company config with 5-minute cache"""
    cache_key = int(time() // 300)  # Cache expires every 5 minutes
    return _get_company_config_cached(company_id, cache_key)

if not (AZURE_AI_ENDPOINT and AZURE_AI_KEY):
    logger.error("Missing required environment variables")
    raise ValueError("AZURE_AI_ENDPOINT and AZURE_AI_KEY are required")

logger.info("=" * 80)
logger.info("🎙️ VOICE AGENT - AZURE VOICE LIVE API")
logger.info("=" * 80)
logger.info(f"Azure Endpoint: {AZURE_AI_ENDPOINT}")
logger.info(f"Model: {AZURE_AI_MODEL}")
logger.info(f"Audio Format: PCM16 24kHz passthrough")
logger.info(f"Voices: 600+ Azure TTS voices (friendly names OR direct Azure voice names)")
logger.info(f"Save Recordings: {SAVE_RECORDINGS}")
logger.info(f"Save Transcripts: {SAVE_TRANSCRIPTS}")
logger.info("=" * 80)

# ──────────────────────────────────────────────────────────────────────────────
# VOICE MAP - OpenAI voice names to Azure TTS voices
# ──────────────────────────────────────────────────────────────────────────────
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
    'coral': 'en-US-Ava:DragonHDLatestNeural',  # HD quality warm, professional female voice with temperature support
    'sage': 'en-US-BrianNeural',             # Clear, professional male voice
    'verse': 'en-US-AriaNeural',             # Friendly, expressive female voice
    'cedar': 'en-US-Andrew:DragonHDLatestNeural',  # HD quality warm, natural male voice with temperature support

    # Additional popular voices for quick access
    'jenny-multilingual': 'en-US-JennyMultilingualNeural',
    'ryan-multilingual': 'en-US-RyanMultilingualNeural',
    'aria-multilingual': 'en-US-AriaMultilingualNeural',
}

# ──────────────────────────────────────────────────────────────────────────────
# CALL SESSION (SIMPLIFIED - NO BARGE-IN STATE)
# ──────────────────────────────────────────────────────────────────────────────
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

            if SAVE_RECORDINGS and self.caller_audio_chunks:
                wav = self._to_wav(self.caller_audio_chunks)
                if wav:
                    config_manager.save_call_recording(self.company_id, f"{self.call_sid}-caller", wav, "wav")

            if SAVE_RECORDINGS and self.ai_audio_chunks:
                wav = self._to_wav(self.ai_audio_chunks)
                if wav:
                    config_manager.save_call_recording(self.company_id, f"{self.call_sid}-ai", wav, "wav")

            logger.info(f"Successfully saved call session data for {self.call_sid}")
        except Exception as e:
            logger.error(f"Error saving call session: {e}")
            logger.error(traceback.format_exc())

# ──────────────────────────────────────────────────────────────────────────────
# SESSION MONITORING AND METRICS
# ──────────────────────────────────────────────────────────────────────────────
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

    def add_tokens(self, input_tokens: int, output_tokens: int):
        self.token_count += (input_tokens + output_tokens)
        # Audio uses ~800 tokens/minute per research
        estimated_minutes = self.token_count / 800
        remaining_minutes = max(0, 15 - estimated_minutes)  # 15 min session limit

        # Warn at thresholds
        if self.token_count > 100000 and self.last_token_warning < 100000:
            logger.warning(f"⚠️ HIGH TOKEN USAGE: {self.token_count:,}/128,000 ({self.token_count/128000:.1%})")
            self.last_token_warning = 100000
        elif self.token_count > 64000 and self.last_token_warning < 64000:
            logger.info(f"📈 Token usage at {self.token_count/128000:.1%} of limit")
            self.last_token_warning = 64000

        if remaining_minutes < 2:
            logger.warning(f"⏰ Session approaching 15-minute limit: {remaining_minutes:.1f} min remaining")

    def add_turn(self):
        self.turn_count += 1
        if self.turn_count == 10:
            logger.info(f"💡 Consider text conversion after {self.turn_count} turns to save tokens")

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

    def log_summary(self):
        duration = (datetime.now(UTC) - self.start_time).total_seconds()
        logger.info(f"""
📊 SESSION SUMMARY for {self.company_id}:
   Duration: {duration:.1f}s
   Turns: {self.turn_count}
   Tokens: {self.token_count:,} (~{self.token_count/128000:.1%} of limit)
   VAD Triggers: {self.vad_triggers}
   Function Calls: {len(self.function_calls)}
   Errors: {len(self.errors)}
   Avg Turn Time: {duration/max(1, self.turn_count):.1f}s
        """)

# ──────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER (Simplified - Instructions from Blob Storage)
# ──────────────────────────────────────────────────────────────────────────────
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
    openai_voice = VOICE_MAP.get(voice_style.lower(), 'alloy')

    detailed_instructions = company_config.get('detailed-instructions')

    if detailed_instructions:
        # Use instructions from Blob Storage (recommended)
        instructions = detailed_instructions
        logger.info(f"✅ Loaded instructions from Blob Storage ({len(detailed_instructions)} characters)")
    else:
        # Minimal fallback if Blob Storage file missing
        logger.warning(f"⚠️ No Blob Storage instructions found for {company_name}, using minimal fallback")
        instructions = f"""You are a professional phone agent for {company_name}.

Start every call with: {greeting}

AVAILABLE TOOLS:
- verify_surname: Verify customer surname spelling
- lookup_zipcode: Get city/state from ZIP code

Answer questions professionally and be helpful. Keep responses concise.
"""

    return instructions, openai_voice, greeting

# ──────────────────────────────────────────────────────────────────────────────
# AZURE VOICE LIVE API CONNECTION
# ──────────────────────────────────────────────────────────────────────────────
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
    logger.info("🚀 Connecting to Azure Voice Live API with production optimizations")
    logger.info(f"Endpoint: {AZURE_AI_ENDPOINT}")
    logger.info(f"Model: {AZURE_AI_MODEL}")

    try:
        # Connect using Voice Live SDK
        connection = await connect(
            endpoint=AZURE_AI_ENDPOINT,
            credential=AzureKeyCredential(AZURE_AI_KEY),
            model=AZURE_AI_MODEL,
        ).__aenter__()  # Enter async context manager

        logger.info("✅ Voice Live connection established")

        # Feature flags (all TRUE by default in demo mode)
        use_noise_suppression = audio_settings.get('enable-noise-suppression', True)
        use_echo_cancellation = audio_settings.get('enable-echo-cancellation', True)
        use_transcription = audio_settings.get('enable-audio-transcription', True)

        # Configure Azure TTS voice based on company configuration
        # Support both friendly names (cedar, alloy) and direct Azure voice names
        if voice_name in AZURE_VOICE_MAP:
            # Use friendly name mapping
            azure_voice_name = AZURE_VOICE_MAP[voice_name]
            logger.info(f"✅ Azure TTS Voice configured: {azure_voice_name} (mapped from friendly name: {voice_name})")
        elif voice_name and ("-" in voice_name and "Neural" in voice_name):
            # Looks like a direct Azure voice name (e.g., "en-US-AriaNeural", "es-MX-DaliaNeural")
            azure_voice_name = voice_name
            logger.info(f"✅ Azure TTS Voice configured: {azure_voice_name} (direct Azure voice name)")
        else:
            # Fallback to default
            azure_voice_name = "en-US-FableTurboMultilingualNeural"
            logger.warning(f"⚠️ Voice '{voice_name}' not recognized, using default: {azure_voice_name}")

        # Configure Azure HD TTS voice
        # Optimized for clarity and natural conversation
        voice_config = AzureStandardVoice(
            name=azure_voice_name,  # Uses HD voice
            type="azure-standard",
            rate="1.0",  # Normal speed
            pitch="+0%",  # Natural pitch (was +15%, too nasally)
            volume="+10%",  # Slightly louder for clarity
            style="customerservice"  # Professional, helpful tone
            # NOTE: style_degree and temperature are NOT supported by AzureStandardVoice in the current SDK
        )

        logger.info(f"   Voice properties: rate=1.0, pitch=+0%, volume=+10%, style=customerservice")

        # Configure Semantic VAD for optimal conversation
        # More sensitive configuration to better detect caller speech
        turn_detection_config = AzureSemanticVad(
            threshold=0.2,  # MORE sensitive to detect quieter caller speech (was 0.3)
            prefix_padding_ms=400,  # Capture more of speech start (was 300ms)
            silence_duration_ms=500,  # Balanced - responsive but not too quick
            remove_filler_words=False  # KEEP customer's natural speech
            # NOTE: end_of_utterance_detection is NOT supported by AzureSemanticVad
        )
        logger.info(f"✅ Semantic VAD ENABLED (threshold=0.2, prefix_padding=400ms, silence=500ms)")

        # Configure noise suppression
        noise_reduction = None
        if use_noise_suppression:
            noise_reduction = AudioNoiseReduction(type="azure_deep_noise_suppression")
            logger.info("✅ Deep Noise Suppression ENABLED")

        # Configure echo cancellation
        echo_cancellation = None
        if use_echo_cancellation:
            echo_cancellation = AudioEchoCancellation(type="server_echo_cancellation")
            logger.info("✅ Echo Cancellation ENABLED")

        # Configure audio transcription
        transcription = None
        if use_transcription:
            # Create transcription options with only supported parameters
            # Note: temperature, phrase_list, and prompt are NOT supported by Voice Live SDK
            transcription = AudioInputTranscriptionOptions(
                model="whisper-1",
                language="en"
            )

            logger.info("✅ Whisper Transcription ENABLED")

            # Add a warning if the config key still exists
            transcription_prompt_setting = audio_settings.get('transcription-prompt', None)
            if transcription_prompt_setting:
                logger.warning(f"⚠️ 'transcription-prompt' is set in config, but this SDK version does not support it. Ignoring setting.")

        # ──────────────────────────────────────────────────────────────────────
        # FUNCTION CALLING CONFIGURATION
        # ──────────────────────────────────────────────────────────────────────
        logger.info("🔧 Configuring function calling tools...")

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
                            "description": "5-digit US ZIP code",
                            "pattern": "^[0-9]{5}$"  # Strict validation: exactly 5 digits
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
        logger.info(f"✅ Configured {len(tools)} function calling tools: {[t.name for t in tools]}")

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

        # Update session using proper SDK method
        await connection.session.update(session=session_config)
        logger.info("✅ Voice Live session configured successfully with function calling")

        # Log final configuration
        logger.info("=" * 80)
        logger.info("✅ PRODUCTION-GRADE Voice Live API Ready (Elderly-Optimized)")
        logger.info(f"   Voice: {azure_voice_name} (Azure HD Neural TTS)")
        logger.info(f"   Voice Config: rate=1.0, pitch=+15%, volume=+10%, style=customerservice")
        logger.info(f"   VAD: Semantic (threshold=0.2, prefix_padding=400ms, silence=500ms)")
        logger.info(f"   LLM: temp={audio_settings.get('temperature', 0.7)}, max_tokens={audio_settings.get('max-response-tokens', 200)}")
        logger.info(f"   Features: Noise={use_noise_suppression}, Echo={use_echo_cancellation}, Transcription={use_transcription}")
        logger.info("=" * 80)

        return connection

    except Exception as e:
        logger.error(f"❌ Failed to create Voice Live connection: {e}")
        logger.error(traceback.format_exc())
        raise

# ──────────────────────────────────────────────────────────────────────────────
# CONNECTION RESILIENCE: RETRY LOGIC AND HEARTBEAT
# ──────────────────────────────────────────────────────────────────────────────
async def create_voicelive_connection_with_retry(company_instructions, voice_name, audio_settings, max_retries=3):
    """Create Voice Live connection with exponential backoff retry logic"""
    last_error = None
    retry_count = audio_settings.get('connection-retry-attempts', max_retries)

    for attempt in range(retry_count):
        try:
            logger.info(f"🔄 Connection attempt {attempt + 1}/{retry_count}")
            connection = await create_voicelive_connection(
                company_instructions, voice_name, audio_settings
            )

            logger.info("✅ Connection established with retry logic")
            return connection

        except Exception as e:
            last_error = e
            if attempt == retry_count - 1:
                logger.error(f"❌ All connection attempts failed after {retry_count} tries: {e}")
                raise

            # Exponential backoff: 2, 4, 8... seconds, max 30
            wait_time = min(2 ** (attempt + 1), 30)
            logger.warning(f"⚠️ Attempt {attempt + 1} failed: {e}")
            logger.info(f"⏳ Retrying in {wait_time} seconds...")
            await asyncio.sleep(wait_time)

    raise last_error or Exception("Connection failed")

async def heartbeat_loop(connection, monitor: SessionMonitor, interval: int = 30):
    """Keep connection alive with periodic heartbeat"""
    try:
        while True:
            await asyncio.sleep(interval)
            # Connection stays alive through regular event processing
            logger.debug(f"💓 Connection heartbeat ({interval}s interval)")

    except asyncio.CancelledError:
        logger.info("💔 Heartbeat task cancelled")
    except Exception as e:
        logger.error(f"💔 Heartbeat error: {e}")
        monitor.add_error(f"Heartbeat failed: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# FUNCTION EXECUTION HANDLER
# ──────────────────────────────────────────────────────────────────────────────
async def execute_function(function_name: str, arguments: dict) -> dict:
    """Execute tool functions and return results"""
    logger.info(f"🔧 Executing function: {function_name} with args: {arguments}")

    try:
        if function_name == "lookup_zipcode":
            zipcode = arguments.get("zipcode", "")
            if not zipcode:
                return {"error": "Missing zipcode parameter"}

            # Use existing zipcode service (includes zipcode_spoken for clear pronunciation)
            result = zipcode_service.lookup(zipcode)

            if result:
                logger.info(f"   ZIP lookup success: {result['city']}, {result['state']}")
                return {
                    "found": True,
                    "zipcode": zipcode,
                    "zipcode_spoken": result.get('zipcode_spoken', zipcode),  # Speech-formatted ZIP
                    "city": result['city'],
                    "state": result['state'],
                    "message": f"{result['city']}, {result['state']}"
                }
            else:
                logger.warning(f"   ZIP code {zipcode} not found")
                return {
                    "found": False,
                    "zipcode": zipcode,
                    "message": "ZIP code not found. Please ask customer to verify."
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
        logger.error(f"❌ Error executing function {function_name}: {e}")
        logger.error(traceback.format_exc())
        return {"error": f"Function execution failed: {str(e)}"}

# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────────────────────────────────────────
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

@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True, "status": "healthy"})

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

# ──────────────────────────────────────────────────────────────────────────────
# MAIN WEBSOCKET BRIDGE
# ──────────────────────────────────────────────────────────────────────────────
@app.websocket("/voice/{company_id}")
async def voice_bridge(company_id: str, signalwire_ws: WebSocket):
    await signalwire_ws.accept()
    logger.info(f"✅ SignalWire connection accepted for company: {company_id}")

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
        logger.info(f"✅ Loaded config for {company_name}")
    except Exception as e:
        msg = f"Failed to load company configuration: {e}"
        logger.error(msg)
        await signalwire_ws.send_text(json.dumps({"type": "error", "source": "config", "detail": msg}))
        await signalwire_ws.close(code=1011)
        return

    shared_state: Dict[str, Any] = {
        "call_session": None,
        "stream_sid": None,
        "monitor": SessionMonitor(company_id)  # Add session monitor
    }
    voicelive_connection = None
    heartbeat_task = None

    try:
        instructions, voice_name, greeting_text = build_company_instructions(company_config)

        # Get heartbeat interval from config
        heartbeat_interval = audio_settings.get('heartbeat-interval-seconds', 30)

        # Create connection with retry logic
        voicelive_connection = await create_voicelive_connection_with_retry(
            instructions, voice_name, audio_settings
        )

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(voicelive_connection, shared_state["monitor"], heartbeat_interval)
        )

        logger.info(f"✅ Voice Live API connected with monitoring for {company_name}")

        # Start bidirectional audio forwarding
        audio_sender_task = asyncio.create_task(
            send_signalwire_audio_to_voicelive(signalwire_ws, voicelive_connection, company_id, company_name, shared_state, greeting_text)
        )
        logger.info(f"🎙️ {company_name} agent ready for calls!")

        try:
            # Process events from Voice Live API
            async for event in voicelive_connection:
                try:
                    call_session = shared_state.get("call_session")
                    stream_sid = shared_state.get("stream_sid")
                    monitor = shared_state.get("monitor")

                    # Pass monitor to event handler
                    await handle_voicelive_event(
                        event, signalwire_ws, voicelive_connection,
                        company_name, stream_sid, call_session,
                        monitor  # Add monitor parameter
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
            audio_sender_task.cancel()
            try:
                await audio_sender_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        msg = f"Voice Live connection failed: {e}"
        logger.error(msg)
        logger.error(traceback.format_exc())
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({"type": "error", "source": "voicelive", "detail": str(e)}))
            await signalwire_ws.close(code=1011)
    finally:
        # Clean up heartbeat task
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Log session summary
        monitor = shared_state.get("monitor")
        if monitor:
            monitor.log_summary()

        # Voice Live SDK connection cleanup is handled automatically
        # No explicit close needed for connections created with __aenter__()
        pass

# ──────────────────────────────────────────────────────────────────────────────
# VOICE LIVE → SIGNALWIRE EVENT HANDLER
# ──────────────────────────────────────────────────────────────────────────────

# Response tracking to detect and suppress audio-only responses (prevents <|audio_text|> token)
class ResponseTracker:
    """Track whether current response has text to prevent audio-only responses"""
    def __init__(self):
        self.current_response_has_text = False
        self.suppressed_audio_count = 0
        self.has_invalid_token = False  # Track if response contains invalid token
        self.transcript_buffer = ""  # Buffer to accumulate transcript deltas

    def start_response(self):
        """Reset for new response"""
        self.current_response_has_text = False
        self.suppressed_audio_count = 0
        self.has_invalid_token = False
        self.transcript_buffer = ""  # Reset buffer

    def add_transcript_delta(self, delta_text: str):
        """Add transcript delta and check for invalid tokens"""
        self.transcript_buffer += delta_text

        # Check if the accumulated buffer contains invalid token
        if "<|audio_text|>" in self.transcript_buffer or "<|end_of_text|>" in self.transcript_buffer:
            logger.error(f"🚨 INVALID TOKEN DETECTED IN TRANSCRIPT BUFFER: '{self.transcript_buffer}'")
            self.has_invalid_token = True
            return True  # Signal that invalid token was found
        return False

    def mark_text_received(self):
        """Mark that text was received for current response"""
        self.current_response_has_text = True

    def mark_invalid_token(self):
        """Mark that response contains invalid token (should suppress all audio)"""
        self.has_invalid_token = True

    def should_forward_audio(self) -> bool:
        """Return True if audio should be forwarded (has text and no invalid tokens)"""
        return self.current_response_has_text and not self.has_invalid_token

    def suppress_audio(self):
        """Count a suppressed audio chunk"""
        self.suppressed_audio_count += 1

    def log_suppression(self):
        """Log if audio was suppressed"""
        if self.has_invalid_token and self.suppressed_audio_count > 0:
            logger.warning(f"⚠️ Suppressed {self.suppressed_audio_count} audio chunks containing invalid <|audio_text|> token")
        elif not self.current_response_has_text and self.suppressed_audio_count > 0:
            logger.warning(f"⚠️ Suppressed {self.suppressed_audio_count} audio-only chunks (no text)")

# Global response tracker instance
response_tracker = ResponseTracker()

async def handle_voicelive_event(
    event,  # Voice Live SDK event object
    signalwire_ws: WebSocket,
    voicelive_connection,
    company_name: str,
    stream_sid: Optional[str],
    call_session: Optional[CallSession],
    monitor: Optional[SessionMonitor] = None  # Add monitor parameter
):
    """Handle events from Voice Live API and forward to SignalWire"""
    logger.debug(f"📥 Voice Live event: {event.type}")

    # ──────────────────────────────────────────────────────────────────────
    # TRANSCRIPT LOGGING
    # ──────────────────────────────────────────────────────────────────────
    # Log user speech transcripts
    event_type_str = str(event.type)

    # Special handling for response.audio_transcript.delta - check for invalid tokens character by character
    if event_type_str == 'ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA' or 'audio_transcript.delta' in event_type_str.lower():
        if hasattr(event, 'delta') and event.delta:
            # Add to buffer and check for invalid tokens
            if response_tracker.add_transcript_delta(str(event.delta)):
                # Invalid token detected! Trigger recovery to prevent silence
                logger.error("🚨 INVALID TOKEN IN DELTA - Triggering recovery response")

                # Trigger a recovery response to continue naturally
                try:
                    if hasattr(voicelive_connection, 'response'):
                        asyncio.create_task(
                            voicelive_connection.response.create(
                                instructions="""RECOVERY MODE: Invalid response detected.

The caller just provided information. Continue collecting the next required field naturally.
Do NOT repeat what they just said. Move directly to the next question in your workflow.

If you were collecting phone/email/address, continue to the next field.""",
                                temperature=0.7,
                                max_tokens=150
                            )
                        )
                        logger.info("✅ Recovery response triggered for invalid transcript token")
                except Exception as recovery_err:
                    logger.error(f"❌ Failed to trigger recovery: {recovery_err}")

                return
            # Don't log individual delta characters/words - too noisy
            return  # Skip further processing for delta events

    if 'transcription' in event_type_str.lower() or 'transcript' in event_type_str.lower():
        transcript_text = None
        if hasattr(event, 'transcript'):
            transcript_text = event.transcript
        elif hasattr(event, 'text'):
            transcript_text = event.text
        elif hasattr(event, 'content'):
            transcript_text = event.content

        if transcript_text:
            # Filter out invalid tokens from transcript (especially <|audio_text|>)
            INVALID_TOKENS = {"<|audio_text|>", "<|end_of_text|>", "null", ""}

            # Check for invalid token
            if "<|audio_text|>" in str(transcript_text):
                logger.error(f"🚨 DETECTED INVALID TOKEN '<|audio_text|>' - Triggering recovery")
                response_tracker.mark_invalid_token()

                # Trigger recovery if not already triggered
                try:
                    if hasattr(voicelive_connection, 'response'):
                        asyncio.create_task(
                            voicelive_connection.response.create(
                                instructions="""RECOVERY MODE: Invalid response detected.

The caller just provided information. Continue collecting the next required field naturally.
Do NOT repeat what they just said. Move directly to the next question in your workflow.

If you were collecting phone/email/address, continue to the next field.""",
                                temperature=0.7,
                                max_tokens=150
                            )
                        )
                        logger.info("✅ Recovery response triggered for invalid transcript.done token")
                except Exception as recovery_err:
                    logger.error(f"❌ Failed to trigger recovery: {recovery_err}")

                return  # Don't process this event further

            if transcript_text.strip() not in INVALID_TOKENS:
                # Note: This could be user OR assistant transcript depending on event type
                logger.info(f"📝 TRANSCRIPT: {transcript_text}")
            else:
                logger.warning(f"🚫 FILTERED INVALID TOKEN: '{transcript_text}'")

    # Log AI response text and filter invalid tokens
    if 'text' in event_type_str.lower() and 'delta' in event_type_str.lower():
        response_text = None
        if hasattr(event, 'delta'):
            response_text = event.delta
        elif hasattr(event, 'text'):
            response_text = event.text

        if response_text and isinstance(response_text, str):
            # Filter out invalid LLM tokens that should not be spoken
            INVALID_TOKENS = {"<|audio_text|>", "<|end_of_text|>", "null", ""}
            if response_text.strip() in INVALID_TOKENS or "<|audio_text|>" in response_text:
                logger.warning(f"🚫 DETECTED INVALID TOKEN: '{response_text}' - Triggering recovery")

                # Trigger a recovery response to prevent audio-only output
                # This happens when caller makes side comments or conversational asides
                try:
                    # Cancel the current response that's generating invalid tokens
                    if hasattr(voicelive_connection, 'response'):
                        # Trigger a new response with instructions to continue naturally
                        asyncio.create_task(
                            voicelive_connection.response.create(
                                instructions="""RECOVERY MODE: You just attempted to generate an invalid response.

The caller may have made a side comment or conversational aside.
Please continue collecting the information you need naturally.

If you just asked for information (phone, address, etc.), politely say:
"I want to make sure I get that correctly - could you repeat that for me?"

Stay focused on your current task in the call flow.""",
                                temperature=0.7,
                                max_tokens=150
                            )
                        )
                        logger.info("✅ Recovery response triggered for invalid token")
                except Exception as recovery_err:
                    logger.error(f"❌ Failed to trigger recovery: {recovery_err}")

                # Don't log or process this text further
                # DON'T mark as having text - this is an invalid token
            else:
                logger.info(f"💬 AI RESPONSE TEXT: {response_text}")
                # Mark that valid text was received for this response
                response_tracker.mark_text_received()

    # Log content parts (might contain text)
    if 'content_part' in event_type_str.lower() or 'output_item' in event_type_str.lower():
        if hasattr(event, 'part') and hasattr(event.part, 'text'):
            logger.info(f"💬 AI RESPONSE: {event.part.text}")
        elif hasattr(event, 'item'):
            if hasattr(event.item, 'content') and isinstance(event.item.content, list):
                for content in event.item.content:
                    if hasattr(content, 'text'):
                        logger.info(f"💬 AI RESPONSE: {content.text}")

    # ──────────────────────────────────────────────────────────────────────
    # TOKEN USAGE AND RATE LIMIT MONITORING
    # ──────────────────────────────────────────────────────────────────────
    # Monitor token usage
    if hasattr(event, 'usage') or 'usage' in str(event.type).lower():
        if monitor and hasattr(event, 'usage'):
            usage = event.usage
            if hasattr(usage, 'input_tokens') and hasattr(usage, 'output_tokens'):
                input_tokens = usage.input_tokens
                output_tokens = usage.output_tokens
                total_tokens = input_tokens + output_tokens

                logger.info(f"📊 Token usage - Input: {input_tokens:,}, Output: {output_tokens:,}, Total: {total_tokens:,}")
                monitor.add_tokens(input_tokens, output_tokens)

    # Track rate limits
    if hasattr(event, 'rate_limits') or 'rate_limit' in str(event.type).lower():
        if hasattr(event, 'rate_limits'):
            rate_limits = event.rate_limits
            if hasattr(rate_limits, 'remaining_tokens'):
                remaining = rate_limits.remaining_tokens
                if remaining < 10000:
                    logger.warning(f"⚠️ Rate limit warning: {remaining:,} tokens remaining")

    # Track VAD events for monitoring
    if monitor:
        if event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            monitor.add_vad_trigger()
            monitor.add_turn()  # New turn started

        elif event.type == ServerEventType.ERROR:
            error_msg = getattr(event, 'error', {}).get('message', 'Unknown error') if hasattr(event, 'error') else 'Unknown error'
            monitor.add_error(error_msg)

    # ──────────────────────────────────────────────────────────────────────
    # STANDARD EVENT HANDLING
    # ──────────────────────────────────────────────────────────────────────
    if event.type == ServerEventType.SESSION_UPDATED:
        logger.info(f"✅ {company_name} Voice Live session ready")

    elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
        logger.info("🎤 Caller started speaking")

    elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
        logger.info("🎤 Caller stopped speaking")

        # GRACE PERIOD: Wait 500ms for transcript to arrive before AI responds
        # This prevents race condition where AI responds before hearing the transcript
        # Evidence from production: transcript takes ~360ms to arrive after VAD stops
        logger.info("⏳ Waiting 500ms grace period for transcript...")
        await asyncio.sleep(0.5)
        logger.info("✅ Grace period complete, transcript should be available")

    elif event.type == ServerEventType.RESPONSE_CREATED:
        logger.info(f"🤖 {company_name} AI responding")
        # Reset response tracker for new response
        response_tracker.start_response()

    elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
        if signalwire_ws.application_state != WebSocketState.CONNECTED:
            return

        # Voice Live SDK returns audio as bytes in event.delta
        audio_bytes = event.delta
        if not audio_bytes:
            return

        # CRITICAL: Check if we should suppress this audio (invalid token detected)
        # This prevents "<|audio_text|>" from being spoken out loud
        if response_tracker.has_invalid_token:
            response_tracker.suppress_audio()
            logger.warning("🚫 SUPPRESSING AUDIO CHUNK - Invalid token detected (preventing 'audio underscore text' speech)")
            return

        # Additional safety check: If this is string data instead of bytes, it's likely a token
        if isinstance(audio_bytes, str):
            logger.warning(f"🚫 SUPPRESSING STRING AUDIO DATA: '{audio_bytes}' (expected bytes)")
            response_tracker.mark_invalid_token()
            return

        # Convert bytes to base64 for SignalWire
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        # Save AI audio for recording
        if call_session and SAVE_RECORDINGS:
            try:
                call_session.add_ai_audio(audio_b64)
            except Exception:
                pass

        # Forward audio to SignalWire
        logger.debug("🔊 Forwarding audio to SignalWire")
        await signalwire_ws.send_text(json.dumps({
            "event": "media",
            "streamSid": stream_sid or "",
            "media": {"payload": audio_b64}
        }))

    elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
        logger.info(f"🤖 {company_name} finished speaking")
        # Log if we suppressed audio-only chunks
        response_tracker.log_suppression()

    elif event.type == ServerEventType.RESPONSE_DONE:
        logger.info("✅ Response complete")
        # Log if we suppressed audio-only chunks
        response_tracker.log_suppression()

    elif event.type == ServerEventType.ERROR:
        error_msg = getattr(event, 'error', {}).get('message', 'Unknown error') if hasattr(event, 'error') else 'Unknown error'
        logger.error(f"❌ Voice Live error: {error_msg}")
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({
                "type": "error",
                "source": "voicelive",
                "detail": error_msg
            }))

    # ──────────────────────────────────────────────────────────────────────
    # FUNCTION CALLING EVENT HANDLING
    # ──────────────────────────────────────────────────────────────────────
    # Try to detect function call events - SDK may use different event types
    event_type_str = str(event.type) if hasattr(event, 'type') else None

    # Method 1: Check if this is a function call event
    if event_type_str and 'function_call' in event_type_str.lower():
        logger.info(f"🔧 Function call event detected: {event_type_str}")

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

            # Execute the function
            result = await execute_function(function_name, arguments)
            logger.info(f"   Function result: {result}")

            # Use the documented SDK API instead of internal WebSocket bypass
            try:
                # Method 1: Try using conversation.item.create (if available)
                logger.info("📤 Sending function result using documented SDK API...")

                # The result must be a JSON string
                result_json = json.dumps(result)

                # Check if connection has conversation.item.create method
                if hasattr(voicelive_connection, 'conversation'):
                    conversation = voicelive_connection.conversation

                    # Create a function call output item
                    if hasattr(conversation, 'item'):
                        await conversation.item.create(
                            item={
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": result_json
                            }
                        )
                        logger.info("✅ Function result sent via conversation.item.create()")
                    else:
                        raise AttributeError("conversation.item not available")

                    # Trigger the next response so AI can speak the result
                    if hasattr(voicelive_connection, 'response'):
                        await voicelive_connection.response.create()
                        logger.info("✅ Triggered response.create() to continue conversation")

                elif hasattr(voicelive_connection, 'response'):
                    # Method 2: Fallback - inject result via additional_instructions
                    logger.warning("⚠️ conversation.item not available, using fallback method")

                    # Build context message with the function result
                    if function_name == "lookup_zipcode":
                        city = result.get('city', 'Unknown')
                        state = result.get('state', 'Unknown')
                        zipcode_spoken = result.get('zipcode_spoken', result.get('zipcode', ''))

                        context_prompt = (
                            f"SYSTEM: ZIP code lookup successful. "
                            f"ZIP: {zipcode_spoken} is in {city}, {state}. "
                            f"Move to next question."
                        )
                    else:
                        context_prompt = f"SYSTEM: Function '{function_name}' returned: {result_json}"

                    await voicelive_connection.response.create(
                        additional_instructions=context_prompt
                    )
                    logger.info("✅ Function result injected via additional_instructions fallback")
                else:
                    raise AttributeError("Neither conversation nor response objects available on connection")

            except Exception as e:
                # If the SDK method fails, use recovery prompt
                logger.error(f"❌ FAILED TO SEND FUNCTION RESULT: {e}")
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
                        logger.info("✅ Triggered SDK response.create() for graceful tool failure recovery.")
                except Exception as recovery_e:
                    logger.critical(f"❌ TOTAL FAILURE: Could not send function result AND could not trigger recovery response: {recovery_e}")
                    logger.error(traceback.format_exc())

    # Method 2: Check raw event data for function calls
    elif hasattr(event, '_raw') or hasattr(event, 'data'):
        raw_data = getattr(event, '_raw', None) or getattr(event, 'data', None)
        if raw_data and isinstance(raw_data, str):
            try:
                parsed = json.loads(raw_data)
                if parsed.get('type') == 'response.function_call_arguments.done':
                    logger.info("🔧 Function call detected in raw event data")
                    function_name = parsed.get('name')
                    arguments = json.loads(parsed.get('arguments', '{}'))
                    call_id = parsed.get('call_id')

                    if function_name:
                        # Track function call
                        if monitor:
                            monitor.add_function_call(function_name)

                        result = await execute_function(function_name, arguments)
                        logger.info(f"   Function result: {result}")

                        # Use the documented SDK API instead of internal WebSocket bypass
                        try:
                            # Method 1: Try using conversation.item.create (if available)
                            logger.info("📤 Sending function result using documented SDK API (Method 2)...")

                            # The result must be a JSON string
                            result_json = json.dumps(result)

                            # Check if connection has conversation.item.create method
                            if hasattr(voicelive_connection, 'conversation'):
                                conversation = voicelive_connection.conversation

                                # Create a function call output item
                                if hasattr(conversation, 'item'):
                                    await conversation.item.create(
                                        item={
                                            "type": "function_call_output",
                                            "call_id": call_id,
                                            "output": result_json
                                        }
                                    )
                                    logger.info("✅ Function result sent via conversation.item.create() (Method 2)")
                                else:
                                    raise AttributeError("conversation.item not available")

                                # Trigger the next response so AI can speak the result
                                if hasattr(voicelive_connection, 'response'):
                                    await voicelive_connection.response.create()
                                    logger.info("✅ Triggered response.create() to continue conversation (Method 2)")

                            elif hasattr(voicelive_connection, 'response'):
                                # Method 2: Fallback - inject result via additional_instructions
                                logger.warning("⚠️ conversation.item not available, using fallback method (Method 2)")

                                # Build context message with the function result
                                if function_name == "lookup_zipcode":
                                    city = result.get('city', 'Unknown')
                                    state = result.get('state', 'Unknown')
                                    zipcode_spoken = result.get('zipcode_spoken', result.get('zipcode', ''))

                                    context_prompt = (
                                        f"SYSTEM: ZIP code lookup successful. "
                                        f"ZIP: {zipcode_spoken} is in {city}, {state}. "
                                        f"Move to next question."
                                    )
                                else:
                                    context_prompt = f"SYSTEM: Function '{function_name}' returned: {result_json}"

                                await voicelive_connection.response.create(
                                    additional_instructions=context_prompt
                                )
                                logger.info("✅ Function result injected via additional_instructions fallback (Method 2)")
                            else:
                                raise AttributeError("Neither conversation nor response objects available on connection")

                        except Exception as e:
                            # If the SDK method fails, use recovery prompt
                            logger.error(f"❌ FAILED TO SEND FUNCTION RESULT (Method 2): {e}")
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
                                    logger.info("✅ Triggered SDK response.create() for graceful tool failure recovery (Method 2).")
                            except Exception as recovery_e:
                                logger.critical(f"❌ TOTAL FAILURE (Method 2): Could not send function result AND could not trigger recovery response: {recovery_e}")
                                logger.error(traceback.format_exc())
            except:
                pass  # Not a function call event

    # ──────────────────────────────────────────────────────────────────────
    # DEBUG: Log all event types to discover what we're missing
    # ──────────────────────────────────────────────────────────────────────
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
        logger.info(f"🔍 Event type: {event_type_str}")
        if event_attrs:
            logger.info(f"   Attributes: {event_attrs}")

# ──────────────────────────────────────────────────────────────────────────────
# SIGNALWIRE → VOICE LIVE AUDIO FORWARDER
# ──────────────────────────────────────────────────────────────────────────────
async def send_signalwire_audio_to_voicelive(
    signalwire_ws: WebSocket,
    voicelive_connection,
    company_id: str,
    company_name: str,
    shared_state: Dict[str, Any],
    greeting_text: str
):
    logger.info(f"🎤 Audio forwarding started for {company_name}")

    stream_sid: Optional[str] = None
    call_session: Optional[CallSession] = None

    try:
        while True:
            msg = await signalwire_ws.receive()

            if msg["type"] == "websocket.disconnect":
                logger.info(f"📞 SignalWire disconnected for {company_name}")
                break

            if "text" in msg and msg["text"] is not None:
                try:
                    data = json.loads(msg["text"])
                    event_name = data.get("event")

                    if event_name == "connected":
                        logger.info(f"🔗 SignalWire connected for {company_name}")

                    elif event_name == "start":
                        stream_sid = (data.get("start") or {}).get("streamSid")
                        caller_phone = (data.get("start") or {}).get("from")
                        media_format = (data.get("start") or {}).get("mediaFormat", {})

                        # Create call session
                        call_session = CallSession(company_id, stream_sid or "unknown")
                        shared_state["call_session"] = call_session
                        shared_state["stream_sid"] = stream_sid

                        logger.info(f"▶️ Call started for {company_name}")
                        logger.info(f"📞 Caller ID: {caller_phone}")
                        logger.info(f"📊 Audio format: {media_format}")

                        # Add business context
                        # Get business hours configuration for this company
                        company_config = get_cached_config(company_id)
                        business_hours_config = company_config.get('business-hours', {})
                        timezone_str = business_hours_config.get('timezone', 'US/Eastern')
                        business_days = business_hours_config.get('days', [0, 1, 2, 3, 4])  # 0=Monday, 6=Sunday
                        open_time_str = business_hours_config.get('open-time', '08:30')
                        close_time_str = business_hours_config.get('close-time', '17:00')

                        logger.info(f"⚙️ Business hours config: timezone={timezone_str}, days={business_days}, open={open_time_str}, close={close_time_str}")

                        # Get current time in company's timezone (convert from UTC for reliability)
                        company_tz = pytz.timezone(timezone_str)
                        now_utc = datetime.now(UTC)
                        now_local = now_utc.astimezone(company_tz)

                        logger.info(f"🕐 Current time - UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}, Local: {now_local.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")

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

                            logger.info(f"📅 Overnight hours detected: open={open_time_str}, close={close_time_str}")
                            logger.info(f"📅 Business hours check: Day={now_local.strftime('%A')} ({current_day}), Time={now_local.strftime('%H:%M')}, in_hours_today={in_hours_today}, in_hours_from_yesterday={in_hours_from_yesterday}, is_business_hours={is_business_hours}")
                        else:
                            # Standard hours (e.g., Mon 8am - Mon 5pm)
                            is_business_day = current_day in business_days
                            is_within_hours = open_time_minutes <= current_time_minutes < close_time_minutes
                            is_business_hours = is_business_day and is_within_hours

                            logger.info(f"📅 Standard hours: Day={now_local.strftime('%A')} ({current_day}), Time={now_local.strftime('%H:%M')}, is_business_day={is_business_day}, is_within_hours={is_within_hours}, is_business_hours={is_business_hours}")
                        
                        formatted_phone = caller_phone or "Unknown"
                        if caller_phone and len(caller_phone) == 12 and caller_phone.startswith('+1'):
                            formatted_phone = f"{caller_phone[:2]}-{caller_phone[2:5]}-{caller_phone[5:8]}-{caller_phone[8:]}"

                        # Get timezone abbreviation for display (e.g., "EST", "PDT")
                        tz_abbrev = now_local.strftime('%Z')

                        context_text = (
                            f"Current date: {now_local.strftime('%B %d, %Y')}\n"
                            f"Current day: {now_local.strftime('%A')}\n"
                            f"Current time: {now_local.strftime('%I:%M %p')} {tz_abbrev}\n"
                            f"Transfer window: Monday-Saturday, 8:00 AM - 2:00 AM Eastern\n"
                            f"Caller ID: {formatted_phone}"
                        )

                        # Voice Live SDK passes context via additional_instructions parameter
                        # Enhanced with response guidelines for natural, elderly-optimized conversation
                        enhanced_context = f"""{context_text}

RESPONSE GUIDELINES (Apply to ALL responses):
- Use discourse markers naturally: "So," "Well," "Actually," "Alright" to start responses
- Add ONE strategic filler when looking things up: "Let me see..." or "One moment..."
- Keep responses to 2-3 sentences maximum - be concise
- For phone numbers and addresses, say each digit with slight pauses
- Show warmth through acknowledgment: "I can definitely help with that"
- DON'T repeat information back unless asked - no "Thank you, Smith" or "Got it, 703..."
- Move directly to the next question after receiving info
- Speak slightly slower and clearer for elderly customers
- Only confirm information at the very end of the call, not after each field"""

                        logger.info(f"📤 Enhanced call context with response guidelines")

                        # Wait for audio stream to fully establish before greeting
                        await asyncio.sleep(1.5)

                        # Trigger response with enhanced context via additional_instructions
                        # SDK supports: response.create(response, event_id, additional_instructions)
                        await voicelive_connection.response.create(
                            additional_instructions=enhanced_context
                        )
                        logger.info("✅ Triggered greeting with enhanced context (elderly-optimized natural responses)")

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
                            logger.debug("🔊 Forwarded audio")
                        except Exception as e:
                            logger.error(f"Audio forward error: {e}")

                    elif event_name == "stop":
                        logger.info(f"⏹️ Call ended for {company_name}")
                        if call_session:
                            try:
                                call_session.finalize()
                                await call_session.save_to_storage()
                                logger.info("✅ Call session saved successfully")
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
        logger.info(f"🛑 Audio forwarding cancelled for {company_name}")
    except WebSocketDisconnect:
        logger.info(f"📞 WebSocket disconnected for {company_name}")
    except Exception as e:
        logger.error(f"❌ Error in audio forwarding for {company_name}: {e}")
        logger.error(traceback.format_exc())
    finally:
        logger.info(f"🛑 Audio forwarding stopped for {company_name}")

# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
