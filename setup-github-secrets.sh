#!/bin/bash

# ============================================================================
# GitHub Secrets Setup Script
# ============================================================================
# This script helps configure GitHub repository secrets for Azure deployment.
#
# Prerequisites:
# - GitHub CLI (gh) installed: https://cli.github.com/
# - Authenticated with GitHub: gh auth login
# - Azure CLI (az) installed: https://docs.microsoft.com/cli/azure/install-azure-cli
# - Authenticated with Azure: az login
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}❌${NC} $1"
}

# ============================================================================
# Check prerequisites
# ============================================================================

log_info "Checking prerequisites..."

if ! command -v gh &> /dev/null; then
    log_error "GitHub CLI (gh) not found. Install from: https://cli.github.com/"
    exit 1
fi

if ! command -v az &> /dev/null; then
    log_error "Azure CLI (az) not found. Install from: https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

log_success "Prerequisites check passed"

# ============================================================================
# Authenticate
# ============================================================================

log_info "Checking GitHub authentication..."
if ! gh auth status &> /dev/null; then
    log_warning "Not authenticated with GitHub. Running: gh auth login"
    gh auth login
else
    log_success "GitHub authentication verified"
fi

log_info "Checking Azure authentication..."
if ! az account show &> /dev/null; then
    log_warning "Not authenticated with Azure. Running: az login"
    az login
else
    log_success "Azure authentication verified"
fi

# ============================================================================
# Get Azure information
# ============================================================================

echo ""
log_info "=== Azure Configuration ==="

# Get subscription ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
log_info "Subscription ID: $SUBSCRIPTION_ID"

# Get tenant ID
TENANT_ID=$(az account show --query tenantId -o tsv)
log_info "Tenant ID: $TENANT_ID"

# Resource group
RESOURCE_GROUP="voice_agents"
log_info "Resource Group: $RESOURCE_GROUP"

# Container App name
CONTAINER_APP_NAME="voice-agents-bridge"
log_info "Container App: $CONTAINER_APP_NAME"

# Container Registry
REGISTRY_NAME="voiceagentsenvironmentf2c46d"
REGISTRY_URL="${REGISTRY_NAME}.azurecr.io"
log_info "Container Registry: $REGISTRY_URL"

# ============================================================================
# Check if Service Principal exists
# ============================================================================

echo ""
log_info "=== Service Principal Setup ==="

SP_NAME="voice-agents-github-deploy"

# Check if SP already exists
SP_APP_ID=$(az ad sp list --display-name "$SP_NAME" --query "[0].appId" -o tsv 2>/dev/null || echo "")

if [ -z "$SP_APP_ID" ]; then
    log_warning "Service Principal '$SP_NAME' not found. Creating..."

    # Create Service Principal with OIDC federation
    SP_OUTPUT=$(az ad sp create-for-rbac \
        --name "$SP_NAME" \
        --role contributor \
        --scopes "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP" \
        --sdk-auth)

    SP_APP_ID=$(echo $SP_OUTPUT | jq -r '.clientId')
    log_success "Service Principal created: $SP_APP_ID"

    # Get Object ID for federated credential
    SP_OBJECT_ID=$(az ad sp show --id "$SP_APP_ID" --query id -o tsv)

    # Get GitHub repository info
    REPO_OWNER=$(gh repo view --json owner -q .owner.login)
    REPO_NAME=$(gh repo view --json name -q .name)

    log_info "Configuring OIDC federation for GitHub Actions..."

    # Create federated credential for main branch
    az ad app federated-credential create \
        --id "$SP_APP_ID" \
        --parameters '{
            "name": "github-deploy-main",
            "issuer": "https://token.actions.githubusercontent.com",
            "subject": "repo:'"$REPO_OWNER/$REPO_NAME"':ref:refs/heads/main",
            "description": "GitHub Actions deployment for main branch",
            "audiences": ["api://AzureADTokenExchange"]
        }' || log_warning "Federated credential for main branch may already exist"

    # Create federated credential for develop branch
    az ad app federated-credential create \
        --id "$SP_APP_ID" \
        --parameters '{
            "name": "github-deploy-develop",
            "issuer": "https://token.actions.githubusercontent.com",
            "subject": "repo:'"$REPO_OWNER/$REPO_NAME"':ref:refs/heads/develop",
            "description": "GitHub Actions deployment for develop branch",
            "audiences": ["api://AzureADTokenExchange"]
        }' || log_warning "Federated credential for develop branch may already exist"

    # Create federated credential for claude-edits branch
    az ad app federated-credential create \
        --id "$SP_APP_ID" \
        --parameters '{
            "name": "github-deploy-claude-edits",
            "issuer": "https://token.actions.githubusercontent.com",
            "subject": "repo:'"$REPO_OWNER/$REPO_NAME"':ref:refs/heads/claude-edits",
            "description": "GitHub Actions deployment for claude-edits branch",
            "audiences": ["api://AzureADTokenExchange"]
        }' || log_warning "Federated credential for claude-edits branch may already exist"

    log_success "OIDC federation configured"
else
    log_success "Service Principal '$SP_NAME' already exists: $SP_APP_ID"
fi

# ============================================================================
# Get Container Registry credentials
# ============================================================================

echo ""
log_info "=== Container Registry Credentials ==="

# Enable admin access on ACR if not already enabled
az acr update --name "$REGISTRY_NAME" --admin-enabled true > /dev/null

# Get registry credentials
REGISTRY_USERNAME=$(az acr credential show --name "$REGISTRY_NAME" --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name "$REGISTRY_NAME" --query "passwords[0].value" -o tsv)

