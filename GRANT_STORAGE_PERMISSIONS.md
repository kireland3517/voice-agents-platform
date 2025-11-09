# Grant Storage Permissions to Service Principal

## Issue
The CI/CD pipeline upload job fails with:
```
ERROR: You do not have the required permissions needed to perform this operation.
Depending on your operation, you may need to be assigned one of the following roles:
    "Storage Blob Data Owner"
    "Storage Blob Data Contributor"
```

## Solution
Grant the service principal "Storage Blob Data Contributor" role on the **voiceagentsinstructions** storage account.

## Steps (Via Azure Portal)

### 1. Navigate to Storage Account
1. Go to: https://portal.azure.com
2. Search for "Storage accounts"
3. Click on: **voiceagentsinstructions**

### 2. Grant Role Assignment
1. In the left sidebar, click **Access Control (IAM)**
2. Click **+ Add** → **Add role assignment**
3. Select the **Role** tab:
   - Search for: **Storage Blob Data Contributor**
   - Select it and click **Next**

4. Select the **Members** tab:
   - Click **+ Select members**
   - Search for: **voice-agents-environmentvoiceagentsenvironmentf2c46dvoice_agentsOidc**
   - Select it and click **Select**
   - Click **Next**

5. Click **Review + assign**
6. Click **Review + assign** again to confirm

### 3. Verify Assignment
1. Stay on the **Access Control (IAM)** page
2. Click the **Role assignments** tab
3. Search for the service principal name
4. Confirm it has the **Storage Blob Data Contributor** role

## Alternative: Via Azure CLI (if you have sufficient permissions)

```bash
# Get your subscription ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# Grant the role
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee 5a1acb48-9aa7-41c9-a66c-d8c1b291c029 \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/voice_agents/providers/Microsoft.Storage/storageAccounts/voiceagentsinstructions"
```

## What This Fixes

After granting permissions, the CI/CD pipeline will be able to:
- ✅ Upload `sarah_instructions_senior_life.md` to the **agent-instructions** container
- ✅ Upload archived versions (v13, v14) to the **prompts/** folder
- ✅ Automatically deploy prompt updates on every commit to main

## Test After Granting Permissions

1. Make a small change to [sarah_instructions_senior_life.md](sarah_instructions_senior_life.md)
2. Commit and push to main
3. Watch the GitHub Actions workflow run
4. Verify the "Upload Prompt to Blob Storage" job succeeds

---

**Service Principal Details:**
- Display Name: `voice-agents-environmentvoiceagentsenvironmentf2c46dvoice_agentsOidc`
- App ID: `5a1acb48-9aa7-41c9-a66c-d8c1b291c029`
- Used by: GitHub Actions OIDC authentication
# Testing blob upload permissions (trigger fresh run)

