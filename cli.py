"""Agent-callable CLI for the research harness.

Designed so a Claude Code (or similar) session can drive the loop without
any Python imports — just shell calls. Every subcommand prints structured
JSON to stdout (machine-readable) and a short human summary to stderr.

Typical agent loop:
    harness context --repo R                # orient: where am I, what's been tried
    harness commit  --repo R --type narrow --claim ... --prediction ... --evidence ... --status ...
    # (review comments are returned in the commit response)
    harness context --repo R                # orient again
    harness branch  --repo R --name rigor-1  # if forking
    ...
    harness render  --repo R --out tree.html

Run subcommands with --help for full args.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from .core import ResearchRepo, ThesisNode, VALID_TYPES, VALID_STATUSES
from .render import render_html
from .reviewer import review as review_node
from .server import ResearchServer
from .publisher import SupabasePublisher, env as env_lookup


def _emit(payload: dict, summary: str = "") -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if summary:
        print(summary, file=sys.stderr)


def _err(msg: str, code: int = 1) -> int:
    json.dump({"ok": False, "error": msg}, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    print(f"error: {msg}", file=sys.stderr)
    return code


def _load_payload(args) -> dict:
    """Read --from-json payload once (caches on args._payload)."""
    if not args.from_json:
        return {}
    if hasattr(args, "_payload"):
        return args._payload
    path = Path(args.from_json)
    raw = sys.stdin.read() if str(path) == "-" else path.read_text()
    args._payload = json.loads(raw)
    return args._payload


def _read_node_from_args(args) -> ThesisNode:
    """Build a ThesisNode from CLI args, supporting --from-json for big payloads."""
    if args.from_json:
        data = _load_payload(args)
        # Allow {"node": {...}, "diary": "..."} or just a flat node dict
        if isinstance(data, dict) and "node" in data:
            data = data["node"]
        return ThesisNode(**data)
    return ThesisNode(
        claim=args.claim or "",
        prediction=args.prediction or "",
        evidence=args.evidence or "",
        status=args.status,
        type=args.type,
        notes=args.notes or "",
    )


def _read_diary_from_args(args) -> str:
    if args.from_json:
        data = _load_payload(args)
        if isinstance(data, dict) and "diary" in data:
            return data["diary"]
    return args.diary or ""


# ---------------- subcommands ----------------


def cmd_init(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    if (repo.path / ".git").exists():
        return _err(f"repo already initialized at {repo.path}")
    repo.init()
    target = _resolve_hook_target(args)
    hook_installed = False
    if target:
        hook_installed = _install_hook(repo, slug=args.slug or repo.path.name, target=target)
    _emit(
        {
            "ok": True,
            "repo": str(repo.path),
            "branch": repo.current_branch(),
            "post_commit_hook": hook_installed,
            "hook_target": target,
        },
        f"initialized {repo.path} on branch {repo.current_branch()}"
        + (f" (post-commit hook → {target})" if hook_installed else ""),
    )
    return 0


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_hook_target(args):
    """Pick a hook target: explicit flag wins, else env-driven, else None."""
    if getattr(args, "no_hook", False):
        return None
    target = getattr(args, "hook_target", None)
    if target == "auto" or target is None:
        if env_lookup("VERCEL_TOKEN"):
            return "vercel"
        if env_lookup("SUPABASE_URL"):
            return "supabase"
        return None
    return target


def _install_hook(repo: ResearchRepo, slug: str, target: str = "vercel") -> bool:
    if target not in {"vercel", "supabase"}:
        raise ValueError(f"unknown hook target {target!r}")
    hook_path = repo.path / ".git" / "hooks" / "post-commit"
    project_root = _project_root()
    sub = "deploy" if target == "vercel" else "publish"
    script = (
        "#!/bin/sh\n"
        f"# auto-installed by harness — runs `harness {sub}` after every commit.\n"
        "# failures are non-fatal: commits succeed regardless of network.\n"
        f'PROJECT_ROOT="{project_root}"\n'
        f'REPO="{repo.path}"\n'
        f'SLUG="{slug}"\n'
        'cd "$PROJECT_ROOT" || exit 0\n'
        f'{{ python3 -m harness.cli --repo "$REPO" {sub} --slug "$SLUG" --quiet; }} '
        f'>"$REPO/.git/last-{sub}.log" 2>&1 || true\n'
    )
    hook_path.write_text(script)
    hook_path.chmod(0o755)
    return True


def cmd_install_hook(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    if not (repo.path / ".git").exists():
        return _err(f"not a git repo: {repo.path}")
    slug = args.slug or repo.path.name
    target = args.hook_target
    if target == "auto":
        target = _resolve_hook_target(args) or "vercel"
    _install_hook(repo, slug, target=target)
    _emit(
        {
            "ok": True,
            "hook": str(repo.path / ".git" / "hooks" / "post-commit"),
            "slug": slug,
            "target": target,
        },
        f"installed post-commit hook (slug={slug}, target={target})",
    )
    return 0


def cmd_publish(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    slug = args.slug or repo.path.name
    try:
        pub = SupabasePublisher.from_env()
    except RuntimeError as e:
        return _err(str(e))
    results = pub.sync_repo(repo, repo_slug=slug)
    payload = {
        "ok": True,
        "slug": slug,
        "results": {k: {"rows": r.rows_sent, "status": r.status} for k, r in results.items()},
    }
    if args.quiet:
        # still emit JSON for caller, but skip stderr summary
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _emit(
            payload,
            "published "
            + ", ".join(f"{k}={r.rows_sent}" for k, r in results.items()),
        )
    return 0


def cmd_commit(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    try:
        node = _read_node_from_args(args)
    except (TypeError, ValueError) as e:
        return _err(f"invalid node: {e}")
    diary = _read_diary_from_args(args)
    node.review_comments = review_node(node)
    sha = repo.commit_node(node, diary_append=diary)
    _emit(
        {
            "ok": True,
            "sha": sha,
            "short": sha[:7],
            "branch": repo.current_branch(),
            "type": node.type,
            "status": node.status,
            "review_comments": node.review_comments,
        },
        f"committed {sha[:7]} on {repo.current_branch()} "
        f"[{node.type}/{node.status}] (reviews: {len(node.review_comments)})",
    )
    return 0


def cmd_branch(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    repo.new_branch(args.name, from_ref=args.from_ref)
    _emit(
        {"ok": True, "branch": repo.current_branch(), "tip": repo.head_sha()},
        f"branched to {args.name} from {args.from_ref or 'HEAD'}",
    )
    return 0


def cmd_checkout(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    repo.checkout(args.ref)
    _emit(
        {"ok": True, "branch": repo.current_branch(), "tip": repo.head_sha()},
        f"checked out {args.ref}",
    )
    return 0


def cmd_synthesize(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    try:
        node = _read_node_from_args(args)
    except (TypeError, ValueError) as e:
        return _err(f"invalid node: {e}")
    if node.type != "synthesis":
        return _err("synthesize requires --type synthesis")
    diary = _read_diary_from_args(args)
    node.review_comments = review_node(node)
    sha = repo.synthesize(
        new_branch_name=args.new_branch,
        base_branch=args.base,
        other_branch=args.other,
        node=node,
        diary_append=diary,
    )
    _emit(
        {
            "ok": True,
            "sha": sha,
            "short": sha[:7],
            "branch": repo.current_branch(),
            "review_comments": node.review_comments,
        },
        f"synthesis {sha[:7]} on {args.new_branch} merging {args.base} ← {args.other}",
    )
    return 0


def cmd_review(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    content = (repo.path / "thesis.json").read_text()
    node = ThesisNode.from_json(content)
    comments = review_node(node)
    _emit(
        {"ok": True, "comments": comments, "node": asdict(node)},
        f"{len(comments)} review comment(s)",
    )
    return 0


def cmd_list(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    nodes = repo.all_nodes()
    branches = repo.all_branches()
    _emit(
        {"ok": True, "nodes": nodes, "branches": branches},
        f"{len(nodes)} node(s), {len(branches)} branch(es)",
    )
    return 0


def cmd_context(args) -> int:
    """Orient the agent: where am I, what siblings exist, what's recently been tried."""
    repo = ResearchRepo(Path(args.repo))
    nodes = repo.all_nodes()
    branches = repo.all_branches()
    if not nodes:
        _emit(
            {
                "ok": True,
                "empty": True,
                "current_branch": repo.current_branch(),
                "valid_next_actions": ["commit (root)"],
                "valid_types": sorted(VALID_TYPES),
                "valid_statuses": sorted(VALID_STATUSES),
            },
            "empty repo — start with a root commit",
        )
        return 0

    sha_to_node = {n["sha"]: n for n in nodes}
    current_branch = repo.current_branch()
    tip_sha = repo.head_sha()
    current_tip = sha_to_node.get(tip_sha)

    # Walk ancestors from tip back to root, attach minimal info
    ancestors = []
    cursor = tip_sha
    seen = set()
    while cursor and cursor in sha_to_node and cursor not in seen:
        seen.add(cursor)
        n = sha_to_node[cursor]
        ancestors.append(
            {
                "short": n["short"],
                "type": n.get("type"),
                "status": n.get("status"),
                "claim": n.get("claim"),
            }
        )
        if n["parents"]:
            cursor = n["parents"][0]
        else:
            cursor = None

    # All branch tips with status (so agent knows what other branches have concluded)
    branch_tips = []
    for name, sha in branches.items():
        if sha in sha_to_node:
            n = sha_to_node[sha]
            branch_tips.append(
                {
                    "branch": name,
                    "short": n["short"],
                    "type": n.get("type"),
                    "status": n.get("status"),
                    "claim": n.get("claim"),
                }
            )

    # Recent diary tail (if exists)
    diary_path = repo.path / "FINDINGS.md"
    diary_tail = ""
    if diary_path.exists():
        diary = diary_path.read_text()
        # last ~30 lines
        diary_tail = "\n".join(diary.splitlines()[-30:])

    payload = {
        "ok": True,
        "current_branch": current_branch,
        "current_tip": current_tip,
        "ancestors": ancestors,
        "all_branch_tips": branch_tips,
        "diary_tail": diary_tail,
        "node_count": len(nodes),
        "branch_count": len(branches),
        "valid_types": sorted(VALID_TYPES),
        "valid_statuses": sorted(VALID_STATUSES),
        "valid_next_actions": [
            "narrow (commit on current branch)",
            "branch + commit (rigor / reframe / pivot)",
            "checkout <ref> + branch (backtrack to parent and try a different fork)",
            "synthesize (merge two branches into a new synthesis node)",
            "stop",
        ],
    }
    _emit(
        payload,
        f"on {current_branch} @ {current_tip['short'] if current_tip else '?'} "
        f"({len(nodes)} nodes, {len(branches)} branches)",
    )
    return 0


