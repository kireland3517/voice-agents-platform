import os
import asyncio
import json
import logging
from typing import Optional
import traceback
import websockets
import base64
import wave
import io
from datetime import datetime
from contextlib import asynccontextmanager
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState
from dotenv import load_dotenv

from config import ConfigManager

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("voice_bridge")

# ──────────────────────────────────────────────────────────────────────────────
# ENV & CONFIG SETUP
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

AZURE_AI_ENDPOINT = os.getenv("AZURE_AI_ENDPOINT", "").strip()
AZURE_AI_KEY = os.getenv("AZURE_AI_KEY", "").strip()
AZURE_AI_MODEL = os.getenv("AZURE_AI_MODEL", "gpt-realtime-mini").strip()

# Initialize configuration manager
config_manager = ConfigManager()

# Validate configuration
if not (AZURE_AI_ENDPOINT and AZURE_AI_KEY):
    logger.error("Missing required environment variables")
    raise ValueError("AZURE_AI_ENDPOINT and AZURE_AI_KEY are required")

logger.info("=" * 80)
logger.info("🎙️ MULTI-TENANT VOICE AGENT BRIDGE - WITH GUARANTEED CLEANUP")
logger.info("=" * 80)
logger.info(f"Azure Endpoint: {AZURE_AI_ENDPOINT}")
logger.info(f"Model: {AZURE_AI_MODEL}")
logger.info(f"Audio Format: PCM16 24kHz (No conversion needed!)")
logger.info(f"API: Azure OpenAI Realtime API")
logger.info(f"Recording: Enabled to {config_manager.get_recordings_container_name()}")
logger.info("=" * 80)

# ──────────────────────────────────────────────────────────────────────────────
# VOICE MAPPING FOR OPENAI VOICES
# ──────────────────────────────────────────────────────────────────────────────
VOICE_MAP = {
    'alloy': 'alloy',      # Neutral, balanced
    'shimmer': 'shimmer',  # Bright, energetic
    'echo': 'echo',        # Resonant, deep
    'ash': 'ash',          # Clear, precise
    'ballad': 'ballad',    # Melodic, smooth
    'coral': 'coral',      # Warm, friendly
    'sage': 'sage',        # Calm, thoughtful
    'verse': 'verse'       # Versatile, expressive
}

# ──────────────────────────────────────────────────────────────────────────────
# DYNAMIC PROMPT BUILDER
# ──────────────────────────────────────────────────────────────────────────────
def build_company_instructions(company_config):
    """Build dynamic instructions based on company configuration"""
    
    company_name = company_config.get('company-name', 'Unknown Company')
    greeting = company_config.get('greeting', f'Thank you for calling {company_name}')
    industry = company_config.get('industry', 'general')
    voice_style = company_config.get('voice-style') or 'alloy'
    detailed_instructions = company_config.get('detailed-instructions')
    
    # Map to OpenAI voice
    openai_voice = VOICE_MAP.get(voice_style.lower(), 'alloy')
    
    # If detailed instructions exist in Blob Storage, use them
    if detailed_instructions:
        instructions = detailed_instructions
    else:
        # Fallback to basic template
        instructions = f"""You are a professional phone agent for {company_name}.

GREETING: {greeting}

INDUSTRY: {industry}

VOICE PERSONALITY:
- Professional and friendly tone appropriate for {industry}
- Clear and natural speech (you're on a phone call)
- Helpful and knowledgeable about {company_name}
- Appropriate pacing for phone conversations

CONVERSATION APPROACH:
1. Start with the greeting exactly as provided
2. Listen actively to understand the caller's needs
3. Provide relevant information about {company_name}
4. Guide the conversation professionally
5. Be helpful while staying within your knowledge scope

IMPORTANT REMINDERS:
- This is a VOICE conversation on the phone
- Speak naturally as you would in a real phone call
- Represent {company_name} professionally at all times
- Follow {industry} industry best practices
- If you need to transfer or escalate, explain clearly

Remember: You ARE the voice of {company_name}. Be professional, warm, and helpful."""

    return instructions, openai_voice

