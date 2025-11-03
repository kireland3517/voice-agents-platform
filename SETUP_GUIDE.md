# Quality Monitoring Setup Guide

## Quick Start (Without MOS Scoring)

Quality monitoring is **already enabled** and working! You don't need to do anything else.

### Verify It's Working

1. **Make a test call** to your voice agent
2. **Check logs** for quality monitoring output:

```bash
# Search for quality monitoring initialization
grep "Quality monitoring enabled" app.log

# Look for end-of-call summaries
grep "AUDIO QUALITY SUMMARY" app.log
grep "NETWORK DIAGNOSTICS SUMMARY" app.log

# Check for any quality warnings
grep -E "HIGH JITTER|LOW SNR|INSTANT RESPONSE" app.log
```

**Expected output:**
```
✅ Quality monitoring enabled for call call-abc123
📊 AUDIO QUALITY SUMMARY - Session call-abc123
   MOS Score: 3.8/5.0 (GOOD)
   Avg SNR: 28.5 dB
   Clipping Events: 0
```

That's it! You're already monitoring:
- ✅ Audio quality (SNR, clipping, dynamic range)
- ✅ Network diagnostics (jitter, packet loss, RTT)
- ✅ Turn-timing analysis (response gaps)

---

## Optional: Enable MOS Scoring (Advanced)

MOS (Mean Opinion Score) provides PESQ-based objective quality scoring (1.0-5.0).

### Windows Setup (Requires C++ Build Tools)

**Option 1: Install Build Tools (Recommended)**

