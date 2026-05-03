"""Render a thesis tree to a self-contained HTML file.

Reads commits from the research repo, computes a depth/lane layout, and
emits SVG + a side detail panel showing each thesis-node's full content.
No external JS libraries required.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, List, Tuple

from .core import ResearchRepo


NODE_COLORS = {
    "root": "#6b7280",
    "narrow": "#3b82f6",
    "rigor": "#f59e0b",
    "reframe": "#a855f7",
    "pivot": "#ec4899",
    "synthesis": "#10b981",
    "unknown": "#9ca3af",
}

STATUS_BADGES = {
    "pending": "·",
    "supported": "✓",
    "not-detected": "?",
    "refuted": "✗",
    "ceiling-bound": "⊓",
    "exhausted": "∅",
}


def _topological_depth(nodes: List[dict]) -> Dict[str, int]:
    sha_to_node = {n["sha"]: n for n in nodes}
    depth: Dict[str, int] = {}
    for n in nodes:  # already topologically ordered (--reverse)
        if not n["parents"]:
            depth[n["sha"]] = 0
        else:
            parent_depths = [depth[p] for p in n["parents"] if p in depth]
            depth[n["sha"]] = (max(parent_depths) if parent_depths else 0) + 1
    return depth


def _assign_lanes(nodes: List[dict]) -> Dict[str, int]:
    """Each new branch gets a fresh rightward lane; narrow stays on parent's lane."""
    lane: Dict[str, int] = {}
    next_free = 0
    for n in nodes:
        t = n.get("type", "unknown")
        if not n["parents"]:
            lane[n["sha"]] = 0
            next_free = max(next_free, 1)
        elif t in {"rigor", "reframe", "pivot"}:
            lane[n["sha"]] = next_free
            next_free += 1
        elif t == "synthesis":
            # Synthesis takes a fresh lane of its own to make the merge readable
            lane[n["sha"]] = next_free
            next_free += 1
        else:  # narrow, root, unknown — stay on first parent's lane
            parent_lane = lane.get(n["parents"][0], 0)
            lane[n["sha"]] = parent_lane
    return lane


def compute_layout(nodes: List[dict]) -> Tuple[Dict[str, int], Dict[str, int]]:
    return _topological_depth(nodes), _assign_lanes(nodes)


_ROW_H = 80
_LANE_W = 140
_MARGIN_X = 60
_MARGIN_Y = 50
_RADIUS = 16


def _coord(depth: int, lane: int) -> Tuple[int, int]:
    return _MARGIN_X + lane * _LANE_W, _MARGIN_Y + depth * _ROW_H


def _edge_path(x1: int, y1: int, x2: int, y2: int) -> str:
    if x1 == x2:
        return f'<path d="M {x1} {y1} L {x2} {y2}" stroke="#cbd5e1" stroke-width="2" fill="none"/>'
    # bezier: drop down then curve sideways
    cx1, cy1 = x1, y1 + (y2 - y1) * 0.5
    cx2, cy2 = x2, y1 + (y2 - y1) * 0.5
    return (
        f'<path d="M {x1} {y1} C {cx1} {cy1}, {cx2} {cy2}, {x2} {y2}" '
        f'stroke="#cbd5e1" stroke-width="2" fill="none"/>'
    )