log_success "Container Registry credentials retrieved"

# ============================================================================
# Get Storage Account names
# ============================================================================

echo ""
log_info "=== Storage Accounts ==="

# List storage accounts in resource group
STORAGE_ACCOUNTS=$(az storage account list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv)

if [ -z "$STORAGE_ACCOUNTS" ]; then
    log_warning "No storage accounts found in resource group"
    STAGING_STORAGE=""
    PRODUCTION_STORAGE=""
else
    # Try to identify staging vs production
    STAGING_STORAGE=$(echo "$STORAGE_ACCOUNTS" | grep -i "staging" | head -n 1 || echo "")
    PRODUCTION_STORAGE=$(echo "$STORAGE_ACCOUNTS" | grep -v -i "staging" | head -n 1 || echo "")

    if [ -z "$STAGING_STORAGE" ]; then
        log_warning "No staging storage account found. Using first available."
        STAGING_STORAGE=$(echo "$STORAGE_ACCOUNTS" | head -n 1)
    fi

    if [ -z "$PRODUCTION_STORAGE" ]; then
        log_warning "No production storage account found. Using first available."
        PRODUCTION_STORAGE=$(echo "$STORAGE_ACCOUNTS" | head -n 1)
    fi

    log_info "Staging Storage: $STAGING_STORAGE"
    log_info "Production Storage: $PRODUCTION_STORAGE"
fi

# ============================================================================
# Set GitHub secrets
# ============================================================================

echo ""
log_info "=== Setting GitHub Repository Secrets ==="

# Set repository secrets
gh secret set VOICEAGENTSBRIDGE_AZURE_CLIENT_ID --body "$SP_APP_ID"
log_success "Set VOICEAGENTSBRIDGE_AZURE_CLIENT_ID"

gh secret set VOICEAGENTSBRIDGE_AZURE_TENANT_ID --body "$TENANT_ID"
log_success "Set VOICEAGENTSBRIDGE_AZURE_TENANT_ID"

gh secret set VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID"
log_success "Set VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID"

gh secret set VOICEAGENTSBRIDGE_REGISTRY_USERNAME --body "$REGISTRY_USERNAME"
log_success "Set VOICEAGENTSBRIDGE_REGISTRY_USERNAME"

gh secret set VOICEAGENTSBRIDGE_REGISTRY_PASSWORD --body "$REGISTRY_PASSWORD"
log_success "Set VOICEAGENTSBRIDGE_REGISTRY_PASSWORD"

# ============================================================================
# Set GitHub environment secrets
# ============================================================================

echo ""
log_info "=== Setting GitHub Environment Secrets ==="

# Check if environments exist
if gh api repos/:owner/:repo/environments/staging &> /dev/null; then
    if [ -n "$STAGING_STORAGE" ]; then
        gh secret set STAGING_STORAGE_ACCOUNT --env staging --body "$STAGING_STORAGE"
        log_success "Set STAGING_STORAGE_ACCOUNT for staging environment"
    else
        log_warning "Skipping STAGING_STORAGE_ACCOUNT (no storage account found)"
    fi
else
    log_warning "Staging environment not found in GitHub. Create it in Settings > Environments."
    log_info "After creating, run: gh secret set STAGING_STORAGE_ACCOUNT --env staging --body \"$STAGING_STORAGE\""
fi

if gh api repos/:owner/:repo/environments/production &> /dev/null; then
    if [ -n "$PRODUCTION_STORAGE" ]; then
        gh secret set PRODUCTION_STORAGE_ACCOUNT --env production --body "$PRODUCTION_STORAGE"
        log_success "Set PRODUCTION_STORAGE_ACCOUNT for production environment"
    else
        log_warning "Skipping PRODUCTION_STORAGE_ACCOUNT (no storage account found)"
    fi
else
    log_warning "Production environment not found in GitHub. Create it in Settings > Environments."
    log_info "After creating, run: gh secret set PRODUCTION_STORAGE_ACCOUNT --env production --body \"$PRODUCTION_STORAGE\""
fi

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "============================================================"
log_success "GitHub Secrets Setup Complete!"
echo "============================================================"
echo ""
log_info "Repository Secrets Set:"
echo "  ✅ VOICEAGENTSBRIDGE_AZURE_CLIENT_ID"
echo "  ✅ VOICEAGENTSBRIDGE_AZURE_TENANT_ID"
echo "  ✅ VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID"
echo "  ✅ VOICEAGENTSBRIDGE_REGISTRY_USERNAME"
echo "  ✅ VOICEAGENTSBRIDGE_REGISTRY_PASSWORD"
echo ""
log_info "Next Steps:"
echo "  1. Create GitHub environments (if not done):"
echo "     - Go to Settings > Environments"
echo "     - Create 'staging' environment (no protection)"
echo "     - Create 'production' environment (add required reviewers)"
echo ""
echo "  2. Set environment secrets (if not set automatically):"
echo "     gh secret set STAGING_STORAGE_ACCOUNT --env staging --body \"$STAGING_STORAGE\""
echo "     gh secret set PRODUCTION_STORAGE_ACCOUNT --env production --body \"$PRODUCTION_STORAGE\""
echo ""
echo "  3. Test deployment:"
echo "     - Push to 'claude-edits' branch → deploys to staging"
echo "     - Push to 'main' branch → deploys to production (requires approval)"
echo ""
echo "  4. View workflow runs:"
echo "     gh run list --workflow=deploy-to-azure.yml"
echo ""
log_success "You're ready to deploy! 🚀"