def cmd_render(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    out = Path(args.out)
    render_html(repo, out, title=args.title, subtitle=args.subtitle)
    _emit(
        {"ok": True, "out": str(out)},
        f"rendered {out}",
    )
    return 0


def cmd_deploy(args) -> int:
    """Render the repo to a static HTML snapshot and deploy it to Vercel."""
    import re
    import shutil as _shutil
    import subprocess as _sp
    import tempfile

    repo = ResearchRepo(Path(args.repo))
    token = args.token or env_lookup("VERCEL_TOKEN")
    if not token:
        return _err("missing VERCEL_TOKEN (env or --token)")
    project = args.project or env_lookup("VERCEL_PROJECT") or repo.path.name
    scope = args.scope or env_lookup("VERCEL_SCOPE")
    refresh = args.refresh

    dist = Path(tempfile.mkdtemp(prefix="harness_deploy_"))
    try:
        out_html = dist / "index.html"
        render_html(
            repo,
            out_html,
            title=args.title or f"Research Thesis Tree — {project}",
            subtitle=args.subtitle or "static snapshot from local git",
        )
        if refresh > 0:
            html = out_html.read_text()
            html = html.replace(
                "</head>",
                f'<meta http-equiv="refresh" content="{refresh}"></head>',
                1,
            )
            out_html.write_text(html)

        cmd = [
            args.npx or "npx", "vercel@latest", "deploy",
            "--token", token, "--prod", "--yes", "--name", project,
        ]
        if scope:
            cmd.extend(["--scope", scope])

        runner = getattr(args, "_runner", None) or _sp.run
        result = runner(cmd, cwd=dist, capture_output=True, text=True, check=False)
    finally:
        _shutil.rmtree(dist, ignore_errors=True)

    if result.returncode != 0:
        return _err(f"vercel deploy failed: {(result.stderr or result.stdout)[-500:]}")

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    url = None
    alias_pat = re.compile(r"https://" + re.escape(project) + r"\.vercel\.app\b")
    m = alias_pat.search(combined)
    if m:
        url = m.group(0)
    else:
        m = re.search(r"https://[a-zA-Z0-9-]+\.vercel\.app\b", combined)
        if m:
            url = m.group(0)

    payload = {"ok": True, "project": project, "url": url}
    if args.quiet:
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _emit(payload, f"deployed {project} → {url}")
    return 0


def cmd_build_dashboard(args) -> int:
    """Bake SUPABASE_URL/ANON_KEY into the static dashboard.html for the repo slug."""
    src = Path(__file__).resolve().parent / "dashboard.html"
    if not src.exists():
        return _err(f"dashboard template missing at {src}")
    url = env_lookup("SUPABASE_URL")
    anon = env_lookup("SUPABASE_ANON_KEY")
    if not url or not anon:
        return _err("missing SUPABASE_URL / SUPABASE_ANON_KEY (env or harness/.env)")
    slug = args.slug or Path(args.repo).name
    template = src.read_text()
    inject = (
        f'<script>'
        f'window.SUPABASE_URL="{url}";'
        f'window.SUPABASE_ANON_KEY="{anon}";'
        f'window.REPO_SLUG="{slug}";'
        f'</script>'
    )
    built = template.replace("</head>", inject + "</head>")
    out = Path(args.out)
    out.write_text(built)
    _emit(
        {"ok": True, "out": str(out), "slug": slug, "url": url},
        f"dashboard built at {out} (slug={slug})",
    )
    return 0


def cmd_serve(args) -> int:
    repo = ResearchRepo(Path(args.repo))
    server = ResearchServer(repo, host=args.host, port=args.port).start()
    msg = (
        f"serving thesis dashboard at {server.url}\n"
        f"  /         — live tree (auto-refresh on commit)\n"
        f"  /version  — current version hash\n"
        f"  /diary    — raw FINDINGS.md\n"
        f"  /health   — liveness probe\n"
        f"watching repo: {repo.path}\n"
        f"press Ctrl-C to stop."
    )
    print(msg, file=sys.stderr)
    _emit({"ok": True, "url": server.url, "host": server.host, "port": server.port})
    try:
        server._thread.join()  # type: ignore[union-attr]
    except KeyboardInterrupt:
        print("\nshutting down...", file=sys.stderr)
        server.stop()
    return 0


# ---------------- arg parsing ----------------


def _add_node_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--type", choices=sorted(VALID_TYPES), default="narrow")
    p.add_argument("--status", choices=sorted(VALID_STATUSES), default="pending")
    p.add_argument("--claim", default=None)
    p.add_argument("--prediction", default=None)
    p.add_argument("--evidence", default=None)
    p.add_argument("--notes", default=None)
    p.add_argument("--diary", default=None, help="appended to FINDINGS.md")
    p.add_argument(
        "--from-json",
        default=None,
        help="path to JSON file with a thesis-node payload (or '-' for stdin)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness")
    parser.add_argument("--repo", required=True, help="research repo path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="initialize a fresh research repo")
    p.add_argument("--no-hook", action="store_true",
                   help="skip post-commit hook entirely")
    p.add_argument("--slug", default=None,
                   help="repo slug (default: dir basename)")
    p.add_argument("--hook-target", choices=["auto", "vercel", "supabase"],
                   default="auto",
                   help="which target the post-commit hook calls (default: auto)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("install-hook", help="install post-commit hook")
    p.add_argument("--slug", default=None)
    p.add_argument("--hook-target", choices=["auto", "vercel", "supabase"],
                   default="auto")
    p.set_defaults(func=cmd_install_hook)

    p = sub.add_parser("publish", help="sync git state to Supabase")
    p.add_argument("--slug", default=None)
    p.add_argument("--quiet", action="store_true",
                   help="suppress stderr summary (used by post-commit hook)")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("deploy", help="render snapshot and deploy to Vercel")
    p.add_argument("--slug", default=None,
                   help="(unused; accepted for hook-script compatibility)")
    p.add_argument("--project", default=None,
                   help="vercel project name (default: repo basename or VERCEL_PROJECT)")
    p.add_argument("--scope", default=None,
                   help="vercel team scope (default: VERCEL_SCOPE)")
    p.add_argument("--token", default=None,
                   help="vercel token (default: VERCEL_TOKEN env)")
    p.add_argument("--title", default=None)
    p.add_argument("--subtitle", default=None)
    p.add_argument("--refresh", type=int, default=30,
                   help="auto-refresh interval in seconds (0 = disabled)")
    p.add_argument("--npx", default=None,
                   help="path to npx executable (default: 'npx')")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("commit", help="commit a thesis node on the current branch")
    _add_node_args(p)
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("branch", help="create a new branch")
    p.add_argument("--name", required=True)
    p.add_argument("--from-ref", default=None, help="ref to branch from (default: HEAD)")
    p.set_defaults(func=cmd_branch)

    p = sub.add_parser("checkout", help="checkout a branch or commit")
    p.add_argument("ref")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("synthesize", help="merge two branches into a new synthesis node")
    p.add_argument("--new-branch", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--other", required=True)
    _add_node_args(p)
    p.set_defaults(func=cmd_synthesize)

    sub.add_parser("review", help="re-run reviewer on the current HEAD's thesis").set_defaults(func=cmd_review)

    sub.add_parser("list", help="list all nodes and branches").set_defaults(func=cmd_list)

    sub.add_parser("context", help="orientation dump for the agent").set_defaults(func=cmd_context)

    p = sub.add_parser("render", help="render the thesis tree to HTML")
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="Research Thesis Tree")
    p.add_argument("--subtitle", default="")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("build-dashboard",
                       help="bake supabase URL+anon key into dashboard.html for offline use")
    p.add_argument("--out", required=True)
    p.add_argument("--slug", default=None)
    p.set_defaults(func=cmd_build_dashboard)

    p = sub.add_parser("serve", help="start the live HTTP dashboard (git-poll fallback)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
