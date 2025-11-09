# Automated Prompt Upload System

## Overview

The voice agents platform uses **fully automated prompt management** via GitHub Actions. When you push changes to `sarah_instructions_senior_life.md` on the main branch, the system automatically:

1. Extracts version metadata from the prompt
2. Creates a versioned archive in `prompts/` directory
3. Commits the archive back to git
4. Uploads both current and archived versions to Azure Blob Storage

**No manual uploads required!**

---

## How It Works

### Workflow Trigger

The GitHub Actions workflow (`.github/workflows/deploy-to-azure.yml`) runs automatically on every push to the `main` branch.

### Automated Steps

1. **Version Extraction**
   - Reads `Version:` and `Changes:` from prompt metadata header
   - Sanitizes description for filename (lowercase, no special chars, max 30 chars)
   - Example: Version 14 + "Changed from exact scripts to principles" → `sarah-v14-changed-from-exact-scripts-to.md`

2. **Archive Creation**
   - Creates `prompts/sarah-v{VERSION}-{description}.md`
   - Commits archive to git repository
   - Pushes commit back to main branch

3. **Blob Storage Upload**
   - **Current version:** Uploads to `agent-instructions/sarah_instructions_senior_life.md` (what app.py loads)
   - **Versioned archive:** Uploads to `agent-instructions/senior-life/prompts/sarah-v{VERSION}-{description}.md`

4. **Azure Blob Versioning**
   - Azure automatically creates timestamped snapshots of every overwrite
   - Provides additional safety net beyond git/file archives

---

## Making Prompt Updates

### Step 1: Edit the Prompt

Edit `sarah_instructions_senior_life.md` in VSCode:

```markdown
---
PROMPT METADATA
Version: 15
Last Updated: 2025-11-10
Changes: Added callback scheduling logic
Git Commit: <will be filled automatically>
Previous Versions: v14 (principles-based), v13 (exact scripts)
---
```

**Important:**
- Increment `Version:` number
- Update `Last Updated:` date
- Describe your changes in `Changes:` field (used for archive filename)

### Step 2: Commit and Push

```bash
git add sarah_instructions_senior_life.md
git commit -m "Ch85: Add callback scheduling logic to Sarah prompt"
git push
```

### Step 3: Automated Deployment

GitHub Actions automatically:
- Creates `prompts/sarah-v15-added-callback-scheduling-logi.md`
- Commits it to git
- Uploads both files to Azure Blob Storage

**That's it!** No manual uploads, no Azure Portal visits needed.

---

## Blob Storage Structure

```
agent-instructions/
├── sarah_instructions_senior_life.md              # Current version (app.py loads this)
└── senior-life/
    └── prompts/
        ├── sarah-v13-exact-scripts.md              # v13 archive
        ├── sarah-v14-changed-from-exact-scripts-to.md  # v14 archive
        └── sarah-v15-added-callback-scheduling-logi.md # v15 archive (new)
```

**Current Version:**
- Location: Root level (`sarah_instructions_senior_life.md`)
- Purpose: Loaded by `config.py` for production calls
- Updates: Automatically on every push

**Archives:**
- Location: `senior-life/prompts/` folder
- Purpose: Version history and rollback capability
- Naming: `sarah-v{VERSION}-{description}.md`

---

## Version Management

See **[prompts/README.md](prompts/README.md)** for:
- How to create new versions
- How to rollback to previous versions
- How to view version history in Azure Portal
- Emergency restore procedures

---

## Azure Blob Versioning

**Enabled:** Yes (configured via `az storage account blob-service-properties update`)

**What it does:**
- Creates automatic timestamped snapshots of every blob overwrite
- Provides point-in-time recovery capability
- Accessible via Azure Portal → Storage Account → Containers → Blob → Versions

**Example:**
```
sarah_instructions_senior_life.md
├── Current (2025-11-09 12:04:45)  ← Active version
├── Version 1 (2025-11-09 01:15:08)
├── Version 2 (2025-11-08 18:42:00)
└── Version 3 (2025-11-07 14:22:15)
```

---

## Viewing Uploads in Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to: Storage accounts → **voiceagentsinstructions**
3. Click: Containers → **agent-instructions**
4. Browse:
   - **sarah_instructions_senior_life.md** (current version)
   - **senior-life/prompts/** (archives)
5. Click any blob → **Versions** tab to see timestamped snapshots

---

## Troubleshooting

### Workflow Fails

Check GitHub Actions logs:
1. Go to GitHub repository → Actions tab
2. Click the failed workflow run
3. Expand "Upload Prompt to Blob Storage" step
4. Look for error messages

**Common issues:**
- Permissions error → Service principal needs "Storage Blob Data Contributor" role
- Metadata parsing error → Check prompt header format
- Git conflict → Archive file already exists (manually delete and re-run)

### Blob Not Updated

Verify workflow completed:
```bash
# Check recent workflow runs
gh run list --workflow=deploy-to-azure.yml --limit 5

# View specific run logs
gh run view <run-id> --log
```

### Manual Upload (Emergency Only)

If automation is broken, you can manually upload:

```bash
# Login to Azure
az login

# Upload current version
az storage blob upload \
  --account-name voiceagentsinstructions \
  --container-name agent-instructions \
  --name sarah_instructions_senior_life.md \
  --file sarah_instructions_senior_life.md \
  --auth-mode login \
  --overwrite
```

**Note:** This bypasses versioning system. Fix automation ASAP.

---

## Service Principal Configuration

**GitHub Actions uses:**
- Service Principal: `voice-agents-github-deployer`
- App ID: `964487a8-510b-4f8c-9e51-0bde7c2d76a1`
- Role: Storage Blob Data Contributor
- Scope: `/subscriptions/.../resourceGroups/voice_agents/providers/Microsoft.Storage/storageAccounts/voiceagentsinstructions`

**To verify permissions:**
```bash
az role assignment list \
  --assignee 964487a8-510b-4f8c-9e51-0bde7c2d76a1 \
  --scope /subscriptions/5b4df114-b699-49ae-bc50-babd8b9af6d4/resourceGroups/voice_agents/providers/Microsoft.Storage/storageAccounts/voiceagentsinstructions
```

---

## Migration Notes

**Old System (deprecated):**
- Manual uploads via `upload_cedar_v2_improved.py`
- Manual blob naming: `{company-id}_instructions.md`
- No version management
- No automation

**New System (current):**
- Automated via GitHub Actions
- Standardized blob naming: `sarah_instructions_senior_life.md`
- Git + blob archives + Azure versioning
- Zero manual intervention

All manual upload scripts have been removed in Ch84 cleanup.

---

## Related Documentation

- [prompts/README.md](prompts/README.md) - Prompt version management guide
- [.github/workflows/deploy-to-azure.yml](.github/workflows/deploy-to-azure.yml) - Workflow configuration
- [README.md](README.md) - Main project documentation
- [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md) - System architecture diagrams

---

**Last Updated:** November 9, 2025 (v21.0)
