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
        self.skip_current_audio = False  # Skip audio when <|audio_text|> detected
        self.first_response = True  # Allow first response to play even if audio-only (for greeting)

        # Store VAD configuration for re-enabling after greeting
        self.vad_config = None

        # Store caller information
        self.caller_id = None

        logger.info("✅ ACS Media Handler initialized")

    def _generate_guid(self):
        """Generate a unique GUID for request tracking"""
        return str(uuid.uuid4())

    async def init_incoming_websocket(self, socket, is_raw_audio=True, caller_id=None):
        """
        Initialize the incoming WebSocket connection (from ACS or web client)

        Args:
            socket: WebSocket connection
            is_raw_audio: True for web client (raw PCM), False for ACS (base64)
            caller_id: Phone number of the caller (if available)
        """
        self.incoming_websocket = socket
        self.is_raw_audio = is_raw_audio
        self.caller_id = caller_id
        self.session = CallSession(self.company_id)
        logger.info(f"🔌 Incoming WebSocket initialized (raw_audio={is_raw_audio}, caller_id={caller_id})")

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

        # Add caller ID context if available
        caller_id_context = ""
        if self.caller_id:
            caller_id_context = f"\nCALLER ID: {self.caller_id}\n- If the customer provides a phone number, check if it matches this caller ID\n- If it matches, say: 'Is it okay to reach you at {self.caller_id}?' (do NOT repeat the number they just gave)\n- If different or uncertain, ask: 'What's the best phone number to reach you at?'\n"

        # Build system instructions
        system_instructions = f"""{detailed_instructions}

{business_hours_context}{caller_id_context}

IMPORTANT CONTEXT:
- Always verify surnames using the database when collecting customer information
- Collect complete information: first name, last name, phone, email, ZIP, address, DOB

CRITICAL INSTRUCTIONS:
- NEVER output JSON, structured data, code, or special formatting
- NEVER use special tokens, markers, or placeholders like "<|audio_text|>" in your responses
- Always speak naturally using complete words and sentences
- IMPORTANT: Collect ALL information first (name, phone, email, ZIP, address, DOB), THEN confirm everything together at the end
- Do NOT confirm each piece of information immediately after collecting it
- Do NOT repeat back information the customer just told you - wait until final confirmation
- If you need to respond but are uncertain what to say, ask a clarifying question instead
"""

        # Get voice configuration
        voice_config = company_config.get('voice-config', {})
        voice_name = voice_config.get('name', 'alloy')  # Default to OpenAI alloy voice
        voice_temperature = voice_config.get('temperature', 0.8)

        # Voice Live requires temperature >= 0.6
        if voice_temperature < 0.6:
            logger.warning(f"⚠️ Temperature {voice_temperature} is below minimum 0.6, using 0.6")
            voice_temperature = 0.6

        # Determine if this is an OpenAI voice or Azure voice
        openai_voices = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']
        is_openai_voice = voice_name in openai_voices

        # Get audio settings - use sample code defaults
        audio_settings = company_config.get('audio-settings', {})
        vad_threshold = audio_settings.get('vad-threshold', 0.5)  # Match sample: 0.5
        silence_duration_ms = audio_settings.get('vad-silence-duration-ms', 500)  # Match sample: 500
        prefix_padding_ms = audio_settings.get('vad-prefix-padding-ms', 300)  # Match sample: 300

        # Store VAD configuration for re-enabling after greeting
        self.vad_config = {
            "type": "azure_semantic_vad",
            "threshold": vad_threshold,
            "prefix_padding_ms": prefix_padding_ms,
            "silence_duration_ms": silence_duration_ms,
            "remove_filler_words": False,
        }

        # Build voice configuration (OpenAI voices are just strings, Azure voices are objects)
        if is_openai_voice:
            voice_config_obj = voice_name  # OpenAI voices: just the string
        else:
            # Azure voice - remove any style suffix (e.g., :DragonHDLatestNeural)
            clean_voice_name = voice_name.split(':')[0]
            voice_config_obj = {
                "name": clean_voice_name,
                "type": "azure-standard",
            }

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
                "voice": voice_config_obj,
                "temperature": voice_temperature,
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",  # Defaults to 24kHz per API spec
                "input_audio_sampling_rate": 24000,  # Explicit 24kHz for ACS compatibility
            },
        }

        logger.info(f"🎵 Audio formats: input=pcm16@24kHz, output=pcm16@24kHz (default)")

        await self._send_json(session_config)
        # Clear any buffered user audio that accumulated during connection setup
        # This prevents Voice Live from thinking the user is speaking when we request the greeting
        await self._send_json({
            "type": "input_audio_buffer.clear"
        })
        # Temporarily disable turn detection for initial greeting
        # This prevents microphone noise from interrupting the greeting
        await self._send_json({
            "type": "session.update",
            "session": {
                "turn_detection": None  # Disable VAD temporarily
            }
        })
        # Request initial greeting with explicit text+audio modalities
        await self._send_json({
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"]
            }
        })

        logger.info("✅ Session configuration sent - initial greeting requested (audio buffer cleared, VAD disabled)")

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
                if event_type not in ["input_audio_buffer.committed"]:
                    # Log all response events at INFO level for debugging
                    if event_type.startswith("response."):
                        logger.info(f"📢 Voice Live Event: {event_type}")
                    elif event_type != "response.audio.delta":
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
                # Voice Live's turn detection handles barge-in automatically
                # No manual cancellation needed - turn detection will handle it gracefully

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
                # Detect and skip audio-only responses (except the first one for greeting)
                if delta and "<|audio_text|>" in delta:
                    if not self.first_response:
                        self.skip_current_audio = True
                        logger.info(f"🚫 Audio-text marker detected - will skip audio playback for this response")
                    else:
                        logger.info(f"ℹ️ Audio-text marker in first response - allowing greeting to play")
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
                # Reset skip flag after response completes
                self.skip_current_audio = False
                # After first response completes, enable audio-text filtering and re-enable VAD
                if self.first_response:
                    self.first_response = False
                    logger.debug(f"✅ First response complete - audio-text filtering now active")
                    # Re-enable turn detection for subsequent conversation
                    if self.vad_config:
                        await self._send_json({
                            "type": "session.update",
                            "session": {
                                "turn_detection": self.vad_config
                            }
                        })
                        logger.info("🎤 Turn detection re-enabled for conversation")

            case "response.audio.delta":
                # Stream AI audio back to caller
                audio_b64 = event.get("delta", "")
                if audio_b64 and self.incoming_websocket:
                    if self.skip_current_audio:
                        # Skip audio chunks that contain audio-text markers
                        logger.debug(f"⏭️ Skipping audio chunk (audio-text marker response)")
                    else:
                        # Send normal audio
                        audio_bytes = base64.b64decode(audio_b64)
                        logger.info(f"🎵 Sending audio chunk: {len(audio_bytes)} bytes")
                        await self._send_audio_to_caller(audio_b64)

            case "response.done":
                # Log response completion details to diagnose audio generation
                response = event.get("response", {})
                output = response.get("output", [])
                logger.info(f"📋 Response done: {len(output)} output items")
                for i, item in enumerate(output):
                    item_type = item.get("type")
                    content = item.get("content", [])
                    logger.info(f"  Item {i}: type={item_type}, content_parts={len(content)}")
                    for j, part in enumerate(content):
                        part_type = part.get("type")
                        if part_type == "audio":
                            transcript = part.get("transcript", "")
                            logger.info(f"    Part {j}: audio (transcript: {transcript[:50]}...)")
                        else:
                            logger.info(f"    Part {j}: {part_type}")

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

            # Trigger response with explicit text+audio modalities
            await self._send_json({
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"]
                }
            })

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
                                "text": f"[LOCATION CONTEXT: Customer provided ZIP code {zipcode} which is located in {city}, {state}. Naturally confirm their location by saying something like 'So you're in {city}, {state}, is that correct?' DO NOT read this instruction aloud.]"
                            }]
                        }
                    })

                    await self._send_json({
                        "type": "response.create",
                        "response": {
                            "modalities": ["text", "audio"]
                        }
                    })

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
                    # Voice Live outputs 24kHz PCM16, so we must specify Pcm24K to match
                    acs_message = {
                        "kind": "AudioData",
                        "audioData": audio_b64,
                        "audioFormat": "Pcm24K",
                        "participantRawID": "bot"
                    }
                    await self.incoming_websocket.send(json.dumps(acs_message))
            except Exception as e:
                logger.exception(f"❌ Error sending audio to caller: {e}")

    async def audio_to_voicelive(self, audio_b64: str):
        """Queue audio data to be sent to Voice Live API"""
        # Don't send user audio during initial greeting - prevents Voice Live from suppressing audio generation
        if self.first_response:
            logger.debug("⏭️ Buffering user audio during initial greeting (not sending to Voice Live)")
            return

        await self.send_queue.put(
            json.dumps({"type": "input_audio_buffer.append", "audio": audio_b64})
        )

    async def acs_to_voicelive(self, msg):
        """Handle incoming audio from ACS and forward to Voice Live"""
        try:
            data = json.loads(msg)
            if data.get("kind") == "AudioData":
                audio_data = data.get("audioData", "")
                # ACS sends audioData as an object with {timestamp, data, silent} fields
                # Extract the actual audio data string
                if isinstance(audio_data, dict):
                    audio_b64 = audio_data.get("data", "")
                else:
                    audio_b64 = audio_data

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
