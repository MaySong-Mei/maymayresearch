"""Unit tests for the Supabase publisher.

These run without network — the publisher is constructed with a mock HTTP
function that captures requests instead of sending them. Live integration
is tested separately in test_integration.py.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from typing import Any, List
from urllib.request import Request

from harness.core import ResearchRepo, ThesisNode
from harness.publisher import SupabasePublisher, load_env_file


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self._body = BytesIO(body)

    def read(self):
        return self._body.read()


class _MockHttp:
    """Captures every request made; returns 201 by default."""

    def __init__(self, status: int = 201):
        self.calls: List[Request] = []
        self.bodies: List[Any] = []
        self.status = status

    def __call__(self, req: Request, timeout: float = 0):
        self.calls.append(req)
        if req.data:
            self.bodies.append(json.loads(req.data.decode()))
        else:
            self.bodies.append(None)
        return _FakeResponse(self.status)


def _seed_repo(path: Path) -> ResearchRepo:
    repo = ResearchRepo(path)
    repo.init()
    repo.commit_node(ThesisNode(claim="r", type="root"))
    repo.commit_node(
        ThesisNode(
            claim="n", type="narrow",
            prediction="p", evidence="e", status="supported",
        )
    )
    repo.new_branch("rigor-x")
    repo.commit_node(
        ThesisNode(claim="rigor", type="rigor", status="exhausted")
    )
    return repo


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pub_test_"))
        self.repo = _seed_repo(self.tmp / "repo")
        self.http = _MockHttp(status=201)
        self.pub = SupabasePublisher(
            url="https://example.supabase.co",
            service_key="sb_secret_TEST",
            http=self.http,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sync_sends_nodes_and_branches(self):
        results = self.pub.sync_repo(self.repo, repo_slug="t1")
        # Three calls: nodes upsert, branches upsert, branches prune (DELETE)
        self.assertEqual(len(self.http.calls), 3)

        nodes_req = self.http.calls[0]
        self.assertIn("/rest/v1/nodes?on_conflict=repo,sha", nodes_req.full_url)
        self.assertEqual(nodes_req.get_method(), "POST")

        branches_req = self.http.calls[1]
        self.assertIn("/rest/v1/branches?on_conflict=repo,name", branches_req.full_url)

        prune_req = self.http.calls[2]
        self.assertEqual(prune_req.get_method(), "DELETE")
        self.assertIn("/rest/v1/branches?repo=eq.t1", prune_req.full_url)

        self.assertEqual(results["nodes"].rows_sent, 3)
        self.assertEqual(results["branches"].rows_sent, 2)

    def test_node_payload_shape(self):
        self.pub.sync_repo(self.repo, repo_slug="shape")
        node_rows = self.http.bodies[0]
        self.assertIsInstance(node_rows, list)
        self.assertEqual(len(node_rows), 3)
        sample = node_rows[0]
        self.assertEqual(set(sample.keys()) >= {
            "repo", "sha", "parents", "type", "status",
            "claim", "prediction", "evidence", "notes",
            "review_comments", "committed_at",
        }, True)
        self.assertEqual(sample["repo"], "shape")
        self.assertIsInstance(sample["parents"], list)

    def test_auth_headers_present(self):
        self.pub.sync_repo(self.repo, repo_slug="auth")
        for req in self.http.calls:
            self.assertEqual(req.headers["Apikey"], "sb_secret_TEST")
            self.assertEqual(req.headers["Authorization"], "Bearer sb_secret_TEST")

    def test_empty_repo_safe(self):
        empty = self.tmp / "empty"
        repo = ResearchRepo(empty)
        repo.init()
        results = self.pub.sync_repo(repo, repo_slug="empty")
        # nodes call still happens but with [] rows → no HTTP issued
        # branches call: empty repo has 1 branch (main, no commits)? actually no — main exists but symbolic-ref only
        # We at least expect no exceptions:
        self.assertIn("nodes", results)


class EnvLoaderTests(unittest.TestCase):
    def test_loads_kv(self):
        tmp = Path(tempfile.mkdtemp(prefix="env_"))
        try:
            f = tmp / ".env"
            f.write_text("# comment\nA=1\nB=\"two words\"\nC=3\n\n")
            data = load_env_file(f)
            self.assertEqual(data, {"A": "1", "B": "two words", "C": "3"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