1. Download [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. Install "Desktop development with C++"
3. Install PESQ:
   ```bash
   pip install pesq scipy
   ```

**Option 2: Use Pre-built Wheels (If Available)**

```bash
pip install --only-binary :all: pesq scipy
```

**Option 3: Skip MOS Scoring**

MOS scoring is **optional**. All other quality monitoring works without it:
- ✅ SNR, clipping, dynamic range analysis (works)
- ✅ Network diagnostics (works)
- ✅ Turn-timing analysis (works)
- ✅ Structured logging (works)
- ❌ PESQ MOS scoring (requires PESQ library)

The system already estimates MOS from other metrics (simplified heuristic).

### Linux/Docker Setup (Easy)

```bash
# PESQ installs easily on Linux
pip install pesq scipy
```

### Enable MOS Scoring in Config

Once PESQ is installed:

**In Azure App Configuration:** `{company-id}/audio-settings`

```json
{
  "enable-mos-scoring": true
}
```

Or set globally in [config.py:260](config.py#L260):
```python
if not audio_settings.get('enable-mos-scoring'):
    audio_settings['enable-mos-scoring'] = True  # Change to True
```

### Verify MOS Scoring

```bash
python -c "from pesq import pesq; print('✅ PESQ installed successfully')"
```

---

## Azure Log Analytics Setup

### Step 1: Create Log Analytics Workspace

1. **Azure Portal** → "Log Analytics workspaces" → "Create"
2. **Basics:**
   - Subscription: [Your subscription]
   - Resource group: [Your resource group]
   - Name: `voice-agent-quality-logs`
   - Region: [Same as your app]
3. Click **Review + Create** → **Create**

### Step 2: Configure Your App to Send Logs

**Option A: Azure Container Apps (Recommended)**

If running on Azure Container Apps:

1. **Portal** → Your Container App → "Monitoring" → "Log Analytics"
2. **Enable** Log Analytics
3. **Select workspace:** `voice-agent-quality-logs`
4. **Save**

Logs are now automatically ingested!

**Option B: Application Insights Integration**

1. **Create Application Insights resource** (if not exists)
2. **Link to Log Analytics workspace:**
   ```bash
   az monitor app-insights component create \
     --app voice-agent-quality \
     --location eastus \
     --resource-group your-rg \
     --workspace voice-agent-quality-logs
   ```
3. **Add instrumentation key** to your app's environment variables:
   ```bash
   APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=your-key"
   ```

**Option C: Manual Ingestion (Custom Table)**

For structured JSON diagnostics, create a custom table:

1. **Portal** → Log Analytics workspace → "Tables" → "Create" → "New custom log (DCR-based)"
2. **Table name:** `CallDiagnostics_CL`
3. **Sample data:** Use this JSON schema:

```json
{
  "event_type": "call_end",
  "timestamp": "2025-01-15T14:32:18.234Z",
  "call_id": "call-abc123",
  "company_id": "senior-life",
  "data": {
    "audio_quality": {
      "estimated_mos": 3.8,
      "avg_snr_db": 28.5
    },
    "network": {
      "jitter_avg_ms": 22.4,
      "packet_loss_rate": 0.023
    }
  }
}
```

4. **Save** and note the ingestion endpoint

### Step 3: Query Your Quality Data

**Azure Portal** → Your workspace → "Logs"

#### Query 1: Find High Jitter Calls

```kusto
// Paste this into Log Analytics query editor
traces
| where message contains "HIGH JITTER"
| project timestamp, message, customDimensions
| order by timestamp desc
```

#### Query 2: Quality Summaries (Last 24 Hours)

```kusto
traces
| where message contains "AUDIO QUALITY SUMMARY"
   or message contains "NETWORK DIAGNOSTICS SUMMARY"
| where timestamp > ago(24h)
| project timestamp, message
| order by timestamp desc
```

#### Query 3: Calls with Quality Issues

```kusto
traces
| where message contains "⚠️" or message contains "🌊" or message contains "⚡"
| where timestamp > ago(24h)
| summarize IssueCount = count() by bin(timestamp, 1h)
| render timechart
```

### Step 4: Create Alerts

**Portal** → Workspace → "Alerts" → "New alert rule"

**Example: Alert on High Jitter**

1. **Condition:** Custom log search
2. **Query:**
   ```kusto
   traces
   | where message contains "HIGH JITTER"
   | where timestamp > ago(5m)
   ```
3. **Threshold:** Greater than 0 results
4. **Evaluation frequency:** 5 minutes
5. **Action group:** Email/SMS/webhook
6. **Alert name:** "Voice Quality: High Jitter Detected"
7. **Create**

---

## Configuration Reference

All settings in [config.py](config.py) (lines 227-269):

```python
# Enable/disable components
'enable-audio-quality-monitoring': True         # Audio quality analysis
'enable-network-diagnostics': True              # Jitter/packet loss/RTT
'enable-mos-scoring': False                     # PESQ MOS (requires library)
'enable-structured-diagnostics-logging': True   # JSON events

# Thresholds (Azure guide recommended)
'quality-jitter-warning-ms': 30.0               # > 30ms = robotic audio
'quality-packet-loss-warning': 0.10             # > 10% = severe
'quality-rtt-warning-ms': 500.0                 # > 500ms = turn issues
'quality-min-snr-db': 20.0                      # < 20 dB = noisy
'quality-min-mos': 3.0                          # < 3.0 = poor quality

# Turn-timing (Guide: 200-500ms = natural)
'quality-min-response-gap-ms': 200.0            # < 200ms = too fast
'quality-max-response-gap-ms': 500.0            # > 500ms = slow

# Analysis intervals
'quality-analysis-interval-seconds': 10         # Audio analysis every 10s
'network-analysis-interval-seconds': 5          # Network analysis every 5s
```

### Per-Company Configuration

Override defaults in **Azure App Configuration:**

**Key:** `{company-id}/audio-settings`

```json
{
  "enable-audio-quality-monitoring": true,
  "enable-network-diagnostics": true,
  "enable-mos-scoring": false,
  "quality-jitter-warning-ms": 25.0,
  "quality-min-snr-db": 25.0
}
```

---

## Testing & Validation

### Test 1: Verify Monitoring is Active

```bash
# Make a test call, then check:
grep "Quality monitoring enabled" app.log

# Expected:
✅ Quality monitoring enabled for call call-abc123
🎵 AudioQualityMonitor initialized for session call-abc123
🌐 NetworkDiagnostics initialized for session call-abc123
```

### Test 2: Trigger Quality Warnings

Simulate poor network conditions to test alerts:

```bash
# Look for warnings during calls with network issues
tail -f app.log | grep -E "⚠️|🌊|⚡|📉"
```

**Example warnings:**
```
🌊 HIGH JITTER: 45.2ms avg - EXPECT ROBOTIC/METALLIC AUDIO
⚡ INSTANT RESPONSE: 85ms gap (sounds robotic)
📉 LOW SNR: ai audio SNR=18.3 dB
```

### Test 3: Review End-of-Call Summary

After any call completes:

```bash
grep -A 15 "AUDIO QUALITY SUMMARY" app.log | tail -20
```

**Expected output:**
```
📊 AUDIO QUALITY SUMMARY - Session call-abc123
   MOS Score: 3.8/5.0 (GOOD)
   Avg SNR: 28.5 dB
   Avg Dynamic Range: 8.2 dB
   Clipping Events: 0
✅ No significant quality issues detected

🌐 NETWORK DIAGNOSTICS SUMMARY - Session call-abc123
   Network Quality: FAIR
   Avg Jitter: 22.4ms (threshold: 30.0ms)
   Avg Packet Loss: 2.3% (threshold: 10.0%)
✅ No significant network issues detected

📈 TURN-TIMING QUALITY (Guide: 200-500ms = natural):
   Avg Response Gap: 380ms
   Natural Gaps (200-500ms): 12/15
```

---

## Troubleshooting

### Issue: "Quality monitoring not showing in logs"

**Check:**
```bash
# Verify quality_monitoring.py exists
ls -l quality_monitoring.py

# Check imports aren't failing
grep "Error.*quality_monitoring" app.log
```

**Fix:** Ensure all new files are deployed:
```bash
git pull
# Restart your app
```

### Issue: "PESQ import errors"

**Check:**
```bash
python -c "from pesq import pesq"
```

**Fix:** Either install C++ build tools (Windows) or disable MOS scoring:
```python
'enable-mos-scoring': False  # in config
```

### Issue: "No structured logs in Log Analytics"

**Check:**
1. App is configured to send logs to workspace
2. `enable-structured-diagnostics-logging: true` in config
3. Wait 5-10 minutes for ingestion

**Query to test:**
```kusto
traces
| where timestamp > ago(1h)
| take 100
```

### Issue: "Too many logs / high cost"

**Reduce verbosity:**
```python
# In config.py, increase intervals
'quality-analysis-interval-seconds': 30  # Was 10
'network-analysis-interval-seconds': 15  # Was 5
```

Or disable for non-critical companies:
```json
{
  "enable-audio-quality-monitoring": false
}
```

---

## Quick Commands Reference

```bash
# Check monitoring is active
grep "Quality monitoring enabled" app.log

# View quality summaries
grep "QUALITY SUMMARY" app.log

# Find quality issues
grep -E "HIGH JITTER|LOW SNR|INSTANT RESPONSE" app.log

# Real-time monitoring
tail -f app.log | grep -E "⚠️|🌊|⚡|📊|🌐"

# Test PESQ (if installed)
python -c "from pesq import pesq; print('✅ PESQ OK')"

# View configuration
grep -A 5 "QUALITY MONITORING SETTINGS" config.py
```

---

## What's Monitored (Out of the Box)

Without any additional setup, you're already tracking:

| Metric | Threshold | Impact |
|--------|-----------|--------|
| **Jitter** | > 30ms | Robotic/metallic audio |
| **Packet Loss** | > 10% | Dropouts, gurgling |
| **RTT** | > 500ms | Overlapping speech |
| **SNR** | < 20 dB | Excessive noise |
| **Clipping** | > 5% | Audio distortion |
| **Dynamic Range** | < 3 dB | "PA system" sound (AGC issue) |
| **Response Gap** | < 100ms or > 1500ms | Robotic or awkward timing |

All metrics logged automatically at:
- Real-time warnings during calls
- Comprehensive summaries at call end
- Periodic snapshots every 5-10 seconds

---

## Next Steps

1. ✅ **You're done!** Monitoring is active
2. Make a test call and check logs
3. (Optional) Enable MOS scoring if you install PESQ
4. (Optional) Set up Log Analytics for historical analysis
5. Review [QUALITY_MONITORING.md](QUALITY_MONITORING.md) for troubleshooting

**Questions?** Check the main [QUALITY_MONITORING.md](QUALITY_MONITORING.md) documentation.