def _render_svg(nodes: List[dict], depth: Dict[str, int], lane: Dict[str, int]) -> str:
    if not nodes:
        return '<svg width="200" height="80"><text x="20" y="40">empty repo</text></svg>'
    max_depth = max(depth.values())
    max_lane = max(lane.values())
    width = _MARGIN_X * 2 + max_lane * _LANE_W
    height = _MARGIN_Y * 2 + max_depth * _ROW_H

    parts: List[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg" class="thesis-tree">'
    ]

    sha_to_node = {n["sha"]: n for n in nodes}
    # edges first
    for n in nodes:
        x2, y2 = _coord(depth[n["sha"]], lane[n["sha"]])
        for p_sha in n["parents"]:
            if p_sha not in sha_to_node:
                continue
            x1, y1 = _coord(depth[p_sha], lane[p_sha])
            parts.append(_edge_path(x1, y1, x2, y2))

    # nodes
    for n in nodes:
        x, y = _coord(depth[n["sha"]], lane[n["sha"]])
        t = n.get("type", "unknown")
        s = n.get("status", "pending")
        color = NODE_COLORS.get(t, NODE_COLORS["unknown"])
        badge = STATUS_BADGES.get(s, "·")
        short = n["short"]
        claim_short = (n.get("claim") or "")[:40]
        if len(n.get("claim") or "") > 40:
            claim_short += "…"
        parts.append(
            f'<g class="node" data-sha="{short}" onclick="focusNode(\'{short}\')">'
            f'  <circle cx="{x}" cy="{y}" r="{_RADIUS}" fill="{color}" '
            f'stroke="#1e293b" stroke-width="2"/>'
            f'  <text x="{x}" y="{y + 5}" text-anchor="middle" '
            f'font-size="14" font-weight="700" fill="white">{html.escape(badge)}</text>'
            f'  <text x="{x + _RADIUS + 8}" y="{y - 4}" font-size="11" '
            f'fill="#475569" font-family="monospace">{short} · {html.escape(t)}</text>'
            f'  <text x="{x + _RADIUS + 8}" y="{y + 10}" font-size="12" '
            f'fill="#0f172a">{html.escape(claim_short)}</text>'
            f"</g>"
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _render_panel(nodes: List[dict], branches: Dict[str, str]) -> str:
    sha_to_branches: Dict[str, List[str]] = {}
    for name, sha in branches.items():
        sha_to_branches.setdefault(sha, []).append(name)

    rows: List[str] = []
    for n in nodes:
        t = n.get("type", "unknown")
        s = n.get("status", "pending")
        color = NODE_COLORS.get(t, NODE_COLORS["unknown"])
        badge = STATUS_BADGES.get(s, "·")
        branch_pills = "".join(
            f'<span class="branch-pill">{html.escape(b)}</span>'
            for b in sha_to_branches.get(n["sha"], [])
        )
        review_html = ""
        comments = n.get("review_comments") or []
        if comments:
            items = "".join(f"<li>{html.escape(c)}</li>" for c in comments)
            review_html = f'<div class="review"><b>Review</b><ul>{items}</ul></div>'
        rows.append(
            f'<article id="node-{n["short"]}" class="node-card" data-type="{t}">'
            f'  <header style="border-left:6px solid {color}">'
            f'    <span class="badge">{html.escape(badge)}</span>'
            f'    <span class="short">{n["short"]}</span>'
            f'    <span class="type">{html.escape(t)}</span>'
            f'    <span class="status">{html.escape(s)}</span>'
            f"    {branch_pills}"
            f"  </header>"
            f'  <div class="claim"><b>Claim:</b> {html.escape(n.get("claim") or "")}</div>'
            f'  <div class="prediction"><b>Prediction:</b> {html.escape(n.get("prediction") or "—")}</div>'
            f'  <div class="evidence"><b>Evidence:</b> {html.escape(n.get("evidence") or "—")}</div>'
            f"  {review_html}"
            f"</article>"
        )
    return "\n".join(rows)


def _legend_html() -> str:
    type_items = "".join(
        f'<span class="legend-item"><span class="dot" style="background:{c}"></span>{html.escape(t)}</span>'
        for t, c in NODE_COLORS.items()
        if t != "unknown"
    )
    status_items = "".join(
        f'<span class="legend-item"><span class="badge-static">{html.escape(b)}</span>{html.escape(s)}</span>'
        for s, b in STATUS_BADGES.items()
    )
    return (
        f'<div class="legend"><div><b>Branching type</b> {type_items}</div>'
        f'<div><b>Status</b> {status_items}</div></div>'
    )


_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
         color: #0f172a; background: #f8fafc; }}
  header.top {{ padding: 18px 28px; background: white; border-bottom: 1px solid #e2e8f0; }}
  header.top h1 {{ margin: 0 0 4px; font-size: 18px; }}
  header.top .sub {{ color: #64748b; font-size: 13px; }}
  .legend {{ display: flex; gap: 32px; padding: 10px 28px; background: white; border-bottom: 1px solid #e2e8f0; font-size: 12px; }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 4px; margin-right: 12px; }}
  .legend .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .legend .badge-static {{ display: inline-flex; width: 18px; height: 18px; border-radius: 50%; background: #1e293b; color: white; align-items: center; justify-content: center; font-weight: 700; font-size: 11px; }}
  main {{ display: grid; grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr); gap: 0; }}
  .tree-pane {{ padding: 24px; overflow: auto; border-right: 1px solid #e2e8f0; background: white; }}
  .panel-pane {{ padding: 24px; overflow: auto; max-height: calc(100vh - 100px); }}
  svg.thesis-tree .node {{ cursor: pointer; }}
  svg.thesis-tree .node:hover circle {{ stroke: #2563eb; stroke-width: 3; }}
  .node-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 14px; overflow: hidden; transition: box-shadow 0.15s; }}
  .node-card.focused {{ box-shadow: 0 0 0 3px #2563eb; }}
  .node-card header {{ padding: 10px 14px; background: #f1f5f9; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px; }}
  .node-card .badge {{ display: inline-flex; width: 22px; height: 22px; border-radius: 50%; background: #1e293b; color: white; align-items: center; justify-content: center; font-weight: 700; }}
  .node-card .short {{ font-family: monospace; color: #475569; }}
  .node-card .type {{ font-weight: 600; }}
  .node-card .status {{ color: #64748b; }}
  .branch-pill {{ background: #1e293b; color: white; padding: 2px 8px; border-radius: 10px; font-family: monospace; font-size: 11px; }}
  .node-card .claim, .node-card .prediction, .node-card .evidence, .node-card .review {{
    padding: 8px 14px; font-size: 13px; line-height: 1.5; border-top: 1px solid #f1f5f9; }}
  .review {{ background: #fef3c7; }}
  .review ul {{ margin: 4px 0 0; padding-left: 20px; }}
</style>
</head>
<body>
<header class="top">
  <h1>{title}</h1>
  <div class="sub">{subtitle}</div>
</header>
{legend}
<main>
  <section class="tree-pane">{svg}</section>
  <section class="panel-pane">{panel}</section>
</main>
<script>
  function focusNode(short) {{
    document.querySelectorAll('.node-card.focused').forEach(e => e.classList.remove('focused'));
    var el = document.getElementById('node-' + short);
    if (el) {{ el.classList.add('focused'); el.scrollIntoView({{ behavior: 'smooth', block: 'center' }}); }}
  }}
</script>
</body>
</html>
"""


def render_html(
    repo: ResearchRepo,
    output: Path,
    title: str = "Research Thesis Tree",
    subtitle: str = "",
) -> None:
    output = Path(output)
    nodes = repo.all_nodes()
    branches = repo.all_branches()
    depth, lane = compute_layout(nodes)
    svg = _render_svg(nodes, depth, lane)
    panel = _render_panel(nodes, branches)
    legend = _legend_html()
    if not subtitle:
        subtitle = f"{len(nodes)} thesis-nodes · {len(branches)} branches"
    html_doc = _TEMPLATE.format(
        title=html.escape(title),
        subtitle=html.escape(subtitle),
        svg=svg,
        panel=panel,
        legend=legend,
    )
    output.write_text(html_doc)
