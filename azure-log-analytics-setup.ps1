# Azure Log Analytics Setup Script for Voice Agent Quality Monitoring (PowerShell)
# Run this to automatically create and configure Log Analytics workspace

param(
    [string]$ResourceGroup = "voice-agents-rg",
    [string]$Location = "eastus",
    [string]$WorkspaceName = "voice-agent-quality-logs",
    [string]$ContainerAppName = "voice-agent-app"
)

Write-Host "🔧 Azure Log Analytics Setup for Voice Agent Quality Monitoring" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "📋 Configuration:" -ForegroundColor Yellow
Write-Host "  Resource Group: $ResourceGroup"
Write-Host "  Location: $Location"
Write-Host "  Workspace Name: $WorkspaceName"
Write-Host "  Container App: $ContainerAppName"
Write-Host ""

$continue = Read-Host "Continue with these settings? (y/n)"
if ($continue -ne "y") {
    Write-Host "Cancelled. Run with custom parameters:" -ForegroundColor Red
    Write-Host '  .\azure-log-analytics-setup.ps1 -ResourceGroup "your-rg" -WorkspaceName "your-workspace"'
    exit 1
}

Write-Host ""
Write-Host "Step 1: Creating Log Analytics Workspace..." -ForegroundColor Green
Write-Host "============================================"

try {
    az monitor log-analytics workspace create `
      --resource-group $ResourceGroup `
      --workspace-name $WorkspaceName `
      --location $Location `
      --retention-time 30

    $workspaceId = az monitor log-analytics workspace show `
      --resource-group $ResourceGroup `
      --workspace-name $WorkspaceName `
      --query customerId -o tsv

    Write-Host "✅ Workspace created! ID: $workspaceId" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Workspace might already exist or error occurred" -ForegroundColor Yellow
    Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "Step 2: Linking Container App to Log Analytics..." -ForegroundColor Green
Write-Host "=================================================="

try {
    az containerapp logs configure `
      --name $ContainerAppName `
      --resource-group $ResourceGroup `
      --enable-log-analytics true `
      --log-analytics-workspace $WorkspaceName

    Write-Host "✅ Container App linked to Log Analytics" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Link might already exist or Container App not found" -ForegroundColor Yellow
    Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "Step 3: Creating Sample Kusto Queries File..." -ForegroundColor Green
Write-Host "=============================================="

$queriesContent = @"
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


// Query 6: End-of-Call Quality Scores
// ====================================
ContainerAppConsoleLogs_CL
| where Log_s contains "MOS Score:"
| where TimeGenerated > ago(24h)
| project TimeGenerated, Log_s
| order by TimeGenerated desc
"@

$queriesContent | Out-File -FilePath "queries.kql" -Encoding UTF8

Write-Host "✅ Sample queries saved to queries.kql" -ForegroundColor Green

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "✅ Setup Complete!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 Log Analytics Workspace:" -ForegroundColor Yellow
Write-Host "  Name: $WorkspaceName"
Write-Host "  Resource Group: $ResourceGroup"
Write-Host ""
Write-Host "📝 Sample Queries:" -ForegroundColor Yellow
Write-Host "  Saved to: queries.kql"
Write-Host "  Import these in Azure Portal → Workspace → Logs"
Write-Host ""
Write-Host "🔔 Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Wait 5-10 minutes for logs to appear"
Write-Host "  2. Make a test call to your voice agent"
Write-Host "  3. Run sample queries in Log Analytics"
Write-Host "  4. Create alert action groups in Azure Portal"
Write-Host ""
Write-Host "📖 Documentation:" -ForegroundColor Yellow
Write-Host "  SETUP_GUIDE.md - Complete setup instructions"
Write-Host "  QUALITY_MONITORING.md - Troubleshooting and API reference"
Write-Host ""
Write-Host "🌐 Open Azure Portal:" -ForegroundColor Yellow
$subscriptionId = (az account show --query id -o tsv)
$portalUrl = "https://portal.azure.com/#@/resource/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.OperationalInsights/workspaces/$WorkspaceName"
Write-Host "  $portalUrl"
Write-Host ""
