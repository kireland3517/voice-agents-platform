# ============================================================================
# GitHub Secrets Setup Script (PowerShell)
# ============================================================================
# This script helps configure GitHub repository secrets for Azure deployment.
#
# Prerequisites:
# - GitHub CLI (gh) installed: https://cli.github.com/
# - Authenticated with GitHub: gh auth login
# - Azure CLI (az) installed: https://docs.microsoft.com/cli/azure/install-azure-cli
# - Authenticated with Azure: az login
# ============================================================================

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# ============================================================================
# Check prerequisites
# ============================================================================

Write-Info "Checking prerequisites..."

if (!(Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-ErrorMsg "GitHub CLI (gh) not found. Install from: https://cli.github.com/"
    exit 1
}

if (!(Get-Command az -ErrorAction SilentlyContinue)) {
    Write-ErrorMsg "Azure CLI (az) not found. Install from: https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
}

Write-Success "Prerequisites check passed"

# ============================================================================
# Authenticate
# ============================================================================

Write-Info "Checking GitHub authentication..."
$ghAuthStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Not authenticated with GitHub. Running: gh auth login"
    gh auth login
} else {
    Write-Success "GitHub authentication verified"
}

Write-Info "Checking Azure authentication..."
try {
    az account show | Out-Null
    Write-Success "Azure authentication verified"
} catch {
    Write-Warning "Not authenticated with Azure. Running: az login"
    az login
}

# ============================================================================
# Get Azure information
# ============================================================================

Write-Host ""
Write-Info "=== Azure Configuration ==="

# Get subscription ID
$SUBSCRIPTION_ID = az account show --query id -o tsv
Write-Info "Subscription ID: $SUBSCRIPTION_ID"

# Get tenant ID
$TENANT_ID = az account show --query tenantId -o tsv
Write-Info "Tenant ID: $TENANT_ID"

# Resource group
$RESOURCE_GROUP = "voice_agents"
Write-Info "Resource Group: $RESOURCE_GROUP"

# Container App name
$CONTAINER_APP_NAME = "voice-agents-bridge"
Write-Info "Container App: $CONTAINER_APP_NAME"

# Container Registry
$REGISTRY_NAME = "voiceagentsenvironmentf2c46d"
$REGISTRY_URL = "$REGISTRY_NAME.azurecr.io"
Write-Info "Container Registry: $REGISTRY_URL"

# ============================================================================
# Check if Service Principal exists
# ============================================================================

Write-Host ""
Write-Info "=== Service Principal Setup ==="

$SP_NAME = "voice-agents-github-deploy"

# Check if SP already exists
$SP_APP_ID = az ad sp list --display-name "$SP_NAME" --query "[0].appId" -o tsv 2>$null

