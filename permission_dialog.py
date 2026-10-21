import sys
import io
import json
import os
import re
import subprocess
import ctypes

# Claude Code blocks a tool only when a PreToolUse hook exits with code 2; any other exit code
# (a crash, a missing module, a timeout) lets the tool run. This script is the only gate once
# install.ps1 has put Bash(*), Edit(*) ... into permissions.allow, so everything below fails
# CLOSED: any problem ends in exit code 2 with a reason on stderr.
try:
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QLabel,
        QTextEdit, QPushButton, QFrame
    )
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont, QPalette, QColor
    QT_AVAILABLE = True
except ImportError:  # the hook then denies; the logic below stays importable for tests
    QT_AVAILABLE = False
    QDialog = object

ALLOWLIST_PATH = os.environ.get("PERMISSION_DIALOG_ALLOWLIST") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "permission_allowlist.json")

# How long one dialog may wait for an answer before the request is denied. install.ps1 sets the
# hook's own timeout above this, so the tool is never released by the engine's timeout.
DIALOG_TIMEOUT_S = int(os.environ.get("PERMISSION_DIALOG_TIMEOUT_S") or 3000)

# ── Colours ────────────────────────────────────────────────────
BG       = "#0D1117"
BG_INPUT = "#161B22"
BORDER   = "#30363D"
TEXT     = "#E6EDF3"
TEXT_DIM = "#8B949E"
GREEN    = "#3FB950"
YELLOW   = "#D29922"
RED      = "#F85149"
BLUE     = "#58A6FF"

TOOL_COLORS = {
    "Bash":      RED,
    "Edit":      YELLOW,
    "Write":     YELLOW,
    "MultiEdit": YELLOW,
}

TOOL_ICONS = {
    "Bash":      "⚡",
    "Edit":      "✏",
    "Write":     "▶",
    "MultiEdit": "▶",
}


def load_allowlist():
    """The saved rules as {pattern: bool}. Anything that is not a JSON object means no rules."""
    try:
        with open(ALLOWLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v is True for k, v in data.items() if isinstance(k, str)}


def save_allowlist(data):
    # write beside, then replace: a crash cannot leave half a file
    tmp = ALLOWLIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, ALLOWLIST_PATH)


# A command is only matched by a saved rule when it is ONE simple command: these characters start a
# second command, redirect output or substitute one (; & | newline ` $( > <).
_SHELL_META = re.compile(r"[;&|\n\r`<>]|\$\(")

# First words that never get a "don't ask again" rule: shells and interpreters run anything
# after them, `cd x && ...` and friends chain, and these tools delete, fetch or reach other machines.
RISKY_FIRST_WORDS = frozenset("""
cd pushd popd sh bash zsh dash fish ksh csh tcsh cmd powershell pwsh python python3 py node deno bun
ruby perl php lua osascript curl wget ssh scp sftp rsync nc ncat rm rmdir del erase rd sudo su doas
eval exec env xargs find awk gawk sed make npx pip pip3 pipx docker kubectl git-shell start explorer
reg regedit schtasks sc taskkill wmic mshta rundll32 certutil bitsadmin msiexec
""".split())


def has_shell_meta(command):
    return bool(_SHELL_META.search(command))


def first_word(command):
    parts = command.strip().split()
    return parts[0] if parts else ""


def bash_pattern(command):
    """`Bash(word *)` for a simple command, or None when a saved rule would be unsafe."""
    command = command.strip()
    if not command or has_shell_meta(command):
        return None
    word = first_word(command)
    if re.search(r"[\\/=*?\[\]\"'$%^(){}~!]", word):  # a path, an env assignment, a glob or a quote
        return None
    if word.lower().removesuffix(".exe") in RISKY_FIRST_WORDS:
        return None
    return f"Bash({word} *)"


def tool_paths(tool, inp):
    """Every file path a file tool call names (MultiEdit may name one at the top and one per edit)."""
    paths = []
    top = inp.get("file_path")
    if isinstance(top, str) and top:
        paths.append(top)
    if tool == "MultiEdit":
        for e in inp.get("edits") or []:
            if isinstance(e, dict) and isinstance(e.get("file_path"), str) and e["file_path"]:
                paths.append(e["file_path"])
    return paths


