import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SETTINGS_MERGE

sys.path.insert(0, str(SETTINGS_MERGE.parent))
import settings_merge as sm  # noqa: E402

GUARD_PATH = "/home/u/.claude/hooks/sdlc-agent/guard.py"


class SettingsMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "settings.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self):
        return sm.main(["install", "--settings", str(self.path), "--python", "/usr/bin/python3", "--hook", GUARD_PATH])

    def uninstall(self):
        return sm.main(["uninstall", "--settings", str(self.path)])

    def load(self):
        return json.loads(self.path.read_text())

    def ours(self, data):
        return [h for g in data.get("hooks", {}).get("PreToolUse", []) for h in g["hooks"] if sm.is_ours(h)]

    def test_install_into_missing_file(self):
        self.assertEqual(self.install(), 0)
        hooks = self.ours(self.load())
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["command"], f'"/usr/bin/python3" "{GUARD_PATH}"')

    def test_preserves_other_settings_and_round_trips(self):
        original = {
            "model": "opus",
            "permissions": {"allow": ["Bash(npm test)"]},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}],
                "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
            },
        }
        self.path.write_text(json.dumps(original))
        self.install()
        after = self.load()
        self.assertEqual(after["model"], "opus")
        self.assertEqual(len(after["hooks"]["PreToolUse"]), 2)
        self.assertEqual(after["hooks"]["Stop"], original["hooks"]["Stop"])
        self.uninstall()
        self.assertEqual(self.load(), original)

    def test_idempotent(self):
        self.install()
        self.install()
        self.assertEqual(len(self.ours(self.load())), 1)

    def test_backup_written(self):
        self.path.write_text("{}")
        self.install()
        self.assertTrue(list(self.tmp.glob("settings.json.sdlc-agent-backup-*")))

    def test_invalid_json_is_left_alone(self):
        self.path.write_text("{ not json")
        self.assertEqual(self.install(), 1)
        self.assertEqual(self.path.read_text(), "{ not json")

    def test_windows_paths_normalised(self):
        cmd = sm.hook_command("C:\\Python312\\python.exe", "C:\\Users\\u\\.claude\\hooks\\sdlc-agent\\guard.py")
        self.assertEqual(cmd, '"C:/Python312/python.exe" "C:/Users/u/.claude/hooks/sdlc-agent/guard.py"')
        self.assertTrue(sm.is_ours({"command": cmd}))

    def test_uninstall_without_file_is_noop(self):
        self.assertEqual(self.uninstall(), 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
