#!/bin/bash
# Azure Log Analytics Setup Script for Voice Agent Quality Monitoring
# Run this to automatically create and configure Log Analytics workspace

set -e

echo "🔧 Azure Log Analytics Setup for Voice Agent Quality Monitoring"
echo "================================================================"
echo ""

# Configuration variables (customize these)
RESOURCE_GROUP="${RESOURCE_GROUP:-voice-agents-rg}"
LOCATION="${LOCATION:-eastus}"
WORKSPACE_NAME="${WORKSPACE_NAME:-voice-agent-quality-logs}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-voice-agent-app}"

echo "📋 Configuration:"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Location: $LOCATION"
echo "  Workspace Name: $WORKSPACE_NAME"
echo "  Container App: $CONTAINER_APP_NAME"
echo ""

read -p "Continue with these settings? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled. Set environment variables to customize:"
    echo "  export RESOURCE_GROUP=your-rg"
    echo "  export LOCATION=eastus"
    echo "  export WORKSPACE_NAME=your-workspace"
    echo "  export CONTAINER_APP_NAME=your-app"
    exit 1
fi

echo ""
echo "Step 1: Creating Log Analytics Workspace..."
echo "============================================"

az monitor log-analytics workspace create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$WORKSPACE_NAME" \
  --location "$LOCATION" \
  --retention-time 30

WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$WORKSPACE_NAME" \
  --query customerId -o tsv)

echo "✅ Workspace created! ID: $WORKSPACE_ID"
echo ""

echo "Step 2: Linking Container App to Log Analytics..."
echo "=================================================="

az containerapp logs configure \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --enable-log-analytics true \
  --log-analytics-workspace "$WORKSPACE_NAME"

echo "✅ Container App linked to Log Analytics"
echo ""

echo "Step 3: Creating Sample Kusto Queries..."
echo "========================================"

# Create a queries.kql file with useful queries
cat > queries.kql <<'EOF'
// ============================================================================
// Voice Agent Quality Monitoring - Kusto Queries
// ============================================================================

// Query 1: Find Calls with High Jitter (Last 24 Hours)
// =====================================================
ContainerAppConsoleLogs_CL
| where Log_s contains "HIGH JITTER"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 2: Quality Summary Dashboard (Last 24 Hours)
// ==================================================
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(24h)
| where Log_s contains "QUALITY SUMMARY" or Log_s contains "DIAGNOSTICS SUMMARY"
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 3: Quality Issues Trending (Last 7 Days)
// ==============================================
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(7d)
| where Log_s contains "⚠️" or Log_s contains "🌊" or Log_s contains "⚡"
| summarize IssueCount = count() by bin(TimeGenerated, 1h)
| render timechart


// Query 4: Instant Response Warnings (Poor Turn-Timing)
// =====================================================
ContainerAppConsoleLogs_CL
| where Log_s contains "INSTANT RESPONSE"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 5: Low SNR Issues (Noisy Audio)
// ======================================
ContainerAppConsoleLogs_CL
| where Log_s contains "LOW SNR"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 6: All Quality Metrics (Last Hour)
// ========================================
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(1h)
| where Log_s contains "Quality monitoring enabled"
   or Log_s contains "QUALITY SUMMARY"
   or Log_s contains "DIAGNOSTICS SUMMARY"
   or Log_s contains "HIGH JITTER"
   or Log_s contains "INSTANT RESPONSE"
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 7: Call Volume and Quality Distribution
// =============================================
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(24h)
| where Log_s contains "Quality monitoring enabled"
| summarize CallCount = count() by bin(TimeGenerated, 1h)
| render timechart


// Query 8: Network Quality Issues (Packet Loss)
// =============================================
ContainerAppConsoleLogs_CL
| where Log_s contains "HIGH PACKET LOSS"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 9: Audio Clipping Detections
// ==================================
ContainerAppConsoleLogs_CL
| where Log_s contains "CLIPPING"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc


// Query 10: End-of-Call Quality Scores
// ====================================
ContainerAppConsoleLogs_CL
| where Log_s contains "MOS Score:"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc
EOF

echo "✅ Sample queries saved to queries.kql"
echo ""

echo "Step 4: Creating Alert Rules..."
echo "================================"

# Alert 1: High Jitter
az monitor scheduled-query create \
  --name "Voice Quality: High Jitter Alert" \
  --resource-group "$RESOURCE_GROUP" \
  --scopes "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.OperationalInsights/workspaces/$WORKSPACE_NAME" \
  --condition "count 'Heartbeat' > 0" \
  --condition-query "ContainerAppConsoleLogs_CL | where Log_s contains 'HIGH JITTER' | where TimeGenerated > ago(5m)" \
  --description "Alert when high jitter (>30ms) is detected in voice calls" \
  --evaluation-frequency 5m \
  --window-size 5m \
  --severity 2 \
  || echo "⚠️  Alert creation requires action group - create manually in portal"

echo ""
echo "================================================================"
echo "✅ Setup Complete!"
echo "================================================================"
echo ""
echo "📊 Log Analytics Workspace:"
echo "  Name: $WORKSPACE_NAME"
echo "  ID: $WORKSPACE_ID"
echo "  Portal: https://portal.azure.com/#@/resource/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.OperationalInsights/workspaces/$WORKSPACE_NAME"
echo ""
echo "📝 Sample Queries:"
echo "  Saved to: queries.kql"
echo "  Import these in Azure Portal → Workspace → Logs"
echo ""
echo "🔔 Next Steps:"
echo "  1. Wait 5-10 minutes for logs to appear"
echo "  2. Test with a call to your voice agent"
echo "  3. Run sample queries in Log Analytics"
echo "  4. Create alert action groups in Azure Portal"
echo ""
echo "📖 Documentation:"
echo "  SETUP_GUIDE.md - Complete setup instructions"
echo "  QUALITY_MONITORING.md - Troubleshooting and API reference"
echo ""
