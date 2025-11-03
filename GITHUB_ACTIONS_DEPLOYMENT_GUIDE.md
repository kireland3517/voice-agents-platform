# GitHub Actions Deployment Guide

## Overview

This guide covers the automated CI/CD pipeline for deploying the Voice Agents Platform to Azure Container Apps using GitHub Actions.

**Workflow File:** [`.github/workflows/deploy-to-azure.yml`](.github/workflows/deploy-to-azure.yml)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Workflow Stages](#workflow-stages)
3. [Environment Configuration](#environment-configuration)
4. [Required Secrets](#required-secrets)
5. [Deployment Triggers](#deployment-triggers)
6. [Manual Deployment](#manual-deployment)
7. [Rollback Procedures](#rollback-procedures)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS WORKFLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Code       │  │  Security   │  │  Automated  │             │
│  │  Quality    │  │  Scanning   │  │  Tests      │             │
│  │  Checks     │  │             │  │             │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                 │                 │                    │
│         └─────────────────┴─────────────────┘                    │
│                           │                                      │
│                  ┌────────▼────────┐                            │
│                  │  Build Docker   │                            │
│                  │  Image          │                            │
│                  └────────┬────────┘                            │
│                           │                                      │
│         ┌─────────────────┴─────────────────┐                  │
│         │                                     │                  │
│  ┌──────▼──────┐                    ┌────────▼────────┐        │
│  │  Deploy to  │                    │  Deploy to      │        │
│  │  Staging    │                    │  Production     │        │
│  │  (Auto)     │                    │  (Approval)     │        │
│  └──────┬──────┘                    └────────┬────────┘        │
│         │                                     │                  │
│         └─────────────────┬─────────────────┘                  │
│                           │                                      │
│                  ┌────────▼────────┐                            │
│                  │  Notifications  │                            │
│                  │  & Reporting    │                            │
│                  └─────────────────┘                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Workflow Stages

### 1. **Code Quality Checks** (`lint` job)

**Purpose:** Ensures code quality and consistency before deployment.

**Tools Used:**
- **Black:** Code formatting validator
- **isort:** Import statement sorting
- **Flake8:** Python linting (syntax errors, undefined names)
- **Pylint:** Static code analysis

**Failure Handling:** Continues even if linting fails (warnings only).

**Duration:** ~2-3 minutes

---

### 2. **Security Scanning** (`security` job)

**Purpose:** Identifies security vulnerabilities in code and dependencies.

**Tools Used:**
- **Bandit:** Security-focused linter for Python
- **Safety:** Dependency vulnerability checker (CVE database)

**Artifacts:** Generates `bandit-report.json` (retained for 30 days)

**Failure Handling:** Continues even if vulnerabilities found (warnings only).

**Duration:** ~3-5 minutes

---

### 3. **Automated Testing** (`test` job)

**Purpose:** Runs unit tests and generates coverage reports.

**Tools Used:**
- **pytest:** Test framework
- **pytest-cov:** Coverage reporting
- **pytest-asyncio:** Async test support

**Artifacts:**
- `coverage.xml`
- `htmlcov/` (HTML coverage report)

**Skip Option:** Can be skipped with manual trigger input.

**Duration:** ~5-10 minutes (depending on test suite size)

---

### 4. **Build & Push Docker Image** (`build` job)

**Purpose:** Builds containerized application and pushes to Azure Container Registry.

**Features:**
- **BuildKit:** Advanced Docker build engine
- **Multi-layer caching:** Speeds up subsequent builds
- **Metadata extraction:** Automatic tagging strategy

**Image Tags Generated:**
- `{branch}` - Branch name (e.g., `main`, `develop`, `claude-edits`)
- `{branch}-{sha}` - Branch + commit SHA (e.g., `main-a1b2c3d`)
- `latest` - Latest successful build from main branch

**Duration:** ~5-10 minutes (first build), ~2-3 minutes (cached)

---

### 5. **Deploy to Staging** (`deploy-staging` job)

**Trigger Conditions:**
- Push to `develop` branch
- Push to `feature/*` branches
- Push to `claude-edits` branch
- Manual trigger with `staging` environment

**Environment:** `staging`

**URL:** `https://voice-agents-bridge-staging.azurecontainerapps.io`

**Features:**
- Automatic deployment (no approval required)
- Health check verification (30s wait + HTTP 200 check)
- Uploads `cedar_instructions_enhanced.md` to staging Blob Storage

**Environment Variables:**
- `ENVIRONMENT=staging`
- `LOG_LEVEL=DEBUG`
- `ENABLE_DETAILED_LOGGING=true`

**Duration:** ~5-7 minutes

---

### 6. **Deploy to Production** (`deploy-production` job)

**Trigger Conditions:**
- Push to `main` branch
- Manual trigger with `production` environment

**Environment:** `production` (requires approval in GitHub)

**URL:** `https://voice-agents-bridge.azurecontainerapps.io`

**Features:**
- **Approval required:** Set up in GitHub environment settings
- **Rollback capability:** Saves current revision before deployment
- **Health check verification:** 60s wait + HTTP 200 check
- **Automatic rollback:** Reverts to previous revision if deployment fails
- **GitHub Release creation:** Creates versioned release on success
- **Blob Storage upload:** Uploads enhanced instructions to production

**Environment Variables:**
- `ENVIRONMENT=production`
- `LOG_LEVEL=INFO`
- `ENABLE_DETAILED_LOGGING=false`

**Duration:** ~7-10 minutes

---

### 7. **Post-Deployment Notifications** (`notify` job)

**Purpose:** Summarizes deployment results.

**Output:**
- GitHub Actions summary (visible in workflow run)
- Optional: Slack, Teams, email notifications (commented out)

**Duration:** <1 minute

---

## Environment Configuration

### GitHub Environments Setup

You need to configure two environments in GitHub:

**Settings → Environments → New environment**

#### Staging Environment

1. **Name:** `staging`
2. **URL:** `https://voice-agents-bridge-staging.azurecontainerapps.io`
3. **Protection rules:** None (auto-deploy)
4. **Secrets:**
   - `STAGING_STORAGE_ACCOUNT` (Azure Storage account name)

#### Production Environment

1. **Name:** `production`
2. **URL:** `https://voice-agents-bridge.azurecontainerapps.io`
3. **Protection rules:**
   - ✅ **Required reviewers:** Add yourself or team members
   - ✅ **Wait timer:** 5 minutes (optional, gives time to cancel)
4. **Secrets:**
   - `PRODUCTION_STORAGE_ACCOUNT` (Azure Storage account name)

---

## Required Secrets

### Repository Secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Description | How to Get |
|-------------|-------------|------------|
| `VOICEAGENTSBRIDGE_AZURE_CLIENT_ID` | Azure Service Principal Client ID | Azure Portal → App Registrations |
| `VOICEAGENTSBRIDGE_AZURE_TENANT_ID` | Azure AD Tenant ID | Azure Portal → Azure Active Directory |
| `VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID` | Azure Subscription ID | Azure Portal → Subscriptions |
| `VOICEAGENTSBRIDGE_REGISTRY_USERNAME` | Azure Container Registry username | Azure Portal → Container Registry → Access keys |
| `VOICEAGENTSBRIDGE_REGISTRY_PASSWORD` | Azure Container Registry password | Azure Portal → Container Registry → Access keys |

### Environment Secrets

**Settings → Environments → {environment} → Add secret**

| Secret Name | Description | Used In |
|-------------|-------------|---------|
| `STAGING_STORAGE_ACCOUNT` | Staging storage account name | Staging deployment |
| `PRODUCTION_STORAGE_ACCOUNT` | Production storage account name | Production deployment |

---

## Deployment Triggers

### Automatic Deployments

| Branch | Environment | Approval Required | Notes |
|--------|-------------|-------------------|-------|
| `main` | Production | ✅ Yes | Creates GitHub Release |
| `develop` | Staging | ❌ No | Auto-deploy |
| `feature/*` | Staging | ❌ No | Feature testing |
| `claude-edits` | Staging | ❌ No | Current active branch |

### File Triggers

Workflow only runs when these files change:
- `**.py` (all Python files)
- `requirements.txt`
- `Dockerfile`
- `.github/workflows/deploy-to-azure.yml`
- `config.py`, `app.py`
- `**.md` (instructions files)

### Pull Request Validation

When opening a PR to `main` or `develop`:
- ✅ Runs: `lint`, `security`, `test`, `build`
- ❌ Skips: `deploy-staging`, `deploy-production`

**Purpose:** Validates code quality before merge, without deploying.

---

## Manual Deployment

### Via GitHub UI

1. Go to **Actions** tab
2. Select **"Deploy Voice Agents Platform to Azure"** workflow
3. Click **"Run workflow"** button
4. Choose:
   - **Branch:** Select branch to deploy
   - **Environment:** `staging` or `production`
   - **Skip tests:** ✅ or ❌ (not recommended)
5. Click **"Run workflow"**

### Via GitHub CLI

```bash
# Deploy to staging
gh workflow run deploy-to-azure.yml \
  --ref claude-edits \
  --field environment=staging \
  --field skip_tests=false

# Deploy to production
gh workflow run deploy-to-azure.yml \
  --ref main \
  --field environment=production \
  --field skip_tests=false
```

---

## Rollback Procedures

### Automatic Rollback

If production deployment fails the health check:
1. Workflow automatically saves the current revision before deployment
2. On failure, activates the previous revision
3. Logs rollback details in workflow output

**No manual intervention required.**

### Manual Rollback (via Azure CLI)

If you need to manually rollback production:

```bash
# 1. List all revisions
az containerapp revision list \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --query "[].{Name:name, Active:properties.active, Created:properties.createdTime}" \
  --output table

# 2. Activate a specific revision
az containerapp revision activate \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --revision <REVISION_NAME>

# 3. Verify activation
az containerapp revision show \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --revision <REVISION_NAME> \
  --query "properties.active"
```

### Manual Rollback (via Azure Portal)

1. Go to Azure Portal → Container Apps → `voice-agents-bridge`
2. Click **"Revision management"** in left sidebar
3. Find the previous working revision
4. Click **"Activate"** next to that revision
5. Confirm activation

---

## Troubleshooting

### Deployment Fails at "Build Docker Image"

**Symptoms:**
```
Error: failed to solve: failed to compute cache key
```

**Solution:**
1. Check Dockerfile syntax
2. Verify all COPY paths exist
3. Clear GitHub Actions cache:
   - Settings → Actions → Caches → Delete all caches

---

### Deployment Fails at "Azure Login"

**Symptoms:**
```
Error: Unable to get OIDC token
```

**Solution:**
1. Verify secrets are set correctly:
   - `VOICEAGENTSBRIDGE_AZURE_CLIENT_ID`
   - `VOICEAGENTSBRIDGE_AZURE_TENANT_ID`
   - `VOICEAGENTSBRIDGE_AZURE_SUBSCRIPTION_ID`
2. Check Service Principal permissions in Azure
3. Ensure OIDC federation is configured for the Service Principal

---

### Health Check Fails After Deployment

**Symptoms:**
```
⚠️ Staging deployment may have issues. Health check returned: 503
```

**Solution:**
1. Check Container App logs in Azure Portal
2. Verify environment variables are set
3. Check if `/health` endpoint exists in app.py:
   ```python
   @app.get("/health")
   async def health():
       return {"status": "healthy"}
   ```
4. Increase wait time before health check (currently 30s/60s)

---

### Blob Storage Upload Fails

**Symptoms:**
```
⚠️ Blob upload skipped (configure STAGING_STORAGE_ACCOUNT secret)
```

**Solution:**
1. Add environment secret:
   - Settings → Environments → staging/production → Add secret
   - Name: `STAGING_STORAGE_ACCOUNT` or `PRODUCTION_STORAGE_ACCOUNT`
   - Value: Storage account name (not full URL)
2. Verify Azure CLI has permissions to upload blobs

---

### Production Deployment Waiting Forever

**Symptoms:**
Workflow shows "Waiting for approval"

**Solution:**
1. Go to Actions → Select workflow run
2. Click **"Review deployments"** button
3. Select **production** environment
4. Click **"Approve and deploy"**

**To configure auto-approval:**
- Settings → Environments → production
- Remove "Required reviewers" protection rule

---

## Best Practices

### 1. Branch Strategy

**Recommended Flow:**
```
feature/new-feature → develop → staging deployment (auto)
                         ↓
                      (testing)
                         ↓
                      merge to main → production deployment (approval)
```

### 2. Testing Before Production

**Always:**
1. Deploy to staging first (`develop` or `feature/*` branch)
2. Test thoroughly in staging environment
3. Only merge to `main` when staging is validated
4. Production deployment requires approval

### 3. Environment Variables

**Never hardcode:**
- API keys
- Connection strings
- Passwords

**Instead:**
- Use GitHub Secrets for sensitive values
- Use environment-specific configs in Container Apps
- Reference via `${{ secrets.SECRET_NAME }}`

### 4. Monitoring After Deployment

**After production deployment:**
1. Check health endpoint: `https://voice-agents-bridge.azurecontainerapps.io/health`
2. Monitor Azure Container Apps logs (first 5 minutes)
3. Test a real phone call to Cedar
4. Check Application Insights for errors (if enabled)

### 5. Rollback Decision

**Roll back if:**
- Health check fails
- Error rate > 5% in first 10 minutes
- Customer complaints about Cedar not responding

**Don't roll back for:**
- Minor log warnings
- Non-critical feature issues
- Cosmetic problems

---

## Workflow Customization

### Enable Slack Notifications

Uncomment the Slack notification step in `notify` job:

```yaml
- name: Send Slack notification
  uses: slackapi/slack-github-action@v1
  with:
    webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
    payload: |
      {
        "text": "Deployment completed for voice-agents-platform",
        "blocks": [
          {
            "type": "section",
            "text": {
              "type": "mrkdwn",
              "text": "*Deployment Status*\nProduction: ${{ needs.deploy-production.result }}\nStaging: ${{ needs.deploy-staging.result }}"
            }
          }
        ]
      }
```

Add secret:
- Settings → Secrets → New secret
- Name: `SLACK_WEBHOOK_URL`
- Value: Your Slack webhook URL

### Add More Environments

To add a `development` environment:

1. Create environment in GitHub:
   - Settings → Environments → New environment: `development`

2. Add deployment job in workflow:
   ```yaml
   deploy-development:
     name: Deploy to Development
     runs-on: ubuntu-latest
     needs: [build]
     if: github.ref == 'refs/heads/dev'
     environment:
       name: development
       url: https://voice-agents-bridge-dev.azurecontainerapps.io
     # ... (same steps as deploy-staging)
   ```

### Change Health Check URL

If your health endpoint is different:

```yaml
- name: Deployment verification
  run: |
    PROD_URL="https://voice-agents-bridge.azurecontainerapps.io/api/status"  # Changed
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" $PROD_URL || echo "000")
```

---

## Workflow Metrics

**Expected Durations:**
- Full workflow (staging): ~20-25 minutes
- Full workflow (production): ~25-35 minutes
- Build only (no deploy): ~10-15 minutes

**Resource Usage:**
- Compute: Ubuntu runner (2-core, 7GB RAM)
- Storage: ~500MB per workflow run
- Artifacts: ~50MB (logs, reports)

**Cost Estimate (GitHub Actions):**
- Public repo: Free (unlimited minutes)
- Private repo: ~10-15 minutes per workflow = ~$0.08-0.12 per run

---

## Security Considerations

### Secret Rotation

Rotate secrets every 90 days:
1. Azure Container Registry password
2. Service Principal credentials
3. Storage account keys

### Least Privilege

Service Principal should have:
- **Reader** on subscription
- **Contributor** on resource group `voice_agents`
- **AcrPush** on container registry
- **Storage Blob Data Contributor** on storage account

### Audit Logging

All deployments are logged:
- GitHub Actions logs (retained 90 days)
- Azure Activity Log (retained 90 days)
- Container Apps revision history (retained indefinitely)

---

## Support & Resources

**Documentation:**
- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [Azure Container Apps Docs](https://learn.microsoft.com/azure/container-apps/)
- [Docker Build Docs](https://docs.docker.com/build/)

**Workflow File:** [`.github/workflows/deploy-to-azure.yml`](.github/workflows/deploy-to-azure.yml)

**Related Files:**
- [`Dockerfile`](Dockerfile)
- [`requirements.txt`](requirements.txt)
- [`config.py`](config.py)

**Issues?**
- Open a GitHub Issue with `deployment` label
- Include workflow run URL
- Attach relevant logs

---

*Generated by Claude Code - Branch: claude-edits - November 3, 2025*
