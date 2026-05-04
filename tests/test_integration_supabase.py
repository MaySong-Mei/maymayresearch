"""Live integration tests against the configured Supabase project.

Skipped automatically when SUPABASE_URL is not configured.

Each test uses a unique slug ("itest_<pid>_<n>") so concurrent runs do not
collide, and the test cleans up its own rows in tearDown.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from harness.core import ResearchRepo, ThesisNode
from harness.publisher import SupabasePublisher, env as env_lookup

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _have_supabase() -> bool:
    return bool(env_lookup("SUPABASE_URL") and env_lookup("SUPABASE_SERVICE_ROLE_KEY"))


def _request(url: str, method: str = "GET", key: str = "") -> tuple[int, bytes]:
    req = urllib.request.Request(url, method=method)
    if key:
        req.add_header("apikey", key)
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Prefer", "return=minimal")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@unittest.skipUnless(_have_supabase(), "SUPABASE_URL/key not set")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = env_lookup("SUPABASE_URL")
        cls.anon = env_lookup("SUPABASE_ANON_KEY")
        cls.service = env_lookup("SUPABASE_SERVICE_ROLE_KEY")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="itest_"))
        self.repo_path = self.tmp / "repo"
        self.slug = f"itest_{os.getpid()}_{int(time.time() * 1000)}"

    def tearDown(self):
        # Clean up rows for our slug
        if self.url and self.service:
            for table in ("nodes", "branches", "reviews"):
                _request(
                    f"{self.url}/rest/v1/{table}?repo=eq.{self.slug}",
                    method="DELETE",
                    key=self.service,
                )
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cli(self, *args: str, stdin: str = "") -> dict:
        result = subprocess.run(
            [sys.executable, "-m", "harness.cli", "--repo", str(self.repo_path), *args],
            cwd=PROJECT_ROOT,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(
                f"CLI {' '.join(args)} failed: rc={result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return json.loads(result.stdout)

    def test_explicit_publish_lands_rows(self):
        self._cli("init", "--slug", self.slug, "--no-hook")
        self._cli(
            "commit",
            "--type", "root",
            "--claim", "live integration root",
            "--diary", "## live root",
        )
        self._cli(
            "commit",
            "--type", "narrow",
            "--claim", "live integration narrow",
            "--prediction", "p", "--evidence", "e",
            "--status", "supported",
        )
        self._cli("publish", "--slug", self.slug)

        status, body = _request(
            f"{self.url}/rest/v1/nodes?repo=eq.{self.slug}&select=type",
            key=self.anon,
        )
        self.assertEqual(status, 200)
        rows = json.loads(body)
        types = sorted(r["type"] for r in rows)
        self.assertEqual(types, ["narrow", "root"])

    def test_post_commit_hook_publishes_automatically(self):
        # explicitly target supabase even if VERCEL_TOKEN is also set
        out = self._cli("init", "--slug", self.slug, "--hook-target", "supabase")
        self.assertTrue(out["post_commit_hook"])
        self.assertEqual(out["hook_target"], "supabase")

        # commit — hook fires automatically
        self._cli(
            "commit",
            "--type", "root",
            "--claim", "auto-publish root",
        )
        # hook runs synchronously after `git commit`, but the python3 -m
        # subprocess can take a beat; give it 1s margin
        time.sleep(0.5)

        status, body = _request(
            f"{self.url}/rest/v1/nodes?repo=eq.{self.slug}&select=claim",
            key=self.anon,
        )
        self.assertEqual(status, 200)
        rows = json.loads(body)
        claims = [r["claim"] for r in rows]
        self.assertIn("auto-publish root", claims)


if __name__ == "__main__":
    unittest.main()
