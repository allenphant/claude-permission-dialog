import sys
import io
import json
import os
import ctypes
import fnmatch

sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor

ALLOWLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "permission_allowlist.json")

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
    try:
        with open(ALLOWLIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_allowlist(data):
    with open(ALLOWLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_similar_pattern(tool, inp):
    if tool == "Bash":
        cmd = inp.get("command", "").strip()
        if not cmd:
            return "Bash(*)"
        first = os.path.basename(cmd.split()[0])
        return f"Bash({first} *)"
    elif tool in ("Edit", "Write", "MultiEdit"):
        if tool == "MultiEdit":
            edits = inp.get("edits", [])
            paths = [e.get("file_path", "") for e in edits if e.get("file_path")]
        else:
            p = inp.get("file_path", "")
            paths = [p] if p else []
        if paths:
            common_dir = os.path.dirname(paths[0]).replace("\\", "/")
            return f"{tool}({common_dir}/*)"
        return f"{tool}(*)"
    return f"{tool}(*)"


def is_allowed(tool, inp):
    for pattern, enabled in load_allowlist().items():
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
            cmd = inp.get("command", "").replace("\\", "/")
            if fnmatch.fnmatch(cmd, pat_arg):
                return True
        elif tool in ("Edit", "Write", "MultiEdit"):
            path = inp.get("file_path", "").replace("\\", "/")
            if fnmatch.fnmatch(path, pat_arg):
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

        self._btn_labels = [
            "Yes",
            f"Yes, and don't ask again for {self._pattern}",
            "No",
        ]
        self._btn_styles = [
            base_btn_style + f"QPushButton:hover, QPushButton:focus {{ color: {GREEN}; background: {GREEN}18; outline: none; }}",
            base_btn_style + f"QPushButton:hover, QPushButton:focus {{ color: {YELLOW}; background: {YELLOW}18; outline: none; }}",
            base_btn_style + f"QPushButton:hover, QPushButton:focus {{ color: {RED}; background: {RED}18; outline: none; }}",
        ]
        btn_actions = [self._allow, self._allow_similar, self._deny]

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
        data = load_allowlist()
        data[self._pattern] = True
        save_allowlist(data)
        self.result_action = "allow"
        self.accept()


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "Unknown")
    inp  = data.get("tool_input", {})
    cwd  = data.get("cwd") or os.getcwd()

    if is_allowed(tool, inp):
        sys.exit(0)

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
        sys.exit(0)
    else:
        print(json.dumps({"reason": "Denied by user"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
