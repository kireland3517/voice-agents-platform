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
import websockets
import pytz

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState
from dotenv import load_dotenv

from config import ConfigManager

from functools import lru_cache
from time import time

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
logger.info("🎙️ VOICE AGENT - AZURE OPENAI REALTIME API")
logger.info("=" * 80)
logger.info(f"Azure Endpoint: {AZURE_AI_ENDPOINT}")
logger.info(f"Model: {AZURE_AI_MODEL}")
logger.info(f"Audio Format: PCM16 24kHz passthrough")
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

    if detailed_instructions:
        instructions = detailed_instructions
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

        instructions = f"""You are a professional phone agent for {company_name}.

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
# AZURE REALTIME WS CONNECTION
# ──────────────────────────────────────────────────────────────────────────────
async def create_azure_websocket_connection(company_instructions, voice_name, audio_settings):
    base_endpoint = AZURE_AI_ENDPOINT.replace("https://", "").replace("http://", "").split('/')[0]
    ws_url = (
        f"wss://{base_endpoint}/openai/realtime"
        f"?api-version=2025-04-01-preview"
        f"&deployment={AZURE_AI_MODEL}"
        f"&api-key={AZURE_AI_KEY}"
    )

    logger.info("Connecting to Azure OpenAI Realtime API")
    logger.info(f"Endpoint: wss://{base_endpoint}/openai/realtime")
    logger.info(f"Deployment: {AZURE_AI_MODEL}")

    azure_ws = await websockets.connect(ws_url)

    # Simple session config - let server VAD handle everything naturally
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": company_instructions,
            "voice": voice_name,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
            },
            "temperature": float(audio_settings.get("temperature", 0.6)),
            "max_response_output_tokens": int(audio_settings.get("max-response-tokens", 2048)),
        }
    }
    
    await azure_ws.send(json.dumps(session_config))
    logger.info("✅ Azure Realtime session configured")
    logger.info(f"   Voice: {voice_name}")
    logger.info(f"   Mode: Natural conversation (server VAD)")
    
    return azure_ws

# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Voice Agent Bridge")

@app.get("/")
def root():
    return {
        "ok": True,
        "service": "Voice Agent Bridge",
        "version": "13.0 - Simplified (No Barge-In)",
        "api": "Azure OpenAI Realtime API",
        "model": AZURE_AI_MODEL,
        "audio_format": "PCM16 24kHz passthrough",
        "features": [
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

    azure_ws = None
    shared_state: Dict[str, Any] = {"call_session": None, "stream_sid": None}

    try:
        instructions, voice_name, greeting_text = build_company_instructions(company_config)
        azure_ws = await create_azure_websocket_connection(instructions, voice_name, audio_settings)
        logger.info(f"✅ Azure OpenAI Realtime connection established for {company_name}")

        # Start bidirectional audio forwarding
        audio_sender_task = asyncio.create_task(
            send_signalwire_audio_to_azure(signalwire_ws, azure_ws, company_id, company_name, shared_state, greeting_text)
        )
        logger.info(f"🎙️ {company_name} agent ready for calls!")

        try:
            async for message in azure_ws:
                try:
                    event = json.loads(message)
                    call_session = shared_state.get("call_session")
                    stream_sid = shared_state.get("stream_sid")
                    await handle_azure_event(event, signalwire_ws, company_name, stream_sid, call_session)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Azure message: {e}")
                except Exception as e:
                    logger.error(f"Error handling Azure event: {e}")
                    logger.error(traceback.format_exc())
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Azure WebSocket connection closed for {company_name}")
        finally:
            audio_sender_task.cancel()
            try:
                await audio_sender_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        msg = f"Azure connection failed: {e}"
        logger.error(msg)
        logger.error(traceback.format_exc())
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({"type": "error", "source": "azure", "detail": str(e)}))
            await signalwire_ws.close(code=1011)
    finally:
        if azure_ws:
            await azure_ws.close()

# ──────────────────────────────────────────────────────────────────────────────
# AZURE → SIGNALWIRE EVENT HANDLER (SIMPLIFIED)
# ──────────────────────────────────────────────────────────────────────────────
AUDIO_DELTA_EVENTS = {"response.audio.delta", "response.output_audio.delta"}
ASR_DONE_EVENTS = {"response.audio_transcript.done", "response.output_audio_transcript.done"}

async def handle_azure_event(
    event: Dict[str, Any],
    signalwire_ws: WebSocket,
    company_name: str,
    stream_sid: Optional[str],
    call_session: Optional[CallSession]
):
    event_type = event.get("type", "")
    logger.debug(f"📥 Azure event: {event_type}")

    if event_type == "session.updated":
        logger.info(f"✅ {company_name} Realtime session ready")

    elif event_type == "input_audio_buffer.speech_started":
        logger.info("🎤 Caller started speaking")

    elif event_type == "input_audio_buffer.speech_stopped":
        logger.info("🎤 Caller stopped speaking")

    elif event_type == "conversation.item.input_audio_transcription.completed":
        if SAVE_TRANSCRIPTS and call_session:
            transcript_text = event.get("transcript", "")
            if transcript_text:
                call_session.add_transcript_entry("caller", transcript_text)
                logger.info(f"📝 Caller: {transcript_text}")

    elif event_type == "response.created":
        logger.info(f"🤖 {company_name} AI responding")

    elif event_type in AUDIO_DELTA_EVENTS:
        if signalwire_ws.application_state != WebSocketState.CONNECTED:
            return
        
        audio_b64 = event.get("delta")
        if not audio_b64:
            return

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

    elif event_type in ASR_DONE_EVENTS:
        if SAVE_TRANSCRIPTS and call_session:
            transcript_text = event.get("transcript", "")
            if transcript_text:
                call_session.add_transcript_entry("ai", transcript_text)
                logger.info(f"📝 AI: {transcript_text}")

    elif event_type == "response.done":
        logger.info("✅ Response complete")

    elif event_type == "error":
        error_msg = (event.get("error") or {}).get("message", "Unknown error")
        logger.error(f"❌ Azure error: {error_msg}")
        if signalwire_ws.application_state == WebSocketState.CONNECTED:
            await signalwire_ws.send_text(json.dumps({
                "type": "error",
                "source": "azure",
                "detail": error_msg
            }))

# ──────────────────────────────────────────────────────────────────────────────
# SIGNALWIRE → AZURE AUDIO FORWARDER
# ──────────────────────────────────────────────────────────────────────────────
async def send_signalwire_audio_to_azure(
    signalwire_ws: WebSocket,
    azure_ws,
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
                            f"Date: {now_local.strftime('%B %d, %Y')}\n"
                            f"Day: {now_local.strftime('%A')}\n"
                            f"Time: {now_local.strftime('%I:%M %p')} {tz_abbrev}\n"
                            f"{'Agents available now for warm transfer' if is_business_hours else 'Outside business hours; schedule callback'}\n"
                            f"CallerID: {formatted_phone}\n"
                            "When collecting a callback number, confirm the caller ID when appropriate."
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

                        logger.info(f"📤 Sending context to model:\n{context_text}")
                        await azure_ws.send(json.dumps(context_message))
                        logger.info("✅ Sent call context to model")

                        # Brief pause then trigger greeting
                        await asyncio.sleep(0.1)
                        
                        initial_response = {
                            "type": "response.create",
                            "response": {
                                "modalities": ["text", "audio"],
                                "instructions": greeting_text
                            }
                        }
                        await azure_ws.send(json.dumps(initial_response))
                        logger.info("✅ Triggered greeting")

                    elif event_name == "media":
                        if not call_session:
                            continue
                        
                        payload = (data.get("media") or {}).get("payload")
                        if not payload:
                            continue

                        # Save caller audio for recording
                        if SAVE_RECORDINGS:
                            call_session.add_caller_audio(payload)

                        # Forward to Azure (server VAD handles turn detection)
                        await azure_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": payload
                        }))
                        logger.debug("📨 Forwarded audio to Azure")

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