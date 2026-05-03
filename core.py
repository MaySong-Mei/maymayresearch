"""Research harness core: thesis nodes + git-backed research repo.

Each commit is a thesis node. A `thesis.json` at the repo root carries the
structured thesis fields; FINDINGS.md is the append-only diary. Branches
represent thesis branchings (rigor / reframe / pivot). Merge commits with
type=synthesis represent thesis synthesis nodes that combine two prior
branches into a new claim.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


VALID_TYPES = {"root", "narrow", "rigor", "reframe", "pivot", "synthesis"}
VALID_STATUSES = {
    "pending",
    "supported",
    "not-detected",
    "refuted",
    "ceiling-bound",
    "exhausted",
}


@dataclass
class ThesisNode:
    claim: str
    prediction: str = ""
    evidence: str = ""
    status: str = "pending"
    type: str = "narrow"
    review_comments: List[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.type not in VALID_TYPES:
            raise ValueError(f"invalid type {self.type!r}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status {self.status!r}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "ThesisNode":
        return cls(**json.loads(s))


class ResearchRepo:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            check=check,
            capture_output=True,
            text=True,
        )

    def init(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self._git("init", "-b", "main")
        self._git("config", "user.email", "harness@local")
        self._git("config", "user.name", "Research Harness")
        self._git("config", "commit.gpgsign", "false")

    def commit_node(self, node: ThesisNode, diary_append: str = "") -> str:
        (self.path / "thesis.json").write_text(node.to_json())
        if diary_append:
            diary = self.path / "FINDINGS.md"
            existing = diary.read_text() if diary.exists() else ""
            diary.write_text(existing + diary_append.rstrip() + "\n\n")
        self._git("add", "-A")
        msg = self._format_commit_msg(node)
        self._git("commit", "-m", msg, "--allow-empty")
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _format_commit_msg(self, node: ThesisNode) -> str:
        head = f"[{node.type}/{node.status}]"
        return f"{head} {node.claim}"[:200]

    def current_branch(self) -> str:
        # symbolic-ref works on an empty repo (before first commit); rev-parse does not.
        return self._git("symbolic-ref", "--short", "HEAD").stdout.strip()

    def head_sha(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def checkout(self, ref: str) -> None:
        self._git("checkout", ref)

    def new_branch(self, name: str, from_ref: Optional[str] = None) -> None:
        if from_ref:
            self._git("checkout", "-b", name, from_ref)
        else:
            self._git("checkout", "-b", name)

    def synthesize(
        self,
        new_branch_name: str,
        base_branch: str,
        other_branch: str,
        node: ThesisNode,
        diary_append: str = "",
    ) -> str:
        """Create a synthesis commit on a new branch from base, merging other.

        The synthesis is a NEW thesis-node (a merge commit) on a new branch.
        Conflicts in thesis.json/FINDINGS.md are resolved by the synthesis
        content provided by the caller.
        """
        if node.type != "synthesis":
            raise ValueError("synthesize requires node.type == 'synthesis'")
        self._git("checkout", base_branch)
        self._git("checkout", "-b", new_branch_name)
        # --no-ff to force a merge commit, --no-commit so we can write resolution
        self._git("merge", "--no-ff", "--no-commit", other_branch, check=False)
        (self.path / "thesis.json").write_text(node.to_json())
        if diary_append:
            diary = self.path / "FINDINGS.md"
            existing = diary.read_text() if diary.exists() else ""
            diary.write_text(existing + diary_append.rstrip() + "\n\n")
        self._git("add", "-A")
        msg = self._format_commit_msg(node)
        self._git("commit", "-m", msg)
        return self.head_sha()

    def all_nodes(self) -> List[dict]:
        """Walk all commits across all branches in parent-before-child order."""
        log = self._git(
            "log", "--all", "--topo-order", "--reverse",
            "--format=%H|%P|%s|%ct",
        ).stdout.strip()
        nodes = []
        for line in log.splitlines():
            sha, parents, subject, timestamp = line.split("|", 3)
            parent_list = parents.split() if parents else []
            try:
                content = self._git("show", f"{sha}:thesis.json").stdout
                node = json.loads(content)
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                node = {"claim": "(no thesis.json)", "type": "unknown", "status": "pending"}
            nodes.append(
                {
                    "sha": sha,
                    "short": sha[:7],
                    "parents": parent_list,
                    "subject": subject,
                    "timestamp": int(timestamp),
                    **node,
                }
            )
        return nodes

    def all_branches(self) -> dict:
        out = self._git(
            "for-each-ref", "--format=%(refname:short)|%(objectname)", "refs/heads/"
        ).stdout
        return {
            line.split("|")[0]: line.split("|")[1]
            for line in out.strip().splitlines()
            if line
        }
