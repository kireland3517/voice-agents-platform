# Azure Resources Setup Guide
## ACS + Voice Live API Migration

**Date:** October 26, 2025
**Prerequisites:** Azure subscription with appropriate permissions

---

## 📋 Overview

This guide will help you create the following Azure resources:

1. ✅ **Azure Communication Services** (telephony)
2. ✅ **ACS Phone Number** (PSTN)
3. ✅ **Event Grid Subscription** (incoming call webhook)
4. ✅ **Azure AI Foundry** (Voice Live API) - *Check if exists*

**Existing Resources (Keep):**
- Azure App Configuration
- Azure Blob Storage
- Azure Container Apps (will redeploy new app)

---

## 🔧 Step 1: Azure Communication Services

### Option A: PowerShell

```powershell
# Variables
$resourceGroup = "voice-agents"  # Use your existing resource group
$location = "eastus"  # Choose region where ACS is available
$acsName = "voice-agents-acs"  # Must be globally unique

# Login to Azure
Connect-AzAccount

# Set subscription (if you have multiple)
Set-AzContext -SubscriptionId "your-subscription-id"

# Create Azure Communication Services resource
New-AzCommunicationService `
    -ResourceGroupName $resourceGroup `
    -Name $acsName `
    -DataLocation "UnitedStates" `
    -Location $location

# Get connection string
$connectionString = Get-AzCommunicationServiceKey `
    -ResourceGroupName $resourceGroup `
    -Name $acsName `
    | Select-Object -ExpandProperty PrimaryConnectionString

Write-Host "✅ ACS Connection String:"
Write-Host $connectionString
Write-Host ""
Write-Host "⚠️ SAVE THIS - Add to .env as ACS_CONNECTION_STRING"
```

### Option B: Azure Portal

1. **Navigate to Azure Portal:** https://portal.azure.com
2. **Click "Create a resource"**
3. **Search for:** "Communication Services"
4. **Click "Create"**
5. **Fill in details:**
   - **Subscription:** Your subscription
   - **Resource Group:** `voice-agents` (existing)
   - **Resource Name:** `voice-agents-acs` (must be unique)
   - **Data Location:** United States
   - **Region:** East US (or region where ACS is available)
6. **Click "Review + Create"**
7. **Click "Create"**
8. **After deployment:**
   - Go to the resource
   - Click "Keys" in left menu
   - **Copy "Primary connection string"**
   - Save to `.env` as `ACS_CONNECTION_STRING`

### Option C: Azure CLI

```bash
# Variables
RESOURCE_GROUP="voice-agents"
LOCATION="eastus"
ACS_NAME="voice-agents-acs"

# Login
az login

# Create ACS resource
az communication create \
  --name $ACS_NAME \
  --resource-group $RESOURCE_GROUP \
  --data-location "UnitedStates" \
  --location $LOCATION

# Get connection string
az communication list-key \
  --name $ACS_NAME \
  --resource-group $RESOURCE_GROUP \
  --query primaryConnectionString \
  --output tsv

echo "✅ Save this connection string to .env"
```

**Expected Output:**
```
endpoint=https://voice-agents-acs.communication.azure.com/;accesskey=your-key-here
```

---

## 📞 Step 2: Get ACS Phone Number

### Option A: PowerShell

```powershell
# Prerequisites: Install module
Install-Module -Name Az.Communication -Force -AllowClobber

# Variables
$resourceGroup = "voice-agents"
$acsName = "voice-agents-acs"
$areaCode = "833"  # Toll-free, or use your preferred area code

# Search for available phone numbers
$searchResult = Find-AzCommunicationPhoneNumber `
    -CommunicationServiceName $acsName `
    -ResourceGroupName $resourceGroup `
    -PhoneNumberType "TollFree" `
    -AssignmentType "Application" `
    -PhoneNumberCapability "Inbound","Outbound" `
    -AreaCode $areaCode `
    -Quantity 1

Write-Host "Available phone numbers:"
$searchResult.PhoneNumbers

# Purchase the phone number
$phoneNumber = $searchResult.PhoneNumbers[0]
$purchase = New-AzCommunicationPhoneNumber `
    -CommunicationServiceName $acsName `
    -ResourceGroupName $resourceGroup `
    -PhoneNumber $phoneNumber

Write-Host "✅ Phone Number Acquired: $phoneNumber"
Write-Host "⚠️ SAVE THIS - Add to .env as ACS_PHONE_NUMBER"
```

### Option B: Azure Portal

1. **Go to your Communication Services resource:** `voice-agents-acs`
2. **In left menu, click "Phone numbers"**
3. **Click "+ Get" button**
4. **Configure:**
   - **Country/Region:** United States
   - **Number type:** Toll-free
   - **Calling:** Make calls ✓
   - **SMS:** (optional)
   - **Area code:** Enter preferred area code (e.g., 833)
5. **Click "Search"**
6. **Select a number from results**
7. **Click "Next"**
8. **Review and click "Place order"**
9. **Wait for provisioning (1-2 minutes)**
10. **Copy the phone number**
11. **Save to `.env` as `ACS_PHONE_NUMBER`**

### Option C: Azure CLI

```bash
# Variables
RESOURCE_GROUP="voice-agents"
ACS_NAME="voice-agents-acs"
AREA_CODE="833"

