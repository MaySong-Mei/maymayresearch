"""Simulate an agent driving the harness CLI from outside Python.

Each node is fully populated:
  claim (hypothesis) / design (methodology) / prediction (falsifiable expectation)
  evidence (results) / decision (next step) / review_comments (auto from reviewer)

This mirrors what a Claude Code agent would write each iteration.

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
    keys = ("ok", "branch", "current_branch", "short", "sha")
    short = {k: payload.get(k) for k in keys if k in payload}
    print(f"\n=== {label} ===")
    print(json.dumps(short, indent=2, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────────────
#  rich node payloads (compressed re-enactment of the user's CoR study)
# ──────────────────────────────────────────────────────────────────────────


ROOT = {
    "node": {
        "type": "root",
        "status": "pending",
        "claim": "Probes are necessary for agents to build good state representation.",
        "design": (
            "Seed thesis. Concrete instances will be tested in subsequent phases. "
            "Working operational definition: a 'probe' is any executed measurement "
            "(test, query, computation) whose result the agent uses to update belief "
            "about hidden state."
        ),
        "prediction": (
            "(seed thesis — not directly tested; refined into testable predictions in children)"
        ),
        "evidence": "—",
        "decision": (
            "Spawn `narrow` child: pick the simplest concrete domain (code debugging, "
            "QuixBugs) where probe vs no-probe is testable."
        ),
    },
    "diary": (
        "# 研究日记\n"
        "## Root thesis\n"
        "Probes are necessary for agents to build good state representation. "
        "We don't yet know in what regime this is testable; the next phase narrows."
    ),
}

NARROW_QUIXBUGS = {
    "node": {
        "type": "narrow",
        "status": "not-detected",
        "claim": "Agent-designed probes outperform no-probe reasoning on QuixBugs (single-function debug).",
        "design": (
            "Two pipelines on all 31 QuixBugs problems, 1 attempt each, 30s timeout per attempt:\n\n"
            "1. **Agent-Probe**: subagent reads buggy code + failing test → designs an executable probe "
            "(typically a small script that calls the function with diagnostic inputs and prints internal state) "
            "→ runs the probe → forms a localization + mechanism hypothesis from observed signals "
            "(pass-rate, output deviation, error type).\n"
            "2. **No-Probe**: same subagent reads buggy code + failing test → reasons in-context with no execution "
            "→ forms localization + mechanism hypothesis directly.\n\n"
            "Scoring: blind grader (separate subagent) scores hypothesis 0–3 against gold patches. "
            "N=20 for No-Probe due to subagent timeouts on long programs; N=31 for Agent-Probe."
        ),
        "prediction": (
            "If agent-probes genuinely build better representations on debug tasks, "
            "agent-probe localization > 90% AND mean score > 2.5; "
            "no-probe < 70% / score < 2.0. Wilcoxon p < 0.05 on matched bugs."
        ),
        "evidence": (
            "Localization: Agent-Probe 31/31, No-Probe 18/20.\n"
            "Mean hypothesis score: Agent-Probe 2.80, No-Probe 2.95.\n"
            "Wilcoxon paired (matched 20 bugs): p = 0.81 — did NOT detect a difference.\n\n"
            "Both pipelines hit ceiling on most bugs (~3.0 max). Ceiling effect dominates: "
            "QuixBugs is in-distribution for the LLM (likely seen during training), so reasoning "
            "alone fully recovers the bug from source text. No headroom for probes to help."
        ),
        "decision": (
            "Prediction was NOT supported, but result is ambiguous: ceiling effect prevents detecting a real gap. "
            "Two children spawned in parallel:\n"
            "1. **rigor-1**: re-test with harder/novel bugs (PRA-Bench 20-bug authored set, "
            "ORB-Bench 15 observation-required bugs, World-Bench multi-file system, real SWE-bench case) "
            "to escape ceiling.\n"
            "2. **pivot-1**: pivot to genuinely OOD environment (BoxingGym Dugongs) where the function form "
            "is hidden by construction — probes are necessary by definition."
        ),
        "notes": (
            "Ceiling-bound; cannot conclude 'probes useless on debug', only 'probes have nothing to add to "
            "an already-saturated baseline'. Status='not-detected' (per methodology — never 'is null')."
        ),
    },
    "diary": (
        "## Phase 1: QuixBugs\n"
        "Did not detect agent-probe vs no-probe gap (p=0.81). "
        "Both hit ceiling at score ~3.0. Spawning rigor-1 (harder bugs) and pivot-1 (OOD) in parallel."
    ),
}

RIGOR_1 = {
    "node": {
        "type": "rigor",
        "status": "exhausted",
        "claim": "Stronger code-domain retest (4 benchmarks, ~70 bugs) to escape QuixBugs ceiling.",
        "design": (
            "Re-run the Agent-Probe vs No-Probe comparison on a much harder corpus:\n\n"
            "- **PRA-Bench**: 20 novel bugs authored by us across 20 mechanism types — no training-data leak.\n"
            "- **ORB-Bench**: 15 'observation-required' bugs (mutable defaults, generator exhaustion, "
            "True==1, list aliasing, float precision, stale cache, DAG double-counting).\n"
            "- **World-Bench**: multi-file warehouse fulfillment system with private business invariants "
            "(VIP discount must apply to ALL shipments, not just first).\n"
            "- **SWE-bench real case**: scikit-learn GaussianMixture bug in a 536-line file.\n\n"
            "Same scoring + timing protocol as parent."
        ),
        "prediction": (
            "If probe value scales with bug difficulty, gap should appear at N>=70 across these 4 benchmarks. "
            "Specifically expect Agent-Probe score > No-Probe by 0.5+ at p<0.05."
        ),
        "evidence": (
            "PRA-Bench: Agent-Probe 18/20 localized at score 2.75; No-Probe 18/20 at 2.95.\n"
            "ORB-Bench: 15/15 vs 15/15, scores 2.87 = 2.87 (identical).\n"
            "World-Bench: both found `idx == 0` bug with same mechanism, confidence 0.99 vs 0.98.\n"
            "SWE-bench: both found e-step ordering bug; No-Probe was 3× faster (14s vs 46s).\n\n"
            "Across 4 benchmarks and ~70 bugs: did not detect a gap at any scale tested. "
            "Branch is exhausted — no remaining narrowing in code domain has falsifiable headroom."
        ),
        "decision": (
            "Code-domain branch exhausted. The boundary discovered: **when the full causal chain from bug "
            "to symptom exists in readable code, LLM reasoning is sufficient**. "
            "This rules out the 'probes help in code' hypothesis but confirms the boundary is real. "
            "No further code-domain phases planned. Wait for sibling pivot-1 (OOD) to provide complementary evidence."
        ),
        "notes": (
            "All 4 benchmarks are within the 'info-in-code' quadrant of the 2D boundary "
            "(scale × observability). Future probes might still help in (large scale, info-not-in-code) "
            "but that's outside this branch's scope."
        ),
    },
    "diary": (
        "## rigor-1: Stronger code-domain retest\n"
        "Across PRA-Bench, ORB-Bench, World-Bench, and SWE-bench: still tied. "
        "Boundary discovered: when bug-to-symptom causal chain is in readable code, reasoning is sufficient. "
        "Branch exhausted."
    ),
}

PIVOT_1 = {
    "node": {
        "type": "pivot",
        "status": "supported",
        "claim": "Probing matters in genuinely OOD environments (BoxingGym Dugongs, hidden function).",
        "design": (
            "BoxingGym Dugongs: agent must predict body length given age. True function is "
            "`length = α - β * |λ|^age + noise` with α, β, λ randomly drawn each session — "
            "hidden by construction, not in training data.\n\n"
            "Two strategies, 5-observation budget each, then predict length on 5 held-out test ages:\n"
            "- **Random-Probe**: 5 ages chosen uniformly at random from [0, 5].\n"
            "- **Targeted-Probe**: subagent chooses each next age conditioned on observations so far.\n\n"
            "Predictor: same LLM agent (in this v1) reads the 5 (age, length) pairs and predicts. "
            "MSE measured on 5 test points. N=2 seeds initially."
        ),
        "prediction": (
            "If targeted probing builds a better representation of the hidden function, "
            "Targeted MSE < Random MSE by ≥ 30% on both seeds."
        ),
        "evidence": (
            "Seed 42: Random MSE 0.1003, Targeted MSE 0.0408 — 59% improvement.\n"
            "Seed 7:  Random MSE 0.0910, Targeted MSE 0.0519 — 43% improvement.\n"
            "Mean: Targeted MSE 0.0464 vs Random 0.0957, **51% MSE reduction across 2/2 seeds.**\n\n"
            "Apparent strategy: targeted agent picks endpoint (age=0), other endpoint (age=5), "
            "midpoint (age=2.5), then refines in steep region — classical informative experimental design."
        ),
        "decision": (
            "Provisional support — but the win could be coming from any of: "
            "(a) genuine adaptive probe selection, "
            "(b) trivial space-filling that any fixed grid would replicate, "
            "(c) LLM-as-predictor advantage that confounds observation quality with predictor prior. "
            "Spawn **rigor-2** to disambiguate: rigorous re-test with 15 seeds, GP regression predictor "
            "(removes (c)), and an explicit space-filling baseline (removes (b))."
        ),
        "notes": (
            "v1 only had N=2 seeds and used the LLM itself as both prober and predictor — "
            "any rigorous claim must control these out."
        ),
    },
    "diary": (
        "## pivot-1: BoxingGym Dugongs\n"
        "Targeted ≈ 50% MSE reduction on 2 seeds. Provisional. "
        "Spawning rigor-2 to control for predictor confound and space-filling."
    ),
}

RIGOR_2 = {
    "node": {
        "type": "rigor",
        "status": "not-detected",
        "claim": "Targeted probing beats space-filling on Dugongs at N=15 with GP regression predictor.",
        "design": (
            "Three observation strategies on the same Dugongs environment:\n\n"
            "- **Random**: 5 ages uniform on [0, 5].\n"
            "- **Fixed**: 5 ages on a deterministic space-filling grid [0, 1.25, 2.5, 3.75, 5].\n"
            "- **Targeted**: LLM agent picks each next age (no repeats allowed).\n\n"
            "Predictor: **Gaussian Process regression** (RBF kernel, MAP hyperparameters) — non-LLM, "
            "removes the predictor-prior confound. N=15 seeds with deterministic env params. "
            "Paired Wilcoxon signed-rank tests on MSE."
        ),
        "prediction": (
            "If targeted probing genuinely helps beyond space-filling, "
            "Targeted vs Fixed Wilcoxon p < 0.05 (one-sided, Targeted wins)."
        ),
        "evidence": (
            "Mean MSE: Random 0.296, Fixed 0.144, Targeted 0.184.\n"
            "Median MSE: Random 0.172, Fixed 0.121, Targeted 0.123.\n"
            "Wilcoxon (one-sided):\n"
            "  - Targeted vs Random: p = 0.227 (not detected)\n"
            "  - Targeted vs Fixed: p = 0.511 — did NOT detect a difference\n"
            "  - Fixed vs Random: p = 0.076 (marginal)\n\n"
            "The v1 'win' was an artifact: targeted LLM agent essentially picks endpoints + midpoint, "
            "a trivial space-filling heuristic that the explicit Fixed grid replicates exactly. "
            "Only signal is coverage > random — a known active-learning result, not a contribution."
        ),
        "decision": (
            "Probe-selection branch exhausted. The hypothesis 'targeted (adaptive) probing helps in OOD' "
            "is too narrow — the active variable might be something else. Spawn **reframe-1**: "
            "the deeper question may not be probe SELECTION but representation UPDATE — "
            "what happens AFTER observation, not how observations are picked."
        ),
        "notes": (
            "BoxingGym is a benchmark designed to reward probing — proving targeted > random on it is circular. "
            "The space-filling baseline is the right control. Future re-tests should use it by default."
        ),
    },
    "diary": (
        "## rigor-2: 15-seed retest + GP\n"
        "Did not detect Targeted vs Fixed difference (p=0.51). v1 was a trivial-heuristic artifact. "
        "Reframing the question: the variable might be representation update, not probe selection."
    ),
}

REFRAME_1 = {
    "node": {
        "type": "reframe",
        "status": "not-detected",
        "claim": (
            "Representation update is the variable that matters, not probe selection. "
            "(The prior claim 'targeted probing helps OOD' was too narrow.)"
        ),
        "design": (
            "Same observations across all conditions — Fixed grid [0, 1.25, 2.5, 3.75, 5], 15 seeds. "
            "The only manipulated variable is HOW the LLM processes the 5 (age, length) pairs:\n\n"
            "- **Implicit (I)**: one LLM call gets all 5 observations at once → predicts.\n"
            "- **Explicit-struct (E-struct)**: 5 sequential LLM calls maintaining a structured belief-state JSON "
            "(`{shape, intercept, asymptote, growth_rate, uncertainty}`); final call uses belief to predict.\n"
            "- **Explicit-free (E-free)**: free-form sequential reasoning trace, processing one observation "
            "at a time with running thoughts; final call predicts.\n\n"
            "If the prior claim was wrong because the active variable is representation update (not probe selection), "
            "then explicit belief tracking (E-struct or E-free) should beat one-shot Implicit on the same observations."
        ),
        "prediction": (
            "Explicit-struct MSE < Implicit MSE on matched seeds; Wilcoxon p < 0.05."
        ),
        "evidence": (
            "Mean MSE: Implicit 2.06, Explicit-struct 1.32, Explicit-free 1.97.\n"
            "Median MSE: Implicit 0.15, E-struct 0.20, E-free 0.18.\n"
            "Wilcoxon: E-struct vs Implicit p=0.62; E-free vs Implicit p=0.85.\n\n"
            "The mean difference for E-struct is driven by a single outlier seed (Seed 6: non-monotonic "
            "exploding function broke all conditions). On median, all three are equivalent. "
            "Did NOT detect difference under N=15."
        ),
        "decision": (
            "Externalizing belief state into the context (structured or free-form) does NOT measurably "
            "improve predictions over implicit one-shot processing. This is consistent with: "
            "**LLM forward pass already does the equivalent of belief update internally at this scale.** "
            "Synthesize this with the code-domain finding (rigor-1) into a boundary thesis: "
            "spawn **synth-1** merging rigor-1 + reframe-1."
        ),
        "notes": (
            "The bicycle analogy ('LLMs internalize observation→update as muscle memory') survives this "
            "test — but as the methodology requires, surviving = not falsified, not proven."
        ),
    },
    "diary": (
        "## reframe-1: representation update is internalized\n"
        "Explicit belief tracking ≈ implicit (p=0.62). The active variable is not probe selection. "
        "Reframe: rep update appears internalized at this scale. Synthesizing with rigor-1."
    ),
}

SYNTH_1 = {
    "node": {
        "type": "synthesis",
        "status": "supported",
        "claim": (
            "Boundary thesis: when causal information lives in readable code (rigor-1) OR in an "
            "LLM-internalized regime such as smooth functional fits (reframe-1), explicit probing "
            "and explicit representation update add no measurable benefit. Probes are valuable "
            "specifically OUTSIDE this internalized regime."
        ),
        "design": (
            "Synthesis node — combines findings from two non-overlapping arms:\n"
            "- **rigor-1**: 4 benchmarks, ~70 bugs, code-debug domain.\n"
            "- **reframe-1**: BoxingGym Dugongs, smooth functional fits.\n\n"
            "Both arms tested 'explicit (probe / belief-update) > implicit reasoning' under different "
            "framings; both produced did-not-detect at adequate N. The synthesis is a 2-dimensional "
            "boundary model: (info-locality × scale)."
        ),
        "prediction": (
            "If the boundary thesis is right, probes/explicit update should yield measurable benefit "
            "in the *complementary* regime: tasks where (a) state is hidden (database, runtime config, "
            "production traffic) OR (b) scale exceeds in-context reading capacity (multi-repo, >10⁵ tokens). "
            "Future phase to construct such a benchmark."
        ),
        "evidence": (
            "Rigor-1 + reframe-1 both did-not-detect under their respective N. The two arms agree on "
            "where the boundary lies: not 'probes are useless' but 'probes have no slack to add inside "
            "the LLM-internalized regime'. This is bounded evidence about effect size in this regime, "
            "consistent with effect being zero or small there."
        ),
        "decision": (
            "Productive next step: construct a benchmark **outside** this regime — e.g. live database "
            "where current row state is hidden from the LLM, or a multi-repo bug requiring information "
            "from files that exceed context. Spawn pivot-2 (or similar) to test the boundary's "
            "complement. The current synthesis should be treated as a hypothesis (not yet confirmed)."
        ),
        "notes": (
            "Two-arm agreement is not confirmation — it's coherent bounded evidence. The synthesis "
            "thesis needs an explicit complementary-regime experiment to graduate from 'supported' "
            "to 'confirmed'."
        ),
    },
    "diary": (
        "## synth-1: Boundary thesis\n"
        "Merged rigor-1 (code) + reframe-1 (rep update on smooth fits). "
        "Synthesis: probing and explicit update help only OUTSIDE the LLM-internalized regime. "
        "Productive next: construct a benchmark in the complementary regime."
    ),
}


# ──────────────────────────────────────────────────────────────────────────


def run(repo_path: Path, html_out: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path)

    step("init", cli(repo_path, "init", "--no-hook"))

    ctx = cli(repo_path, "context")
    step("context (empty)", ctx)

    step("commit root",
         cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(ROOT)))

    step("commit narrow (QuixBugs)",
         cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(NARROW_QUIXBUGS)))

    cli(repo_path, "branch", "--name", "rigor-1")
    step("commit rigor-1",
         cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(RIGOR_1)))

    cli(repo_path, "checkout", "main")
    cli(repo_path, "branch", "--name", "pivot-1")
    step("commit pivot-1",
         cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(PIVOT_1)))

    cli(repo_path, "branch", "--name", "rigor-2")
    step("commit rigor-2",
         cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(RIGOR_2)))

    cli(repo_path, "branch", "--name", "reframe-1")
    step("commit reframe-1",
         cli(repo_path, "commit", "--from-json", "-", stdin=json.dumps(REFRAME_1)))

    step("synthesize",
         cli(repo_path, "synthesize",
             "--new-branch", "synth-1",
             "--base", "rigor-1",
             "--other", "reframe-1",
             "--from-json", "-",
             stdin=json.dumps(SYNTH_1)))

    cli(repo_path, "render", "--out", str(html_out),
        "--title", "研究 thesis 树 — agent-driven demo",
        "--subtitle", "compressed re-enactment of the CoR study, fully populated nodes")

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
