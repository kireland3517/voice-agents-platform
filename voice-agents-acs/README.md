# Voice Agent - ACS + Voice Live API

Complete rebuild of the voice agent platform using **Azure Communication Services** and **Azure AI Foundry Voice Live API** to replace SignalWire + Azure OpenAI Realtime API.

## 🎯 Key Features

- ✅ **Azure Communication Services** for telephony (replaces SignalWire)
- ✅ **Voice Live API** for real-time speech-to-speech (replaces Realtime API)
- ✅ **Surname Verification** with 162K phonetic matching database
- ✅ **Business Hours Logic** with overnight hours support
- ✅ **ZIP Code Lookup** with automatic city/state confirmation
- ✅ **Information Collection** (name, phone, email, address, DOB)
- ✅ **Call Recordings & Transcripts** saved to Azure Blob Storage
- ✅ **Multi-tenant** company configuration via Azure App Configuration

---

## 📊 Architecture

```
Phone Call → ACS → WebSocket → Voice Live API
                 ↓
        Azure App Configuration
        Azure Blob Storage
        Surname Database (162K)
        ZIP Code Database
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Azure Resources Created** (see [AZURE_SETUP_GUIDE.md](../AZURE_SETUP_GUIDE.md))
  - Azure Communication Services
  - ACS Phone Number
  - Azure AI Foundry (Voice Live API)
  - Azure App Configuration (existing)
  - Azure Blob Storage (existing)

- **Python 3.11+**
- **Development Tools** (for local testing)
  - Azure DevTunnel (for local ACS webhooks)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy template
cp .env.template .env

# Edit .env with your Azure resource credentials
nano .env
```

**Required variables:**
- `ACS_CONNECTION_STRING` - From Azure Communication Services
- `AZURE_VOICE_LIVE_ENDPOINT` - From Azure AI Foundry
- `AZURE_VOICE_LIVE_API_KEY` - From Azure AI Foundry
- `APP_CONFIG_CONNECTION_STRING` - Existing Azure App Configuration
- `AZURE_STORAGE_CONNECTION_STRING` - Existing Azure Blob Storage

### 4. Run Locally

#### Web Client Test (No Phone Required)

```bash
python server.py
```

Open http://localhost:8000 in your browser and click "Start Talking to Agent"

#### Phone Call Test (with DevTunnel)

Terminal 1 - Start DevTunnel:
```bash
devtunnel login
devtunnel create --allow-anonymous
devtunnel port create -p 8000
devtunnel host
```

Note the tunnel URL (e.g., `https://abc123.devtunnels.ms:8000`)

Terminal 2 - Run Server:
```bash
# Add tunnel URL to .env
echo 'ACS_DEV_TUNNEL=https://abc123.devtunnels.ms:8000' >> .env

python server.py
```

Terminal 3 - Create Event Grid Subscription:
```powershell
# In Azure Portal:
# Go to ACS resource → Events → + Event Subscription
# Event Type: IncomingCall
# Endpoint: https://abc123.devtunnels.ms:8000/acs/incomingcall
```

Call your ACS phone number to test!

---

## 🐳 Docker Deployment

### Build Image

```bash
docker build -t voice-agent-acs .
```

### Run Container

```bash
docker run --env-file .env -p 8000:8000 voice-agent-acs
```

---

## ☁️ Azure Container Apps Deployment

### 1. Build and Push to Azure Container Registry

```powershell
# Variables
$resourceGroup = "voice-agents"
$acrName = "voiceagentsacr"  # Must be globally unique
$imageName = "voice-agent-acs"
$tag = "latest"

# Create ACR if not exists
az acr create `
    --resource-group $resourceGroup `
    --name $acrName `
    --sku Basic

# Login to ACR
az acr login --name $acrName

# Build and push image
az acr build `
    --registry $acrName `
    --image "${imageName}:${tag}" `
    --file Dockerfile `
    .
```

### 2. Deploy to Container Apps

```powershell
# Variables
$containerAppName = "voice-agent-acs"
$containerAppEnv = "voice-agents-env"  # Existing or new environment

# Create Container App Environment (if needed)
az containerapp env create `
    --name $containerAppEnv `
    --resource-group $resourceGroup `
    --location eastus

# Deploy Container App
az containerapp create `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --environment $containerAppEnv `
    --image "${acrName}.azurecr.io/${imageName}:${tag}" `
    --target-port 8000 `
    --ingress external `
    --registry-server "${acrName}.azurecr.io" `
    --registry-identity system `
    --env-vars `
        ACS_CONNECTION_STRING=secretref:acs-connection-string `
        AZURE_VOICE_LIVE_ENDPOINT=secretref:voice-live-endpoint `
        AZURE_VOICE_LIVE_API_KEY=secretref:voice-live-api-key `
        VOICE_LIVE_MODEL="gpt-realtime-mini" `
        APP_CONFIG_CONNECTION_STRING=secretref:app-config-connection `
        AZURE_STORAGE_CONNECTION_STRING=secretref:storage-connection `
        COMPANY_ID="senior-life" `
        LOG_LEVEL="INFO" `
        ENABLE_SURNAME_VERIFICATION="true" `
        ENABLE_RECORDING="true"

# Set secrets
az containerapp secret set `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --secrets `
        acs-connection-string="YOUR_ACS_CONNECTION_STRING" `
        voice-live-endpoint="https://your-foundry.services.ai.azure.com" `
        voice-live-api-key="YOUR_VOICE_LIVE_API_KEY" `
        app-config-connection="YOUR_APP_CONFIG_CONNECTION" `
        storage-connection="YOUR_STORAGE_CONNECTION"
