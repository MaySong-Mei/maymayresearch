"""Unit tests for the research harness.

Run from the project root:
    python3 -m unittest harness.tests.test_harness -v
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from harness.core import ResearchRepo, ThesisNode
from harness.render import _topological_depth, _assign_lanes, render_html
from harness.reviewer import review


class TestThesisNode(unittest.TestCase):
    def test_validates_type(self):
        with self.assertRaises(ValueError):
            ThesisNode(claim="x", type="bogus")

    def test_validates_status(self):
        with self.assertRaises(ValueError):
            ThesisNode(claim="x", status="bogus")

    def test_roundtrip_json(self):
        n = ThesisNode(
            claim="c", prediction="p", evidence="e",
            status="supported", type="narrow",
            review_comments=["a", "b"], notes="hello",
        )
        n2 = ThesisNode.from_json(n.to_json())
        self.assertEqual(n, n2)


class TestRepoOps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness_test_"))
        self.repo = ResearchRepo(self.tmp / "repo")
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_init_creates_main(self):
        self.assertEqual(self.repo.current_branch(), "main")

    def test_commit_node_writes_thesis(self):
        sha = self.repo.commit_node(ThesisNode(claim="root", type="root"))
        self.assertTrue((self.repo.path / "thesis.json").exists())
        nodes = self.repo.all_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["sha"], sha)
        self.assertEqual(nodes[0]["claim"], "root")
        self.assertEqual(nodes[0]["type"], "root")

    def test_commit_appends_diary(self):
        self.repo.commit_node(ThesisNode(claim="r", type="root"), diary_append="line A")
        self.repo.commit_node(ThesisNode(claim="n", type="narrow"), diary_append="line B")
        diary = (self.repo.path / "FINDINGS.md").read_text()
        self.assertIn("line A", diary)
        self.assertIn("line B", diary)
        self.assertLess(diary.index("line A"), diary.index("line B"))

    def test_branching_and_backtrack(self):
        self.repo.commit_node(ThesisNode(claim="root", type="root"))
        self.repo.commit_node(ThesisNode(claim="narrow on main", type="narrow"))
        main_tip = self.repo.head_sha()
        # branch off and commit
        self.repo.new_branch("rigor-x")
        self.repo.commit_node(ThesisNode(claim="rigor branch", type="rigor"))
        # backtrack
        self.repo.checkout("main")
        self.assertEqual(self.repo.head_sha(), main_tip)
        # the rigor branch survives
        branches = self.repo.all_branches()
        self.assertIn("rigor-x", branches)

    def test_synthesize_creates_merge_commit(self):
        self.repo.commit_node(ThesisNode(claim="root", type="root"))
        self.repo.commit_node(ThesisNode(claim="A claim", type="narrow"))
        # branch B from main
        self.repo.new_branch("branch-b")
        self.repo.commit_node(ThesisNode(claim="B claim", type="reframe",
                                          prediction="p", evidence="prior thesis was wrong because..."))
        b_tip = self.repo.head_sha()
        # back to main, branch C
        self.repo.checkout("main")
        self.repo.new_branch("branch-c")
        self.repo.commit_node(ThesisNode(claim="C claim", type="rigor",
                                          prediction="p", evidence="e"))
        c_tip = self.repo.head_sha()
        # synthesize
        synth_sha = self.repo.synthesize(
            new_branch_name="synth-x",
            base_branch="branch-c",
            other_branch="branch-b",
            node=ThesisNode(claim="combined", type="synthesis",
                            evidence="rigorous + reframe agree"),
        )
        # synthesis commit must have two parents
        nodes = {n["sha"]: n for n in self.repo.all_nodes()}
        synth = nodes[synth_sha]
        self.assertEqual(len(synth["parents"]), 2)
        self.assertEqual(synth["type"], "synthesis")
        self.assertIn(b_tip, synth["parents"])
        self.assertIn(c_tip, synth["parents"])


class TestReviewer(unittest.TestCase):
    def test_falsifiability_missing(self):
        n = ThesisNode(claim="x", type="narrow")  # no prediction
        comments = review(n)
        self.assertTrue(any("falsifiability" in c for c in comments))

    def test_root_skips_falsifiability(self):
        n = ThesisNode(claim="x", type="root")  # no prediction OK
        self.assertFalse(any("falsifiability" in c for c in review(n)))

    def test_null_overclaim_flagged(self):
        n = ThesisNode(claim="x", type="narrow", prediction="p",
                       evidence="thesis is false; null hypothesis confirmed.")
        comments = review(n)
        self.assertTrue(any("phrasing" in c for c in comments))

    def test_did_not_detect_passes(self):
        n = ThesisNode(claim="x", type="narrow", prediction="p",
                       evidence="did not detect a difference at N=15.")
        self.assertFalse(any("phrasing" in c for c in review(n)))

    def test_directional_claim_needs_ceiling(self):
        n = ThesisNode(claim="probes help on debugging", type="narrow",
                       prediction="p", evidence="tied across 70 bugs")
        comments = review(n)
        self.assertTrue(any("ceiling" in c for c in comments))

    def test_directional_claim_with_ceiling_passes(self):
        n = ThesisNode(claim="probes help on debugging", type="narrow",
                       prediction="p", evidence="tied; baseline near ceiling.")
        self.assertFalse(any("ceiling" in c for c in review(n)))

    def test_reframe_must_reference_parent(self):
        n = ThesisNode(claim="new direction entirely", type="reframe",
                       prediction="p", evidence="something")
        comments = review(n)
        self.assertTrue(any("reframe" in c for c in comments))

    def test_reframe_ok_with_parent_ref(self):
        n = ThesisNode(claim="new direction; the prior claim was too narrow",
                       type="reframe", prediction="p",
                       evidence="prior thesis didn't explain the data")
        self.assertFalse(any("reframe" in c for c in review(n)))


class TestLayout(unittest.TestCase):
    def _line(self, sha, parents, type_):
        return {"sha": sha, "parents": parents, "type": type_, "status": "pending"}

    def test_depth_linear(self):
        nodes = [
            self._line("a", [], "root"),
            self._line("b", ["a"], "narrow"),
            self._line("c", ["b"], "narrow"),
        ]
        depth = _topological_depth(nodes)
        self.assertEqual(depth["a"], 0)
        self.assertEqual(depth["b"], 1)
        self.assertEqual(depth["c"], 2)

    def test_lane_assignment_for_branching(self):
        nodes = [
            self._line("a", [], "root"),
            self._line("b", ["a"], "narrow"),
            self._line("c", ["b"], "rigor"),  # new lane
            self._line("d", ["b"], "pivot"),  # another new lane
        ]
        lanes = _assign_lanes(nodes)
        self.assertEqual(lanes["a"], 0)
        self.assertEqual(lanes["b"], 0)
        self.assertNotEqual(lanes["c"], 0)
        self.assertNotEqual(lanes["d"], 0)
        self.assertNotEqual(lanes["c"], lanes["d"])

    def test_synthesis_takes_fresh_lane(self):
        nodes = [
            self._line("a", [], "root"),
            self._line("b", ["a"], "rigor"),
            self._line("c", ["a"], "reframe"),
            self._line("s", ["b", "c"], "synthesis"),
        ]
        lanes = _assign_lanes(nodes)
        # synthesis should be on its own lane, distinct from both parents
        self.assertNotEqual(lanes["s"], lanes["b"])
        self.assertNotEqual(lanes["s"], lanes["c"])


class TestRenderEndToEnd(unittest.TestCase):
    def test_render_smoke(self):
        tmp = Path(tempfile.mkdtemp(prefix="harness_render_"))
        try:
            repo = ResearchRepo(tmp / "repo")
            repo.init()
            repo.commit_node(ThesisNode(claim="root", type="root"))
            repo.commit_node(ThesisNode(claim="narrow", type="narrow",
                                         prediction="p", evidence="e"))
            out = tmp / "out.html"
            render_html(repo, out, title="t", subtitle="s")
            content = out.read_text()
            self.assertIn("<svg", content)
            self.assertIn("<title>t</title>", content)
            self.assertIn("narrow", content)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
