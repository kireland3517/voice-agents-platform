# Sarah Prompt Versions

This directory contains archived versions of Sarah's prompt for reference and rollback purposes.

## Automated Versioning System

**Every time you push to main:**
1. The CI/CD workflow extracts version number and description from `sarah_instructions_senior_life.md`
2. Creates an archive: `prompts/sarah-v{VERSION}-{description}.md`
3. Commits the archive back to git
4. Uploads to Azure Blob Storage:
   - Root: `sarah_instructions_senior_life.md` (what app.py loads)
   - Archive: `senior-life/prompts/sarah-v{VERSION}-{description}.md`

**Azure Blob Versioning:** Also enabled - Azure automatically snapshots every overwrite with a timestamp for safety.

## Current Active Version

**File in Blob Storage:** `sarah_instructions_senior_life.md` (root of agent-instructions container)
**Version:** 14 (Principles-based)
**Source File:** `../sarah_instructions_senior_life.md`

## Version History

### v14 - Principles-Based (Current)
**File:** `sarah-v14-principles.md`
**Changes:** Changed from exact scripts to principles for natural voice pacing (Ch83)
- Phone numbers: "Read digits in groups (3-3-4 pattern) with natural pauses"
- Natural variation instead of rigid templates
- Improved voice cadence and reduced robotic delivery

**When to use:** Default/current version for natural conversational flow

### v13 - Exact Scripts
**File:** `sarah-v13-exact-scripts.md`
**Changes:** Version management system, context injection timing, 10-digit phone format
- Phone numbers: "Say: 'I see you're calling from five, four, zero, seven...'"
- Exact word-for-word templates
- More predictable but potentially robotic

**When to use:** If you need highly consistent exact phrasing (e.g., legal/compliance requirements)

## How to Create a New Version

1. Edit `sarah_instructions_senior_life.md` in the repo root
2. Update the metadata header:
   ```markdown
   ---
   PROMPT METADATA
   Version: 15
   Last Updated: 2025-11-09
   Changes: Brief description of what changed
   Git Commit: (will be filled after commit)
   Previous Versions: v14 (principles), v13 (exact scripts)
   ---
   ```
3. Commit and push to main
4. The workflow automatically:
   - Creates `prompts/sarah-v15-brief-description.md`
   - Commits it to git
   - Uploads to Azure Blob Storage

**That's it!** No manual archiving needed.

## How to Switch Versions

### Rollback to Previous Version:

```bash
# 1. Copy desired version back to main file
cp prompts/sarah-v13-exact-scripts.md sarah_instructions_senior_life.md

# 2. Update version metadata in file to NEXT version (v15)
# Add note in Changes: "Rollback to v13 exact scripts"

# 3. Commit and push
git add sarah_instructions_senior_life.md
git commit -m "Ch84: Rollback to v13 exact scripts"
git push

# CI/CD will auto-archive as v15 and deploy
```

## Viewing Version History in Azure

### Azure Portal:
1. Go to: Storage account → **voiceagentsinstructions** → Containers → **agent-instructions**
2. Navigate to folder: **senior-life/prompts/**
3. You'll see all archived versions with descriptive names

### Azure Blob Versions (timestamped snapshots):
1. Go to: Storage account → **voiceagentsinstructions** → Containers → **agent-instructions**
2. Click on: `sarah_instructions_senior_life.md`
3. Click the **Versions** tab
4. See all historical versions with timestamps (automatic backups)

## Emergency Restore

If you need to restore from Azure Blob versioned snapshot:

```bash
# List all versions with timestamps
az storage blob list \
  --account-name voiceagentsinstructions \
  --container-name agent-instructions \
  --prefix sarah_instructions_senior_life.md \
  --include v \
  --auth-mode login

# Download specific version by version ID
az storage blob download \
  --account-name voiceagentsinstructions \
  --container-name agent-instructions \
  --name sarah_instructions_senior_life.md \
  --version-id "2025-11-09T01:15:07.7051939Z" \
  --file sarah_restored.md \
  --auth-mode login
```