```

### 3. Configure Event Grid Subscription

After deployment, get the Container App URL:

```powershell
az containerapp show `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --query properties.configuration.ingress.fqdn `
    --output tsv
```

Then create Event Grid subscription in Azure Portal:
- Go to ACS resource → Events → + Event Subscription
- **Event Type:** IncomingCall
- **Endpoint:** `https://your-container-app-url/acs/incomingcall`

---

## 🧪 Testing

### Test Checklist

- [ ] Web client connects and responds
- [ ] ACS phone call connects
- [ ] Voice Live API conversation flows naturally
- [ ] Surname verification triggers when asking for last name
- [ ] ZIP code lookup confirms city/state
- [ ] Business hours logic works (test during/outside hours)
- [ ] Call recording saves to blob storage
- [ ] Transcript saves to blob storage

### Test Scenarios

**Scenario 1: During Business Hours**
1. Call ACS number
2. AI greets and asks for information
3. Provide first name, last name (test surname verification)
4. Provide ZIP code (confirm city/state auto-lookup)
5. Complete information collection
6. AI should offer to transfer to agent

**Scenario 2: Outside Business Hours**
1. Call ACS number
2. AI greets
3. AI should mention closed status
4. AI should offer callback, NOT transfer

**Scenario 3: Surname Verification**
1. When AI asks for last name, say "Smith"
2. AI should confirm spelling: "S-M-I-T-H"
3. Say an uncommon name like "Frankowitz"
4. AI should ask you to spell it

---

## 📁 Project Structure

```
voice-agents-acs/
├── server.py                      # Main Quart application
├── app/
│   ├── handlers/
│   │   ├── acs_event_handler.py   # Incoming call & callbacks
│   │   └── acs_media_handler.py   # Audio streaming & Voice Live
│   ├── services/
│   │   ├── config_manager.py      # Azure App Config & Blob
│   │   ├── surname_service.py     # Surname verification
│   │   ├── zipcode_service.py     # ZIP code lookup
│   │   └── business_hours.py      # Business hours logic
│   └── models/
│       └── call_session.py        # Session state tracking
├── data/
│   ├── surnames.db               # Downloaded from blob on startup
│   └── us-zipcodes.csv           # Embedded in container
├── static/
│   └── index.html                # Web test client
├── surname_verifier.py           # Phonetic matching logic
├── voice_agent_integration.py    # Surname integration wrapper
├── requirements.txt
├── Dockerfile
├── .env.template
└── README.md
```

---

## 🔧 Configuration

### Azure App Configuration Keys

Reuses existing configuration structure:

- `senior-life/basic-info` - Company name, greeting, industry
- `senior-life/voice-config` - Voice name, temperature, style
- `senior-life/business-hours` - Timezone, days, open/close times
- `senior-life/contact-info` - Phone, email for agent reference
- `senior-life/audio-settings` - VAD threshold, silence duration
- `senior-life/business-rules` - Transfer policies, callback rules

### Azure Blob Storage Containers

- `agent-instructions` - Detailed system prompts per company
- `agent-data` - surnames.db (7MB database)
- `call-recordings` - Audio WAV files
- `call-transcripts` - JSON transcripts

---

## 💰 Cost Savings

**Before (SignalWire + Realtime API):**
- ~$310 per 1000 minutes

**After (ACS + Voice Live API):**
- ~$169 per 1000 minutes

**Savings: 45% reduction (~$141/1000 min)**

---

## 🆘 Troubleshooting

### Issue: surnames.db not downloading

**Check:**
1. Blob storage connection string is correct
2. `agent-data` container exists
3. `surnames.db` file is uploaded to blob

**Fix:**
```bash
# Upload surnames.db manually
az storage blob upload \
    --account-name voiceagentsinstructions \
    --container-name agent-data \
    --name surnames.db \
    --file path/to/surnames.db \
    --connection-string "YOUR_CONNECTION_STRING"
```

### Issue: Event Grid webhook validation fails

**Cause:** Application not accessible when creating subscription

**Fix:**
1. Ensure application is running and accessible
2. Check firewall/network security group rules
3. Test webhook URL manually: `curl https://your-url/health`

### Issue: Voice Live API connection fails

**Check:**
1. Endpoint ends with `.services.ai.azure.com`
2. Model deployment name is correct (`gpt-realtime-mini`)
3. API key is valid
4. Region supports Voice Live API (try Sweden Central)

---

## 📚 Related Documentation

- [Migration Architecture](../ACS_MIGRATION_ARCHITECTURE.md)
- [Azure Setup Guide](../AZURE_SETUP_GUIDE.md)
- [Azure Communication Services Docs](https://learn.microsoft.com/azure/communication-services/)
- [Voice Live API Docs](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live)

---

## 🎯 Next Steps

1. ✅ Complete Azure resources setup
2. ✅ Test locally with web client
3. ✅ Test locally with phone (DevTunnel)
4. ⏭️ Deploy to Azure Container Apps
5. ⏭️ Configure Event Grid subscription
6. ⏭️ Production testing with real calls
7. ⏭️ Monitor and optimize

---

## 📞 Support

For issues or questions:
- Check [Troubleshooting](#-troubleshooting) section above
- Review [Azure Setup Guide](../AZURE_SETUP_GUIDE.md)
- Consult Azure Communication Services documentation
