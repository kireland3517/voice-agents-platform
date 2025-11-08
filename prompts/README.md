# Sarah Prompt Versions

This directory contains archived versions of Sarah's prompt for reference and rollback purposes.

## Current Active Version

**File in Blob Storage:** `senior-life/instructions.md`
**Version:** 14 (Principles-based)
**Source File:** `../sarah_instructions_senior_life.md`

## Version History

### v14 - Principles-Based (Current)
**File:** `sarah-v14-principles.md`
**Changes:** Removed exact word-for-word scripts, replaced with flexible principles
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

## How to Switch Versions

### Via Azure Portal (Manual):
1. Go to: Azure Portal → voiceagentsstorage → Containers → company-configs → senior-life
2. Upload the desired version file
3. Rename it to `instructions.md` (or use "Copy" feature)
4. Restart the container app (or wait for next call)

### Via CI/CD (Automated):
1. Copy desired version to `sarah_instructions_senior_life.md` in repo root
2. Update version metadata in the file
3. Commit and push
4. CI/CD will automatically upload to blob storage

## Rollback Process

If you need to rollback from v14 to v13:

```bash
# 1. Copy v13 back to main file
cp prompts/sarah-v13-exact-scripts.md sarah_instructions_senior_life.md

# 2. Update version number in file to v15 (or next version)
# Add note: "Rollback to exact scripts from v13"

# 3. Commit and push
git add sarah_instructions_senior_life.md
git commit -m "Rollback to v13 exact scripts (now v15)"
git push

# CI/CD will auto-deploy
```

## Future: Blob Versioning

Once blob versioning is enabled on Azure Storage:
- Every upload automatically saves previous version
- Can restore any version via Azure Portal
- No need to manually manage version files
- Git history serves as documentation, blob storage has the backups