# ──────────────────────────────────────────────────────────────────────────────
# CALL RECORDING FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────
async def save_call_recording(call_recording):
    """Merge and save call recording to Azure Blob Storage"""
    
    logger.info(f"🚀 save_call_recording() function STARTED")
    logger.info(f"📦 Call recording data: caller_chunks={len(call_recording.get('caller_audio', []))}, ai_chunks={len(call_recording.get('ai_audio', []))}")
    
    try:
        if not call_recording.get('caller_audio') and not call_recording.get('ai_audio'):
            logger.warning("⚠️ No audio data to save - skipping recording")
            return
        
        logger.info(f"💾 Saving call recording for {call_recording['company_id']}")
        
        # Get blob service client
        blob_service_client = config_manager.get_blob_service_client()
        container_name = config_manager.get_recordings_container_name()
        
        logger.info(f"📁 Using container: {container_name}")
        
        # Generate file paths
        timestamp = call_recording['start_time'].strftime("%Y%m%d-%H%M%S")
        company_id = call_recording['company_id']
        stream_sid = call_recording.get('stream_sid', 'unknown')[:12]
        
        logger.info(f"📝 Filename: {company_id}/{timestamp}-{stream_sid}")
        
        # Initialize variables for metadata
        caller_pcm = b''
        ai_pcm = b''
        
        # Decode and save caller audio
        if call_recording.get('caller_audio'):
            try:
                logger.info(f"🎤 Processing caller audio ({len(call_recording['caller_audio'])} chunks)...")
                caller_pcm = b''.join([base64.b64decode(chunk) for chunk in call_recording['caller_audio']])
                
                # Create WAV file
                caller_wav = io.BytesIO()
                with wave.open(caller_wav, 'wb') as wav:
                    wav.setnchannels(1)  # Mono
                    wav.setsampwidth(2)  # 16-bit
                    wav.setframerate(24000)  # 24kHz
                    wav.writeframes(caller_pcm)
                
                # Upload to Blob Storage
                blob_path = f"{company_id}/{timestamp}-{stream_sid}-caller.wav"
                blob_client = blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_path
                )
                
                logger.info(f"📤 Uploading caller audio to: {blob_path}")
                caller_wav.seek(0)
                blob_client.upload_blob(caller_wav.getvalue(), overwrite=True)
                logger.info(f"✅ Saved caller audio: {blob_path}")
                
            except Exception as e:
                logger.error(f"❌ Failed to save caller audio: {e}")
                logger.error(traceback.format_exc())
        
        # Decode and save AI audio
        if call_recording.get('ai_audio'):
            try:
                logger.info(f"🤖 Processing AI audio ({len(call_recording['ai_audio'])} chunks)...")
                ai_pcm = b''.join([base64.b64decode(chunk) for chunk in call_recording['ai_audio']])
                
                # Create WAV file
                ai_wav = io.BytesIO()
                with wave.open(ai_wav, 'wb') as wav:
                    wav.setnchannels(1)  # Mono
                    wav.setsampwidth(2)  # 16-bit
                    wav.setframerate(24000)  # 24kHz
                    wav.writeframes(ai_pcm)
                
                # Upload to Blob Storage
                blob_path = f"{company_id}/{timestamp}-{stream_sid}-ai.wav"
                blob_client = blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_path
                )
                
                logger.info(f"📤 Uploading AI audio to: {blob_path}")
                ai_wav.seek(0)
                blob_client.upload_blob(ai_wav.getvalue(), overwrite=True)
                logger.info(f"✅ Saved AI audio: {blob_path}")
                
            except Exception as e:
                logger.error(f"❌ Failed to save AI audio: {e}")
                logger.error(traceback.format_exc())
        
        # Create mixed/combined audio (optional - both channels merged)
        if caller_pcm and ai_pcm:
            try:
                logger.info(f"🎚️ Creating mixed audio...")
                
                # Pad shorter audio with silence
                max_len = max(len(caller_pcm), len(ai_pcm))
                caller_pcm_padded = caller_pcm + b'\x00' * (max_len - len(caller_pcm))
                ai_pcm_padded = ai_pcm + b'\x00' * (max_len - len(ai_pcm))
                
                # Mix by averaging samples
                import numpy as np
                caller_array = np.frombuffer(caller_pcm_padded, dtype=np.int16)
                ai_array = np.frombuffer(ai_pcm_padded, dtype=np.int16)
                mixed_array = (caller_array.astype(np.int32) + ai_array.astype(np.int32)) // 2
                mixed_pcm = mixed_array.astype(np.int16).tobytes()
                
                # Create WAV file
                mixed_wav = io.BytesIO()
                with wave.open(mixed_wav, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(mixed_pcm)
                
                # Upload to Blob Storage
                blob_path = f"{company_id}/{timestamp}-{stream_sid}-mixed.wav"
                blob_client = blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_path
                )
                
                logger.info(f"📤 Uploading mixed audio to: {blob_path}")
                mixed_wav.seek(0)
                blob_client.upload_blob(mixed_wav.getvalue(), overwrite=True)
                logger.info(f"✅ Saved mixed audio: {blob_path}")
                
            except Exception as e:
                logger.error(f"❌ Failed to save mixed audio: {e}")
                logger.error(traceback.format_exc())
        
        # Save metadata JSON
        try:
            metadata = {
                "company_id": call_recording['company_id'],
                "company_name": call_recording.get('company_name', ''),
                "stream_sid": call_recording.get('stream_sid', ''),
                "start_time": call_recording['start_time'].isoformat(),
                "end_time": call_recording['end_time'].isoformat(),
                "duration_seconds": (call_recording['end_time'] - call_recording['start_time']).total_seconds(),
                "caller_chunks": len(call_recording.get('caller_audio', [])),
                "ai_chunks": len(call_recording.get('ai_audio', [])),
                "caller_audio_bytes": len(caller_pcm),
                "ai_audio_bytes": len(ai_pcm)
            }
            
            blob_path = f"{company_id}/{timestamp}-{stream_sid}-metadata.json"
            blob_client = blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            
            logger.info(f"📤 Uploading metadata to: {blob_path}")
            blob_client.upload_blob(json.dumps(metadata, indent=2), overwrite=True)
            logger.info(f"✅ Saved metadata: {blob_path}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save metadata: {e}")
            logger.error(traceback.format_exc())
        
        logger.info(f"🎉 Call recording saved successfully!")
        
    except Exception as e:
        logger.error(f"❌ Error in save_call_recording: {e}")
        logger.error(traceback.format_exc())

