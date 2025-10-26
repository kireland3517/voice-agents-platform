# ACS + Voice Live API Migration Architecture

**Date:** October 26, 2025
**Migration Type:** Complete rebuild from SignalWire to Azure Communication Services
**Runtime:** Python (Quart framework)

> 📊 **Visual Diagrams:** See [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md) for comprehensive Mermaid diagrams including:
> - Overall system architecture
> - Call initiation sequence
> - Active call audio flow
> - Surname verification flow
> - ZIP code lookup flow
> - Business hours logic
> - Call termination sequence
> - Component interaction map
> - Deployment architecture

---

## 🎯 Migration Overview

### Current Stack (SignalWire)
```
Phone → SignalWire → FastAPI WebSocket → Azure OpenAI Realtime API
```

### New Stack (ACS + Voice Live)
```
Phone → Azure Communication Services → Quart WebSocket → Azure AI Foundry Voice Live API
```

---

## 📊 Architecture Components

### 1. **Azure Communication Services (ACS)**
**Replaces:** SignalWire telephony integration
**Provides:**
- PSTN phone number
- Call automation APIs
- Media streaming (PCM audio, 24kHz)
- Event Grid integration
- WebSocket bidirectional audio

**Resources Needed:**
- Communication Services resource
- Phone number (acquired via ACS)
- Event Grid subscription for `IncomingCall` events

### 2. **Azure AI Foundry - Voice Live API**
**Replaces:** Azure OpenAI Realtime API
**Provides:**
- Real-time speech-to-speech
- Built-in turn detection (Semantic VAD)
- Azure Deep Noise Suppression
- Server echo cancellation
- Integration with your gpt-realtime-mini model

**Resources Needed:**
- Azure AI Foundry resource (with .services.ai.azure.com endpoint)
- Voice Live API enabled
- API key OR Managed Identity

### 3. **Python Application (Quart Framework)**
**Replaces:** FastAPI app.py
**Framework:** Quart (async Flask alternative, better WebSocket support)
**Structure:**
```
voice-agents-acs/
├── server.py                      # Main Quart application
├── app/
│   ├── handlers/
│   │   ├── acs_event_handler.py   # ACS call events
│   │   ├── acs_media_handler.py   # Audio streaming to Voice Live
│   │   └── conversation_handler.py # Business logic integration
│   ├── services/
│   │   ├── config_manager.py      # Azure App Config (reuse existing)
│   │   ├── surname_service.py     # Surname verification
│   │   ├── zipcode_service.py     # ZIP code lookup
│   │   └── business_hours.py      # Business hours logic
│   └── models/
│       └── call_session.py        # Session state tracking
├── data/
│   ├── surnames.db               # Downloaded from blob on startup
│   └── us-zipcodes.csv           # Embedded in container
├── requirements.txt
├── .env
└── Dockerfile
```

### 4. **Azure Resources (Reused)**
**Keep these existing resources:**
- ✅ Azure App Configuration (company configs)
- ✅ Azure Blob Storage:
  - `agent-instructions` (detailed instructions)
  - `agent-data` (surnames.db - 7MB)
  - `call-recordings` (audio files)
  - `call-transcripts` (JSON transcripts)

---

## 🔄 Data Flow

### Call Initiation
```
1. Customer dials ACS phone number
2. ACS sends IncomingCall event → Event Grid
3. Event Grid webhook → /acs/incomingcall endpoint
4. Application answers call with media streaming options
5. ACS establishes WebSocket connection → /acs/ws
6. Application connects to Voice Live API
7. Application sends session configuration:
   - Load company config from App Configuration
   - Load detailed instructions from blob
   - Download surnames.db from blob (if not cached)
   - Add business hours context
   - Configure Voice Live session
```

### Active Call
```
1. ACS streams caller audio (PCM 24kHz) → WebSocket
2. Application forwards audio → Voice Live API
3. Voice Live API:
   - Real-time STT (speech-to-text)
   - LLM processing (gpt-realtime-mini)
   - Real-time TTS (text-to-speech)
4. Application receives AI audio ← Voice Live API
5. Application forwards AI audio → ACS WebSocket
6. ACS plays audio to caller
7. Surname verification hooks trigger when AI asks for last name
8. ZIP code lookup triggers when collecting address
9. Business hours logic embedded in system prompt
```

### Call Termination
```
1. Caller hangs up OR AI transfers call
2. ACS sends CallDisconnected event
3. Application closes Voice Live WebSocket
4. Application saves recording to blob storage
5. Application saves transcript to blob storage
6. Application cleans up session state
```

---

## 🧩 Feature Integration

### 1. **Surname Verification** (162K Database)
**Files:** `surname_verifier.py`, `voice_agent_integration.py`
**Database:** `surnames.db` in `agent-data` blob container
**Integration Point:**
- Monitor Voice Live transcription events
- Detect when AI asks for last name
- Run phonetic matching (Double Metaphone + Jaro-Winkler)
- Inject verification prompt into conversation
- Send updated instructions to Voice Live

**Startup Process:**
```python
# On application startup
if not os.path.exists('data/surnames.db'):
    download_from_blob('agent-data', 'surnames.db', 'data/surnames.db')
```

### 2. **ZIP Code Lookup**
**File:** `data/us-zipcodes.csv` (808KB, embedded)
**Integration Point:**
- Monitor conversation for ZIP code mention
- Lookup city/state
- Auto-confirm with customer

