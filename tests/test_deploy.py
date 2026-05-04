"""Unit tests for `harness deploy` (Vercel) — subprocess fully mocked.

We don't want tests to actually call out to npx vercel, so cmd_deploy
accepts an `_runner` injection point on its args namespace. Live deploys
are out-of-scope here (they're verified manually).
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

from harness import cli
from harness.core import ResearchRepo, ThesisNode


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _seed_repo(path: Path) -> ResearchRepo:
    repo = ResearchRepo(path)
    repo.init()
    repo.commit_node(ThesisNode(claim="r", type="root"))
    repo.commit_node(
        ThesisNode(claim="n", type="narrow", prediction="p", evidence="e",
                   status="supported")
    )
    return repo


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deploy_test_"))
        self.repo = _seed_repo(self.tmp / "repo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ns(self, **overrides):
        defaults = dict(
            repo=str(self.repo.path),
            slug=None,
            project="testproj",
            scope=None,
            token="vcp_FAKE",
            title=None,
            subtitle=None,
            refresh=30,
            npx="npx",
            quiet=False,
        )
        defaults.update(overrides)
        ns = argparse.Namespace(**defaults)
        return ns

    def _run(self, args, runner):
        args._runner = runner
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_deploy(args)
        return rc, out.getvalue(), err.getvalue()

    def test_command_shape(self):
        captured: List[List[str]] = []

        def runner(cmd, **kw):
            captured.append(cmd)
            return _FakeCompleted(0, "Deployment ready https://testproj.vercel.app", "")

        rc, _, _ = self._run(self._ns(), runner)
        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        cmd = captured[0]
        self.assertIn("vercel@latest", " ".join(cmd))
        self.assertIn("--prod", cmd)
        self.assertIn("--yes", cmd)
        self.assertIn("--name", cmd)
        self.assertEqual(cmd[cmd.index("--name") + 1], "testproj")
        self.assertEqual(cmd[cmd.index("--token") + 1], "vcp_FAKE")
        self.assertNotIn("--scope", cmd)

    def test_scope_passed_through(self):
        captured: List[List[str]] = []

        def runner(cmd, **kw):
            captured.append(cmd)
            return _FakeCompleted(0, "https://testproj.vercel.app", "")

        rc, _, _ = self._run(self._ns(scope="my-team"), runner)
        self.assertEqual(rc, 0)
        cmd = captured[0]
        self.assertEqual(cmd[cmd.index("--scope") + 1], "my-team")

    def test_url_extraction(self):
        runner = MagicMock(return_value=_FakeCompleted(
            0, "noise\nDeployment ready https://testproj.vercel.app done", "")
        )
        rc, stdout, _ = self._run(self._ns(), runner)
        self.assertEqual(rc, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["url"], "https://testproj.vercel.app")
        self.assertEqual(payload["project"], "testproj")

    def test_url_fallback_when_alias_absent(self):
        runner = MagicMock(return_value=_FakeCompleted(
            0, "Deployment https://testproj-abc123-team.vercel.app ready", "")
        )
        rc, stdout, _ = self._run(self._ns(), runner)
        self.assertEqual(rc, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["url"],
                         "https://testproj-abc123-team.vercel.app")

    def test_failure_returns_error(self):
        runner = MagicMock(return_value=_FakeCompleted(
            1, "", "fatal: cannot deploy: bad scope"))
        rc, stdout, _ = self._run(self._ns(), runner)
        self.assertNotEqual(rc, 0)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("vercel deploy failed", payload["error"])
        self.assertIn("bad scope", payload["error"])

    def test_missing_token(self):
        # Stub env_lookup so VERCEL_TOKEN appears unset
        original = cli.env_lookup
        cli.env_lookup = lambda key, default=None: None
        try:
            ns = self._ns(token=None)
            rc, stdout, _ = self._run(ns, MagicMock())
            self.assertNotEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertIn("VERCEL_TOKEN", payload["error"])
        finally:
            cli.env_lookup = original


class HookInstallTests(unittest.TestCase):
    """Hooks should call `harness deploy` for vercel target, `publish` for supabase."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hook_test_"))
        self.repo = ResearchRepo(self.tmp / "repo")
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vercel_hook_calls_deploy(self):
        cli._install_hook(self.repo, slug="x", target="vercel")
        hook = (self.repo.path / ".git" / "hooks" / "post-commit").read_text()
        self.assertIn("harness.cli", hook)
        self.assertIn(" deploy ", hook)
        self.assertNotIn(" publish ", hook)

    def test_supabase_hook_calls_publish(self):
        cli._install_hook(self.repo, slug="x", target="supabase")
        hook = (self.repo.path / ".git" / "hooks" / "post-commit").read_text()
        self.assertIn(" publish ", hook)
        self.assertNotIn(" deploy ", hook)

    def test_unknown_target_rejected(self):
        with self.assertRaises(ValueError):
            cli._install_hook(self.repo, slug="x", target="bogus")


if __name__ == "__main__":
    unittest.main()
