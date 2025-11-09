# Cleanup Script - Remove unnecessary files from voice-agents-platform
# Created: 2025-11-08
# Safe to delete files identified during Ch84 workspace cleanup

Write-Host "=== Voice Agents Platform Cleanup Script ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script will DELETE the following files:" -ForegroundColor Yellow
Write-Host ""

# Define files to delete
$filesToDelete = @(
    # Troubleshooting docs
    "DEBUG_PERMISSIONS.md",
    "FIX_PERMISSIONS_CORRECT_SP.md",
    "GRANT_STORAGE_PERMISSIONS.md",
    "ENABLE_BLOB_VERSIONING.md",
    "VERIFY_PERMISSIONS.md",

    # Manual upload scripts
    "upload_cedar_v2_improved.py",
    "upload_sarah_instructions.py",

    # Cedar instruction files (deprecated - only using Sarah now)
    "cedar_instructions.md",
    "cedar_instructions_enhanced.md",
    "cedar_instructions_realtime.md",
    "cedar_instructions_realtime_v2_enhanced.md",
    "cedar_instructions_realtime_v2_improved.md",
    "cedar_instructions_realtime_v3_json_states.md",
    "cedar_instructions_SSML.md",
    "cedar_instructions_updated.md",

    # Analysis/optimization files
    "optimize_sarah_prompt.py",
    "prompt_analysis.ipynb",
    "Optimize_Prompts.ipynb",
    "prompt_analysis_output.txt",
    "sarah_prompt_analysis_results.json",
    "sarah_prompt_optimization_results.json",

    # Test/temporary files
    "latest-call-ai.wav",
    "latest-call-caller.wav",
    "latest-call-transcript.json",
    "nul"
)

# Directories to delete
$dirsToDelete = @(
    "voice-agents-platform",
    "azure-voice-change-agent"
)

# Display files
Write-Host "FILES:" -ForegroundColor Yellow
foreach ($file in $filesToDelete) {
    if (Test-Path $file) {
        Write-Host "  - $file" -ForegroundColor White
    } else {
        Write-Host "  - $file (not found, will skip)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "DIRECTORIES:" -ForegroundColor Yellow
foreach ($dir in $dirsToDelete) {
    if (Test-Path $dir) {
        Write-Host "  - $dir\" -ForegroundColor White
    } else {
        Write-Host "  - $dir\ (not found, will skip)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "WARNING: This action cannot be undone!" -ForegroundColor Red
Write-Host ""

# Ask for confirmation
$confirmation = Read-Host "Type 'DELETE' to confirm deletion (or anything else to cancel)"

if ($confirmation -eq "DELETE") {
    Write-Host ""
    Write-Host "Deleting files..." -ForegroundColor Green

    $deletedCount = 0
    $skippedCount = 0

    # Delete files
    foreach ($file in $filesToDelete) {
        if (Test-Path $file) {
            try {
                Remove-Item $file -Force
                Write-Host "  ✓ Deleted: $file" -ForegroundColor Green
                $deletedCount++
            } catch {
                Write-Host "  ✗ Failed to delete: $file" -ForegroundColor Red
            }
        } else {
            $skippedCount++
        }
    }

    # Delete directories
    foreach ($dir in $dirsToDelete) {
        if (Test-Path $dir) {
            try {
                Remove-Item $dir -Recurse -Force
                Write-Host "  ✓ Deleted: $dir\" -ForegroundColor Green
                $deletedCount++
            } catch {
                Write-Host "  ✗ Failed to delete: $dir\" -ForegroundColor Red
            }
        } else {
            $skippedCount++
        }
    }

    Write-Host ""
    Write-Host "=== Cleanup Complete ===" -ForegroundColor Cyan
    Write-Host "Deleted: $deletedCount items" -ForegroundColor Green
    Write-Host "Skipped: $skippedCount items (not found)" -ForegroundColor Gray

} else {
    Write-Host ""
    Write-Host "Cleanup cancelled. No files were deleted." -ForegroundColor Yellow
}
