"""Non-blocking reviewer. Returns comments, never refuses a commit.

Encodes the user's METHODOLOGY_NOTES as soft checks: falsifiability,
ceiling acknowledgement, "did not detect" vs "is null", reframe
must point at the parent claim that failed.
"""

from __future__ import annotations

import re
from typing import List

from .core import ThesisNode


_NULL_OVERCLAIM = re.compile(
    r"\b(is null|null hypothesis (is )?confirmed|confirmed null|no effect|"
    r"thesis is false|disproved)\b",
    re.I,
)
_DIRECTIONAL_CLAIM = re.compile(
    r"\b(helps?|doesn'?t help|does not help|no benefit|outperforms?|"
    r"is better than|is worse than|beats|loses to)\b",
    re.I,
)
_CEILING_TOKEN = re.compile(
    r"\b(ceiling|saturat|baseline.{0,30}(near|at|already)|headroom|"
    r"top-?out|maxed out)\b",
    re.I,
)
_REFRAME_PARENT_REF = re.compile(
    r"\b(parent|prior claim|previous (claim|thesis)|because|since|"
    r"earlier (we|the) thesis|the original)\b",
    re.I,
)


def review(node: ThesisNode) -> List[str]:
    comments: List[str] = []

    if node.type not in {"root", "synthesis"} and not node.prediction.strip():
        comments.append(
            "[falsifiability] No prediction logged. Before running the experiment, "
            "what observation would have made you say this thesis was wrong?"
        )

    if _NULL_OVERCLAIM.search(node.evidence) or _NULL_OVERCLAIM.search(node.claim):
        comments.append(
            "[phrasing] 'is null' / 'no effect' / 'thesis is false' overclaims. "
            "Prefer 'did not detect under [conditions, N=k]'."
        )

    if _DIRECTIONAL_CLAIM.search(node.claim):
        full = f"{node.claim}\n{node.evidence}\n{node.notes}"
        if not _CEILING_TOKEN.search(full):
            comments.append(
                "[ceiling] This claim asserts an effect direction without addressing "
                "ceiling. Where is the baseline relative to task ceiling?"
            )

    if node.type == "reframe":
        full = f"{node.claim}\n{node.evidence}\n{node.notes}"
        if not _REFRAME_PARENT_REF.search(full):
            comments.append(
                "[reframe] A reframe-branch should explicitly name which prior "
                "claim is being abandoned and why."
            )

    return comments
