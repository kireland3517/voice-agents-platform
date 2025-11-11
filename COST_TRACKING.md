# Cost Tracking and Monitoring

This document explains how to track, monitor, and analyze costs for your voice agent platform.

## Overview

The voice agent platform includes comprehensive cost tracking for all major components:

- **Azure OpenAI Realtime API** - Audio and text token usage
- **SignalWire Telephony** - Inbound call minutes
- **Azure Container Apps** - Compute resources
- **Azure Blob Storage** - Call recordings, transcripts, and cost data

## Current Pricing (as of Nov 2024)

### Azure OpenAI Realtime API (gpt-realtime-mini)

| Component | Price per Million Tokens |
|-----------|-------------------------|
| Input Audio | $0.06 |
| Output Audio | $0.24 |
| Input Text | $0.60 |
| Output Text | $2.40 |

### SignalWire Telephony

| Service | Price |
|---------|-------|
| Inbound Calls | $0.0085/minute |

### Azure Infrastructure

| Component | Estimated Price |
|-----------|----------------|
| Container Apps | ~$0.0002/minute |
| Blob Storage | ~$0.0001/call |

### **Estimated Total: $0.015 - $0.017 per minute**

## Architecture

### Automatic Cost Tracking

Costs are automatically tracked for every call:

1. **Call Start**: Cost tracking begins when a call is initiated
2. **During Call**: Token usage is tracked in real-time
3. **Call End**: Final costs are calculated and saved to blob storage

### Cost Data Storage

Cost breakdowns are saved as JSON files in Azure Blob Storage:

```
Container: call-costs
Path: {company_id}/{call_sid}-costs.json
```

Example cost file structure:

```json
{
  "cost_breakdown": {
    "call_sid": "CA1234567890abcdef",
    "company_id": "senior-life",
    "start_time": "2024-11-10T15:30:00Z",
    "end_time": "2024-11-10T15:35:00Z",
    "duration_seconds": 300.0,
    "input_audio_tokens": 50000,
    "output_audio_tokens": 60000,
    "input_text_tokens": 1000,
    "output_text_tokens": 2000,
    "openai_input_audio_cost": 0.003,
    "openai_output_audio_cost": 0.0144,
    "openai_input_text_cost": 0.0006,
    "openai_output_text_cost": 0.0048,
    "signalwire_cost": 0.0425,
    "container_apps_cost": 0.001,
    "storage_cost": 0.0001,
    "total_openai_cost": 0.0228,
    "total_telephony_cost": 0.0425,
    "total_infrastructure_cost": 0.0011,
    "total_cost": 0.0664,
    "cost_per_minute": 0.01328
  },
  "pricing_version": "2024-11",
  "currency": "USD"
}
```

## API Endpoints

### Get Daily Cost Summary

```bash
GET /costs/daily?date=2024-11-10
```

**Response:**

```json
{
  "date": "2024-11-10",
  "total_calls": 45,
  "total_duration_minutes": 225.5,
  "total_cost": 3.42,
  "avg_cost_per_call": 0.076,
  "avg_duration_minutes": 5.01,
  "breakdown": {
    "openai": 1.85,
    "telephony": 1.45,
    "infrastructure": 0.12
  }
}
```

### Get Individual Call Costs

```bash
GET /costs/call/{call_sid}
```

**Response:**

```json
{
  "call_sid": "CA1234567890abcdef",
  "company_id": "senior-life",
  "duration_seconds": 300.0,
  "total_cost": 0.0664,
  "cost_per_minute": 0.01328,
  "openai_input_audio_cost": 0.003,
  "openai_output_audio_cost": 0.0144,
  "signalwire_cost": 0.0425,
  ...
}
```

### Get Current Pricing Configuration

```bash
GET /costs/pricing
```

**Response:**

