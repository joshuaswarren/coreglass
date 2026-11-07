"""The daily ledger's commit step: changes commit and push; a clean tree is a success.

Drives the installed commit-ledger.sh (the same script daily.sh calls) against a
throwaway git repo with a bare origin, so both the push path and the
nothing-changed path are exercised end to end.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

COMMIT_SH = Path(
    os.environ.get(
        "CG_COMMIT_LEDGER_SH",
        Path.home() / ".local/share/coreglass/ledger/commit-ledger.sh",
    )
)

LEDGER_DATE = "2026-11-07"


def git(repo, *args):
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {out.stderr}")
    return out.stdout.strip()


@unittest.skipUnless(COMMIT_SH.exists(), "commit-ledger.sh is not installed on this host")
class TestLedgerCommit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.origin = tmp / "origin.git"
        self.repo = tmp / "repo"
        subprocess.run(
            ["git", "init", "--bare", "-q", "-b", "main", str(self.origin)], check=True
        )
        clone = subprocess.run(
            ["git", "clone", "-q", str(self.origin), str(self.repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(clone.returncode, 0, clone.stderr)
        # The CT's git wrapper enforces this identity; use it so the seed commit passes.
        mandated = "816217+joshuaswarren@users.noreply.github.com"
        git(self.repo, "config", "user.email", mandated)
        git(self.repo, "config", "user.name", "coreglass ledger test")
        docs = self.repo / "docs"
        docs.mkdir()
        (docs / "LEDGER.md").write_text("day 1\n", encoding="utf-8")
        (docs / "ledger.json").write_text("{}\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "seed")
        git(self.repo, "push", "-qu", "origin", "main")

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self):
        return subprocess.run(
            ["bash", str(COMMIT_SH), str(self.repo), LEDGER_DATE],
            capture_output=True,
            text=True,
        )

    def test_changed_docs_commit_and_push(self):
        (self.repo / "docs" / "LEDGER.md").write_text("day 2\n", encoding="utf-8")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("committed", result.stdout)
        sha = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), sha)
        self.assertNotEqual(sha, git(self.repo, "rev-parse", "main~1"))
        subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin"], check=True)
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), sha)

    def test_clean_tree_is_success(self):
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean", result.stdout)
        head_before = git(self.repo, "rev-parse", "origin/main")
        result = self.commit()  # still clean on the second call
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), head_before)


if __name__ == "__main__":
    unittest.main()