def canon_path(path):
    """A comparable absolute path: separators unified, `..` and symlinks resolved, case folded on Windows."""
    return os.path.normcase(os.path.realpath(path.replace("\\", "/"))).replace("\\", "/")


def protected_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~/.claude")
    names = [ALLOWLIST_PATH, os.path.abspath(__file__),
             os.path.join(home, "settings.json"), os.path.join(home, "settings.local.json")]
    names += [os.path.join(here, n) for n in ("permission_allowlist.json",)]
    return {canon_path(n) for n in names}


def file_pattern(tool, inp):
    """`Tool(<dir>/*)` for the directory of the first path, or None when there is no path to build one from."""
    paths = tool_paths(tool, inp)
    if not paths:
        return None
    directory = os.path.dirname(paths[0].replace("\\", "/"))
    if not directory:
        return None
    return f"{tool}({directory}/*)"


def get_similar_pattern(tool, inp):
    """The "don't ask again" rule offered for this request, or None when none is safe to offer."""
    if tool == "Bash":
        return bash_pattern(inp.get("command", "") if isinstance(inp.get("command", ""), str) else "")
    if tool in ("Edit", "Write", "MultiEdit"):
        return file_pattern(tool, inp)
    return None


def _inside(directory, path):
    d = canon_path(directory)
    p = canon_path(path)
    return p.startswith(d.rstrip("/") + "/")


def is_allowed(tool, inp):
    """True only for a request a saved rule covers completely. Any doubt means ask."""
    if not isinstance(inp, dict):
        return False
    rules = load_allowlist()
    for pattern, enabled in rules.items():
        if not enabled:
            continue
        if "(" not in pattern:
            if pattern == tool:
                return True
            continue
        pat_tool, pat_arg = pattern.rstrip(")").split("(", 1)
        if pat_tool != tool:
            continue
        if tool == "Bash":
            command = inp.get("command", "")
            if not isinstance(command, str) or not command.strip() or has_shell_meta(command):
                continue
            # the rule is "<word> *": the same first word, then anything that is still one simple command
            if pat_arg.endswith(" *") and "*" not in pat_arg[:-2] and first_word(command) == pat_arg[:-2] \
                    and command.strip().startswith(pat_arg[:-1]):
                return True
        elif tool in ("Edit", "Write", "MultiEdit"):
            if not pat_arg.endswith("/*"):
                continue
            paths = tool_paths(tool, inp)
            if not paths:
                continue
            blocked = protected_paths()
            if any(canon_path(p) in blocked for p in paths):
                continue
            if all(_inside(pat_arg[:-2], p) for p in paths):
                return True
    return False


def force_foreground(hwnd):
    try:
        VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.BringWindowToTop(hwnd)
        ctypes.windll.user32.FlashWindow(hwnd, True)
    except Exception:
        pass