# Search for available numbers
az communication phonenumber list-available \
  --connection-string $ACS_CONNECTION_STRING \
  --phone-number-type "tollFree" \
  --assignment-type "application" \
  --capabilities "calling" \
  --area-code $AREA_CODE \
  --quantity 1

# Purchase (replace with actual number from search)
az communication phonenumber buy \
  --connection-string $ACS_CONNECTION_STRING \
  --phone-number "+18335551234"

echo "✅ Phone number acquired"
```

**Expected Output:**
```
+18335551234
```

---

## 📡 Step 3: Event Grid Subscription

**Important:** This step should be done AFTER deploying your application, as you need the webhook URL.

For now, we'll document the steps. You'll execute this after deployment.

### Portal Steps (Do Later)

1. **Go to your Communication Services resource:** `voice-agents-acs`
2. **In left menu, click "Events"**
3. **Click "+ Event Subscription"**
4. **Fill in details:**
   - **Name:** `incoming-call-webhook`
   - **Event Schema:** Event Grid Schema
   - **Event Types:** Filter to specific events
     - ✓ Check **IncomingCall**
   - **Endpoint Type:** Web Hook
   - **Endpoint:** `https://your-container-app-url/acs/incomingcall`
     - Replace with your actual Container App URL after deployment
5. **Click "Create"**

### PowerShell Command (Do Later)

```powershell
# EXECUTE AFTER APPLICATION DEPLOYMENT
$resourceGroup = "voice-agents"
$acsName = "voice-agents-acs"
$webhookUrl = "https://your-container-app-url/acs/incomingcall"  # Update after deployment

# Get ACS resource ID
$acsResourceId = (Get-AzCommunicationService `
    -ResourceGroupName $resourceGroup `
    -Name $acsName).Id

# Create Event Grid subscription
New-AzEventGridSubscription `
    -ResourceId $acsResourceId `
    -EventSubscriptionName "incoming-call-webhook" `
    -Endpoint $webhookUrl `
    -EndpointType "webhook" `
    -IncludedEventType "Microsoft.Communication.IncomingCall"

Write-Host "✅ Event Grid subscription created"
```

---

## 🤖 Step 4: Azure AI Foundry (Voice Live API)

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
# Azure Communication Services
ACS_CONNECTION_STRING="endpoint=https://voice-agents-acs.communication.azure.com/;accesskey=..."
ACS_PHONE_NUMBER="+18335551234"

# Azure AI Foundry - Voice Live API
AZURE_VOICE_LIVE_ENDPOINT="https://voice-agents-ai-foundry.services.ai.azure.com"
AZURE_VOICE_LIVE_API_KEY="your-api-key-here"
VOICE_LIVE_MODEL="gpt-realtime-mini"

# Existing Resources (already have)
APP_CONFIG_CONNECTION_STRING="..."
AZURE_STORAGE_CONNECTION_STRING="..."
BLOB_CONTAINER_NAME="agent-instructions"
DATA_CONTAINER_NAME="agent-data"
RECORDINGS_CONTAINER_NAME="call-recordings"
TRANSCRIPTS_CONTAINER_NAME="call-transcripts"

# Application Settings
COMPANY_ID="senior-life"
LOG_LEVEL="INFO"
```

### Resources Created

- ✅ Azure Communication Services: `voice-agents-acs`
- ✅ Phone Number: `+1833XXXXXXX`
- ✅ Event Grid Subscription: (will create after deployment)
- ✅ Azure AI Foundry: `voice-agents-ai-foundry`
- ✅ Model Deployment: `gpt-realtime-mini`

---

## 📝 Next Steps

1. ✅ Complete this setup guide
2. ➡️ Build the Python application (see next guide)
3. ➡️ Deploy to Azure Container Apps
4. ➡️ Create Event Grid subscription (Step 3, after deployment)
5. ➡️ Test with phone calls

---

## 🆘 Troubleshooting

### Issue: Phone number search returns no results

**Solution:** Try different area codes or regions. Some area codes may be unavailable.

```powershell
# Try multiple area codes
@("833", "844", "855", "866", "877", "888") | ForEach-Object {
    Write-Host "Searching area code: $_"
    Find-AzCommunicationPhoneNumber `
        -CommunicationServiceName $acsName `
        -ResourceGroupName $resourceGroup `
        -PhoneNumberType "TollFree" `
        -AssignmentType "Application" `
        -PhoneNumberCapability "Inbound","Outbound" `
        -AreaCode $_ `
        -Quantity 1
}
```

### Issue: Azure AI Foundry not available in region

**Solution:** Use **Sweden Central** - it has the best AI Foundry availability.

### Issue: Voice Live API not enabled

**Solution:** Voice Live API may require preview access. Check:
- https://learn.microsoft.com/azure/ai-services/speech-service/voice-live
- Request preview access if needed

### Issue: Event Grid webhook validation fails

**Solution:** Ensure your application is deployed and accessible before creating the Event Grid subscription. The webhook must respond to validation events.

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

