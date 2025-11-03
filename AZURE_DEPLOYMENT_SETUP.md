# Azure Continuous Deployment Setup

## Issue You're Seeing

The error `RoleAssignmentExists` means Azure is trying to create a role that already exists. This is **not critical** - it's just a warning that can be ignored.

However, the continuous deployment didn't fully complete because the GitHub connection needs authentication.

---

## Fix: Manual Setup in Azure Portal (Easiest)

### Option 1: Azure Portal (Recommended - 2 minutes)

1. **Go to Azure Portal** → Your Container App `voice-agents-bridge`

2. **Click "Deployment" → "Continuous deployment"**

3. **If you see the error, click "Remove" first** to clear the failed state

4. **Click "Add" or "Configure GitHub"**

5. **Authenticate with GitHub** when prompted

6. **Select:**
   - Organization: `kireland3517`
   - Repository: `voice-agents-platform`
   - Branch: `feature/acs-quality-monitoring`

7. **Click "Save"**

8. **Wait ~30 seconds** for Azure to configure GitHub Actions

9. **Verify:** Go to https://github.com/kireland3517/voice-agents-platform/actions
   - You should see a new workflow file created

**Done!** Every push to `feature/acs-quality-monitoring` will now auto-deploy.

---

## Option 2: Azure CLI (Requires GitHub CLI)

### Prerequisites

```bash
# Install GitHub CLI if not installed
# Windows: winget install GitHub.cli
# Mac: brew install gh

# Login to GitHub
gh auth login
```

### Setup Command

```bash
az containerapp github-action add \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --repo-url https://github.com/kireland3517/voice-agents-platform \
  --branch feature/acs-quality-monitoring \
  --login-with-github
```

This will:
1. Prompt for GitHub authentication
2. Create a workflow file in your repo
3. Configure deployment secrets
4. Enable auto-deployment

---

## Option 3: Manual GitHub Actions Setup

If Azure's built-in CD doesn't work, create your own workflow:

### Step 1: Create GitHub Secrets

Go to GitHub → Repository → Settings → Secrets and variables → Actions

Add these secrets:

1. **AZURE_CREDENTIALS**
   ```bash
   # Get these values
   az ad sp create-for-rbac --name voice-agent-deployer \
     --role contributor \
     --scopes /subscriptions/$(az account show --query id -o tsv)/resourceGroups/voice_agents \
     --sdk-auth
   ```
   Copy the entire JSON output

2. **AZURE_CONTAINER_REGISTRY** (if using ACR)
   - Value: Your ACR name (e.g., `yourregistry.azurecr.io`)

3. **ACR_USERNAME** and **ACR_PASSWORD**
   ```bash
   az acr credential show --name yourregistry
   ```

### Step 2: Create Workflow File

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Azure

on:
  push:
    branches:
      - feature/acs-quality-monitoring

env:
  AZURE_CONTAINER_APP: voice-agents-bridge
  RESOURCE_GROUP: voice_agents

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Azure Login
        uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Deploy to Container App
        run: |
          az containerapp up \
            --name ${{ env.AZURE_CONTAINER_APP }} \
            --resource-group ${{ env.RESOURCE_GROUP }} \
            --source .
```

Commit and push this file - deployments will start automatically!

---

## Verify Deployment is Working

### Check GitHub Actions

```bash
# Open in browser
https://github.com/kireland3517/voice-agents-platform/actions
```

You should see workflows running when you push to the branch.

### Check Azure Logs

```bash
az containerapp logs show \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --follow
```

Look for:
```
Quality monitoring enabled for call...
AudioQualityMonitor initialized...
NetworkDiagnostics initialized...
```

---

## Test the Deployment

### Trigger a Deployment

```bash
# Make a small change
echo "# Test deployment" >> README.md

# Commit and push
git add README.md
git commit -m "test: Trigger deployment"
git push origin feature/acs-quality-monitoring
```

### Monitor Deployment

1. **GitHub Actions:** https://github.com/kireland3517/voice-agents-platform/actions
   - Watch the build/deploy progress

2. **Azure Portal:** Container App → Revisions
   - New revision should appear in ~2-5 minutes

3. **Test Call:** Make a call and check logs
   ```bash
   az containerapp logs show \
     --name voice-agents-bridge \
     --resource-group voice_agents \
     --tail 50
   ```

---

## Troubleshooting

### "RoleAssignmentExists" Error

**This is OK!** It means the role is already set up. The deployment should still work.

**Fix:** In Azure Portal → Continuous Deployment → Remove → Add again

### "LinkedRepoNotFound" Error

GitHub connection didn't complete.

**Fix:** Use Option 1 (Azure Portal) or Option 3 (Manual GitHub Actions)

### Deployment Successful But Quality Monitoring Not Working

**Check:**
```bash
# Verify files were deployed
az containerapp exec \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --command "ls -la *.py"
```

You should see:
```
audio_quality_monitor.py
network_diagnostics.py
call_diagnostics_logger.py
quality_monitoring.py
mos_scorer.py
```

### GitHub Actions Failing

**Check:**
1. All secrets are configured correctly
2. AZURE_CREDENTIALS is valid JSON
3. ACR credentials are correct

**Re-generate credentials:**
```bash
az ad sp create-for-rbac --name voice-agent-deployer \
  --role contributor \
  --scopes /subscriptions/$(az account show --query id -o tsv)/resourceGroups/voice_agents \
  --sdk-auth
```

---

## Quick Reference

**Your Resources:**
- Resource Group: `voice_agents`
- Container App: `voice-agents-bridge`
- GitHub Repo: `kireland3517/voice-agents-platform`
- Branch: `feature/acs-quality-monitoring`

**Useful Commands:**
```bash
# Check deployment status
az containerapp revision list \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --query "[].{Name:name, Active:properties.active, Created:properties.createdTime}" \
  -o table

# View live logs
az containerapp logs show \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --follow

# Restart app
az containerapp revision restart \
  --name voice-agents-bridge \
  --resource-group voice_agents
```

---

## Recommended Approach

**For quickest setup:**
1. Use **Option 1 (Azure Portal)** - it's the most reliable
2. If that fails, use **Option 3 (Manual GitHub Actions)**
3. Verify by checking GitHub Actions and Azure logs

**Once working:**
- Every `git push` to `feature/acs-quality-monitoring` auto-deploys
- Check logs after deployment to verify quality monitoring is active
- Make a test call to see quality metrics in action

---

## Next Steps After Setup

1. **Merge to main** when ready for production
2. **Update CD to deploy from main branch**
3. **Set up alerts** in Log Analytics for quality issues
4. **Monitor quality metrics** in real calls

**Questions?** Check the main [QUALITY_MONITORING.md](QUALITY_MONITORING.md) guide.
