"""Simulate an agent driving the harness CLI from outside Python.

This script does NOT import harness — it shells out to `python3 -m harness.cli`
exactly the way a Claude Code session (or any other agent) would. It's the
clearest demonstration that the CLI is sufficient for an autonomous loop.

The "agent" here is a deterministic script. A real agent would replace
`decide_next_action()` with an LLM call that reads the `context` payload
and emits a JSON action.

Run:
    python3 -m harness.agent_demo /tmp/agent_demo /tmp/agent_demo.html
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def cli(repo: Path, *args: str, stdin: str = "") -> Dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "--repo", str(repo), *args],
        cwd=PROJECT_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"CLI failed: {' '.join(args)}")
    return json.loads(result.stdout)


def step(label: str, payload: Dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    summary_keys = ("ok", "branch", "current_branch", "short", "sha", "review_comments")
    short = {k: payload.get(k) for k in summary_keys if k in payload}
    print(json.dumps(short, indent=2, ensure_ascii=False))


def run(repo_path: Path, html_out: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path)

    # ---- agent step 1: init ----
    step("init", cli(repo_path, "init"))

    # ---- agent step 2: orient (empty) ----
    ctx = cli(repo_path, "context")
    step("context (empty)", ctx)

    # ---- agent step 3: root commit ----
    root = {
        "node": {
            "type": "root",
            "claim": "Probes are necessary for agents to build state representation.",
            "status": "pending",
        },
        "diary": "# Diary\n\n## Root\nProbes are necessary for representation.",
    }
    step("commit root", cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(root)))

    # ---- agent step 4: narrow on main ----
    narrow = {
        "node": {
            "type": "narrow",
            "status": "not-detected",
            "claim": "Agent-probes outperform no-probe reasoning on QuixBugs.",
            "prediction": "agent-probe localization > 90%, no-probe < 70%.",
            "evidence": "agent-probe 31/31, no-probe 18/20 — did not detect a gap.",
            "notes": "baseline near ceiling.",
        },
        "diary": "## QuixBugs\nTied. Baseline near ceiling.",
    }
    step("commit narrow", cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(narrow)))

    # ---- agent step 5: orient again ----
    ctx = cli(repo_path, "context")
    step("context (after narrow)", {
        "current_branch": ctx["current_branch"],
        "current_tip": ctx["current_tip"]["short"],
        "ancestor_chain": [a["short"] + "/" + a["type"] for a in ctx["ancestors"]],
        "branch_tips": [(b["branch"], b["status"]) for b in ctx["all_branch_tips"]],
    })

    # ---- agent step 6: agent decides this branch is exhausted in code domain → rigor branch ----
    cli(repo_path, "branch", "--name", "rigor-1")
    rigor = {
        "node": {
            "type": "rigor",
            "status": "exhausted",
            "claim": "Stronger code-domain retest with larger N.",
            "prediction": "if probing helps, gap will appear at N>=70.",
            "evidence": "across 4 benchmarks ~70 bugs: did not detect.",
            "notes": "code-domain branch saturated; baseline near ceiling.",
        },
        "diary": "## rigor-1\nStill tied. Branch exhausted.",
    }
    step("commit rigor-1", cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(rigor)))

    # ---- agent step 7: backtrack — checkout main, decide to pivot ----
    cli(repo_path, "checkout", "main")
    cli(repo_path, "branch", "--name", "pivot-1")
    pivot = {
        "node": {
            "type": "pivot",
            "status": "supported",
            "claim": "Probing matters in genuinely OOD environments (BoxingGym Dugongs).",
            "prediction": "with hidden function, targeted probing beats random.",
            "evidence": "targeted MSE 0.046, random 0.096 across 2 seeds — 51% improvement.",
            "notes": "provisional; small N.",
        },
        "diary": "## pivot-1\nTargeted ≈50% MSE reduction. Provisional.",
    }
    step("commit pivot-1", cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(pivot)))

    # ---- agent step 8: rigor on pivot — control for space-filling ----
    cli(repo_path, "branch", "--name", "rigor-2")
    rigor2 = {
        "node": {
            "type": "rigor",
            "status": "not-detected",
            "claim": "Targeted beats space-filling at N=15 with GP regression.",
            "prediction": "Wilcoxon p<0.05 if v1 win was real.",
            "evidence": "Wilcoxon p=0.51 — did not detect difference; baseline near ceiling for sampled curves.",
            "notes": "v1 'win' was a trivial-heuristic artifact.",
        },
        "diary": "## rigor-2\nDid not detect. v1 was an artifact.",
    }
    step("commit rigor-2", cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(rigor2)))

    # ---- agent step 9: reframe — rep update is the deeper variable ----
    cli(repo_path, "branch", "--name", "reframe-1")
    reframe = {
        "node": {
            "type": "reframe",
            "status": "not-detected",
            "claim": "Representation update, not probe selection, is the variable; the prior claim was too narrow.",
            "prediction": "explicit belief tracking beats implicit one-shot.",
            "evidence": "Wilcoxon p=0.62 — did not detect difference; the prior thesis is abandoned.",
            "notes": "rep update appears internalized at this scale.",
        },
        "diary": "## reframe-1\nrep update internalized. Reframed.",
    }
    step("commit reframe-1", cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(reframe)))

    # ---- agent step 10: synthesize rigor-1 + reframe-1 ----
    synth = {
        "node": {
            "type": "synthesis",
            "status": "supported",
            "claim": (
                "Boundary thesis: probing/explicit rep update help only OUTSIDE "
                "the LLM-internalized regime (readable code + smooth functional fits)."
            ),
            "evidence": "rigor-1 (code, ceiling) + reframe-1 (rep update internalized) agree on the boundary.",
        },
        "diary": "## synth-1\nBoundary thesis. Productive next: find domain outside the regime.",
    }
    step(
        "synthesize",
        cli(
            repo_path,
            "synthesize",
            "--new-branch", "synth-1",
            "--base", "rigor-1",
            "--other", "reframe-1",
            "--from-json", "-",
            stdin=json.dumps(synth),
        ),
    )

    # ---- final: render ----
    cli(repo_path, "render", "--out", str(html_out),
        "--title", "Research Thesis Tree — agent-driven demo",
        "--subtitle", "Built end-to-end via shell-only CLI calls.")
    listing = cli(repo_path, "list")
    print(f"\nfinal: {len(listing['nodes'])} nodes, {len(listing['branches'])} branches")
    print(f"html : {html_out}")
    print(f"repo : {repo_path}")


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python3 -m harness.agent_demo <repo> <html_out>", file=sys.stderr)
        return 2
    run(Path(sys.argv[1]), Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
