# GitHub Secrets Setup for Manual Deployment

## Step 1: Add AZURE_CREDENTIALS Secret

1. **Go to your GitHub repository settings:**
   - Visit: https://github.com/kireland3517/voice-agents-platform/settings/secrets/actions

2. **Click "New repository secret"**

3. **Add the secret:**
   - Name: `AZURE_CREDENTIALS`
   - Value: Copy and paste the entire JSON below:

```json
{
  "clientId": "964487a8-510b-4f8c-9e51-0bde7c2d76a1",
  "clientSecret": "Zts8Q~1eClbnUBwb5LaYGvQkG0uwVpX3R7V-.ddp",
  "subscriptionId": "5b4df114-b699-49ae-bc50-babd8b9af6d4",
  "tenantId": "b0dac3a1-29f5-490a-b841-bb2fa0674680",
  "activeDirectoryEndpointUrl": "https://login.microsoftonline.com",
  "resourceManagerEndpointUrl": "https://management.azure.com/",
  "activeDirectoryGraphResourceId": "https://graph.windows.net/",
  "sqlManagementEndpointUrl": "https://management.core.windows.net:8443/",
  "galleryEndpointUrl": "https://gallery.azure.com/",
  "managementEndpointUrl": "https://management.core.windows.net/"
}
```

4. **Click "Add secret"**

## Step 2: Commit and Push the Workflow File

The workflow file is already configured at `.github/workflows/deploy-quality-monitoring.yml`

```bash
# Commit the updated workflow file
git add .github/workflows/deploy-quality-monitoring.yml
git commit -m "Configure GitHub Actions deployment for quality monitoring"
git push origin feature/acs-quality-monitoring
```

## Step 3: Verify the Deployment

1. **Check GitHub Actions:**
   - Visit: https://github.com/kireland3517/voice-agents-platform/actions
   - You should see the workflow running automatically after the push

2. **Monitor the deployment:**
   - Click on the workflow run to see detailed logs
   - It will run tests, then deploy to Azure

3. **Verify in Azure:**
   ```powershell
   # Check for new revision
   az containerapp revision list `
     --name voice-agents-bridge `
     --resource-group voice_agents `
     --query "[].{Name:name, Active:properties.active, Created:properties.createdTime}" `
     -o table
   ```

## What This Does

- **No Azure Portal authorization needed!**
- GitHub Actions will automatically deploy every time you push to `feature/acs-quality-monitoring`
- The workflow:
  1. Runs quality monitoring tests
  2. Deploys to Azure Container Apps using `az containerapp up`
  3. No ACR or Docker registry required!

## Troubleshooting

### Workflow fails with authentication error

**Check:**
- AZURE_CREDENTIALS secret is correctly formatted JSON
- No extra spaces or characters
- All fields are present

**Fix:** Delete and re-add the secret in GitHub

### Workflow runs but deployment fails

**Check deployment logs:**
```powershell
az containerapp logs show `
  --name voice-agents-bridge `
  --resource-group voice_agents `
  --follow
```

### Want to trigger deployment manually?

```bash
# Make an empty commit
git commit --allow-empty -m "test: Trigger deployment"
git push origin feature/acs-quality-monitoring
```

Or use the "Actions" tab in GitHub and click "Run workflow" (workflow_dispatch is enabled)

## Next Steps

After the first successful deployment:

1. **Make a test call** to verify quality monitoring is working
2. **Check logs** for quality metrics:
   ```powershell
   az containerapp logs show `
     --name voice-agents-bridge `
     --resource-group voice_agents `
     --tail 100 | Select-String "QUALITY|MOS|JITTER"
   ```
3. **Monitor future deployments** - they'll happen automatically on every push!

---

**This method bypasses all the GitHub authorization popup issues!**