# ──────────────────────────────────────────────────────────────────────────────
# AZURE CONNECTION CONTEXT MANAGER (GUARANTEED CLEANUP)
# ──────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def azure_connection(company_instructions, voice_name, company_name):
    """Context manager ensuring Azure WebSocket cleanup"""
    ws = None
    try:
        # Build WebSocket URL
        base_endpoint = AZURE_AI_ENDPOINT.replace("https://", "").replace("http://", "")
        base_endpoint = base_endpoint.split('/')[0]
        
        ws_url = f"wss://{base_endpoint}/openai/realtime"
        ws_url += f"?api-version=2025-04-01-preview"
        ws_url += f"&deployment={AZURE_AI_MODEL}"
        ws_url += f"&api-key={AZURE_AI_KEY}"
        
        logger.info(f"Connecting to Azure OpenAI Realtime API for {company_name}")
        
        # Connect
        ws = await websockets.connect(ws_url)
        
        # Configure session
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
                    "silence_duration_ms": 500
                },
                "temperature": 0.8,
                "max_response_output_tokens": 4096
            }
        }
        
        await ws.send(json.dumps(session_config))
        logger.info(f"✅ Azure session configured for {company_name}")
        
        yield ws
        
    finally:
        # GUARANTEED cleanup
        if ws:
            try:
                await asyncio.wait_for(ws.close(), timeout=5.0)
                logger.info(f"🔌 Azure WebSocket closed for {company_name}")
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Azure close timeout for {company_name}")
            except Exception as e:
                logger.error(f"❌ Azure close error for {company_name}: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Multi-Tenant Voice Agent Bridge with Guaranteed Cleanup")

