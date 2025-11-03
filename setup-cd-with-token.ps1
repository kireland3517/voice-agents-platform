# Azure Continuous Deployment Setup with GitHub Token
# Use this if the GitHub authorization popup doesn't appear

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubToken
)

$ErrorActionPreference = "Stop"

Write-Host "Azure Container App - Continuous Deployment Setup (Token Method)" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

# Configuration
$RESOURCE_GROUP = "voice_agents"
$CONTAINER_APP_NAME = "voice-agents-bridge"
$GITHUB_REPO = "kireland3517/voice-agents-platform"
$BRANCH = "feature/acs-quality-monitoring"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Resource Group: $RESOURCE_GROUP"
Write-Host "  Container App: $CONTAINER_APP_NAME"
Write-Host "  GitHub Repo: $GITHUB_REPO"
Write-Host "  Branch: $BRANCH"
Write-Host ""

Write-Host "Step 1: Checking current GitHub connection..." -ForegroundColor Yellow
$existingConnection = az containerapp github-action show `
    --name $CONTAINER_APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --output none 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  GitHub Actions already configured!" -ForegroundColor Green
    Write-Host "  Removing existing connection..." -ForegroundColor Yellow
    az containerapp github-action delete `
        --name $CONTAINER_APP_NAME `
        --resource-group $RESOURCE_GROUP `
        --yes
}

Write-Host ""
Write-Host "Step 2: Setting up GitHub Actions deployment with token..." -ForegroundColor Yellow

az containerapp github-action add `
    --name $CONTAINER_APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --repo-url "https://github.com/$GITHUB_REPO" `
    --branch $BRANCH `
    --token $GitHubToken

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Failed to setup continuous deployment" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible issues:" -ForegroundColor Yellow
    Write-Host "  1. Invalid GitHub token"
    Write-Host "  2. Token missing required scopes (repo, workflow, admin:repo_hook)"
    Write-Host "  3. Repository not found or no access"
    Write-Host ""
    Write-Host "To create a new token:" -ForegroundColor Yellow
    Write-Host "  1. Go to: https://github.com/settings/tokens"
    Write-Host "  2. Generate new token (classic)"
    Write-Host "  3. Select scopes: repo, workflow, admin:repo_hook"
    Write-Host "  4. Copy token and run this script again"
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "Step 3: Verifying configuration..." -ForegroundColor Yellow
az containerapp github-action show `
    --name $CONTAINER_APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --query "{Branch:branch, Repo:repoUrl, Status:status}" `
    -o table

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "SUCCESS: Continuous deployment configured!" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Push changes to $BRANCH" -ForegroundColor White
Write-Host "  2. GitHub Actions will automatically build and deploy" -ForegroundColor White
Write-Host "  3. Check deployment status:" -ForegroundColor White
Write-Host "     https://github.com/$GITHUB_REPO/actions" -ForegroundColor Cyan
Write-Host ""
Write-Host "To trigger a deployment now:" -ForegroundColor Yellow
Write-Host "  git commit --allow-empty -m 'Trigger deployment'" -ForegroundColor White
Write-Host "  git push origin $BRANCH" -ForegroundColor White
Write-Host ""
