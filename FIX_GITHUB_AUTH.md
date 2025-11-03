# Fix GitHub Authorization Popup Not Appearing

## The Problem

After disconnecting the first continuous deployment, Azure no longer shows the GitHub authorization popup when setting up a new branch deployment.

## Quick Fix Solutions (Try in Order)

---

### Solution 1: Force Re-authentication via Azure Portal (Easiest - 2 minutes)

1. **Clear browser cache/cookies for Azure Portal**
   - Press `Ctrl+Shift+Delete` in your browser
   - Select "Cookies and other site data"
   - Clear for "All time"
   - Close and reopen browser

2. **Use Incognito/Private Window**
   - Open Azure Portal in private/incognito window
   - Sign in fresh
   - Go to Container App → Continuous deployment → Add
   - The authorization popup should appear

3. **Try different browser**
   - Sometimes Edge vs Chrome vs Firefox handle OAuth differently
   - Try the setup in a different browser

---

### Solution 2: Install Azure Container Apps GitHub App Manually (3 minutes)

The authorization popup installs a GitHub App. Do this manually first:

1. **Go to GitHub Apps Installation**
   - Visit: https://github.com/apps/azure-container-apps/installations/new
   - Or: https://github.com/settings/installations
   - Look for "Azure Container Apps" app

2. **Install/Configure the App**
   - Click "Install" or "Configure" if already installed
   - Select your account: `kireland3517`
   - Choose: "Only select repositories"
   - Select: `voice-agents-platform`
   - Click "Install" or "Save"

3. **Now Try Azure Portal Setup**
   - Azure Portal → Container App → Continuous deployment → Add
   - Select branch: `feature/acs-quality-monitoring`
   - Should work without popup (already authorized)

---

### Solution 3: Use Azure CLI with GitHub Token (5 minutes)

Bypass the popup entirely by providing authentication directly:

#### Step 3.1: Create GitHub Personal Access Token

1. **Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
   - Direct link: https://github.com/settings/tokens

2. **Generate new token (classic)**
   - Note: "Azure Container Apps Deployment"
   - Expiration: 90 days (or longer)
   - Select scopes:
     - ✅ `repo` (all)
     - ✅ `workflow`
     - ✅ `admin:repo_hook` (all)
   - Click "Generate token"
   - **COPY THE TOKEN** (you won't see it again)

#### Step 3.2: Use Token with Azure CLI

```bash
# Set your token as a variable
$GITHUB_TOKEN = "ghp_your_token_here"

# Setup continuous deployment with token
az containerapp github-action add `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --repo-url https://github.com/kireland3517/voice-agents-platform `
  --branch feature/acs-quality-monitoring `
  --token $GITHUB_TOKEN
```

This will:
- Create GitHub Actions workflow in your repo
- Configure deployment secrets
- Enable auto-deployment
- NO popup needed!

---

### Solution 4: Manual GitHub Actions Setup (10 minutes - Most Reliable)

Create the deployment workflow yourself - no Azure authorization needed:

#### Step 4.1: Create Azure Service Principal

```powershell
# Get Azure credentials for GitHub
az ad sp create-for-rbac `
  --name "voice-agents-github-deployer" `
  --role contributor `
  --scopes /subscriptions/$(az account show --query id -o tsv)/resourceGroups/voice_agents `
  --sdk-auth
```

**Copy the entire JSON output** - you'll need it in the next step.

#### Step 4.2: Add GitHub Secrets

1. **Go to GitHub Repository Settings**
   - https://github.com/kireland3517/voice-agents-platform/settings/secrets/actions

2. **Click "New repository secret"** and add:

   **AZURE_CREDENTIALS**
   ```json
   {
     "clientId": "...",
     "clientSecret": "...",
     "subscriptionId": "...",
     "tenantId": "...",
     ...
   }
   ```
   (Paste the full JSON from Step 4.1)

#### Step 4.3: Update Workflow File

The workflow file already exists at `.github/workflows/deploy-quality-monitoring.yml`

We need to update it with your actual resource names:

```yaml
env:
  AZURE_CONTAINER_APP_NAME: voice-agents-bridge
  AZURE_RESOURCE_GROUP: voice_agents
```

I'll update this file for you below.

---

## Which Solution Should You Use?

| Solution | Time | Reliability | Recommendation |
|----------|------|-------------|----------------|
| 1. Clear cache/incognito | 2 min | Medium | Try first - easiest |
| 2. Manual GitHub App install | 3 min | High | Try second - usually works |
| 3. Azure CLI with token | 5 min | High | If Solutions 1-2 fail |
| 4. Manual GitHub Actions | 10 min | Highest | Most control, always works |

---

## Verify It's Working

After setup, verify deployment is configured:

```bash
# Check GitHub connection
az containerapp github-action show `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --query "{Branch:branch, Repo:repoUrl, Status:status}" `
  -o table

# Check GitHub Actions workflows
# Visit: https://github.com/kireland3517/voice-agents-platform/actions
```

Look for a workflow file created at:
`.github/workflows/voice-agents-bridge-AutoDeployTrigger-*.yml`

---

## Test the Deployment

Trigger a deployment:

```bash
# Make a small change to trigger deployment
git commit --allow-empty -m "test: Trigger deployment"
git push origin feature/acs-quality-monitoring
```

Watch deployment:
- **GitHub**: https://github.com/kireland3517/voice-agents-platform/actions
- **Azure**: Container App → Revisions (new revision should appear in 2-5 min)

---

## Still Not Working?

If none of these work, there may be an organizational policy blocking GitHub Apps.

**Check:**
1. Are you a repository admin?
2. Is your GitHub organization blocking third-party app access?
3. Try using Solution 4 (Manual GitHub Actions) - this always works

**Need help?** Let me know which solution you tried and what error you got.
