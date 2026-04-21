"""
test_dialog.py — interactive test runner for permission_dialog.py
Usage: python test_dialog.py
"""
import subprocess
import json
import sys

SCRIPT = "C:/Users/raging/.claude/permission_dialog.py"

CASES = [
    {
        "label": "Bash — short command (git status)",
        "payload": {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "cwd": "C:/Users/raging/Desktop/Vibe_coding/claude-permission-dialog",
        },
    },
    {
        "label": "Bash — long command (grep with long path)",
        "payload": {
            "tool_name": "Bash",
            "tool_input": {
                "command": 'grep -n "export" /c/Users/raging/Desktop/Vibe_coding/Hexordle/packages/client/src/lib/'
            },
            "cwd": "C:/Users/raging/Desktop/Vibe_coding/Hexordle",
        },
    },
    {
        "label": "Edit — long file path (tests word wrap on allow-similar)",
        "payload": {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "C:/Users/raging/Desktop/Vibe_coding/Hexordle/packages/client/src/components/Game.tsx",
                "old_string": "foo",
                "new_string": "bar",
                "replace_all": False,
            },
            "cwd": "C:/Users/raging/Desktop/Vibe_coding/Hexordle",
        },
    },
    {
        "label": "Write — new file",
        "payload": {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "C:/Users/raging/Desktop/test_output.txt",
                "content": "hello world",
            },
            "cwd": "C:/Users/raging/Desktop",
        },
    },
    {
        "label": "Bash — multiline script",
        "payload": {
            "tool_name": "Bash",
            "tool_input": {
                "command": "npm install\nnpm run build\nnpm run test"
            },
            "cwd": "C:/Users/raging/Desktop/Vibe_coding/Hexordle",
        },
    },
]


def run_case(case):
    payload_str = json.dumps(case["payload"], ensure_ascii=False)
    result = subprocess.run(
        [sys.executable, SCRIPT],
        input=payload_str,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    code = result.returncode
    outcome = {0: "ALLOWED", 2: "DENIED"}.get(code, f"exit {code}")
    stderr = result.stderr.strip()
    print(f"  → {outcome}" + (f"  [stderr: {stderr}]" if stderr else ""))


def reset_allowlist():
    allowlist_path = "C:/Users/raging/.claude/permission_allowlist.json"
    with open(allowlist_path, "w", encoding="utf-8") as f:
        json.dump({}, f)
    print(f"  allowlist cleared: {allowlist_path}\n")


def main():
    print("=" * 60)
    print("  permission_dialog test runner")
    print("=" * 60)
    print()

    reset_allowlist()

    for i, case in enumerate(CASES, 1):
        print(f"[{i}/{len(CASES)}] {case['label']}")
        run_case(case)
        print()


if __name__ == "__main__":
    main()