@app.get("/")
def root():
    return {
        "ok": True, 
        "service": "multi-tenant voice agent bridge", 
        "version": "9.0 - Production with Guaranteed Cleanup",
        "api": "Azure OpenAI Realtime API",
        "model": AZURE_AI_MODEL,
        "audio_format": "PCM16 24kHz passthrough",
        "features": [
            "Server-side Voice Activity Detection",
            "Native audio streaming",
            "OpenAI voices (8 options)",
            "Production-ready GA model",
            "Azure Blob Storage for instructions",
            "Full call recording (separate streams)",
            "Guaranteed resource cleanup"
        ],
        "supported_companies": ["senior-life", "monster-vacations"]
    }

@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True, "status": "healthy"})

@app.get("/companies/{company_id}/config")
def get_company_config(company_id: str):
    """Debug endpoint to view company configuration"""
    try:
        config = config_manager.get_company_config(company_id)
        if not config or not config.get('company-name'):
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        return {"company_id": company_id, "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────────────────────────────────────
# RECORDING MANAGEMENT ENDPOINTS
# ──────────────────────────────────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
from datetime import timedelta

@app.get("/recordings/{company_id}")
async def list_recordings(
    company_id: str,
    days: int = 7,  # Default: last 7 days
    limit: int = 100
):
    """
    List all recordings for a company
    
    Example: GET /recordings/senior-life?days=30&limit=50
    """
    try:
        blob_service_client = config_manager.get_blob_service_client()
        container_name = config_manager.get_recordings_container_name()
        container_client = blob_service_client.get_container_client(container_name)
        
        # Calculate cutoff date
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # List blobs in company folder
        blob_prefix = f"{company_id}/"
        blobs = container_client.list_blobs(name_starts_with=blob_prefix)
        
        recordings = []
        seen_calls = set()
        
        for blob in blobs:
            # Only include metadata files and recent recordings
            if blob.name.endswith('-metadata.json') and blob.last_modified >= cutoff_date:
                # Extract call info from filename
                # Format: company_id/YYYYMMDD-HHMMSS-streamid-metadata.json
                parts = blob.name.split('/')[-1].split('-')
                if len(parts) >= 3:
                    date_str = parts[0]
                    time_str = parts[1]
                    stream_id = parts[2]
                    
                    call_key = f"{date_str}-{time_str}-{stream_id}"
                    
                    if call_key not in seen_calls:
                        seen_calls.add(call_key)
                        
                        # Download metadata
                        try:
                            blob_client = blob_service_client.get_blob_client(
                                container=container_name,
                                blob=blob.name
                            )
                            metadata_json = blob_client.download_blob().readall()
                            metadata = json.loads(metadata_json)
                            
                            recordings.append({
                                "call_id": call_key,
                                "company_id": company_id,
                                "stream_sid": stream_id,
                                "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                                "time": f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}",
                                "start_time": metadata.get('start_time'),
                                "end_time": metadata.get('end_time'),
                                "caller_duration": f"{metadata.get('caller_duration_seconds', 0):.1f}s",
                                "ai_duration": f"{metadata.get('ai_duration_seconds', 0):.1f}s",
                                "caller_audio_url": f"/recordings/{company_id}/{call_key}/caller",
                                "ai_audio_url": f"/recordings/{company_id}/{call_key}/ai",
                                "metadata_url": f"/recordings/{company_id}/{call_key}/metadata"
                            })
                        except Exception as e:
                            logger.warning(f"Could not load metadata for {blob.name}: {e}")
        
        # Sort by date (most recent first)
        recordings.sort(key=lambda x: x['date'] + x['time'], reverse=True)
        
        # Apply limit
        recordings = recordings[:limit]
        
        return {
            "company_id": company_id,
            "total_recordings": len(recordings),
            "days": days,
            "recordings": recordings
        }
        
    except Exception as e:
        logger.error(f"Error listing recordings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recordings/{company_id}/{call_id}/caller")
async def download_caller_audio(company_id: str, call_id: str):
    """
    Download caller audio file
    
    Example: GET /recordings/senior-life/20250119-143022-abc123456789/caller
    """
    try:
        blob_service_client = config_manager.get_blob_service_client()
        container_name = config_manager.get_recordings_container_name()
        
        blob_path = f"{company_id}/{call_id}-caller.wav"
        blob_client = blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_path
        )
        
        # Check if blob exists
        if not blob_client.exists():
            raise HTTPException(status_code=404, detail="Recording not found")
        
        # Stream the audio file
        blob_data = blob_client.download_blob()
        
        return StreamingResponse(
            blob_data.chunks(),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'attachment; filename="{call_id}-caller.wav"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading caller audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recordings/{company_id}/{call_id}/ai")
async def download_ai_audio(company_id: str, call_id: str):
    """
    Download AI audio file
    
    Example: GET /recordings/senior-life/20250119-143022-abc123456789/ai
    """
    try:
        blob_service_client = config_manager.get_blob_service_client()
        container_name = config_manager.get_recordings_container_name()
        
        blob_path = f"{company_id}/{call_id}-ai.wav"
        blob_client = blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_path
        )
        
        if not blob_client.exists():
            raise HTTPException(status_code=404, detail="Recording not found")
        
        blob_data = blob_client.download_blob()
        
        return StreamingResponse(
            blob_data.chunks(),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'attachment; filename="{call_id}-ai.wav"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading AI audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recordings/{company_id}/{call_id}/metadata")
async def get_recording_metadata(company_id: str, call_id: str):
    """
    Get metadata for a specific recording
    
    Example: GET /recordings/senior-life/20250119-143022-abc123456789/metadata
    """
    try:
        blob_service_client = config_manager.get_blob_service_client()
        container_name = config_manager.get_recordings_container_name()
        
        blob_path = f"{company_id}/{call_id}-metadata.json"
        blob_client = blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_path
        )
        
        if not blob_client.exists():
            raise HTTPException(status_code=404, detail="Metadata not found")
        
        metadata_json = blob_client.download_blob().readall()
        metadata = json.loads(metadata_json)
        
        return metadata
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/recordings/{company_id}/{call_id}")
async def delete_recording(company_id: str, call_id: str):
    """
    Delete a recording (all files: caller, ai, metadata)
    
    Example: DELETE /recordings/senior-life/20250119-143022-abc123456789
    """
    try:
        blob_service_client = config_manager.get_blob_service_client()
        container_name = config_manager.get_recordings_container_name()
        
        files_deleted = []
        files_not_found = []
        
        # Delete all three files
        for file_type in ['caller', 'ai', 'metadata']:
            extension = 'wav' if file_type in ['caller', 'ai'] else 'json'
            blob_path = f"{company_id}/{call_id}-{file_type}.{extension}"
            
            blob_client = blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            
            try:
                if blob_client.exists():
                    blob_client.delete_blob()
                    files_deleted.append(blob_path)
                else:
                    files_not_found.append(blob_path)
            except Exception as e:
                logger.error(f"Error deleting {blob_path}: {e}")
        
        return {
            "deleted": files_deleted,
            "not_found": files_not_found,
            "status": "success" if files_deleted else "no_files_found"
        }
        
    except Exception as e:
        logger.error(f"Error deleting recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────────────────────────────────────
# MULTI-TENANT WEBSOCKET ENDPOINT WITH GUARANTEED CLEANUP
# ──────────────────────────────────────────────────────────────────────────────
@app.websocket("/voice/{company_id}")
async def voice_bridge(company_id: str, signalwire_ws: WebSocket):
    """Pure voice-to-voice multi-tenant bridge with guaranteed cleanup"""
    
    await signalwire_ws.accept()
    logger.info(f"✅ SignalWire connection accepted for company: {company_id}")
    
    # Initialize call recording storage
    call_recording = {
        'caller_audio': [],
        'ai_audio': [],
        'start_time': datetime.utcnow(),
        'company_id': company_id,
        'stream_sid': None
    }
    
    # Load company configuration
    try:
        company_config = config_manager.get_company_config(company_id)
        if not company_config or not company_config.get('company-name'):
            error_msg = f"Company '{company_id}' not found in configuration"
            logger.error(error_msg)
            await signalwire_ws.send_text(json.dumps({
                "type": "error", "source": "config", "detail": error_msg
            }))
            await signalwire_ws.close(code=1008)
            return
            
        company_name = company_config['company-name']
        logger.info(f"✅ Loaded config for {company_name}")
        
    except Exception as e:
        error_msg = f"Failed to load company configuration: {e}"
        logger.error(error_msg)
        await signalwire_ws.send_text(json.dumps({
            "type": "error", "source": "config", "detail": error_msg
        }))
        await signalwire_ws.close(code=1011)
        return

    # Build company-specific instructions
    company_instructions, voice_name = build_company_instructions(company_config)
    
    # Use context manager for guaranteed Azure connection cleanup
    async with azure_connection(company_instructions, voice_name, company_name) as azure_ws:
        tasks = []
        
        try:
            logger.info(f"✅ Azure connection established for {company_name}")
            
            async def forward_signalwire_to_azure():
                """Forward audio from SignalWire to Azure with recording"""
                try:
                    while True:
                        msg = await signalwire_ws.receive()
                        
                        if msg["type"] == "websocket.disconnect":
                            logger.info(f"📞 SignalWire disconnected for {company_name}")
                            break
                        
                        if "text" in msg and msg["text"] is not None:
                            data = json.loads(msg["text"])
                            
                            if data.get("event") == "connected":
                                logger.info(f"🔗 SignalWire connected for {company_name}")
                            
                            elif data.get("event") == "start":
                                stream_sid = data.get("start", {}).get("streamSid")
                                call_recording['stream_sid'] = stream_sid
                                media_format = data.get("start", {}).get("mediaFormat", {})
                                
                                logger.info(f"▶️ Call started for {company_name}")
                                logger.info(f"🔴 Recording enabled - Stream ID: {stream_sid}")
                                
                                if media_format.get("encoding") != "audio/x-L16":
                                    logger.warning(f"⚠️ Expected L16 encoding, got: {media_format.get('encoding')}")
                                if media_format.get("sampleRate") != 24000:
                                    logger.warning(f"⚠️ Expected 24000Hz, got: {media_format.get('sampleRate')}")
                            
                            elif data.get("event") == "media":
                                payload = data.get("media", {}).get("payload")
                                if payload:
                                    # Store caller audio for recording FIRST
                                    call_recording['caller_audio'].append(payload)
                                    
                                    # Then forward to Azure
                                    azure_message = {
                                        "type": "input_audio_buffer.append",
                                        "audio": payload
                                    }
                                    await azure_ws.send(json.dumps(azure_message))
                                    logger.debug(f"📨 Forwarded audio to Azure (recorded)")
                            
                            elif data.get("event") == "stop":
                                logger.info(f"⏹️ Call ended for {company_name}")
                                logger.info(f"📼 Captured {len(call_recording['caller_audio'])} caller chunks, {len(call_recording['ai_audio'])} AI chunks")
                                break
                
                except WebSocketDisconnect:
                    logger.info(f"📞 SignalWire WebSocket disconnected for {company_name}")
                except asyncio.CancelledError:
                    logger.info(f"🛑 Forward task cancelled for {company_name}")
                    raise
                except Exception as e:
                    logger.error(f"❌ Error in forward task for {company_name}: {e}")
                    logger.error(traceback.format_exc())
                    raise
            
            async def receive_from_azure():
                """Receive responses from Azure and forward to SignalWire"""
                try:
                    async for message in azure_ws:
                        event = json.loads(message)
                        event_type = event.get("type", "")
                        
                        if event_type == "session.updated":
                            logger.info(f"✅ {company_name} Realtime session ready")
                        
                        elif event_type == "response.audio.delta":
                            if "delta" in event and signalwire_ws.application_state == WebSocketState.CONNECTED:
                                azure_audio_base64 = event["delta"]
                                
                                # Store AI audio for recording FIRST
                                call_recording['ai_audio'].append(azure_audio_base64)
                                
                                # Then send to SignalWire
                                media_message = {
                                    "event": "media",
                                    "streamSid": call_recording.get('stream_sid') or "",
                                    "media": {
                                        "payload": azure_audio_base64
                                    }
                                }
                                await signalwire_ws.send_text(json.dumps(media_message))
                                logger.debug(f"🔊 Forwarded audio to SignalWire (recorded)")
                        
                        elif event_type == "error":
                            error_msg = event.get("error", {}).get("message", "Unknown error")
                            logger.error(f"❌ Azure error: {error_msg}")
                
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"Azure WebSocket closed for {company_name}")
                except asyncio.CancelledError:
                    logger.info(f"🛑 Receive task cancelled for {company_name}")
                    raise
                except Exception as e:
                    logger.error(f"❌ Error in receive task for {company_name}: {e}")
                    logger.error(traceback.format_exc())
                    raise
            
            # Create and track tasks
            tasks = [
                asyncio.create_task(forward_signalwire_to_azure()),
                asyncio.create_task(receive_from_azure())
            ]
            
            logger.info(f"🎙️ {company_name} agent ready for calls!")
            
            # Wait for first task to complete (indicates disconnect/error)
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Check for exceptions in completed tasks
            for task in done:
                if task.exception():
                    logger.error(f"Task failed with exception: {task.exception()}")
        
        finally:
            logger.info(f"🔍 Starting cleanup for {company_name}")
            
            # STEP 1: Cancel all pending tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            
            # STEP 2: Wait for all tasks to complete cancellation
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                        logger.error(f"Task {i} cleanup error: {result}")
            
            logger.info(f"✅ Tasks cleaned up for {company_name}")
            
            # STEP 3: Save recording (tasks are now stopped)
            logger.info(f"📊 Recording stats - Caller: {len(call_recording.get('caller_audio', []))} chunks, AI: {len(call_recording.get('ai_audio', []))} chunks")
            
            if call_recording.get('caller_audio') or call_recording.get('ai_audio'):
                logger.info(f"📼 Saving call recording for {company_name}")
                try:
                    await asyncio.wait_for(save_call_recording(call_recording), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.error(f"❌ Recording save timeout for {company_name}")
                except Exception as e:
                    logger.error(f"❌ Recording save error for {company_name}: {e}")
                    logger.error(traceback.format_exc())
            else:
                logger.warning(f"⚠️ No audio captured for {company_name} - skipping recording save")
            
            # STEP 4: Close SignalWire connection
            try:
                await signalwire_ws.close()
            except Exception:
                pass
            
            logger.info(f"🎉 Cleanup complete for {company_name}")
    
    # Azure WebSocket is GUARANTEED closed here due to context manager
    logger.info(f"✅ Full session cleanup complete for {company_name}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)