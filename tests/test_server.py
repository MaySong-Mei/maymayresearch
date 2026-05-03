"""Tests for the live HTTP dashboard server.

Binds to an ephemeral port on 127.0.0.1, fetches via urllib, and asserts
that the version hash advances when a new commit lands.

Run from project root:
    python3 -m unittest harness.tests.test_server -v
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from harness.core import ResearchRepo, ThesisNode
from harness.server import ResearchServer


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="server_test_"))
        self.repo = ResearchRepo(self.tmp / "repo")
        self.repo.init()
        self.repo.commit_node(ThesisNode(claim="root", type="root"))
        self.server = ResearchServer(self.repo, host="127.0.0.1", port=0).start()

    def tearDown(self):
        self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, path: str, timeout: float = 3.0):
        with urlopen(self.server.url + path, timeout=timeout) as r:
            return r.status, r.headers, r.read()


class TestRoutes(ServerTestCase):
    def test_root_serves_html(self):
        status, headers, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        text = body.decode()
        self.assertIn("<svg", text)
        self.assertIn("__SERVER_VERSION__", text)  # auto-refresh wired up

    def test_version_returns_json_hash(self):
        status, _, body = self._get("/version")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("version", payload)
        self.assertEqual(len(payload["version"]), 12)

    def test_health(self):
        status, _, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_diary_serves_findings(self):
        # Commit a node with diary content
        self.repo.commit_node(
            ThesisNode(claim="x", type="narrow"),
            diary_append="## Test diary section\nhello world",
        )
        status, _, body = self._get("/diary")
        self.assertEqual(status, 200)
        self.assertIn(b"Test diary section", body)

    def test_unknown_path_404(self):
        with self.assertRaises(HTTPError) as cm:
            self._get("/does-not-exist")
        self.assertEqual(cm.exception.code, 404)


class TestLiveUpdate(ServerTestCase):
    def test_version_changes_on_commit(self):
        _, _, body1 = self._get("/version")
        v1 = json.loads(body1)["version"]

        self.repo.commit_node(
            ThesisNode(claim="another", type="narrow",
                       prediction="p", evidence="e", status="supported"),
            diary_append="## another\n",
        )

        _, _, body2 = self._get("/version")
        v2 = json.loads(body2)["version"]
        self.assertNotEqual(v1, v2)

    def test_html_re_renders_on_commit(self):
        _, _, body1 = self._get("/")
        self.assertNotIn(b"sentinel-claim-X9", body1)

        self.repo.commit_node(
            ThesisNode(claim="sentinel-claim-X9", type="narrow",
                       prediction="p", evidence="e", status="supported"),
        )

        _, _, body2 = self._get("/")
        self.assertIn(b"sentinel-claim-X9", body2)


if __name__ == "__main__":
    unittest.main()
