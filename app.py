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
    ServerVad,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    ServerEventType
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
logger.info(f"Voice: Azure TTS (en-US-FableTurboMultilingualNeural)")
logger.info(f"Save Recordings: {SAVE_RECORDINGS}")
logger.info(f"Save Transcripts: {SAVE_TRANSCRIPTS}")
logger.info("=" * 80)

# ──────────────────────────────────────────────────────────────────────────────
# VOICE MAP
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
# PROMPT BUILDER
# ──────────────────────────────────────────────────────────────────────────────
def build_company_instructions(company_config):
    company_name = company_config.get('company-name', 'Unknown Company')
    greeting = company_config.get('greeting', f'Thank you for calling {company_name}')
    industry = company_config.get('industry', 'general')

    voice_config = company_config.get('voice-config', {})
    voice_style = voice_config.get('voice-style', 'alloy')
    openai_voice = VOICE_MAP.get(voice_style.lower(), 'alloy')

    contact_info = company_config.get('contact-info', {})
    customer_service_phone = contact_info.get('customer-service-phone')
    customer_service_email = contact_info.get('customer-service-email')

    business_rules = company_config.get('business-rules', {})
    callback_timeframe = business_rules.get('callback-timeframe')
    transfer_hours = business_rules.get('transfer-hours')

    detailed_instructions = company_config.get('detailed-instructions')

    # Voice consistency guidance (applies to all instructions)
    voice_consistency_prefix = """VOICE DELIVERY GUIDELINES:
- Maintain consistent tone, pitch, and pacing throughout the entire conversation
- Use the same professional, warm voice quality for every response
- Avoid sudden changes in speaking style or vocal characteristics
- Speak naturally and conversationally with stable prosody

"""

    if detailed_instructions:
        instructions = voice_consistency_prefix + detailed_instructions
    else:
        contact_section = ""
        if customer_service_phone or customer_service_email:
            contact_section = "\n\nCONTACT INFORMATION:"
            if customer_service_phone:
                contact_section += f"\n- Customer Service Phone: {customer_service_phone}"
            if customer_service_email:
                contact_section += f"\n- Customer Service Email: {customer_service_email}"

        business_section = ""
        if callback_timeframe or transfer_hours:
            business_section = "\n\nBUSINESS GUIDELINES:"
            if callback_timeframe:
                business_section += f"\n- Callback timeframe: {callback_timeframe}"
            if transfer_hours:
                business_section += f"\n- Transfer/live agent hours: {transfer_hours}"

        instructions = voice_consistency_prefix + f"""You are a professional phone agent for {company_name}.

GREETING: {greeting}

INDUSTRY: {industry}

VOICE PERSONALITY:
- Professional and friendly
- Natural phone cadence
- Helpful and knowledgeable about {company_name}
- Appropriate pacing

CONVERSATION APPROACH:
1) Start with the greeting exactly as provided
2) Listen to the caller's need
3) Provide relevant information
4) Guide the conversation professionally
5) Stay within scope; escalate or schedule when needed
{contact_section}
{business_section}
"""
    
    return instructions, openai_voice, greeting

# ──────────────────────────────────────────────────────────────────────────────
# AZURE VOICE LIVE API CONNECTION
# ──────────────────────────────────────────────────────────────────────────────
async def create_voicelive_connection(company_instructions, voice_name, audio_settings):
    """
    Create Voice Live API connection with Azure TTS voice.
    Configured voice provides consistent prosody with SSML support.
    """
    logger.info("Connecting to Azure Voice Live API")
    logger.info(f"Endpoint: {AZURE_AI_ENDPOINT}")
    logger.info(f"Model: {AZURE_AI_MODEL}")

    # Connect using Voice Live SDK
    connection = await connect(
        endpoint=AZURE_AI_ENDPOINT,
        credential=AzureKeyCredential(AZURE_AI_KEY),
        model=AZURE_AI_MODEL,
    ).__aenter__()  # Enter async context manager

    # Configure Azure TTS voice (for SSML prosody support and consistent tone)
    # Using en-US-FableTurboMultilingualNeural - OpenAI Fable voice (British-ish) with SSML support
    voice_config = AzureStandardVoice(
        name="en-US-FableTurboMultilingualNeural",
        type="azure-standard"
    )

    # Configure turn detection with Server VAD
    turn_detection_config = ServerVad(
        threshold=0.3,              # Lower = more sensitive to interruptions
        prefix_padding_ms=200,      # Less padding = faster interruption detection
        silence_duration_ms=800     # Shorter silence = quicker turn-end detection
    )

    # NOTE: Voice Live API doesn't support tools in RequestSession yet
    # Function calling would need to be handled separately if needed
    # For now, we'll configure without tools and handle in Azure OpenAI model

    # Create session configuration
    session_config = RequestSession(
        modalities=[Modality.TEXT, Modality.AUDIO],
        instructions=company_instructions,
        voice=voice_config,
        input_audio_format=InputAudioFormat.PCM16,
        output_audio_format=OutputAudioFormat.PCM16,
        turn_detection=turn_detection_config,
        temperature=float(audio_settings.get("temperature", 0.4)),
        max_response_output_tokens=int(audio_settings.get("max-response-tokens", 2048))
    )

    # Update session
    await connection.session.update(session=session_config)

    logger.info("✅ Voice Live API session configured")
    logger.info(f"   Voice: en-US-FableTurboMultilingualNeural (Azure TTS)")
    logger.info(f"   Mode: Natural conversation (server VAD)")
    logger.info(f"   Temperature: {audio_settings.get('temperature', 0.4)}")

    return connection

# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Voice Agent Bridge")

@app.get("/")
def root():
    return {
        "ok": True,
        "service": "Voice Agent Bridge",
        "version": "14.0 - Azure Voice Live API",
        "api": "Azure Voice Live API",
        "model": AZURE_AI_MODEL,
        "voice": "en-US-FableTurboMultilingualNeural (Azure TTS)",
        "audio_format": "PCM16 24kHz passthrough",
        "features": [
            "Azure TTS voices with SSML support",
            "Consistent prosody",
            "Server-side VAD",
            "Native audio streaming",
            "Natural conversation flow",
            "Call recordings & transcripts" if SAVE_RECORDINGS or SAVE_TRANSCRIPTS else None
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

    shared_state: Dict[str, Any] = {"call_session": None, "stream_sid": None}
    voicelive_connection = None
    try:
        instructions, voice_name, greeting_text = build_company_instructions(company_config)
        voicelive_connection = await create_voicelive_connection(instructions, voice_name, audio_settings)
        logger.info(f"✅ Azure Voice Live API connection established for {company_name}")

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
                    await handle_voicelive_event(event, signalwire_ws, voicelive_connection, company_name, stream_sid, call_session)
                except Exception as e:
                    logger.error(f"Error handling Voice Live event: {e}")
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
        # Voice Live SDK connection cleanup is handled automatically
        # No explicit close needed for connections created with __aenter__()
        pass

# ──────────────────────────────────────────────────────────────────────────────
# VOICE LIVE → SIGNALWIRE EVENT HANDLER
# ──────────────────────────────────────────────────────────────────────────────
async def handle_voicelive_event(
    event,  # Voice Live SDK event object
    signalwire_ws: WebSocket,
    voicelive_connection,
    company_name: str,
    stream_sid: Optional[str],
    call_session: Optional[CallSession]
):
    """Handle events from Voice Live API and forward to SignalWire"""
    logger.debug(f"📥 Voice Live event: {event.type}")

    if event.type == ServerEventType.SESSION_UPDATED:
        logger.info(f"✅ {company_name} Voice Live session ready")

    elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
        logger.info("🎤 Caller started speaking")

    elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
        logger.info("🎤 Caller stopped speaking")

    elif event.type == ServerEventType.RESPONSE_CREATED:
        logger.info(f"🤖 {company_name} AI responding")

    elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
        if signalwire_ws.application_state != WebSocketState.CONNECTED:
            return

        # Voice Live SDK returns audio as bytes in event.delta
        audio_bytes = event.delta
        if not audio_bytes:
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

    elif event.type == ServerEventType.RESPONSE_DONE:
        logger.info("✅ Response complete")

    elif event.type == ServerEventType.ERROR:
        error_msg = getattr(event, 'error', {}).get('message', 'Unknown error') if hasattr(event, 'error') else 'Unknown error'
        logger.error(f"❌ Voice Live error: {error_msg}")
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({
                "type": "error",
                "source": "voicelive",
                "detail": error_msg
            }))

    # Note: Function calling temporarily removed
    # Voice Live SDK doesn't support tools in RequestSession yet
    # Will re-add when SDK supports function calling

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

                        context_message = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "system",
                                "content": [{
                                    "type": "input_text",
                                    "text": context_text
                                }]
                            }
                        }

                        # Note: Voice Live SDK handles context differently
                        # Context is provided in the initial instructions
                        logger.info(f"📤 Call context:\n{context_text}")

                        # Wait for audio stream to fully establish before greeting
                        await asyncio.sleep(1.5)

                        # Trigger response - Cedar will use his script's greeting
                        # Voice Live SDK uses response.create() method
                        await voicelive_connection.response.create()
                        logger.info("✅ Triggered greeting (Cedar will use his script)")

                    elif event_name == "media":
                        if not call_session:
                            continue
                        
                        payload = (data.get("media") or {}).get("payload")
                        if not payload:
                            continue

                        # Save caller audio for recording
                        if SAVE_RECORDINGS:
                            call_session.add_caller_audio(payload)

                        # Forward to Voice Live API (server VAD handles turn detection)
                        await voicelive_connection.input_audio_buffer.append(audio=payload)
                        logger.debug("📨 Forwarded audio to Voice Live")

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