class PermissionDialog(QDialog):
    def __init__(self, tool, inp, cwd):
        super().__init__()
        self.result_action = "deny"
        self._pattern = get_similar_pattern(tool, inp)
        self._accent  = TOOL_COLORS.get(tool, BLUE)
        self._build(tool, inp, cwd)

        self._timer = QTimer()
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(lambda: force_foreground(int(self.winId())))
        self._timer.start()

    def _build(self, tool, inp, cwd):
        accent = self._accent
        icon   = TOOL_ICONS.get(tool, "·")

        self.setWindowTitle("claude · permission")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setMinimumWidth(540)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(f"background: {BG}; color: {TEXT};")

        mono = QFont()
        mono.setFamilies(["Consolas", "Courier New"])
        mono.setPointSize(10)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────
        from PyQt6.QtWidgets import QHBoxLayout as _HBox
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background: #161B22; border-bottom: 1px solid {BORDER};")
        hbl = _HBox(header_frame)
        hbl.setContentsMargins(14, 8, 14, 8)

        tool_lbl = QLabel(f"{icon}  {tool}")
        tool_lbl.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        tool_lbl.setStyleSheet(f"color: {accent}; background: transparent;")
        hbl.addWidget(tool_lbl)

        hbl.addStretch()

        project = os.path.basename(cwd.rstrip("/\\")) if cwd else "~"
        path_lbl = QLabel(f"📁 {project}  ")
        path_lbl.setFont(QFont("Consolas", 9))
        path_lbl.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        path_lbl.setToolTip(cwd)
        hbl.addWidget(path_lbl)

        root.addWidget(header_frame)

        # ── Content ───────────────────────────────────────────────
        content = QVBoxLayout()
        content.setContentsMargins(14, 12, 14, 12)
        content.setSpacing(6)

        for key, val in inp.items():
            key_lbl = QLabel(f"  {key}")
            key_lbl.setFont(QFont("Consolas", 9))
            key_lbl.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
            content.addWidget(key_lbl)

            box = QTextEdit()
            box.setPlainText(str(val))
            box.setReadOnly(True)
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            box.setFont(mono)
            box.setStyleSheet(f"""
                QTextEdit {{
                    background: {BG_INPUT};
                    color: {TEXT};
                    border: 1px solid {BORDER};
                    border-left: 3px solid {accent};
                    padding: 5px 8px;
                    border-radius: 0;
                }}
                QScrollBar:vertical {{
                    background: {BG}; width: 6px;
                }}
                QScrollBar::handle:vertical {{
                    background: {BORDER}; border-radius: 3px; min-height: 16px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            """)
            lines = str(val).count("\n") + 1
            box.setFixedHeight(min(120, max(38, lines * 20 + 14)))
            content.addWidget(box)

        content_frame = QFrame()
        content_frame.setLayout(content)
        content_frame.setStyleSheet(f"background: {BG};")
        root.addWidget(content_frame)

        # ── Divider ───────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {BORDER};")
        root.addWidget(div)

        # ── Buttons ───────────────────────────────────────────────
        btn_area = QVBoxLayout()
        btn_area.setContentsMargins(14, 10, 14, 14)
        btn_area.setSpacing(4)

        prompt = QLabel("Do you want to allow this?")
        prompt.setFont(QFont("Consolas", 9))
        prompt.setStyleSheet(f"color: {TEXT_DIM}; background: transparent; padding-bottom: 4px;")
        btn_area.addWidget(prompt)

        base_btn_style = f"""
            QPushButton {{
                font-family: Consolas;
                font-size: 11px;
                color: {TEXT};
                background: {BG_INPUT};
                border: none;
                padding: 8px 14px;
                text-align: left;
                border-radius: 2px;
            }}
        """

        yes_style = base_btn_style + f"QPushButton:hover, QPushButton:focus {{ color: {GREEN}; background: {GREEN}18; outline: none; }}"
        similar_style = base_btn_style + f"QPushButton:hover, QPushButton:focus {{ color: {YELLOW}; background: {YELLOW}18; outline: none; }}"
        no_style = base_btn_style + f"QPushButton:hover, QPushButton:focus {{ color: {RED}; background: {RED}18; outline: none; }}"
        # No "don't ask again" when no safe rule exists (shells, interpreters, chained commands, ...)
        if self._pattern:
            self._btn_labels = ["Yes", f"Yes, and don't ask again for {self._pattern}", "No"]
            self._btn_styles = [yes_style, similar_style, no_style]
            btn_actions = [self._allow, self._allow_similar, self._deny]
        else:
            self._btn_labels = ["Yes", "No"]
            self._btn_styles = [yes_style, no_style]
            btn_actions = [self._allow, self._deny]

        self._buttons = []
        for i, (label, style, action) in enumerate(zip(self._btn_labels, self._btn_styles, btn_actions)):
            btn = QPushButton(f"  {label}")
            btn.setStyleSheet(style)
            btn.clicked.connect(action)
            # track focus via mouse click
            btn.installEventFilter(self)
            btn._btn_idx = i
            btn_area.addWidget(btn)
            self._buttons.append(btn)

        btn_frame = QFrame()
        btn_frame.setLayout(btn_area)
        btn_frame.setStyleSheet(f"background: #161B22;")
        root.addWidget(btn_frame)

        self._btn_idx = 0
        self._update_focus_indicator()

        self._buttons[0].setDefault(True)
        self._buttons[0].setFocus()

        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )

    def _update_focus_indicator(self):
        for i, btn in enumerate(self._buttons):
            prefix = "> " if i == self._btn_idx else "  "
            btn.setText(f"{prefix}{self._btn_labels[i]}")

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent as _QEvent
        if event.type() == _QEvent.Type.FocusIn and hasattr(obj, "_btn_idx"):
            self._btn_idx = obj._btn_idx
            self._update_focus_indicator()
        return False

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self._deny()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self._btn_idx = (self._btn_idx + 1) % len(self._buttons)
            self._buttons[self._btn_idx].setFocus()
            self._update_focus_indicator()
        elif key == Qt.Key.Key_Up:
            self._btn_idx = (self._btn_idx - 1) % len(self._buttons)
            self._buttons[self._btn_idx].setFocus()
            self._update_focus_indicator()

    def _allow(self):
        self._timer.stop()
        self.result_action = "allow"
        self.accept()

    def _deny(self):
        self._timer.stop()
        self.result_action = "deny"
        self.reject()

    def _allow_similar(self):
        self._timer.stop()
        if not self._pattern:
            self._deny()
            return
        data = load_allowlist()
        data[self._pattern] = True
        save_allowlist(data)
        self.result_action = "allow"
        self.accept()