if ([string]::IsNullOrEmpty($SP_APP_ID)) {
    Write-Warning "Service Principal '$SP_NAME' not found. Creating..."

    # Create Service Principal
    $SP_OUTPUT = az ad sp create-for-rbac `
        --name "$SP_NAME" `
        --role contributor `
        --scopes "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP" `
        --sdk-auth | ConvertFrom-Json

    $SP_APP_ID = $SP_OUTPUT.clientId
    Write-Success "Service Principal created: $SP_APP_ID"

    # Get GitHub repository info
    $REPO_OWNER = gh repo view --json owner -q .owner.login
    $REPO_NAME = gh repo view --json name -q .name

    Write-Info "Configuring OIDC federation for GitHub Actions..."

    # Create federated credential for main branch
    try {
        az ad app federated-credential create `
            --id "$SP_APP_ID" `
            --parameters "{
                `"name`": `"github-deploy-main`",
                `"issuer`": `"https://token.actions.githubusercontent.com`",
                `"subject`": `"repo:$REPO_OWNER/$REPO_NAME:ref:refs/heads/main`",
                `"description`": `"GitHub Actions deployment for main branch`",
                `"audiences`": [`"api://AzureADTokenExchange`"]
            }" | Out-Null
    } catch {
        Write-Warning "Federated credential for main branch may already exist"
    }

    # Create federated credential for develop branch
    try {
        az ad app federated-credential create `
            --id "$SP_APP_ID" `
            --parameters "{
                `"name`": `"github-deploy-develop`",
                `"issuer`": `"https://token.actions.githubusercontent.com`",
                `"subject`": `"repo:$REPO_OWNER/$REPO_NAME:ref:refs/heads/develop`",
                `"description`": `"GitHub Actions deployment for develop branch`",
                `"audiences`": [`"api://AzureADTokenExchange`"]
            }" | Out-Null
    } catch {
        Write-Warning "Federated credential for develop branch may already exist"
    }

    # Create federated credential for claude-edits branch
    try {
        az ad app federated-credential create `
            --id "$SP_APP_ID" `
            --parameters "{
                `"name`": `"github-deploy-claude-edits`",
                `"issuer`": `"https://token.actions.githubusercontent.com`",
                `"subject`": `"repo:$REPO_OWNER/$REPO_NAME:ref:refs/heads/claude-edits`",
                `"description`": `"GitHub Actions deployment for claude-edits branch`",
                `"audiences`": [`"api://AzureADTokenExchange`"]
            }" | Out-Null
    } catch {
        Write-Warning "Federated credential for claude-edits branch may already exist"
    }

    Write-Success "OIDC federation configured"
} else {
    Write-Success "Service Principal '$SP_NAME' already exists: $SP_APP_ID"
}

# ============================================================================
# Get Container Registry credentials
# ============================================================================

Write-Host ""
Write-Info "=== Container Registry Credentials ==="

# Enable admin access on ACR if not already enabled
az acr update --name "$REGISTRY_NAME" --admin-enabled true | Out-Null

# Get registry credentials
$REGISTRY_USERNAME = az acr credential show --name "$REGISTRY_NAME" --query username -o tsv
$REGISTRY_PASSWORD = az acr credential show --name "$REGISTRY_NAME" --query "passwords[0].value" -o tsv

Write-Success "Container Registry credentials retrieved"

# ============================================================================
# Get Storage Account names
# ============================================================================

Write-Host ""
Write-Info "=== Storage Accounts ==="

# List storage accounts in resource group
$STORAGE_ACCOUNTS = az storage account list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv

if ([string]::IsNullOrEmpty($STORAGE_ACCOUNTS)) {
    Write-Warning "No storage accounts found in resource group"
    $STAGING_STORAGE = ""
    $PRODUCTION_STORAGE = ""
} else {
    # Try to identify staging vs production
    $storageArray = $STORAGE_ACCOUNTS -split "`n"
    $STAGING_STORAGE = ($storageArray | Where-Object { $_ -match "staging" } | Select-Object -First 1)
    $PRODUCTION_STORAGE = ($storageArray | Where-Object { $_ -notmatch "staging" } | Select-Object -First 1)

    if ([string]::IsNullOrEmpty($STAGING_STORAGE)) {
        Write-Warning "No staging storage account found. Using first available."
        $STAGING_STORAGE = $storageArray[0]
    }

    if ([string]::IsNullOrEmpty($PRODUCTION_STORAGE)) {
        Write-Warning "No production storage account found. Using first available."
        $PRODUCTION_STORAGE = $storageArray[0]
    }

    Write-Info "Staging Storage: $STAGING_STORAGE"
    Write-Info "Production Storage: $PRODUCTION_STORAGE"
}

# ============================================================================
# Set GitHub secrets
# ============================================================================

Write-Host ""
Write-Info "=== Setting GitHub Repository Secrets ==="

# Set repository secrets
gh secret set VOICEAGENTSBRIDGE_AZURE_CLIENT_ID --body "$SP_APP_ID"
Write-Success "Set VOICEAGENTSBRIDGE_AZURE_CLIENT_ID"

gh secret set VOICEAGENTSBRIDGE_AZURE_TENANT_ID --body "$TENANT_ID"
Write-Success "Set VOICEAGENTSBRIDGE_AZURE_TENANT_ID"

