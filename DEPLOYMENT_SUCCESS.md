# Deployment Success - Next Steps

## Status: Successfully Deployed! ✓

Your quality monitoring branch has been deployed to Azure Container Apps.

**Active Revision:** `voice-agents-bridge--0000166`
**Deployed:** 2025-11-03 05:10:30 UTC
**Traffic:** 100% to new revision
**Status:** Running and healthy

---

## What's Now Active

### Automatic Deployment
- Every push to `feature/acs-quality-monitoring` branch auto-deploys
- GitHub Actions workflow: https://github.com/kireland3517/voice-agents-platform/actions
- Deployment time: ~3-5 minutes

### Quality Monitoring Features
Quality monitoring will activate automatically on the next call:

| Feature | Status | Details |
|---------|--------|---------|
| **Jitter Detection** | ✓ Active | Warns if >30ms (robotic/metallic audio) |
| **Packet Loss** | ✓ Active | Warns if >10% (dropouts, gurgling) |
| **RTT/Latency** | ✓ Active | Warns if >500ms (overlapping speech) |
| **SNR Analysis** | ✓ Active | Warns if <20 dB (excessive noise) |
| **Clipping Detection** | ✓ Active | Alerts if >5% (audio distortion) |
| **Dynamic Range** | ✓ Active | Detects AGC issues (PA system sound) |
| **Response Timing** | ✓ Active | Flags robotic (<100ms) or awkward (>1500ms) gaps |
| **MOS Scoring** | ⚠ Disabled | Requires gcc build tools (optional) |

---

## Next Steps

### 1. Test Quality Monitoring (5 minutes)

**Make a test call** to your voice agent number.

After the call ends, check the logs:

```powershell
# View quality monitoring logs
az containerapp logs show `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --tail 100 | Select-String "Quality monitoring|AUDIO QUALITY|NETWORK DIAGNOSTICS|JITTER|SNR"
```

**Expected output:**
```
Quality monitoring enabled for call call-abc123
AudioQualityMonitor initialized for session call-abc123
NetworkDiagnostics initialized for session call-abc123

...after call ends...

AUDIO QUALITY SUMMARY - Session call-abc123
   Avg SNR: 28.5 dB
   Clipping Events: 0

NETWORK DIAGNOSTICS SUMMARY - Session call-abc123
   Network Quality: GOOD
   Avg Jitter: 15.2ms
   Avg Packet Loss: 1.2%

TURN-TIMING QUALITY:
   Avg Response Gap: 380ms
   Natural Gaps (200-500ms): 12/15
```

### 2. Monitor Real-Time Quality (During Calls)

Watch for quality warnings during active calls:

```powershell
# Follow logs in real-time
az containerapp logs show `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --follow
```

Look for warnings like:
- `HIGH JITTER: 45.2ms avg - EXPECT ROBOTIC/METALLIC AUDIO`
- `LOW SNR: ai audio SNR=18.3 dB (threshold: 20.0 dB)`
- `INSTANT RESPONSE: 85ms gap (sounds robotic - should be 200-500ms)`
- `CLIPPING: ai audio peak=0.983 (distortion risk)`

### 3. Set Up Azure Log Analytics (Optional - 10 minutes)

For historical analysis and alerting:

```powershell
# Run the automated setup script
.\azure-log-analytics-setup.ps1 `
  -ResourceGroup "voice_agents" `
  -WorkspaceName "voice-quality-logs" `
  -ContainerAppName "voice-agents-bridge"
```

This enables:
- Historical quality trend analysis
- Automated alerts for quality issues
- Custom Kusto queries for diagnostics
- Quality dashboards

### 4. Merge to Main Branch (When Ready)

Once you've verified everything works:

```bash
# Switch to main branch
git checkout main

# Merge the quality monitoring feature
git merge feature/acs-quality-monitoring

# Push to main
git push origin main
```

**Note:** You'll need to update the GitHub Actions workflow to deploy from `main` instead of the feature branch.

---

## Configuration

All quality monitoring settings are in [config.py](config.py) lines 227-269.

### Current Settings

```python
# Feature flags
'enable-audio-quality-monitoring': True
'enable-network-diagnostics': True
'enable-mos-scoring': False  # Disabled (no PESQ library)
'enable-structured-diagnostics-logging': True

