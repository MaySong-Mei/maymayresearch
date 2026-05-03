"""End-to-end tests for the harness CLI invoked via subprocess.

Verifies an agent can drive the harness through stdin/stdout alone — no
Python imports needed on the agent side.

Run from project root:
    python3 -m unittest harness.tests.test_cli -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=PROJECT_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
    )


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cli_test_"))
        self.repo = self.tmp / "repo"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ok(self, result: subprocess.CompletedProcess, msg: str = "") -> dict:
        if result.returncode != 0:
            self.fail(
                f"{msg or 'CLI'} failed: rc={result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return json.loads(result.stdout)


class TestCliBasic(CliTestCase):
    def test_init_then_context_empty(self):
        out = self._ok(_run_cli("--repo", str(self.repo), "init"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["branch"], "main")

        ctx = self._ok(_run_cli("--repo", str(self.repo), "context"))
        self.assertTrue(ctx["empty"])

    def test_double_init_errors(self):
        _run_cli("--repo", str(self.repo), "init")
        result = _run_cli("--repo", str(self.repo), "init")
        self.assertNotEqual(result.returncode, 0)
        body = json.loads(result.stdout)
        self.assertFalse(body["ok"])

    def test_commit_returns_review_comments(self):
        _run_cli("--repo", str(self.repo), "init")
        # claim with directional language ("helps") and no ceiling → expect comment
        result = _run_cli(
            "--repo", str(self.repo), "commit",
            "--type", "narrow",
            "--claim", "probes help on debugging tasks",
            "--prediction", "agent-probe > no-probe by 20%",
            "--evidence", "agent-probe = no-probe across N=70",
            "--status", "not-detected",
        )
        out = self._ok(result)
        self.assertTrue(out["ok"])
        self.assertIn("sha", out)
        self.assertTrue(any("ceiling" in c for c in out["review_comments"]))

    def test_invalid_node_args(self):
        _run_cli("--repo", str(self.repo), "init")
        result = _run_cli(
            "--repo", str(self.repo), "commit",
            "--type", "narrow", "--status", "bogus",
        )
        # argparse rejects bogus status with rc != 0; either that or our valueerror path
        self.assertNotEqual(result.returncode, 0)


class TestCliFullFlow(CliTestCase):
    """Exercise a small but complete agent flow end-to-end."""

    def test_full_flow(self):
        repo = str(self.repo)
        # 1. init
        self._ok(_run_cli("--repo", repo, "init"))

        # 2. root commit on main
        self._ok(_run_cli(
            "--repo", repo, "commit",
            "--type", "root",
            "--claim", "probes are necessary",
            "--diary", "# Diary\nroot",
        ))

        # 3. narrow commit on main
        out = self._ok(_run_cli(
            "--repo", repo, "commit",
            "--type", "narrow",
            "--claim", "test on QuixBugs",
            "--prediction", "agent-probe > no-probe",
            "--evidence", "tied across 31 bugs",
            "--status", "not-detected",
            "--notes", "baseline near ceiling",
            "--diary", "## QuixBugs: tied",
        ))
        narrow_sha = out["sha"]

        # 4. context after narrow
        ctx = self._ok(_run_cli("--repo", repo, "context"))
        self.assertEqual(ctx["current_branch"], "main")
        self.assertEqual(ctx["current_tip"]["short"], narrow_sha[:7])
        self.assertEqual(len(ctx["ancestors"]), 2)  # narrow + root
        self.assertEqual(ctx["node_count"], 2)

        # 5. branch (rigor)
        self._ok(_run_cli("--repo", repo, "branch", "--name", "rigor-1"))
        self._ok(_run_cli(
            "--repo", repo, "commit",
            "--type", "rigor",
            "--claim", "stronger retest",
            "--prediction", "with N=70 gap appears if real",
            "--evidence", "still tied; baseline saturated",
            "--status", "exhausted",
        ))

        # 6. checkout main, branch reframe
        self._ok(_run_cli("--repo", repo, "checkout", "main"))
        self._ok(_run_cli("--repo", repo, "branch", "--name", "reframe-1"))
        self._ok(_run_cli(
            "--repo", repo, "commit",
            "--type", "reframe",
            "--claim", "rep update is the variable; the prior claim was too narrow",
            "--prediction", "explicit beats implicit",
            "--evidence", "did not detect difference; the prior thesis is abandoned",
            "--status", "not-detected",
        ))

        # 7. synthesize rigor-1 + reframe-1
        out = self._ok(_run_cli(
            "--repo", repo, "synthesize",
            "--new-branch", "synth-1",
            "--base", "rigor-1",
            "--other", "reframe-1",
            "--type", "synthesis",
            "--status", "supported",
            "--claim", "boundary thesis: probes only help outside the internalized regime",
            "--evidence", "rigor-1 + reframe-1 agree",
        ))
        synth_sha = out["sha"]

        # 8. final list — synthesis must have 2 parents
        listing = self._ok(_run_cli("--repo", repo, "list"))
        sha_to_node = {n["sha"]: n for n in listing["nodes"]}
        self.assertIn(synth_sha, sha_to_node)
        self.assertEqual(len(sha_to_node[synth_sha]["parents"]), 2)
        self.assertEqual(sha_to_node[synth_sha]["type"], "synthesis")

        # 9. render
        out_html = self.tmp / "tree.html"
        self._ok(_run_cli(
            "--repo", repo, "render", "--out", str(out_html), "--title", "flow",
        ))
        self.assertTrue(out_html.exists())
        content = out_html.read_text()
        self.assertIn("synthesis", content)


class TestCliFromJson(CliTestCase):
    def test_commit_from_json_stdin(self):
        repo = str(self.repo)
        _run_cli("--repo", repo, "init")
        # root commit needed first for non-empty repo
        _run_cli(
            "--repo", repo, "commit",
            "--type", "root", "--claim", "r",
        )
        payload = {
            "node": {
                "claim": "stdin commit",
                "prediction": "p",
                "evidence": "e",
                "status": "supported",
                "type": "narrow",
            },
            "diary": "## stdin section\n",
        }
        result = _run_cli(
            "--repo", repo, "commit", "--from-json", "-",
            stdin=json.dumps(payload),
        )
        out = self._ok(result)
        self.assertTrue(out["ok"])
        # diary should contain the stdin section
        diary = (self.repo / "FINDINGS.md").read_text()
        self.assertIn("stdin section", diary)


if __name__ == "__main__":
    unittest.main()
