# INSTRUCTIONS FOR UPDATING CEDAR'S SCRIPT

## The Problem

Cedar is still saying things like "Got it, your email is..." because the instructions are loaded from **Azure Blob Storage**, not from the code.

The code changes I made enforce the behavior, but Cedar's LLM prompt (the script) needs to be updated in Blob Storage to match.

## What You Need to Do

1. **Open the file**: `cedar_instructions_updated.md` (I just created it)

2. **Upload it to Azure Blob Storage** at the location where Cedar loads instructions from

3. **The key changes in the new script:**
   - Removed ALL examples of repeating information back
   - Added explicit "Do NOT repeat" warnings with examples
   - Changed response flow to move directly to next question
   - Kept only the final confirmation step for reading back all info

## Where to Upload

Based on the code, Cedar loads instructions from Blob Storage for each company. You'll need to upload this to:

**Container**: `voiceagentsinstructions` (or similar)
**Path**: `senior-life/instructions.md` (or wherever the current script is stored)

## Key Section Changes

### OLD (current Blob Storage script):
```
Last Name: "What's your last name?"
* Customer: "Jones" → Say: "Got it, Jones. What's your first name?"
```

### NEW (updated script):
```
Last Name: "What's your last name?"
* Customer: "Jones" → Move directly to: "What's your first name?"
* Do NOT say "Got it, Jones"
```

This pattern is applied to EVERY field collection step.

## Why This Matters

The code I deployed will help, but Cedar's behavior is primarily driven by the instructions prompt. Until you update the Blob Storage script, Cedar will continue confirming after each field because that's what the current instructions tell it to do.

## Next Steps After Upload

1. Upload the new `cedar_instructions_updated.md` to Blob Storage
2. Make a test call
3. Cedar should now move smoothly from question to question without repeating information
4. Only at the END will Cedar read back everything for final confirmation
