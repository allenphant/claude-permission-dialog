# claude-permission-dialog uninstaller
# Run with: powershell -ExecutionPolicy Bypass -File uninstall.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$CLAUDE_DIR  = "$env:USERPROFILE\.claude"
$SETTINGS    = "$CLAUDE_DIR\settings.json"
$ALLOWLIST   = "$CLAUDE_DIR\permission_allowlist.json"
$DEST_SCRIPT = "$CLAUDE_DIR\permission_dialog.py"

Write-Host ""
Write-Host "claude-permission-dialog uninstaller" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $SETTINGS) {
    $settings = Get-Content $SETTINGS -Raw -Encoding UTF8 | ConvertFrom-Json

    # Remove PreToolUse permission_dialog hook
    if ($settings.hooks -and $settings.hooks.PreToolUse) {
        $settings.hooks.PreToolUse = @($settings.hooks.PreToolUse | Where-Object {
            -not ($_.hooks | Where-Object { $_.command -like "*permission_dialog*" })
        })
    }

    # Remove Stop tada hook
    if ($settings.hooks -and $settings.hooks.Stop) {
        $settings.hooks.Stop = @($settings.hooks.Stop | Where-Object {
            -not ($_.hooks | Where-Object { $_.command -like "*tada*" })
        })
    }

    # Remove permissions.allow rules added by installer
    $rulesToRemove = @("Bash(*)", "Edit(*)", "Write(*)", "MultiEdit(*)")
    if ($settings.permissions -and $settings.permissions.allow) {
        $settings.permissions.allow = @($settings.permissions.allow | Where-Object {
            $rulesToRemove -notcontains $_
        })
    }

    $settings | ConvertTo-Json -Depth 10 | Set-Content $SETTINGS -Encoding UTF8
    Write-Host "[OK] settings.json restored" -ForegroundColor Green
}

if (Test-Path $DEST_SCRIPT) { Remove-Item $DEST_SCRIPT; Write-Host "[OK] permission_dialog.py removed" -ForegroundColor Green }
if (Test-Path $ALLOWLIST)   { Remove-Item $ALLOWLIST;   Write-Host "[OK] allowlist removed" -ForegroundColor Green }

Write-Host ""
Write-Host "Done. Restart Claude Code to apply." -ForegroundColor Cyan
Write-Host ""