# Quality thresholds (Azure recommended)
'quality-jitter-warning-ms': 30.0
'quality-packet-loss-warning': 0.10  # 10%
'quality-rtt-warning-ms': 500.0
'quality-snr-warning-db': 20.0
'quality-clipping-threshold': 0.95
'quality-min-response-gap-ms': 200.0
'quality-max-response-gap-ms': 500.0

# Analysis intervals
'quality-analysis-interval-seconds': 10
'network-analysis-interval-seconds': 5
```

### Per-Company Overrides

Configure in Azure App Configuration for specific companies:

```json
{
  "enable-audio-quality-monitoring": true,
  "quality-jitter-warning-ms": 25.0,
  "quality-packet-loss-warning": 0.05
}
```

---

## Troubleshooting

### No quality monitoring logs after a call?

**Check files deployed:**
```powershell
az containerapp exec `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --command "ls -la *.py | grep quality"
```

You should see:
- `audio_quality_monitor.py`
- `network_diagnostics.py`
- `call_diagnostics_logger.py`
- `quality_monitoring.py`
- `mos_scorer.py`

**Check for import errors:**
```powershell
az containerapp logs show `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --tail 200 | Select-String "Error|ImportError|quality"
```

### Want to enable MOS scoring?

MOS scoring requires PESQ library with gcc build tools. Two options:

**Option 1: Use fuller Docker image** (adds ~200MB)
In `.github/workflows/deploy-quality-monitoring.yml`, the Dockerfile would need to change from `python:3.12-slim` to `python:3.12` and install build tools.

**Option 2: Use pre-built PESQ binary** (advanced)
Build PESQ on a Linux machine and copy the `.so` file into the container.

For now, all other quality monitoring works without MOS scoring.

### Deployment taking too long?

Normal deployment time: 3-5 minutes

If it takes >10 minutes:
- Check GitHub Actions logs for stuck steps
- Verify Azure Container Registry is accessible
- Check Azure resource quotas

---

## Quick Reference Commands

```powershell
# Check active revision
az containerapp revision list `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --query "[?properties.active].{Name:name, Traffic:properties.trafficWeight}" `
  -o table

# View recent logs
az containerapp logs show `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --tail 50

# Trigger manual deployment
# Go to: https://github.com/kireland3517/voice-agents-platform/actions
# Click "Deploy Quality Monitoring Branch to Azure" → "Run workflow"

# Or push empty commit:
git commit --allow-empty -m "test: Trigger deployment"
git push origin feature/acs-quality-monitoring

# Rollback to previous revision (if needed)
az containerapp revision activate `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --revision voice-agents-bridge--0000165
```

---

## Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - 30-second verification guide
- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Detailed setup instructions
- **[QUALITY_MONITORING.md](QUALITY_MONITORING.md)** - Complete technical documentation
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Implementation details
- **[AZURE_DEPLOYMENT_SETUP.md](AZURE_DEPLOYMENT_SETUP.md)** - Deployment troubleshooting

---

## What We Accomplished

1. ✓ Implemented comprehensive audio quality monitoring
2. ✓ Added network diagnostics (jitter, packet loss, RTT)
3. ✓ Created turn-timing analysis for conversational flow
4. ✓ Built structured logging for Azure Log Analytics
5. ✓ Set up automatic GitHub Actions deployment
6. ✓ Resolved all dependency conflicts
7. ✓ Successfully deployed to Azure Container Apps
8. ✓ Quality monitoring ready to use on next call

**Your voice agent platform now has enterprise-grade quality monitoring!**

---

## Summary

**Status:** ✓ Deployed and Ready

**To verify it's working:**
1. Make a test call
2. Check logs for quality metrics
3. Look for warnings if quality issues detected

**Future deployments:**
- Just push to `feature/acs-quality-monitoring` branch
- GitHub Actions handles everything automatically
- Takes 3-5 minutes

**Questions?** Check the documentation files listed above.
