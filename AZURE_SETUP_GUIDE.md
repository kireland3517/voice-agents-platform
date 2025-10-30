# Azure Resources Setup Guide
## Voice Live API with SignalWire

**Date:** October 30, 2025
**Status:** Current Production Setup
**Prerequisites:** Azure subscription with appropriate permissions

---

## 📋 Overview

This guide will help you create and configure the following Azure resources for the voice agents platform:

### Required Azure Resources:

1. **Azure AI Services** (Voice Live API endpoint)
2. **Azure App Configuration** (company-specific settings)
3. **Azure Blob Storage** (instructions, recordings, transcripts)
4. **Azure Container Apps** (application hosting)

### External Service (Not Azure):

- **SignalWire** - Phone number and telephony (+1 208-361-7864)

---

## 🤖 Step 1: Azure AI Services (Voice Live API)

### Check If You Already Have It

**Look for a resource with endpoint ending in:** `.services.ai.azure.com`

### Option A: Check via Portal

1. **Go to:** https://portal.azure.com
2. **Click "All resources"**
3. **Search for:** "AI Foundry" or "Azure AI services"
4. **Look for resources with type:** "Azure AI services"
5. **Click on the resource**
6. **Go to "Keys and Endpoint"**
7. **Check if endpoint ends with:** `.services.ai.azure.com`

### Option B: Check via PowerShell

```powershell
# List all Cognitive Services accounts
Get-AzCognitiveServicesAccount |
    Select-Object Name, ResourceGroupName, Endpoint, Kind |
    Where-Object { $_.Endpoint -like "*.services.ai.azure.com" }
```

### If You DON'T Have It - Create New

#### Portal Steps:

1. **Navigate to:** https://portal.azure.com
2. **Click "Create a resource"**
3. **Search for:** "Azure AI services"
4. **Click "Create"**
5. **Fill in details:**
   - **Subscription:** Your subscription
   - **Resource Group:** `voice-agents`
   - **Region:** **Sweden Central** (strongly recommended for AI Foundry availability)
   - **Name:** `voice-agents-ai-foundry`
   - **Pricing Tier:** Standard S0
6. **Click "Review + Create"**
7. **Click "Create"**
8. **After deployment:**
   - Go to resource
   - Click "Keys and Endpoint"
   - **Copy Endpoint** (should end with `.services.ai.azure.com`)
   - **Copy Key 1**
   - Save to `.env`:
     - `AZURE_VOICE_LIVE_ENDPOINT`
     - `AZURE_VOICE_LIVE_API_KEY`

#### PowerShell:

```powershell
# Variables
$resourceGroup = "voice-agents"
$location = "swedencentral"  # Recommended for AI Foundry
$aiName = "voice-agents-ai-foundry"

# Create Azure AI services resource
New-AzCognitiveServicesAccount `
    -ResourceGroupName $resourceGroup `
    -Name $aiName `
    -Location $location `
    -SkuName "S0" `
    -Kind "AIServices"

# Get keys and endpoint
$keys = Get-AzCognitiveServicesAccountKey `
    -ResourceGroupName $resourceGroup `
    -Name $aiName

$account = Get-AzCognitiveServicesAccount `
    -ResourceGroupName $resourceGroup `
    -Name $aiName

Write-Host "✅ Azure AI Foundry Created"
Write-Host ""
Write-Host "Endpoint: $($account.Endpoint)"
Write-Host "API Key: $($keys.Key1)"
Write-Host ""
Write-Host "⚠️ SAVE THESE - Add to .env:"
Write-Host "  AZURE_VOICE_LIVE_ENDPOINT=$($account.Endpoint)"
Write-Host "  AZURE_VOICE_LIVE_API_KEY=$($keys.Key1)"
```

### Deploy gpt-realtime-mini Model

#### Via Azure AI Foundry Portal:

1. **Navigate to:** https://ai.azure.com
2. **Sign in with your Azure account**
3. **Click "Deployments"** (left menu)
4. **Click "+ Deploy model"**
5. **Search for:** "gpt-realtime-mini"
6. **Select and click "Deploy"**
7. **Configure:**
   - **Deployment name:** `gpt-realtime-mini`
   - **Version:** Latest
   - **Deployment type:** Standard
8. **Click "Deploy"**
9. **Save deployment name:** `gpt-realtime-mini` (for `.env` as `VOICE_LIVE_MODEL`)

---

## ✅ Verification Checklist

After completing all steps, verify you have:

### Environment Variables Ready

```bash
# Azure AI Services - Voice Live API
AZURE_AI_ENDPOINT="https://your-resource.services.ai.azure.com"
AZURE_AI_KEY="your-api-key-here"
AZURE_AI_MODEL="gpt-realtime-mini"

