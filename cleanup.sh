#!/bin/bash
# Cleanup Script - Remove unnecessary files from voice-agents-platform
# Created: 2025-11-08
# Safe to delete files identified during Ch84 workspace cleanup

echo "=== Voice Agents Platform Cleanup Script ==="
echo ""
echo "This script will DELETE the following files:"
echo ""

# Define files to delete
FILES_TO_DELETE=(
    # Troubleshooting docs
    "DEBUG_PERMISSIONS.md"
    "FIX_PERMISSIONS_CORRECT_SP.md"
    "GRANT_STORAGE_PERMISSIONS.md"
    "ENABLE_BLOB_VERSIONING.md"
    "VERIFY_PERMISSIONS.md"

    # Manual upload scripts
    "upload_cedar_v2_improved.py"
    "upload_sarah_instructions.py"

    # Cedar instruction files (deprecated - only using Sarah now)
    "cedar_instructions.md"
    "cedar_instructions_enhanced.md"
    "cedar_instructions_realtime.md"
    "cedar_instructions_realtime_v2_enhanced.md"
    "cedar_instructions_realtime_v2_improved.md"
    "cedar_instructions_realtime_v3_json_states.md"
    "cedar_instructions_SSML.md"
    "cedar_instructions_updated.md"

    # Analysis/optimization files
    "optimize_sarah_prompt.py"
    "prompt_analysis.ipynb"
    "Optimize_Prompts.ipynb"
    "prompt_analysis_output.txt"
    "sarah_prompt_analysis_results.json"
    "sarah_prompt_optimization_results.json"

    # Test/temporary files
    "latest-call-ai.wav"
    "latest-call-caller.wav"
    "latest-call-transcript.json"
    "nul"
)

# Directories to delete
DIRS_TO_DELETE=(
    "voice-agents-platform"
    "azure-voice-change-agent"
)

# Display files
echo "FILES:"
for file in "${FILES_TO_DELETE[@]}"; do
    if [ -f "$file" ]; then
        echo "  - $file"
    else
        echo "  - $file (not found, will skip)"
    fi
done

echo ""
echo "DIRECTORIES:"
for dir in "${DIRS_TO_DELETE[@]}"; do
    if [ -d "$dir" ]; then
        echo "  - $dir/"
    else
        echo "  - $dir/ (not found, will skip)"
    fi
done

echo ""
echo "WARNING: This action cannot be undone!"
echo ""

# Ask for confirmation
read -p "Type 'DELETE' to confirm deletion (or anything else to cancel): " confirmation

if [ "$confirmation" = "DELETE" ]; then
    echo ""
    echo "Deleting files..."

    deleted_count=0
    skipped_count=0

    # Delete files
    for file in "${FILES_TO_DELETE[@]}"; do
        if [ -f "$file" ]; then
            if rm "$file" 2>/dev/null; then
                echo "  ✓ Deleted: $file"
                ((deleted_count++))
            else
                echo "  ✗ Failed to delete: $file"
            fi
        else
            ((skipped_count++))
        fi
    done

    # Delete directories
    for dir in "${DIRS_TO_DELETE[@]}"; do
        if [ -d "$dir" ]; then
            if rm -rf "$dir" 2>/dev/null; then
                echo "  ✓ Deleted: $dir/"
                ((deleted_count++))
            else
                echo "  ✗ Failed to delete: $dir/"
            fi
        else
            ((skipped_count++))
        fi
    done

    echo ""
    echo "=== Cleanup Complete ==="
    echo "Deleted: $deleted_count items"
    echo "Skipped: $skipped_count items (not found)"

else
    echo ""
    echo "Cleanup cancelled. No files were deleted."
fi
