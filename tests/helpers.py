import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "ship" / "scripts"
GUARD = ROOT / "hooks" / "guard.py"
SETTINGS_MERGE = ROOT / "installer" / "settings_merge.py"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class TempEnvCase(unittest.TestCase):
    """Isolated SDLC_AGENT_HOME plus a throwaway git repo with an origin remote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-test-")).resolve()
        self.home = self.tmp / "agent-home"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "remote", "add", "origin", "git@github.com:acme/widgets.git")
        (self.repo / "README.md").write_text("x\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "init")
        self._old_env = os.environ.get("SDLC_AGENT_HOME")
        os.environ["SDLC_AGENT_HOME"] = str(self.home)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("SDLC_AGENT_HOME", None)
        else:
            os.environ["SDLC_AGENT_HOME"] = self._old_env
        shutil.rmtree(self.tmp, ignore_errors=True)