# Azure Storage & Configuration
APP_CONFIG_CONNECTION_STRING="Endpoint=https://...;Id=...;Secret=..."
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
BLOB_CONTAINER_NAME="agent-instructions"
RECORDINGS_CONTAINER_NAME="call-recordings"
TRANSCRIPTS_CONTAINER_NAME="call-transcripts"

# Application Settings
SAVE_RECORDINGS="true"
SAVE_TRANSCRIPTS="true"
LOG_LEVEL="INFO"
```

### Resources Created

- ✅ Azure AI Services: `voice-agents-ai-foundry` (endpoint: `.services.ai.azure.com`)
- ✅ Model Deployment: `gpt-realtime-mini`
- ✅ Azure App Configuration
- ✅ Azure Blob Storage (with containers: agent-instructions, call-recordings, call-transcripts)
- ✅ Azure Container Apps
- ✅ SignalWire Account with phone number: `+1-208-361-7864`

### Configuration in Azure App Config

For each company (e.g., `senior-life`), create these sections:

```
{company-id}/basic-info - {"company-name": "...", "greeting": "...", "industry": "..."}
{company-id}/voice-config - {"voice-style": "..."}
{company-id}/audio-settings - {"vad-threshold": 0.3, "vad-silence-duration-ms": 800, ...}
{company-id}/business-hours - {"timezone": "US/Eastern", "days": [0,1,2,3,4], "open-time": "08:30", "close-time": "17:00"}
{company-id}/contact-info - {"customer-service-phone": "...", "customer-service-email": "..."}
{company-id}/business-rules - {"callback-timeframe": "...", "transfer-hours": "..."}
```

---

## 📝 Next Steps

1. ✅ Complete this setup guide
2. ➡️ Configure SignalWire cXML bin with WebSocket URL
3. ➡️ Deploy application to Azure Container Apps
4. ➡️ Upload company instructions to Blob Storage (`{company-id}-instructions.txt`)
5. ➡️ Test with phone calls

---

## 🆘 Troubleshooting

### Issue: Azure AI Foundry not available in region

**Solution:** Use **Sweden Central** - it has the best AI Foundry/AI Services availability for Voice Live API.

### Issue: Voice Live API not enabled

**Solution:** Voice Live API may require preview access or specific regions. Check:
- https://learn.microsoft.com/azure/ai-services/speech-service/voice-live
- Ensure you're deploying the `gpt-realtime-mini` model
- Use Sweden Central region for best availability

### Issue: Cannot find gpt-realtime-mini model

**Solution:**
1. Go to Azure AI Foundry portal: https://ai.azure.com
2. Navigate to Model Catalog
3. Search for "gpt-realtime-mini"
4. If not available, check if you need to request access or use a different region

### Issue: SignalWire WebSocket connection fails

**Solution:**
1. Verify Container App is deployed and running
2. Check that ingress is enabled and set to "External"
3. Verify WebSocket URL in SignalWire cXML bin matches Container App FQDN
4. Check Container App logs for connection errors

---

## 💡 Cost Optimization Tips

1. **Use toll-free numbers (833, 844, etc.)** - Often cheaper than local numbers
2. **Choose region wisely** - Pricing varies by region
3. **Monitor usage** - Set up Azure budgets and alerts
4. **Use Managed Identity** - Instead of API keys (no additional cost, better security)

---

## 📞 Support

If you encounter issues:
- Azure Communication Services: https://learn.microsoft.com/azure/communication-services/
- Azure AI Foundry: https://learn.microsoft.com/azure/ai-studio/
- Voice Live API: https://learn.microsoft.com/azure/ai-services/speech-service/voice-live

