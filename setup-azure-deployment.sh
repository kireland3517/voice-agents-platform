#!/bin/bash
# Setup Azure Container App Continuous Deployment
# This script configures GitHub Actions deployment for the quality monitoring branch

set -e

echo "Azure Container App - Continuous Deployment Setup"
echo "=================================================="
echo ""

# Configuration
RESOURCE_GROUP="voice_agents"
CONTAINER_APP_NAME="voice-agents-bridge"
GITHUB_REPO="kireland3517/voice-agents-platform"
BRANCH="feature/acs-quality-monitoring"

echo "Configuration:"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Container App: $CONTAINER_APP_NAME"
echo "  GitHub Repo: $GITHUB_REPO"
echo "  Branch: $BRANCH"
echo ""

echo "Step 1: Checking if GitHub is already connected..."
if az containerapp github-action show \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --output none 2>/dev/null; then
  echo "  GitHub Actions already configured!"
  echo "  Updating to use $BRANCH branch..."
else
  echo "  No GitHub connection found. Setting up..."
fi

echo ""
echo "Step 2: Setting up GitHub Actions deployment..."
echo "  (You may be prompted to authenticate with GitHub)"
echo ""

# This will prompt for GitHub authentication if needed
az containerapp github-action add \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --repo-url "https://github.com/$GITHUB_REPO" \
  --branch "$BRANCH" \
  --token "$(gh auth token 2>/dev/null || echo 'PLACEHOLDER')" \
  --login-with-github

echo ""
echo "Step 3: Verifying configuration..."
az containerapp github-action show \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "{Branch:branch, Repo:repoUrl, Status:status}" \
  -o table

echo ""
echo "=================================================="
echo "SUCCESS: Continuous deployment configured!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "  1. Push changes to $BRANCH"
echo "  2. GitHub Actions will automatically build and deploy"
echo "  3. Check deployment status:"
echo "     https://github.com/$GITHUB_REPO/actions"
echo ""
echo "To trigger a deployment now:"
echo "  git commit --allow-empty -m 'Trigger deployment'"
echo "  git push origin $BRANCH"
echo ""