def allow():
    """Approve through the hook's own decision, so no blanket `Bash(*)` rule is needed in permissions.allow."""
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "approved in the permission dialog or by a saved rule",
    }}) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def deny(reason):
    """Block the tool: exit code 2 is the only code that does, and stderr goes back to the model."""
    sys.stderr.write(f"Denied: {reason}\n")
    sys.stderr.flush()
    sys.exit(2)


def show_dialog(data):
    """Runs in the child process: the dialog itself. Prints ALLOW and exits 0 only on an explicit yes."""
    if not QT_AVAILABLE:
        deny("PyQt6 is not installed, so the permission dialog cannot be shown (pip install PyQt6)")
    tool = data.get("tool_name", "Unknown")
    inp = data.get("tool_input", {})
    cwd = data.get("cwd") or os.getcwd()
    if not isinstance(inp, dict):
        inp = {}

    app = QApplication(sys.argv)

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,     QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    app.setPalette(pal)

    dlg = PermissionDialog(tool, inp, cwd)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    QTimer.singleShot(100, lambda: (force_foreground(int(dlg.winId())), dlg.activateWindow()))

    app.exec()

    if dlg.result_action == "allow":
        sys.stdout.write("ALLOW\n")
        sys.stdout.flush()
        sys.exit(0)
    deny("Denied by user")


def run_dialog(payload, timeout_s=None, child_cmd=None):
    """Show the dialog in a child process and return True only if the user said yes.

    A child so that a crash of the GUI (any exit code, even a segfault) cannot be mistaken for
    approval, and so that nobody answering for `timeout_s` seconds ends in a denial rather than
    in the engine's own hook timeout releasing the tool.
    """
    timeout_s = DIALOG_TIMEOUT_S if timeout_s is None else timeout_s
    cmd = child_cmd or [sys.executable, os.path.abspath(__file__), "--dialog"]
    try:
        run = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                             encoding="utf-8", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False, f"nobody answered within {timeout_s} s"
    except Exception as e:  # cannot even start the dialog
        return False, f"the dialog could not start ({type(e).__name__})"
    if run.returncode == 0 and run.stdout.strip() == "ALLOW":
        return True, ""
    reason = (run.stderr or "").strip().splitlines()
    return False, reason[-1] if reason else f"the dialog ended without approval (exit {run.returncode})"


def main():
    try:
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
        raw = sys.stdin.read()
        if len(sys.argv) > 1 and sys.argv[1] == "--dialog":
            show_dialog(json.loads(raw))
            return
        data = json.loads(raw)
        if not isinstance(data, dict):
            deny("the hook input is not a JSON object")
        tool = data.get("tool_name", "Unknown")
        inp = data.get("tool_input", {})
        if is_allowed(tool, inp):
            allow()
        ok, reason = run_dialog(raw)
        if ok:
            allow()
        deny(reason or "Denied by user")
    except SystemExit:
        raise
    except BaseException as e:  # anything unexpected is a denial, never a pass
        deny(f"permission dialog error ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