gh secret set VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID"
Write-Success "Set VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID"

gh secret set VOICEAGENTSBRIDGE_REGISTRY_USERNAME --body "$REGISTRY_USERNAME"
Write-Success "Set VOICEAGENTSBRIDGE_REGISTRY_USERNAME"

gh secret set VOICEAGENTSBRIDGE_REGISTRY_PASSWORD --body "$REGISTRY_PASSWORD"
Write-Success "Set VOICEAGENTSBRIDGE_REGISTRY_PASSWORD"

# ============================================================================
# Set GitHub environment secrets
# ============================================================================

Write-Host ""
Write-Info "=== Setting GitHub Environment Secrets ==="

# Check if environments exist
try {
    gh api repos/:owner/:repo/environments/staging | Out-Null
    if (![string]::IsNullOrEmpty($STAGING_STORAGE)) {
        gh secret set STAGING_STORAGE_ACCOUNT --env staging --body "$STAGING_STORAGE"
        Write-Success "Set STAGING_STORAGE_ACCOUNT for staging environment"
    } else {
        Write-Warning "Skipping STAGING_STORAGE_ACCOUNT (no storage account found)"
    }
} catch {
    Write-Warning "Staging environment not found in GitHub. Create it in Settings - Environments."
    Write-Info "After creating, run: gh secret set STAGING_STORAGE_ACCOUNT --env staging --body `"$STAGING_STORAGE`""
}

try {
    gh api repos/:owner/:repo/environments/production | Out-Null
    if (![string]::IsNullOrEmpty($PRODUCTION_STORAGE)) {
        gh secret set PRODUCTION_STORAGE_ACCOUNT --env production --body "$PRODUCTION_STORAGE"
        Write-Success "Set PRODUCTION_STORAGE_ACCOUNT for production environment"
    } else {
        Write-Warning "Skipping PRODUCTION_STORAGE_ACCOUNT (no storage account found)"
    }
} catch {
    Write-Warning "Production environment not found in GitHub. Create it in Settings - Environments."
    Write-Info "After creating, run: gh secret set PRODUCTION_STORAGE_ACCOUNT --env production --body `"$PRODUCTION_STORAGE`""
}

# ============================================================================
# Summary
# ============================================================================

Write-Host ""
Write-Host "============================================================"
Write-Success "GitHub Secrets Setup Complete!"
Write-Host "============================================================"
Write-Host ""
Write-Info "Repository Secrets Set:"
Write-Host "  [OK] VOICEAGENTSBRIDGE_AZURE_CLIENT_ID"
Write-Host "  [OK] VOICEAGENTSBRIDGE_AZURE_TENANT_ID"
Write-Host "  [OK] VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID"
Write-Host "  [OK] VOICEAGENTSBRIDGE_REGISTRY_USERNAME"
Write-Host "  [OK] VOICEAGENTSBRIDGE_REGISTRY_PASSWORD"
Write-Host ""
Write-Info "Next Steps:"
Write-Host "  1. Create GitHub environments (if not done):"
Write-Host "     - Go to Settings - Environments"
Write-Host "     - Create 'staging' environment (no protection)"
Write-Host "     - Create 'production' environment (add required reviewers)"
Write-Host ""
Write-Host "  2. Set environment secrets (if not set automatically):"
Write-Host "     gh secret set STAGING_STORAGE_ACCOUNT --env staging --body `"$STAGING_STORAGE`""
Write-Host "     gh secret set PRODUCTION_STORAGE_ACCOUNT --env production --body `"$PRODUCTION_STORAGE`""
Write-Host ""
Write-Host "  3. Test deployment:"
Write-Host "     - Push to 'claude-edits' branch - deploys to staging"
Write-Host "     - Push to 'main' branch - deploys to production (requires approval)"
Write-Host ""
Write-Host "  4. View workflow runs:"
Write-Host "     gh run list --workflow=deploy-to-azure.yml"
Write-Host ""
Write-Success "Setup complete! Ready to deploy."
