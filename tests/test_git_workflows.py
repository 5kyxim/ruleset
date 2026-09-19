import datetime
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "main"
        self.remote = self.base / "remote.git"
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.run_command(["git", "init", "--bare", str(self.remote)], self.base)
        self.run_command(["git", "init", "-b", "main", str(self.repo)], self.base)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / ".github").mkdir()
        (self.repo / ".github" / "workflow-placeholder").write_text("test\n")
        self.git("add", ".")
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)).isoformat()
        self.run_command(["git", "commit", "-m", "Initial"], self.repo,
                         dict(self.env, GIT_AUTHOR_DATE=old, GIT_COMMITTER_DATE=old))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "main")

    def run_command(self, command, cwd, env=None):
        return subprocess.check_output(command, cwd=cwd, env=env or self.env,
                                       text=True, stderr=subprocess.STDOUT).strip()

    def git(self, *args):
        return self.run_command(["git", *args], self.repo)

    def test_keepalive_only_after_threshold(self):
        before = self.git("rev-parse", "HEAD")
        self.run_command(["bash", str(ROOT / "scripts/keepalive.sh")], self.repo)
        after = self.git("rev-parse", "HEAD")
        self.assertNotEqual(before, after)
        self.assertEqual(self.git("diff", "--name-only", before, after), ".github/keepalive")
        self.run_command(["bash", str(ROOT / "scripts/keepalive.sh")], self.repo)
        self.assertEqual(after, self.git("rev-parse", "HEAD"))

    def test_release_create_append_and_noop(self):
        output = self.base / "output"
        output.mkdir()
        (output / "proxy.json").write_text('{"version":2,"rules":[]}\n')
        for iteration in range(3):
            if iteration == 1:
                (output / "proxy.json").unlink()
                (output / "direct.json").write_text('{"version":2,"rules":[]}\n')
            self.run_command([
                "bash", str(ROOT / "scripts/publish.sh"), str(output),
                str(self.base / f"release-{iteration}"), "a" * 40,
            ], self.repo)
            self.git("fetch", "origin", "release:refs/remotes/origin/release")
            self.assertEqual(self.git("rev-list", "--count", "origin/release"),
                             "1" if iteration == 0 else "2")
        self.assertEqual(self.git("ls-tree", "--name-only", "origin/release"), "direct.json")
        self.assertEqual(self.git("rev-list", "--count", "main"), "1")


if __name__ == "__main__":
    unittest.main()
