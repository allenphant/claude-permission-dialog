# claude-permission-dialog installer
# Run with: powershell -ExecutionPolicy Bypass -File install.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SCRIPT_DIR   = Split-Path -Parent $MyInvocation.MyCommand.Path
$CLAUDE_DIR   = "$env:USERPROFILE\.claude"
$SETTINGS     = "$CLAUDE_DIR\settings.json"
$DEST_SCRIPT  = "$CLAUDE_DIR\permission_dialog.py"
$HOOK_COMMAND = "python $($DEST_SCRIPT -replace '\\', '/')"
$TADA_COMMAND = "powershell.exe -Command `"(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\tada.wav').PlaySync()`""

Write-Host ""
Write-Host "claude-permission-dialog installer" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python found" -ForegroundColor Green

# Check Claude Code
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Claude Code CLI not found. Install from https://claude.ai/code" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Claude Code found" -ForegroundColor Green

# Install PyQt6
Write-Host ""
Write-Host "Installing PyQt6..." -ForegroundColor Yellow
pip install PyQt6 --quiet
Write-Host "[OK] PyQt6 installed" -ForegroundColor Green

# Copy script
Write-Host ""
Write-Host "Copying permission_dialog.py to $CLAUDE_DIR ..." -ForegroundColor Yellow
Copy-Item "$SCRIPT_DIR\permission_dialog.py" $DEST_SCRIPT -Force
Write-Host "[OK] Script copied" -ForegroundColor Green

# Update settings.json
Write-Host ""
Write-Host "Updating ~/.claude/settings.json ..." -ForegroundColor Yellow

if (-not (Test-Path $SETTINGS)) {
    '{}' | Set-Content $SETTINGS -Encoding UTF8
}

$settings = Get-Content $SETTINGS -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not $settings.hooks) {
    $settings | Add-Member -NotePropertyName hooks -NotePropertyValue ([PSCustomObject]@{})
}

# ── PreToolUse hook (permission dialog) ──────────────────────────
$hookEntry = [PSCustomObject]@{
    matcher = "Bash|Edit|Write|MultiEdit"
    hooks   = @(
        [PSCustomObject]@{ type = "command"; command = $HOOK_COMMAND }
    )
}

if (-not $settings.hooks.PreToolUse) {
    $settings.hooks | Add-Member -NotePropertyName PreToolUse -NotePropertyValue @()
}

# Remove existing entries to avoid duplicates
$settings.hooks.PreToolUse = @($settings.hooks.PreToolUse | Where-Object {
    $_.hooks -and ($_.hooks | Where-Object { $_.command -notlike "*permission_dialog*" })
})
$settings.hooks.PreToolUse += $hookEntry

# ── Stop hook (tada sound) ────────────────────────────────────────
$tadaEntry = [PSCustomObject]@{
    hooks = @(
        [PSCustomObject]@{ type = "command"; command = $TADA_COMMAND }
    )
}

if (-not $settings.hooks.Stop) {
    $settings.hooks | Add-Member -NotePropertyName Stop -NotePropertyValue @()
}

# Remove existing tada entries to avoid duplicates
$settings.hooks.Stop = @($settings.hooks.Stop | Where-Object {
    $_.hooks -and ($_.hooks | Where-Object { $_.command -notlike "*tada*" })
})
$settings.hooks.Stop += $tadaEntry

# ── permissions.allow (suppress Claude's own prompt) ─────────────
$allowRules = @("Bash(*)", "Edit(*)", "Write(*)", "MultiEdit(*)")
if (-not $settings.permissions) {
    $settings | Add-Member -NotePropertyName permissions -NotePropertyValue (
        [PSCustomObject]@{ allow = $allowRules }
    )
} else {
    if (-not $settings.permissions.allow) {
        $settings.permissions | Add-Member -NotePropertyName allow -NotePropertyValue $allowRules
    } else {
        foreach ($rule in $allowRules) {
            if ($settings.permissions.allow -notcontains $rule) {
                $settings.permissions.allow += $rule
            }
        }
    }
}

$settings | ConvertTo-Json -Depth 10 | Set-Content $SETTINGS -Encoding UTF8
Write-Host "[OK] settings.json updated" -ForegroundColor Green

Write-Host ""
Write-Host "Done! Restart Claude Code for changes to take effect." -ForegroundColor Cyan
Write-Host ""
Write-Host "Keyboard shortcuts:" -ForegroundColor White
Write-Host "  Up / Down     move between options"
Write-Host "  Enter / Space confirm"
Write-Host "  Escape        deny"
Write-Host ""