```json
{
  "currency": "USD",
  "pricing_version": "2024-11",
  "components": {
    "openai_realtime_api": {
      "input_audio_per_million_tokens": 0.06,
      "output_audio_per_million_tokens": 0.24,
      "input_text_per_million_tokens": 0.60,
      "output_text_per_million_tokens": 2.40
    },
    "signalwire": {
      "inbound_per_minute": 0.0085
    },
    "azure_infrastructure": {
      "container_apps_per_minute": 0.0002,
      "storage_per_call": 0.0001
    }
  },
  "estimated_cost_per_minute": {
    "min": 0.015,
    "max": 0.017,
    "description": "Estimated total cost per minute of conversation"
  }
}
```

## Using the Cost Tracking API

### Example: Get Today's Costs

```python
import requests
from datetime import datetime

# Get today's date
today = datetime.now().strftime("%Y-%m-%d")

# Query the API
response = requests.get(f"https://your-app.azurecontainerapps.io/costs/daily?date={today}")
data = response.json()

print(f"Total calls today: {data['total_calls']}")
print(f"Total cost: ${data['total_cost']:.2f}")
print(f"Average cost per call: ${data['avg_cost_per_call']:.2f}")
```

### Example: Monitor Costs in Real-Time

```python
import requests
import time

def monitor_costs():
    """Monitor costs and alert if they exceed threshold"""
    threshold = 10.0  # $10 per day

    while True:
        response = requests.get("https://your-app.azurecontainerapps.io/costs/daily")
        data = response.json()

        if data['total_cost'] > threshold:
            print(f"⚠️  Cost alert! Daily cost ${data['total_cost']:.2f} exceeds ${threshold:.2f}")
            # Send alert via email, Slack, etc.

        time.sleep(3600)  # Check every hour

monitor_costs()
```

### Example: Analyze Cost Trends

```python
import requests
from datetime import datetime, timedelta

def analyze_weekly_costs():
    """Get cost trends for the past week"""
    costs = []

    for i in range(7):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        response = requests.get(f"https://your-app.azurecontainerapps.io/costs/daily?date={date}")
        data = response.json()
        costs.append({
            "date": date,
            "total_cost": data['total_cost'],
            "total_calls": data['total_calls']
        })

    # Calculate trends
    total_week_cost = sum(c['total_cost'] for c in costs)
    total_week_calls = sum(c['total_calls'] for c in costs)
    avg_daily_cost = total_week_cost / 7

    print(f"Weekly cost: ${total_week_cost:.2f}")
    print(f"Weekly calls: {total_week_calls}")
    print(f"Average daily cost: ${avg_daily_cost:.2f}")

    return costs

analyze_weekly_costs()
```

## Setting Up Cost Alerts

### Using the Setup Script

The `setup_cost_alerts.py` script helps you create Azure Monitor alerts:

```bash
python setup_cost_alerts.py \
  --subscription-id "your-subscription-id" \
  --resource-group "voice-agents-rg" \
  --email "alerts@example.com" \
  --daily-threshold 50 \
  --spike-threshold 10
```

This will:
1. Create an Azure Action Group for notifications
2. Provide instructions for setting up cost budget alerts
3. Guide you through creating custom metric alerts

### Manual Alert Setup

#### 1. Create Action Group

```bash
az monitor action-group create \
  --name voice-agents-cost-alerts \
  --resource-group voice-agents-rg \
  --short-name CostAlert \
  --action email CostAlerts alerts@example.com
```

#### 2. Create Budget Alert (Azure Portal)

1. Go to **Cost Management + Billing** in Azure Portal
2. Select your subscription
3. Click **Budgets** → **+ Add**
4. Configure:
   - Name: `voice-agents-daily-budget`
   - Amount: `$50` (monthly)
   - Alert conditions: 80%, 90%, 100%
   - Action group: `voice-agents-cost-alerts`

#### 3. Create Custom Metric Alert (Optional)

For application-level alerts based on your cost tracker data:

1. Export cost metrics to Application Insights
2. Create custom metric alert
3. Set threshold and action group

## Customizing Pricing

To update pricing constants (e.g., if SignalWire rates change):

