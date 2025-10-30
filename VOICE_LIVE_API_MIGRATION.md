# Migration from Azure OpenAI Realtime API to Azure Voice Live API

## Overview
This document outlines the changes needed to migrate from direct Azure OpenAI Realtime API WebSocket connection to Azure Voice Live API SDK.

## Why Migrate?
- **Full SSML Support**: Azure TTS voices support complete SSML prosody controls (pitch, rate, volume)
- **Better Voice Options**: 600+ Azure Neural voices vs 6 OpenAI voices
- **Consistent Prosody**: Azure TTS voices maintain stable tone throughout responses
- **Advanced Features**: Noise suppression, echo cancellation, semantic VAD

## Key Changes Required

### 1. Imports

**REMOVE:**
```python
import websockets
```

**ADD:**
```python
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
```

### 2. Connection Method

**OLD (Direct WebSocket):**
```python
async def create_azure_websocket_connection(company_instructions, voice_name, audio_settings):
    base_endpoint = AZURE_AI_ENDPOINT.replace("https://", "").replace("http://", "").split('/')[0]
    ws_url = (
        f"wss://{base_endpoint}/openai/realtime"
        f"?api-version=2025-04-01-preview"
        f"&deployment={AZURE_AI_MODEL}"
        f"&api-key={AZURE_AI_KEY}"
    )
    azure_ws = await websockets.connect(ws_url)

    # Send session config as JSON
    session_config = {
        "type": "session.update",
        "session": { ... }
    }
    await azure_ws.send(json.dumps(session_config))
    return azure_ws
```

**NEW (Voice Live SDK):**
```python
async def create_voicelive_connection(company_instructions, voice_name, audio_settings):
    # Connect using SDK
    connection = await connect(
        endpoint=AZURE_AI_ENDPOINT,
        credential=AzureKeyCredential(AZURE_AI_KEY),
        model=AZURE_AI_MODEL,
    ).__aenter__()  # Enter async context manager

    # Configure voice (Azure TTS voice for SSML support)
    voice_config = AzureStandardVoice(
        name="en-US-AvaNeural",  # Or any Azure Neural voice
        type="azure-standard"
    )

    # Configure session using typed models
    session_config = RequestSession(
        modalities=[Modality.TEXT, Modality.AUDIO],
        instructions=company_instructions,
        voice=voice_config,
        input_audio_format=InputAudioFormat.PCM16,
        output_audio_format=OutputAudioFormat.PCM16,
        turn_detection=ServerVad(
            threshold=0.3,
            prefix_padding_ms=200,
            silence_duration_ms=800
        ),
        temperature=float(audio_settings.get("temperature", 0.4)),
        max_response_output_tokens=int(audio_settings.get("max-response-tokens", 2048))
    )

    await connection.session.update(session=session_config)
    return connection
```

### 3. Sending Audio

**OLD:**
```python
audio_append = {
    "type": "input_audio_buffer.append",
    "audio": audio_base64
}
await azure_ws.send(json.dumps(audio_append))
```

**NEW:**
```python
await connection.input_audio_buffer.append(audio=audio_base64)
```

### 4. Event Handling

**OLD:**
```python
message = await azure_ws.recv()
event = json.loads(message)
event_type = event.get("type")

if event_type == "response.audio.delta":
    audio_data = base64.b64decode(event.get("delta", ""))
    # Send to SignalWire
```

**NEW:**
```python
async for event in connection:
    if event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
        audio_data = event.delta  # Already decoded bytes
        # Send to SignalWire
```

### 5. Available Event Types

**Voice Live SDK ServerEventType Enum:**
- `SESSION_UPDATED` - Session configuration confirmed
- `INPUT_AUDIO_BUFFER_SPEECH_STARTED` - User started speaking
- `INPUT_AUDIO_BUFFER_SPEECH_STOPPED` - User stopped speaking
- `RESPONSE_CREATED` - Assistant response started
- `RESPONSE_AUDIO_DELTA` - Audio chunk from assistant
- `RESPONSE_AUDIO_DONE` - Assistant finished speaking
- `RESPONSE_DONE` - Complete response finished
- `ERROR` - Error occurred
- `CONVERSATION_ITEM_CREATED` - New conversation item

### 6. Voice Configuration for SSML

**For Full SSML Support (prosody, pitch, rate):**
```python
voice_config = AzureStandardVoice(
    name="en-US-AvaNeural",      # Or en-US-GuyNeural, en-US-JennyNeural, etc.
    type="azure-standard"
)
```

**Available Azure Neural Voices for Senior Life (warm, empathetic):**
- `en-US-AvaNeural` - Female, friendly and warm
- `en-US-GuyNeural` - Male, warm and reassuring
- `en-US-JennyNeural` - Female, customer service friendly
- `en-US-AriaNeural` - Female, conversational
- `en-US-DavisNeural` - Male, natural and smooth

**HD Voices (even better quality):**
- `en-US-Ava:DragonHDLatestNeural`
- `en-US-Guy:DragonHDLatestNeural`

### 7. Function Calling (Tools)

Function calling configuration stays similar but uses Voice Live models:

```python
from azure.ai.voicelive.models import FunctionTool, FunctionParameters

tools = [
    FunctionTool(
        name="verify_surname",
        description="Verify the spelling of a caller's last name...",
        parameters=FunctionParameters(
            type="object",
            properties={
                "surname": {
                    "type": "string",
                    "description": "The surname as heard from the caller"
                }
            },
            required=["surname"]
        )
    )
]
```

## Migration Steps

1. **Update requirements.txt** ✅ (Already done)
2. **Update imports** - Add Voice Live SDK imports
3. **Refactor connection function** - Use `connect()` instead of websockets
4. **Update session configuration** - Use typed models
5. **Update event handling loop** - Use `async for event in connection`
6. **Update audio sending** - Use `connection.input_audio_buffer.append()`
7. **Choose Azure TTS voice** - Select voice from 600+ options
8. **Test with SignalWire** - Verify audio bridge works
9. **Add SSML prosody controls** (optional) - Fine-tune voice characteristics

## Benefits After Migration

✅ **Consistent voice prosody** - No more feminine voice shift
✅ **SSML prosody control** - Adjust pitch, rate, volume dynamically
✅ **Better voice options** - 600+ voices vs 6
✅ **Empathetic voices** - Better suited for senior insurance sales
✅ **Advanced features** - Noise suppression, echo cancellation
✅ **Same audio format** - PCM16 24kHz (no changes needed)

## Voice Recommendation for Cedar

Based on "empathetic and relatable" requirement:

**Top Choice: `en-US-GuyNeural`**
- Male voice
- Warm, reassuring tone
- Natural conversational style
- Excellent for customer service

**Alternative: `en-US-AvaNeural`**
- Female voice
- Friendly and approachable
- Very consistent prosody
- Great for building trust

## Next Steps

1. Review this migration guide
2. Approve full refactor of app.py
3. I'll update the code to use Voice Live API
4. Test with SignalWire phone calls
5. Fine-tune voice with SSML if needed