### 3. **Business Hours Logic**
**Reuse from:** `app.py` lines 527-571
**Features:**
- Timezone aware (pytz)
- Overnight hours support (e.g., Mon 8am - Tue 2am)
- Day of week filtering
- Inject into Voice Live system prompt

**Example Prompt Injection:**
```python
current_time = datetime.now(pytz.timezone(config['business-hours']['timezone']))
is_business_hours = check_business_hours(current_time, config)

context = f"""
Current Time: {current_time.strftime('%A, %B %d, %Y at %I:%M %p %Z')}
Business Status: {'OPEN - can transfer to agent' if is_business_hours else 'CLOSED - offer callback'}
"""
```

### 4. **Information Collection Flow**
**Fields to collect:**
1. First name
2. Last name (with surname verification)
3. Phone number (format validation)
4. Email address
5. ZIP code (with city/state lookup)
6. Street address
7. Date of birth

**State Management:**
```python
class CallSession:
    def __init__(self):
        self.collected_info = {
            'first_name': None,
            'last_name': None,
            'last_name_verified': False,
            'phone': None,
            'email': None,
            'zipcode': None,
            'city': None,
            'state': None,
            'address': None,
            'dob': None
        }
        self.transcript = []
        self.audio_chunks = []
```

---

## 🔐 Configuration & Environment

### Environment Variables (.env)
```bash
# Azure Communication Services
ACS_CONNECTION_STRING="endpoint=https://...;accesskey=..."
ACS_DEV_TUNNEL=""  # Only for local testing

# Azure AI Foundry - Voice Live API
AZURE_VOICE_LIVE_ENDPOINT="https://your-foundry.services.ai.azure.com"
AZURE_VOICE_LIVE_API_KEY="your-api-key"
VOICE_LIVE_MODEL="gpt-realtime-mini"

# Azure App Configuration (reuse existing)
APP_CONFIG_CONNECTION_STRING="Endpoint=https://...;Id=...;Secret=..."

# Azure Blob Storage (reuse existing)
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=..."
BLOB_CONTAINER_NAME="agent-instructions"
DATA_CONTAINER_NAME="agent-data"
RECORDINGS_CONTAINER_NAME="call-recordings"
TRANSCRIPTS_CONTAINER_NAME="call-transcripts"

# Application Settings
COMPANY_ID="senior-life"
LOG_LEVEL="INFO"
ENABLE_SURNAME_VERIFICATION="true"
ENABLE_RECORDING="true"
```

### Azure App Configuration Keys (Keep existing)
```
senior-life/basic-info
senior-life/voice-config
senior-life/business-hours
senior-life/contact-info
senior-life/audio-settings
senior-life/business-rules
```

---

## 📦 Dependencies (requirements.txt)

```python
# Web framework
quart>=0.20.0
quart-cors>=0.8.0

# WebSocket
websockets>=15.0.0

# Azure SDKs
azure-communication-callautomation>=1.4.0
azure-communication-identity>=1.5.0
azure-eventgrid>=4.22.0
azure-appconfiguration>=1.4.0
azure-storage-blob>=12.19.0
azure-identity>=1.23.0
azure-core>=1.34.0

# AI/ML
openai[realtime]>=1.93.0

# Existing dependencies (reuse)
python-dotenv>=1.0.0
pytz>=2024.1

# Surname verification dependencies
phonetics>=1.0.5
jellyfish>=1.0.0

# HTTP client
httpx>=0.28.0
aiohttp>=3.12.14

# Protocol support
h2>=4.3.0
```

---

## 🚀 Deployment Strategy

### Phase 1: Azure Resources
1. Create Azure Communication Services
2. Get ACS phone number
3. Configure Event Grid subscription
4. Verify Azure AI Foundry resource exists

### Phase 2: Application Build
1. Build new Python application structure
2. Integrate ACS handlers
3. Connect Voice Live API
4. Port surname verification
5. Add business hours logic
6. Implement information collection

### Phase 3: Testing
1. Local testing with DevTunnel
2. Web client testing
3. Phone call testing
4. End-to-end validation

### Phase 4: Cutover
1. Update phone routing (keep SignalWire as backup)
2. Monitor first production calls
3. Validate recordings/transcripts
4. Full cutover when stable

---

## 💰 Cost Comparison

### Current (SignalWire + Realtime API)
- SignalWire: ~$10/1000 min
- Azure OpenAI Realtime: ~$300/1000 min
- **Total: ~$310/1000 min**

### New (ACS + Voice Live)
- ACS: ~$5/1000 min
- Voice Live API: ~$64/1000 min
- Azure OpenAI (text): ~$100/1000 min
- **Total: ~$169/1000 min**

**Savings: ~$141/1000 minutes (45% reduction)**

---

## 🎯 Success Criteria

### Must Have (Launch)
- ✅ Incoming calls route to ACS number
- ✅ Voice Live API conversation works
- ✅ Surname verification triggers correctly
- ✅ Business hours logic works
- ✅ Recordings saved to blob
- ✅ Transcripts saved to blob

### Nice to Have (Post-launch)
- Real-time call monitoring dashboard
- Call analytics
- A/B testing framework
- Multi-language support

---

## 📝 Next Steps

1. **Create Azure Resources** (see AZURE_SETUP_GUIDE.md)
2. **Build Application** (start with server.py)
3. **Local Testing** (DevTunnel + web client)
4. **Deploy to Container Apps**
5. **Production Testing**
6. **Cutover**
