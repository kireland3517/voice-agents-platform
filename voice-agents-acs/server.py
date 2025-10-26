"""
Voice Agent Server - ACS + Voice Live API Integration
Replaces SignalWire + Azure OpenAI Realtime API
"""
import asyncio
import logging
import os

from quart import Quart, request, websocket
from quart_cors import cors
from dotenv import load_dotenv

from app.handlers.acs_event_handler import AcsEventHandler
from app.handlers.acs_media_handler import ACSMediaHandler

# Load environment variables
load_dotenv()

# Initialize Quart app
app = Quart(__name__, static_folder='static')
app = cors(app, allow_origin="*")

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Application configuration
app.config.update({
    # Azure Communication Services
    "ACS_CONNECTION_STRING": os.getenv("ACS_CONNECTION_STRING"),
    "ACS_PHONE_NUMBER": os.getenv("ACS_PHONE_NUMBER"),
    "ACS_DEV_TUNNEL": os.getenv("ACS_DEV_TUNNEL", ""),

    # Azure AI Foundry - Voice Live API
    "AZURE_VOICE_LIVE_ENDPOINT": os.getenv("AZURE_VOICE_LIVE_ENDPOINT"),
    "AZURE_VOICE_LIVE_API_KEY": os.getenv("AZURE_VOICE_LIVE_API_KEY"),
    "VOICE_LIVE_MODEL": os.getenv("VOICE_LIVE_MODEL", "gpt-realtime-mini"),

    # Azure App Configuration
    "APP_CONFIG_CONNECTION_STRING": os.getenv("APP_CONFIG_CONNECTION_STRING"),

    # Azure Blob Storage
    "AZURE_STORAGE_CONNECTION_STRING": os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
    "BLOB_CONTAINER_NAME": os.getenv("BLOB_CONTAINER_NAME", "agent-instructions"),
    "DATA_CONTAINER_NAME": os.getenv("DATA_CONTAINER_NAME", "agent-data"),
    "RECORDINGS_CONTAINER_NAME": os.getenv("RECORDINGS_CONTAINER_NAME", "call-recordings"),
    "TRANSCRIPTS_CONTAINER_NAME": os.getenv("TRANSCRIPTS_CONTAINER_NAME", "call-transcripts"),

    # Application Settings
    "COMPANY_ID": os.getenv("COMPANY_ID", "senior-life"),
    "ENABLE_SURNAME_VERIFICATION": os.getenv("ENABLE_SURNAME_VERIFICATION", "true").lower() == "true",
    "ENABLE_RECORDING": os.getenv("ENABLE_RECORDING", "true").lower() == "true",

    # Managed Identity (optional)
    "AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID": os.getenv("AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID", ""),
})

# Validate required configuration
required_vars = [
    "ACS_CONNECTION_STRING",
    "AZURE_VOICE_LIVE_ENDPOINT",
    "AZURE_VOICE_LIVE_API_KEY",
    "APP_CONFIG_CONNECTION_STRING",
    "AZURE_STORAGE_CONNECTION_STRING"
]

missing_vars = [var for var in required_vars if not app.config.get(var)]
if missing_vars:
    logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

logger.info("=" * 80)
logger.info("🎙️ VOICE AGENT - ACS + VOICE LIVE API")
logger.info("=" * 80)
logger.info(f"Company ID: {app.config['COMPANY_ID']}")
logger.info(f"Voice Live Endpoint: {app.config['AZURE_VOICE_LIVE_ENDPOINT']}")
logger.info(f"Voice Live Model: {app.config['VOICE_LIVE_MODEL']}")
logger.info(f"Surname Verification: {app.config['ENABLE_SURNAME_VERIFICATION']}")
logger.info(f"Recording Enabled: {app.config['ENABLE_RECORDING']}")
logger.info("=" * 80)

# Initialize ACS event handler
acs_handler = AcsEventHandler(app.config)


@app.route("/")
async def index():
    """Serve the web client test page"""
    return await app.send_static_file("index.html")


@app.route("/health", methods=["GET"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "voice-agent-acs",
        "company": app.config['COMPANY_ID']
    }, 200


@app.route("/acs/incomingcall", methods=["POST"])
async def incoming_call_handler():
    """
    Handles incoming call events from Azure Communication Services Event Grid.
    This is the webhook that ACS calls when a call comes in.
    """
    logger.info("📞 Incoming call webhook triggered")

    try:
        events = await request.get_json()
        host_url = request.host_url.replace("http://", "https://", 1).rstrip("/")

        return await acs_handler.process_incoming_call(events, host_url, app.config)

    except Exception as e:
        logger.exception(f"❌ Error processing incoming call: {e}")
        return {"error": str(e)}, 500


@app.route("/acs/callbacks/<context_id>", methods=["POST"])
async def acs_event_callbacks(context_id):
    """
    Handles ACS callback events (call connected, disconnected, etc.)
    """
    logger.info(f"📡 ACS callback for context: {context_id}")

    try:
        raw_events = await request.get_json()
        return await acs_handler.process_callback_events(context_id, raw_events, app.config)

    except Exception as e:
        logger.exception(f"❌ Error processing callback: {e}")
        return {"error": str(e)}, 500


@app.websocket("/acs/ws")
async def acs_websocket():
    """
    WebSocket endpoint for ACS to stream audio to Voice Live API.
    This handles the bidirectional audio streaming.
    """
    logger.info("🔌 ACS WebSocket connection initiated")

    try:
        handler = ACSMediaHandler(app.config)
        await handler.init_incoming_websocket(websocket, is_raw_audio=False)

        # Connect to Voice Live API
        asyncio.create_task(handler.connect())

        # Stream audio from ACS to Voice Live
        while True:
            msg = await websocket.receive()
            await handler.acs_to_voicelive(msg)

    except Exception as e:
        logger.exception(f"❌ ACS WebSocket error: {e}")

    finally:
        logger.info("🔌 ACS WebSocket connection closed")


@app.websocket("/web/ws")
async def web_websocket():
    """
    WebSocket endpoint for web browser testing.
    Allows testing the voice agent from a web page without a phone call.
    """
    logger.info("🌐 Web client WebSocket connection initiated")

    try:
        handler = ACSMediaHandler(app.config)
        await handler.init_incoming_websocket(websocket, is_raw_audio=True)

        # Connect to Voice Live API
        asyncio.create_task(handler.connect())

        # Stream audio from web client to Voice Live
        while True:
            msg = await websocket.receive()
            await handler.web_to_voicelive(msg)

    except Exception as e:
        logger.exception(f"❌ Web WebSocket error: {e}")

    finally:
        logger.info("🌐 Web WebSocket connection closed")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    logger.info(f"🚀 Starting server on port {port}")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )
