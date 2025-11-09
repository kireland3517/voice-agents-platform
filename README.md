# Azure Voice Live API - Voice Agent Platform

**Version:** 21.0
**Status:** Production
**Last Updated:** November 9, 2025

Real-time AI voice agent platform powered by Azure Voice Live API with function calling, enabling natural phone conversations for insurance companies.

---

## 🎯 What This Does

Customers call a phone number → Azure handles the call → AI agent (Sarah for Senior Life) answers → Natural conversation with voice → Information collected → Transfer to human agent or schedule callback.

**Key Features:**
- ✅ Natural, human-like AI voice conversations
- ✅ Real-time speech-to-text and text-to-speech
- ✅ **Function calling** for surname verification and ZIP code lookup
- ✅ Per-company customization (voice, personality, business rules)
- ✅ Business hours awareness with transfer logic
- ✅ Call recording and transcription
- ✅ Production-grade monitoring and resilience

---

## 🏗️ Architecture

### High-Level Flow

```
Phone Call → SignalWire → Azure Voice Live API → AI Processing → Voice Response
                ↓                    ↓
         WebSocket Audio      Function Calling
                                (Surname/ZIP)
```

### Technology Stack

- **AI:** Azure Voice Live API (gpt-realtime-mini)
- **Speech:** Whisper (transcription) + Azure Neural TTS (synthesis)
- **Telephony:** SignalWire (phone numbers, PSTN integration)
- **Backend:** Python 3.12, Quart (async web framework)
- **Storage:** Azure Blob Storage (instructions, recordings, transcripts)
- **Config:** Azure App Configuration (per-company settings)
- **Deployment:** Azure Container Apps
- **Database:** SQLite (162K surnames), CSV (40K ZIP codes)

---

## 🚀 Current Version: 21.0

### What's New in v21.0

**Automated Prompt Management** 🎉
- GitHub Actions CI/CD for automated prompt uploads to Azure Blob Storage
- Automated prompt versioning with git integration
- Version archive system: `prompts/sarah-v{VERSION}-{description}.md`
- Azure Blob Versioning enabled for automatic timestamped snapshots
- Principles-based conversation flow (v14) instead of exact scripts

**Infrastructure Improvements:**
- Workspace cleanup (Ch84): Removed deprecated Cedar files and troubleshooting docs
- Fixed Pylance import warnings with pyrightconfig.json
- Cleanup scripts for future maintenance (cleanup.ps1, cleanup.sh)
- Streamlined blob storage structure

**Prompt Updates:**
- Sarah v14: Natural phone number grouping (3-3-4 pattern)
- Principles-based guidance for flexible, natural voice cadence
- Removed exact word-for-word scripts for more conversational flow

---

## 📋 Function Calling

### Available Functions

#### 1. `verify_surname`
Verifies customer surname spelling using phonetic matching.

**Example:**
```
Customer: "My last name is Smith"
AI: Calls verify_surname("Smith")
Result: {status: "multiple", options: ["SMITH", "SMYTH"]}
AI: "Is that spelled S-M-I-T-H or S-M-Y-T-H?"
```

#### 2. `lookup_zipcode`
Validates ZIP code and confirms city/state.

**Example:**
```
Customer: "My ZIP code is 22030"
AI: Calls lookup_zipcode("22030")
Result: {found: true, city: "Fairfax", state: "Virginia"}
AI: "So that's Fairfax, Virginia, correct?"
```

### How It Works

1. **SDK Detection:** Voice Live API fires `response.function_call_arguments.done` event
2. **Execution:** Python function executes locally (database lookup)
3. **SDK Bypass:** Raw WebSocket message sent directly to API
4. **AI Response:** Cedar uses the result in conversation

**Note:** We bypass the Azure Voice Live SDK for function outputs due to SDK limitations. See [FUNCTION_CALLING.md](FUNCTION_CALLING.md) for details.

---

## 📁 Project Structure

```
voice-agents-platform/
├── app.py                           # Main application (Quart server, WebSocket handling)
├── config.py                        # Configuration manager (Azure App Config, Blob Storage)
├── surname_verifier.py              # Surname verification service (162K database)
├── zipcode_service.py               # ZIP code lookup service (40K entries)
├── call_session.py                  # Call session tracking
│
├── sarah_instructions_senior_life.md # Current production prompt (v14)
├── prompts/                         # Versioned prompt archives
│   ├── README.md                    # Prompt management guide
│   ├── sarah-v13-exact-scripts.md   # v13 archive
│   └── sarah-v14-changed-from...md  # v14 archive (auto-generated)
│
├── .github/workflows/               # CI/CD automation
│   └── deploy-to-azure.yml          # Automated deployments & prompt uploads
│
├── cleanup.ps1                      # PowerShell cleanup script
├── cleanup.sh                       # Bash cleanup script
├── pyrightconfig.json               # VSCode Pylance configuration
│
├── FUNCTION_CALLING.md              # Function calling architecture & SDK bypass
├── ARCHITECTURE_DIAGRAMS.md         # Mermaid diagrams (12 diagrams)
├── Technical_Architecture.md        # Detailed technical documentation
│
├── Dockerfile                       # Container build configuration
├── requirements.txt                 # Python dependencies
└── .env.example                     # Environment variable template
```

---

## 🔧 Configuration

### Per-Company Settings (Azure App Configuration)

Each company has isolated configuration under `{company-id}/*`:

- **basic-info:** Company name, greeting, industry
- **voice-config:** Azure TTS voice selection (600+ voices available)
- **audio-settings:** VAD threshold (0.5), silence duration (500ms), temperature (0.8), max tokens (1500)
- **business-hours:** Timezone, operating days/hours (supports overnight)
- **contact-info:** Transfer phone number, support email
- **business-rules:** Callback timeframes, transfer policies

### System Instructions (Blob Storage)

Detailed AI personality and conversation scripts:
- **Current Version:** `agent-instructions/sarah_instructions_senior_life.md`
- **Archives:** `agent-instructions/senior-life/prompts/sarah-v{VERSION}-{description}.md`
- **Versioning:** Azure Blob Versioning enabled (automatic timestamped snapshots)
- **Deployment:** Automated via GitHub Actions on every push to main
- **Content:** Complete system prompt, call flow, objection handling
- **Management:** See `prompts/README.md` for version management guide

---

## 📊 Monitoring & Observability

### SessionMonitor Metrics

Tracked per call:
- Token usage (with 64k/100k warnings)
- Turn count (conversation exchanges)
- Function calls executed
- VAD triggers (speech detection events)
- Errors encountered
- Call duration

### Logging

```
🔧 Function call: verify_surname with args: {'surname': 'Smith'}
   Surname verification: 46 candidates found
   Function result: {'status': 'multiple', ...}
✅ Function result sent via raw WebSocket

📊 SESSION SUMMARY for Senior Life Insurance Company:
   Duration: 59.7s
   Turns: 8
   Tokens: 4,523 (~3.5% of limit)
   Function Calls: 2
   Errors: 0
```

---

## 🚀 Deployment

### Build & Deploy

```bash
# Build Docker image
az acr build \
  --registry voiceagentsenvironmentf2c46d \
  --image voice-agent:v20.0-$(date +%s) \
  --platform linux/amd64 \
  .

# Deploy to Azure Container Apps
az containerapp update \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --image voiceagentsenvironmentf2c46d.azurecr.io/voice-agent:v20.0-<TIMESTAMP>
```

### Environment Variables

Required:
```
AZURE_AI_ENDPOINT=https://...cognitiveservices.azure.com
AZURE_AI_KEY=<key>
AZURE_AI_MODEL=gpt-realtime-mini
APP_CONFIG_CONNECTION_STRING=<connection-string>
BLOB_CONNECTION_STRING=<connection-string>
```

Optional:
```
SAVE_RECORDINGS=true
SAVE_TRANSCRIPTS=true
LOG_LEVEL=INFO
```

---

## 📚 Documentation

- **[FUNCTION_CALLING.md](FUNCTION_CALLING.md)** - Complete function calling guide
- **[ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md)** - 12 Mermaid diagrams
- **[Technical_Architecture.md](Technical_Architecture.md)** - Detailed technical docs
- **[VOICE_LIVE_API_MIGRATION.md](VOICE_LIVE_API_MIGRATION.md)** - Migration from SignalWire

---

## 🔬 Testing

### Test a Call

1. Call the company phone number (e.g., +1-833-XXX-XXXX)
2. Speak naturally with Cedar
3. Provide surname: "My last name is Ireland"
4. Provide ZIP: "My ZIP code is 22030"
5. Observe function calling in action

### View Logs

```bash
# Stream Container App logs
az containerapp logs show \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --follow

# Look for:
# - 🔧 Function call events
# - ✅ Function result sent
# - 📊 Session summaries
```

---

## ⚠️ Known Issues & Workarounds

### SDK Limitation: Function Calling

**Issue:** Azure Voice Live SDK (`azure-ai-voicelive` v1.0.0) doesn't properly support function output submission.

**Symptom:**
```python
TypeError: ConversationRequestItem.__init__() got an unexpected keyword argument 'call_id'
```

**Workaround:** We bypass the SDK and send raw WebSocket messages directly:
```python
ws = voicelive_connection._ws or voicelive_connection.ws
await ws.send(json.dumps({
    "type": "conversation.item.create",
    "item": {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result)
    }
}))
```

**Status:** Production workaround in place. Will migrate to SDK method when fixed.

---

## 🎓 Key Concepts

### Voice Activity Detection (VAD)

**Semantic VAD:**
- Threshold: 0.5 (balanced sensitivity)
- Silence: 500ms (natural pause detection)
- Padding: 300ms (prevent cutoff)
- Result: 40-60% better turn detection vs standard VAD

### Audio Processing

**Format:** PCM16, 24kHz, mono
**Chunking:** 100ms optimal chunks (research-backed)
- 2400 samples per chunk @ 24kHz
- 4800 bytes per chunk (16-bit)
- Buffered for alignment

### Token Management

**Limits:**
- Context window: 128,000 tokens
- Typical call: 3,000-5,000 tokens
- Audio usage: ~800 tokens/minute
- Session limit: ~15 minutes

---

## 🔗 Quick Links

- [Azure Voice Live API Docs](https://learn.microsoft.com/azure/ai-services/openai/realtime-audio)
- [SignalWire Docs](https://developer.signalwire.com/)
- [Azure App Configuration](https://learn.microsoft.com/azure/azure-app-configuration/)
- [Azure Blob Storage](https://learn.microsoft.com/azure/storage/blobs/)

---

## 📝 License

Proprietary - Senior Life Insurance Company

---

## 👥 Support

For issues or questions:
1. Check [FUNCTION_CALLING.md](FUNCTION_CALLING.md) for function calling issues
2. Review logs for error messages
3. Consult architecture diagrams for flow understanding
4. Contact development team

---

**Version History:**
- v21.0 (Nov 9, 2025) - Automated prompt management, GitHub Actions CI/CD, Azure Blob Versioning, workspace cleanup (Ch84)
- v20.0 (Nov 1, 2025) - Function calling via SDK bypass, production optimizations
- v19.x (Oct 31, 2025) - Function calling iterations, transcription fixes
- v18.x (Oct 30, 2025) - Initial function calling implementation
- v17.x (Oct 29, 2025) - Voice Live API migration complete
- v16.x and earlier - SignalWire Voice Live implementation