Edit [cost_tracker.py](cost_tracker.py:67-79):

```python
class CostTracker:
    # Update these values as pricing changes
    PRICE_INPUT_AUDIO_PER_MILLION = 0.06
    PRICE_OUTPUT_AUDIO_PER_MILLION = 0.24
    PRICE_INPUT_TEXT_PER_MILLION = 0.60
    PRICE_OUTPUT_TEXT_PER_MILLION = 2.40
    PRICE_SIGNALWIRE_PER_MINUTE = 0.0085
    PRICE_CONTAINER_APPS_PER_MINUTE = 0.0002
    PRICE_STORAGE_PER_CALL = 0.0001
```

## Cost Optimization Tips

### 1. Optimize Token Usage

- Use `max-response-tokens: 200` for shorter, faster responses
- Enable semantic VAD to reduce false turn endings
- Keep prompts concise to minimize input tokens

### 2. Monitor High-Cost Calls

```bash
# Find calls with costs above $1
curl "https://your-app.azurecontainerapps.io/costs/daily" | \
  jq '.calls[] | select(.total_cost > 1.0)'
```

### 3. Analyze Cost Patterns

- Compare weekday vs. weekend costs
- Identify peak hours
- Monitor average call duration trends

### 4. Set Up Automated Reports

Create a daily cost report script:

```python
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def send_daily_report():
    # Get today's costs
    response = requests.get("https://your-app.azurecontainerapps.io/costs/daily")
    data = response.json()

    # Create email
    subject = f"Voice Agent Daily Cost Report - {datetime.now().strftime('%Y-%m-%d')}"
    body = f"""
    Daily Cost Summary
    ==================
    Total Calls: {data['total_calls']}
    Total Cost: ${data['total_cost']:.2f}
    Average Cost/Call: ${data['avg_cost_per_call']:.2f}

    Breakdown:
    - OpenAI: ${data['breakdown']['openai']:.2f}
    - Telephony: ${data['breakdown']['telephony']:.2f}
    - Infrastructure: ${data['breakdown']['infrastructure']:.2f}
    """

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = 'reports@example.com'
    msg['To'] = 'team@example.com'

    # Send email (configure SMTP settings)
    with smtplib.SMTP('smtp.example.com', 587) as server:
        server.starttls()
        server.login('user', 'password')
        server.send_message(msg)

# Schedule this to run daily
send_daily_report()
```

## Troubleshooting

### Costs Not Appearing

1. **Check logs for cost tracking errors**:
   ```bash
   az containerapp logs show \
     --name voice-agents-bridge \
     --resource-group voice-agents-rg \
     | grep "cost"
   ```

2. **Verify blob storage container exists**:
   ```bash
   az storage container list \
     --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
     | grep "call-costs"
   ```

3. **Check if cost tracker is initialized**:
   Look for `💰 Started cost tracking` in logs

### Inaccurate Cost Calculations

1. **Verify pricing constants** are up to date in [cost_tracker.py](cost_tracker.py:67-79)
2. **Check token counting** - ensure tokens are being tracked correctly
3. **Validate duration calculation** - confirm call start/end times are accurate

### Missing Cost Data

If cost data is missing for some calls:

1. Check if calls ended abruptly (disconnections)
2. Verify blob storage permissions
3. Look for exceptions in `finalize_call_costs()` or `save_call_costs()`

## Future Enhancements

Potential improvements to the cost tracking system:

1. **Real-time cost dashboard** - Web UI for visualizing costs
2. **Cost predictions** - ML-based forecasting of monthly costs
3. **Per-company cost allocation** - Track costs by company_id
4. **Integration with Azure Cost Management API** - Unified cost view
5. **Automated cost optimization recommendations** - Identify savings opportunities

## Support

For questions or issues with cost tracking:

1. Check the logs for error messages
2. Review this documentation
3. Verify API endpoints are accessible
4. Contact support with call_sid for specific cost inquiries

---

**Last Updated**: November 2024
**Pricing Version**: 2024-11
