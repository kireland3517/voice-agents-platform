"""
ACS Event Handler
Processes incoming call events and call automation callbacks from Azure Communication Services
"""
import json
import logging
import uuid
from urllib.parse import urlencode, urlparse, urlunparse

from azure.communication.callautomation import (
    AudioFormat,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    StreamingTransportType
)
from azure.communication.callautomation.aio import CallAutomationClient
from azure.eventgrid import EventGridEvent, SystemEventNames
from quart import Response

logger = logging.getLogger(__name__)


class AcsEventHandler:
    """Handles ACS event processing and call answering logic"""

    def __init__(self, config):
        """Initialize ACS client"""
        self.acs_client = CallAutomationClient.from_connection_string(
            config["ACS_CONNECTION_STRING"]
        )
        logger.info("✅ ACS Event Handler initialized")

    async def process_incoming_call(self, events: list, host_url: str, config: dict):
        """
        Process incoming call events from Event Grid.
        Answers the call and sets up media streaming to Voice Live API.

        Args:
            events: List of Event Grid events
            host_url: The host URL of this application
            config: Application configuration

        Returns:
            Response object
        """
        logger.info("📞 Processing incoming call events")

        for event_dict in events:
            event = EventGridEvent.from_dict(event_dict)
            logger.info(f"Event type: {event.event_type}")

            # Handle Event Grid subscription validation
            if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
                logger.info("🔐 Validating Event Grid subscription")
                validation_code = event.data["validationCode"]
                return Response(
                    response=json.dumps({"validationResponse": validation_code}),
                    status=200,
                    content_type="application/json"
                )

            # Handle incoming call
            if event.event_type == "Microsoft.Communication.IncomingCall":
                logger.info(f"📞 Incoming call received: {event.data}")

                # Extract caller information
                caller_info = event.data["from"]
                caller_id = (
                    caller_info["phoneNumber"]["value"]
                    if caller_info["kind"] == "phoneNumber"
                    else caller_info["rawId"]
                )

                logger.info(f"👤 Caller ID: {caller_id}")

                # Get incoming call context (required to answer the call)
                incoming_call_context = event.data["incomingCallContext"]

                # Generate unique context ID for this call
                context_id = str(uuid.uuid4())

                # Build callback URL with caller ID as query parameter
                query_parameters = urlencode({"callerId": caller_id})

                callback_events_uri = (
                    f"{config['ACS_DEV_TUNNEL']}/acs/callbacks"
                    if config["ACS_DEV_TUNNEL"]
                    else f"{host_url}/acs/callbacks"
                )
                callback_uri = f"{callback_events_uri}/{context_id}?{query_parameters}"

                # Build WebSocket URL for media streaming with caller ID
                parsed_url = urlparse(callback_events_uri)
                websocket_url = urlunparse(
                    ("wss", parsed_url.netloc, "/acs/ws", "", query_parameters, "")
                )

                logger.info(f"🔗 Callback URL: {callback_uri}")
                logger.info(f"🔌 WebSocket URL: {websocket_url}")

                # Configure media streaming options
                media_streaming_options = MediaStreamingOptions(
                    transport_url=websocket_url,
                    transport_type=StreamingTransportType.WEBSOCKET,
                    content_type=MediaStreamingContentType.AUDIO,
                    audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                    start_media_streaming=True,
                    enable_bidirectional=True,
                    audio_format=AudioFormat.PCM24_K_MONO,  # 24kHz PCM mono
                )

                # Answer the call
                logger.info("📞 Answering call...")
                result = await self.acs_client.answer_call(
                    incoming_call_context=incoming_call_context,
                    operation_context="incomingCall",
                    callback_url=callback_uri,
                    media_streaming=media_streaming_options,
                )

                logger.info(f"✅ Call answered! Connection ID: {result.call_connection_id}")
                return Response(status=200)

        logger.warning("⚠️ No incoming call event found in request")
        return Response(status=400)

    async def process_callback_events(self, context_id: str, raw_events: list, config: dict):
        """
        Process ACS callback events (call connected, disconnected, etc.)

        Args:
            context_id: Unique context ID for this call
            raw_events: List of callback events from ACS
            config: Application configuration

        Returns:
            Response object
        """
        logger.info(f"📡 Processing callbacks for context: {context_id}")

        for event_dict in raw_events:
            event_type = event_dict.get("type")
            logger.info(f"Event type: {event_type}")

            if event_type == "Microsoft.Communication.CallConnected":
                logger.info("✅ Call connected successfully")

            elif event_type == "Microsoft.Communication.CallDisconnected":
                logger.info("📴 Call disconnected")
                # TODO: Trigger cleanup, save recordings/transcripts

            elif event_type == "Microsoft.Communication.CallTransferAccepted":
                logger.info("🔄 Call transfer accepted")

            elif event_type == "Microsoft.Communication.CallTransferFailed":
                logger.warning("⚠️ Call transfer failed")

            elif event_type == "Microsoft.Communication.RecognizeCompleted":
                logger.info("🎤 Recognition completed")

            elif event_type == "Microsoft.Communication.RecognizeFailed":
                logger.warning("⚠️ Recognition failed")

            else:
                logger.debug(f"Unhandled event type: {event_type}")

        return Response(status=200)
