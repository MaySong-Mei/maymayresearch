"""Demo scenario: walk a small thesis tree end-to-end through the harness.

The scenario is a compressed re-enactment of the user's own CoR study
(probes vs reasoning), exercising every action the harness supports:
narrow, rigor branch, pivot branch, backtrack, reframe branch, and synthesis.

Run:
    python3 -m harness.demo /tmp/research_demo demo.html
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .core import ResearchRepo, ThesisNode
from .render import render_html
from .reviewer import review


def _commit(repo: ResearchRepo, node: ThesisNode, diary: str = "") -> str:
    node.review_comments = review(node)
    return repo.commit_node(node, diary_append=diary)


def run(repo_path: Path) -> ResearchRepo:
    if repo_path.exists():
        shutil.rmtree(repo_path)
    repo = ResearchRepo(repo_path)
    repo.init()

    # 1. ROOT on main
    _commit(
        repo,
        ThesisNode(
            type="root",
            claim="Probes are necessary for agents to build good state representation.",
            prediction="(seed thesis; iterations refine it)",
            evidence="—",
            status="pending",
        ),
        diary="# Research Diary\n\n## Root thesis\nProbes are necessary for agents to build good state representation.",
    )

    # 2. NARROW on main: QuixBugs test
    _commit(
        repo,
        ThesisNode(
            type="narrow",
            claim="Agent-designed probes outperform no-probe reasoning on code debugging.",
            prediction="agent-probe localization >90%, no-probe <70% on QuixBugs (N=31).",
            evidence="agent-probe 31/31; no-probe 18/20 — did not detect a gap.",
            status="not-detected",
            notes="Baseline is near task ceiling — no-probe already maxes out, so we cannot conclude probes are useless here.",
        ),
        diary="## Phase 1: QuixBugs\nAgent-probe ≈ no-probe. did not detect difference (baseline near ceiling).",
    )

    # 3. RIGOR branch: stronger retest in code domain
    repo.new_branch("rigor-1")
    _commit(
        repo,
        ThesisNode(
            type="rigor",
            claim="Re-test code-domain probing with stronger baselines and larger N (PRA-Bench, ORB-Bench, World-Bench, SWE-bench).",
            prediction="if probing genuinely helps, gap will appear at N≥70 across 4 benchmarks.",
            evidence="across 4 benchmarks and ~70 bugs: agent-probe ≈ no-probe at every scale tested (did not detect).",
            status="exhausted",
            notes="Branch exhausted: no remaining narrowing in code domain has falsifiable headroom — saturated baseline.",
        ),
        diary="## rigor-1: Stronger code-domain retest\nAcross 4 benchmarks ~70 bugs: still no detected gap. Branch exhausted.",
    )

    # 4. BACKTRACK to main, then PIVOT branch: BoxingGym
    repo.checkout("main")
    repo.new_branch("pivot-1")
    _commit(
        repo,
        ThesisNode(
            type="pivot",
            claim="Probing matters in genuinely OOD environments where the function is hidden (BoxingGym Dugongs).",
            prediction="with a hidden length=α-β·|λ|^age function, targeted probing beats uniform random sampling.",
            evidence="targeted MSE 0.046, random MSE 0.096 across 2 seeds — 51% improvement.",
            status="supported",
            notes="Provisional support; small N, no rigorous baseline yet.",
        ),
        diary="## pivot-1: BoxingGym Dugongs\nTargeted probing wins ~50% MSE reduction on 2 seeds. Provisional.",
    )

    # 5. RIGOR branch on pivot-1: 15 seeds + space-filling control + GP regression
    repo.new_branch("rigor-2")
    _commit(
        repo,
        ThesisNode(
            type="rigor",
            claim="Targeted probing beats space-filling on Dugongs at N=15 with a GP regression predictor.",
            prediction="targeted vs space-filling Wilcoxon p<0.05 if the v1 win was real.",
            evidence="targeted MSE 0.184, space-filling 0.144, Wilcoxon p=0.51 — did not detect difference under N=15.",
            status="not-detected",
            notes="The v1 'win' came from the LLM picking endpoints+midpoint — a trivial space-filling heuristic. No advantage over an explicit space-filling design.",
        ),
        diary="## rigor-2: 15-seed retest + GP\nDid not detect targeted vs space-filling difference. v1 win was a trivial-heuristic artifact.",
    )

    # 6. REFRAME branch: not probe selection but representation update
    repo.new_branch("reframe-1")
    _commit(
        repo,
        ThesisNode(
            type="reframe",
            claim="The variable that matters isn't probe selection — the prior claim 'targeted probing helps OOD' is too narrow. The deeper variable is representation update: explicit belief tracking should beat implicit if rep update is the active ingredient.",
            prediction="explicit-struct (sequential belief-state JSON) MSE < implicit (one-shot) MSE on the same observations.",
            evidence="implicit MSE 2.06, explicit-struct 1.32, explicit-free 1.97; Wilcoxon p=0.62 — did not detect difference.",
            status="not-detected",
            notes="Consistent with: LLM forward pass already internalizes belief update at this scale. The parent thesis ('probe selection is the variable') is abandoned; representation update appears internalized.",
        ),
        diary="## reframe-1: representation update is internalized\nExplicit belief tracking ≈ implicit. The active variable is not probe selection. Reframe: rep update is internalized at this scale.",
    )

    # 7. SYNTHESIS: combine rigor-1 (code-domain tied) with reframe-1 (rep-update internalized)
    repo.synthesize(
        new_branch_name="synth-1",
        base_branch="rigor-1",
        other_branch="reframe-1",
        node=ThesisNode(
            type="synthesis",
            claim="Boundary thesis: when the causal information lives in readable code (rigor-1) OR within an LLM-internalized regime such as smooth functional fits (reframe-1), explicit probing and explicit representation update add no measurable benefit. Probes are valuable specifically OUTSIDE this internalized regime — in domains with truly hidden state, scale beyond reading capacity, or non-deterministic behavior.",
            prediction="(synthesis node — productive next step is to find a domain outside the internalized regime, e.g. live system state, multi-repo scale, or stochastic processes.)",
            evidence="rigor-1: code-domain ~70 bugs, no detected gap. reframe-1: implicit ≈ explicit on functional fits. Two arms agree on the boundary.",
            status="supported",
        ),
        diary_append="## synth-1: Boundary thesis\nMerged rigor-1 (code) + reframe-1 (rep update). Synthesis: probing/explicit update only matter outside the internalized regime.",
    )

    return repo


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python3 -m harness.demo <repo_path> <html_output>", file=sys.stderr)
        return 2
    repo_path = Path(sys.argv[1])
    html_path = Path(sys.argv[2])
    repo = run(repo_path)
    render_html(
        repo,
        html_path,
        title="Research Thesis Tree — CoR study (demo)",
        subtitle="Compressed replay of the probes-vs-reasoning study under the harness.",
    )
    print(f"repo: {repo_path}")
    print(f"html: {html_path}")
    print(f"branches: {sorted(repo.all_branches().keys())}")
    print(f"nodes:    {len(repo.all_nodes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
