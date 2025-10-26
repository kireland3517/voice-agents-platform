"""
ACS Media Handler
Manages bidirectional audio streaming between ACS and Voice Live API
Integrates surname verification, business hours, and information collection
"""
import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime

from azure.identity.aio import ManagedIdentityCredential
from websockets.asyncio.client import connect as ws_connect

from app.services.config_manager import ConfigManager
from app.services.surname_service import SurnameService
from app.services.zipcode_service import ZipcodeService
from app.services.business_hours import check_business_hours, get_business_hours_context
from app.models.call_session import CallSession

logger = logging.getLogger(__name__)


class ACSMediaHandler:
    """Manages audio streaming between client and Azure Voice Live API"""

    def __init__(self, config):
        """Initialize media handler with configuration"""
        self.endpoint = config["AZURE_VOICE_LIVE_ENDPOINT"]
        self.model = config["VOICE_LIVE_MODEL"]
        self.api_key = config["AZURE_VOICE_LIVE_API_KEY"]
        self.client_id = config["AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID"]
        self.company_id = config["COMPANY_ID"]

        # Configuration managers
        self.config_manager = ConfigManager(config)
        self.surname_service = SurnameService(config) if config["ENABLE_SURNAME_VERIFICATION"] else None
        self.zipcode_service = ZipcodeService()

        # WebSocket connections
        self.voice_live_ws = None
        self.incoming_websocket = None

        # Audio and message queues
        self.send_queue = asyncio.Queue()
        self.send_task = None

        # Session tracking
        self.session = None
        self.is_raw_audio = True

        # State tracking for custom features
        self.listening_for_surname = False
        self.listening_for_zipcode = False
        self.skip_current_audio = False  # Flag to skip audio chunks with markers

        logger.info("✅ ACS Media Handler initialized")

    def _generate_guid(self):
        """Generate a unique GUID for request tracking"""
        return str(uuid.uuid4())

    async def init_incoming_websocket(self, socket, is_raw_audio=True):
        """
        Initialize the incoming WebSocket connection (from ACS or web client)

        Args:
            socket: WebSocket connection
            is_raw_audio: True for web client (raw PCM), False for ACS (base64)
        """
        self.incoming_websocket = socket
        self.is_raw_audio = is_raw_audio
        self.session = CallSession(self.company_id)
        logger.info(f"🔌 Incoming WebSocket initialized (raw_audio={is_raw_audio})")

    async def connect(self):
        """Connect to Azure Voice Live API via WebSocket"""
        try:
            # Build Voice Live WebSocket URL
            endpoint = self.endpoint.rstrip("/")
            model = self.model.strip()
            url = f"{endpoint}/voice-live/realtime?api-version=2025-05-01-preview&model={model}"
            url = url.replace("https://", "wss://")

            headers = {"x-ms-client-request-id": self._generate_guid()}

            # Authenticate (Managed Identity or API Key)
            if self.client_id:
                async with ManagedIdentityCredential(client_id=self.client_id) as credential:
                    token = await credential.get_token(
                        "https://cognitiveservices.azure.com/.default"
                    )
                    headers["Authorization"] = f"Bearer {token.token}"
                    logger.info("🔐 Authenticated with Managed Identity")
            else:
                headers["api-key"] = self.api_key
                logger.info("🔑 Authenticated with API Key")

            # Connect to Voice Live API
            self.voice_live_ws = await ws_connect(url, additional_headers=headers)
            logger.info("✅ Connected to Voice Live API")

            # Send session configuration
            await self._send_session_config()

            # Start receiver and sender loops
            asyncio.create_task(self._receiver_loop())
            self.send_task = asyncio.create_task(self._sender_loop())

        except Exception as e:
            logger.exception(f"❌ Failed to connect to Voice Live API: {e}")
            raise

    async def _send_session_config(self):
        """
        Send session configuration to Voice Live API.
        This includes the AI's instructions, voice settings, turn detection, etc.
        """
        # Load company configuration
        company_config = await self.config_manager.get_company_config_async(self.company_id)

        # Get detailed instructions from blob storage
        detailed_instructions = company_config.get('detailed-instructions', '')

        # Add business hours context
        business_hours_context = await get_business_hours_context(company_config)

        # Build system instructions
        system_instructions = f"""{detailed_instructions}

{business_hours_context}

IMPORTANT CONTEXT:
- Always verify surnames using the database when collecting customer information
- Confirm city/state when customer provides ZIP code
- Collect complete information: first name, last name, phone, email, ZIP, address, DOB

CRITICAL INSTRUCTIONS:
- NEVER use special tokens, markers, or placeholders like "<|audio_text|>" in your responses
- Always speak naturally using complete words and sentences
- If you need to respond but are uncertain what to say, ask a clarifying question instead
"""

        # Get voice configuration
        voice_config = company_config.get('voice-config', {})
        voice_name = voice_config.get('name', 'en-US-Aria:DragonHDLatestNeural')
        voice_temperature = voice_config.get('temperature', 0.8)

        # Get audio settings
        audio_settings = company_config.get('audio-settings', {})
        vad_threshold = audio_settings.get('vad-threshold', 0.3)
        silence_duration_ms = audio_settings.get('vad-silence-duration-ms', 200)
        prefix_padding_ms = audio_settings.get('vad-prefix-padding-ms', 200)

        # Build session configuration
        session_config = {
            "type": "session.update",
            "session": {
                "instructions": system_instructions,
                "modalities": ["text", "audio"],  # Ensure both text and audio outputs
                "turn_detection": {
                    "type": "azure_semantic_vad",
                    "threshold": vad_threshold,
                    "prefix_padding_ms": prefix_padding_ms,
                    "silence_duration_ms": silence_duration_ms,
                    "remove_filler_words": False,
                },
                "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
                "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
                "voice": {
                    "name": voice_name,
                    "type": "azure-standard",
                    "temperature": voice_temperature,
                },
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
            },
        }

        logger.info(f"🎵 Audio formats: input=pcm16, output=pcm16, sample_rate=24kHz")

        await self._send_json(session_config)
        await self._send_json({"type": "response.create"})

        logger.info("✅ Session configuration sent")

    async def _send_json(self, obj):
        """Send a JSON object to Voice Live API"""
        if self.voice_live_ws:
            await self.voice_live_ws.send(json.dumps(obj))

    async def _sender_loop(self):
        """Continuously send messages from queue to Voice Live API"""
        try:
            while True:
                msg = await self.send_queue.get()
                if self.voice_live_ws:
                    await self.voice_live_ws.send(msg)
        except Exception as e:
            logger.exception(f"❌ Sender loop error: {e}")

    async def _receiver_loop(self):
        """
        Handle incoming events from Voice Live API.
        This is where we integrate surname verification and other custom logic.
        """
        try:
            async for message in self.voice_live_ws:
                event = json.loads(message)
                event_type = event.get("type")

                # Log events
                if event_type not in ["response.audio.delta", "input_audio_buffer.committed"]:
                    logger.debug(f"Voice Live Event: {event_type}")

                # Handle different event types
                await self._handle_voice_live_event(event_type, event)

        except Exception as e:
            logger.exception(f"❌ Receiver loop error: {e}")

    async def _handle_voice_live_event(self, event_type: str, event: dict):
        """Handle specific Voice Live API events"""

        match event_type:
            case "session.created":
                session_id = event.get("session", {}).get("id")
                logger.info(f"🎤 Voice Live Session ID: {session_id}")

            case "input_audio_buffer.speech_started":
                logger.info(f"👂 Speech started at {event.get('audio_start_ms')}ms")
                await self.stop_audio()

            case "input_audio_buffer.speech_stopped":
                logger.info("🤐 Speech stopped")

            case "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript")
                logger.info(f"👤 User: {transcript}")
                self.session.add_transcript("user", transcript)

                # Surname verification trigger
                if self.surname_service and self.listening_for_surname:
                    await self._verify_surname(transcript)

                # ZIP code lookup trigger
                if self.listening_for_zipcode:
                    await self._lookup_zipcode(transcript)

            case "response.audio_transcript.delta":
                delta = event.get("delta", "")
                # Detect audio-only marker token and set flag to skip audio
                if delta and "<|audio_text|>" in delta:
                    self.skip_current_audio = True
                    logger.debug(f"🚫 Detected <|audio_text|> marker, will skip audio for this response")
                elif delta:
                    self.session.add_assistant_partial(delta)

            case "response.audio_transcript.done":
                transcript = event.get("transcript", "")
                # Filter out audio-only marker (Voice Live uses this for speech without text)
                if transcript and transcript.strip() != "<|audio_text|>":
                    logger.info(f"🤖 Assistant: {transcript}")
                    self.session.add_transcript("assistant", transcript)
                else:
                    logger.debug(f"🎵 Audio-only response (no transcript)")
                # Reset skip flag for next response
                self.skip_current_audio = False

            case "response.audio.delta":
                # Stream AI audio back to caller
                audio_b64 = event.get("delta", "")
                if audio_b64 and self.incoming_websocket:
                    # Skip audio if this is part of an audio-text marker response
                    if not self.skip_current_audio:
                        # Debug: log audio chunk info
                        audio_bytes = base64.b64decode(audio_b64)
                        logger.debug(f"🎵 Audio chunk: {len(audio_bytes)} bytes, first 16 bytes: {audio_bytes[:16].hex()}")
                        await self._send_audio_to_caller(audio_b64)
                    else:
                        logger.debug(f"⏭️ Skipping audio chunk (audio_text marker detected)")

            case "conversation.item.input_audio_transcription.failed":
                error_msg = event.get("error")
                logger.warning(f"⚠️ Transcription Error: {error_msg}")

            case "error":
                error_msg = event.get("error", {})
                logger.error(f"❌ Voice Live Error: {error_msg}")

    async def _verify_surname(self, transcript: str):
        """
        Verify surname against database using phonetic matching.
        Inject verification prompt back into Voice Live session.
        """
        if not self.surname_service:
            return

        try:
            # Extract surname from transcript (simplified - may need better NLP)
            # Assuming the transcript contains just the surname
            result = await self.surname_service.verify_surname(transcript)

            # Generate prompt based on verification result
            prompt_type = result['prompt_type']
            llm_prompt = result['llm_prompt']

            logger.info(f"📝 Surname verification: {prompt_type}")

            # Inject prompt into Voice Live conversation
            await self._send_json({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "system",
                    "content": [{
                        "type": "input_text",
                        "text": llm_prompt
                    }]
                }
            })

            # Trigger response
            await self._send_json({"type": "response.create"})

            # Reset listening flag
            self.listening_for_surname = False

        except Exception as e:
            logger.exception(f"❌ Surname verification error: {e}")

    async def _lookup_zipcode(self, transcript: str):
        """
        Look up ZIP code and auto-confirm city/state.
        """
        try:
            # Extract ZIP code from transcript (simple regex pattern)
            import re
            zip_match = re.search(r'\b\d{5}\b', transcript)

            if zip_match:
                zipcode = zip_match.group()
                result = self.zipcode_service.lookup(zipcode)

                if result:
                    city = result['city']
                    state = result['state']

                    logger.info(f"📍 ZIP {zipcode} → {city}, {state}")

                    # Inject confirmation prompt
                    await self._send_json({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "system",
                            "content": [{
                                "type": "input_text",
                                "text": f"The customer's ZIP code {zipcode} corresponds to {city}, {state}. Confirm this with them."
                            }]
                        }
                    })

                    await self._send_json({"type": "response.create"})

                # Reset listening flag
                self.listening_for_zipcode = False

        except Exception as e:
            logger.exception(f"❌ ZIP code lookup error: {e}")

    async def stop_audio(self):
        """Stop AI audio playback (for barge-in)"""
        await self._send_json({"type": "response.cancel"})

    async def _send_audio_to_caller(self, audio_b64: str):
        """Send AI audio back to the caller via ACS WebSocket"""
        if self.incoming_websocket:
            try:
                if self.is_raw_audio:
                    # Web client expects raw audio
                    audio_bytes = base64.b64decode(audio_b64)
                    logger.debug(f"📤 Sending {len(audio_bytes)} bytes to web client")
                    await self.incoming_websocket.send(audio_bytes)
                else:
                    # ACS expects JSON-wrapped base64 audio
                    acs_message = {
                        "kind": "AudioData",
                        "audioData": audio_b64,
                        "audioFormat": "Pcm16K",
                        "participantRawID": "bot"
                    }
                    await self.incoming_websocket.send(json.dumps(acs_message))
            except Exception as e:
                logger.exception(f"❌ Error sending audio to caller: {e}")

    async def audio_to_voicelive(self, audio_b64: str):
        """Queue audio data to be sent to Voice Live API"""
        await self.send_queue.put(
            json.dumps({"type": "input_audio_buffer.append", "audio": audio_b64})
        )

    async def acs_to_voicelive(self, msg):
        """Handle incoming audio from ACS and forward to Voice Live"""
        try:
            data = json.loads(msg)
            if data.get("kind") == "AudioData":
                audio_b64 = data.get("audioData", "")
                if audio_b64:
                    await self.audio_to_voicelive(audio_b64)
        except Exception as e:
            logger.exception(f"❌ ACS to Voice Live error: {e}")

    async def web_to_voicelive(self, msg):
        """Handle incoming audio from web client and forward to Voice Live"""
        try:
            # Web client sends raw audio bytes
            if isinstance(msg, bytes):
                audio_b64 = base64.b64encode(msg).decode('utf-8')
                await self.audio_to_voicelive(audio_b64)
        except Exception as e:
            logger.exception(f"❌ Web to Voice Live error: {e}")
