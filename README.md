# claude-permission-dialog

A terminal-style permission dialog for [Claude Code](https://claude.ai/code) on Windows.

Replaces the built-in terminal permission prompt with a floating PyQt6 window — keyboard-driven, dark-themed, and project-aware. Also plays a 🎉 sound when Claude finishes a task.

![screenshot placeholder]

## Features

- **Dark terminal UI** — Consolas font, colour-coded by tool type
- **Project-aware** — shows which folder the request is coming from
- **Keyboard navigation** — `↑ ↓` to move, `Enter` to confirm, `Esc` to deny
- **`>` cursor indicator** — highlights the currently selected option
- **Allow Similar** — skip future dialogs matching the same pattern (e.g. `Bash(git *)`)
- **Re-flashes every 30s** if ignored — never silently times out
- **Tada sound** — plays `tada.wav` when Claude finishes a task

## Requirements

- Windows 10 / 11
- Python 3.10+
- Claude Code CLI

## Install

```powershell
git clone https://github.com/YOUR_USERNAME/claude-permission-dialog
cd claude-permission-dialog
powershell -ExecutionPolicy Bypass -File install.ps1
```

Restart Claude Code after installing.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` `↓` | Move between options |
| `Tab` | Move down |
| `Enter` / `Space` | Confirm selected option |
| `Esc` | Deny |

## Options

| Option | Description |
|--------|-------------|
| **Yes** | Allow this one request |
| **Yes, and don't ask again for `[pattern]`** | Save pattern to allowlist, skip future matching requests |
| **No** | Deny the request |

## Allow Similar

Selecting the second option saves a pattern like `Bash(git *)` or `Edit(/path/to/project/*)` to `~/.claude/permission_allowlist.json`. Future requests matching that pattern skip the dialog entirely.

To reset the allowlist:

```powershell
echo {} > $env:USERPROFILE\.claude\permission_allowlist.json
```

## Hooks Installed

| Event | Action |
|-------|--------|
| `PreToolUse` (Bash, Edit, Write, MultiEdit) | Shows permission dialog |
| `Stop` | Plays `tada.wav` when Claude finishes |

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

Removes both hooks, the script, and the allowlist from `~/.claude/`.

## How It Works

```
Claude wants to run Bash
  → PreToolUse hook fires
    → permission_dialog.py reads tool JSON from stdin
      → dialog appears
        → user presses Enter (allow) or Esc (deny)
          → exit 0 (allow) or exit 2 (deny) returned to Claude Code

Claude finishes task
  → Stop hook fires
    → tada.wav plays
```
