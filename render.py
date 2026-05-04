"""Render a thesis tree to a self-contained HTML file.

Layout: horizontal (depth → x, lane → y). Tree grows rightward over time.
Click a node to open a modal with its full thesis content. The "日记"
button opens FINDINGS.md content in a modal.

UI chrome: Chinese (中文). Thesis content (claim/prediction/evidence/diary)
passes through as-stored — if the repo is in English, the modal shows
English text inside Chinese chrome.

No external JS libs.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
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

TYPE_ZH = {
    "root": "根",
    "narrow": "收敛",
    "rigor": "严格化",
    "reframe": "重构",
    "pivot": "转向",
    "synthesis": "综合",
    "unknown": "未知",
}

STATUS_ZH = {
    "pending": "待定",
    "supported": "已支持",
    "not-detected": "未检出",
    "refuted": "已反驳",
    "ceiling-bound": "触顶",
    "exhausted": "已穷尽",
}


# ── layout (orientation-independent) ──────────────────────────────────────


def _topological_depth(nodes: List[dict]) -> Dict[str, int]:
    sha_to_node = {n["sha"]: n for n in nodes}
    depth: Dict[str, int] = {}
    for n in nodes:
        if not n["parents"]:
            depth[n["sha"]] = 0
        else:
            parent_depths = [depth[p] for p in n["parents"] if p in depth]
            depth[n["sha"]] = (max(parent_depths) if parent_depths else 0) + 1
    return depth


def _assign_lanes(nodes: List[dict]) -> Dict[str, int]:
    """Each new branch gets a fresh lane; narrow stays on parent's lane."""
    lane: Dict[str, int] = {}
    next_free = 0
    for n in nodes:
        t = n.get("type", "unknown")
        if not n["parents"]:
            lane[n["sha"]] = 0
            next_free = max(next_free, 1)
        elif t in {"rigor", "reframe", "pivot", "synthesis"}:
            lane[n["sha"]] = next_free
            next_free += 1
        else:
            parent_lane = lane.get(n["parents"][0], 0)
            lane[n["sha"]] = parent_lane
    return lane


def compute_layout(nodes: List[dict]) -> Tuple[Dict[str, int], Dict[str, int]]:
    return _topological_depth(nodes), _assign_lanes(nodes)


# ── SVG rendering (horizontal: depth → x, lane → y) ───────────────────────


_COL_W = 200
_ROW_H = 90
_MARGIN_X = 60
_MARGIN_Y = 60
_RADIUS = 18


def _coord(depth: int, lane: int) -> Tuple[int, int]:
    return _MARGIN_X + depth * _COL_W, _MARGIN_Y + lane * _ROW_H


def _edge_path(x1: int, y1: int, x2: int, y2: int) -> str:
    if y1 == y2:
        return (f'<path d="M {x1} {y1} L {x2} {y2}" '
                f'stroke="#cbd5e1" stroke-width="2" fill="none"/>')
    mx = x1 + (x2 - x1) * 0.5
    return (
        f'<path d="M {x1} {y1} C {mx} {y1}, {mx} {y2}, {x2} {y2}" '
        f'stroke="#cbd5e1" stroke-width="2" fill="none"/>'
    )


def _render_svg(nodes: List[dict], depth: Dict[str, int], lane: Dict[str, int]) -> str:
    if not nodes:
        return '<div class="empty">空仓库</div>'
    max_depth = max(depth.values())
    max_lane = max(lane.values())
    width = _MARGIN_X * 2 + max_depth * _COL_W
    height = _MARGIN_Y * 2 + max_lane * _ROW_H

    parts: List[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg" class="thesis-tree" '
        'preserveAspectRatio="xMinYMid meet">'
    ]

    sha_to_node = {n["sha"]: n for n in nodes}
    for n in nodes:
        x2, y2 = _coord(depth[n["sha"]], lane[n["sha"]])
        for p_sha in n["parents"]:
            if p_sha not in sha_to_node:
                continue
            x1, y1 = _coord(depth[p_sha], lane[p_sha])
            parts.append(_edge_path(x1, y1, x2, y2))

    for n in nodes:
        x, y = _coord(depth[n["sha"]], lane[n["sha"]])
        t = n.get("type", "unknown")
        s = n.get("status", "pending")
        color = NODE_COLORS.get(t, NODE_COLORS["unknown"])
        badge = STATUS_BADGES.get(s, "·")
        short = n["short"]
        type_label = html.escape(TYPE_ZH.get(t, t))
        claim_short = (n.get("claim") or "")
        if len(claim_short) > 28:
            claim_short = claim_short[:28] + "…"
        parts.append(
            f'<g class="node" data-sha="{short}" onclick="window.openNode(\'{short}\')" tabindex="0">'
            f'  <circle cx="{x}" cy="{y}" r="{_RADIUS}" fill="{color}" '
            f'stroke="#1e293b" stroke-width="2"/>'
            f'  <text x="{x}" y="{y + 5}" text-anchor="middle" '
            f'font-size="14" font-weight="700" fill="white">{html.escape(badge)}</text>'
            f'  <text x="{x}" y="{y - _RADIUS - 8}" text-anchor="middle" '
            f'font-size="10" fill="#64748b" font-family="monospace">{short}</text>'
            f'  <text x="{x}" y="{y + _RADIUS + 14}" text-anchor="middle" '
            f'font-size="11" font-weight="600" fill="{color}">{type_label}</text>'
            f'  <text x="{x}" y="{y + _RADIUS + 28}" text-anchor="middle" '
            f'font-size="11" fill="#0f172a">{html.escape(claim_short)}</text>'
            f"</g>"
        )
    parts.append("</svg>")
    return "\n".join(parts)


# ── node payload (embedded JSON for modal) ────────────────────────────────


def _node_payload(n: dict, branches: Dict[str, str]) -> dict:
    sha_to_branches: Dict[str, List[str]] = {}
    for name, sha in branches.items():
        sha_to_branches.setdefault(sha, []).append(name)
    return {
        "short": n["short"],
        "sha": n["sha"],
        "type": n.get("type", "unknown"),
        "status": n.get("status", "pending"),
        "claim": n.get("claim") or "",
        "prediction": n.get("prediction") or "",
        "evidence": n.get("evidence") or "",
        "notes": n.get("notes") or "",
        "review_comments": n.get("review_comments") or [],
        "parents": n.get("parents") or [],
        "branches": sha_to_branches.get(n["sha"], []),
    }


# ── markdown → light HTML ─────────────────────────────────────────────────


_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE = re.compile(r"`([^`\n]+)`")


def _md_to_html(md: str) -> str:
    if not md:
        return ""
    md = html.escape(md)
    md = _BOLD.sub(r"<strong>\1</strong>", md)
    md = _ITALIC.sub(r"<em>\1</em>", md)
    md = _CODE.sub(r"<code>\1</code>", md)

    out: List[str] = []
    para: List[str] = []

    def flush():
        if para:
            text = " ".join(p for p in para if p).strip()
            if text:
                out.append(f"<p>{text}</p>")
            para.clear()

    for raw in md.split("\n"):
        line = raw.rstrip()
        if line.startswith("### "):
            flush()
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            flush()
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            flush()
            out.append(f"<h1>{line[2:]}</h1>")
        elif not line:
            flush()
        else:
            para.append(line)
    flush()
    return "\n".join(out)


# ── legend ────────────────────────────────────────────────────────────────


def _legend_html() -> str:
    type_items = "".join(
        f'<span class="legend-item"><span class="dot" style="background:{c}"></span>'
        f'{html.escape(TYPE_ZH.get(t, t))}</span>'
        for t, c in NODE_COLORS.items()
        if t != "unknown"
    )
    status_items = "".join(
        f'<span class="legend-item"><span class="badge-static">{html.escape(b)}</span>'
        f'{html.escape(STATUS_ZH.get(s, s))}</span>'
        for s, b in STATUS_BADGES.items()
    )
    return (
        f'<div class="legend">'
        f'<div><b>分支类型</b> {type_items}</div>'
        f'<div><b>状态</b> {status_items}</div>'
        f'</div>'
    )


# ── HTML template ─────────────────────────────────────────────────────────


_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
         color: #0f172a; background: #f8fafc; }}
  header.top {{ padding: 16px 28px; background: white; border-bottom: 1px solid #e2e8f0;
                display: flex; align-items: center; gap: 16px; }}
  header.top h1 {{ margin: 0; font-size: 17px; }}
  header.top .sub {{ color: #64748b; font-size: 13px; }}
  header.top .actions {{ margin-left: auto; display: flex; gap: 8px; }}
  header.top button {{ padding: 6px 14px; border: 1px solid #cbd5e1; border-radius: 6px;
                       background: white; cursor: pointer; font-size: 13px; color: #0f172a; }}
  header.top button:hover {{ background: #f1f5f9; }}
  .legend {{ display: flex; gap: 32px; padding: 10px 28px; background: white;
             border-bottom: 1px solid #e2e8f0; font-size: 12px; flex-wrap: wrap; }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 4px; margin-right: 12px; }}
  .legend .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .legend .badge-static {{ display: inline-flex; width: 18px; height: 18px; border-radius: 50%;
                            background: #1e293b; color: white; align-items: center; justify-content: center;
                            font-weight: 700; font-size: 11px; }}
  main {{ padding: 24px; overflow: auto; min-height: calc(100vh - 130px); }}
  svg.thesis-tree {{ max-width: 100%; }}
  svg.thesis-tree .node {{ cursor: pointer; }}
  svg.thesis-tree .node:hover circle {{ stroke: #2563eb; stroke-width: 3; }}
  svg.thesis-tree .node:focus {{ outline: none; }}
  svg.thesis-tree .node:focus circle {{ stroke: #2563eb; stroke-width: 3; }}
  .empty {{ padding: 40px; color: #64748b; text-align: center; }}

  /* modal */
  .modal-overlay {{ position: fixed; inset: 0; background: rgba(15,23,42,0.55);
                     display: none; align-items: center; justify-content: center;
                     padding: 24px; z-index: 100; }}
  .modal-overlay.open {{ display: flex; }}
  .modal-card {{ background: white; border-radius: 12px; max-width: 720px; width: 100%;
                  max-height: 85vh; overflow: auto; box-shadow: 0 24px 60px rgba(15,23,42,0.3);
                  position: relative; }}
  .modal-close {{ position: absolute; top: 12px; right: 12px; border: none; background: transparent;
                   font-size: 22px; cursor: pointer; color: #64748b; line-height: 1; }}
  .modal-close:hover {{ color: #0f172a; }}
  .modal-body {{ padding: 28px 28px 24px; }}
  .modal-body h2 {{ margin: 0 0 8px; font-size: 18px; }}
  .modal-body .meta {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
                       font-size: 12px; margin-bottom: 16px; }}
  .modal-body .meta .badge {{ display: inline-flex; width: 22px; height: 22px; border-radius: 50%;
                               background: #1e293b; color: white; align-items: center; justify-content: center;
                               font-weight: 700; }}
  .modal-body .meta .short {{ font-family: monospace; color: #475569; }}
  .modal-body .branch-pill {{ background: #1e293b; color: white; padding: 2px 8px; border-radius: 10px;
                              font-family: monospace; font-size: 11px; }}
  .modal-body section {{ margin-top: 14px; }}
  .modal-body section h3 {{ margin: 0 0 4px; font-size: 13px; color: #64748b; font-weight: 600;
                            text-transform: uppercase; letter-spacing: 0.04em; }}
  .modal-body section .body {{ font-size: 14px; line-height: 1.55; white-space: pre-wrap;
                                word-wrap: break-word; }}
  .modal-body .reviews {{ background: #fef3c7; border-radius: 8px; padding: 10px 14px; margin-top: 14px; }}
  .modal-body .reviews ul {{ margin: 4px 0 0; padding-left: 20px; }}

  /* diary modal larger */
  .modal-card.wide {{ max-width: 960px; }}
  .diary-content h1 {{ font-size: 22px; margin-top: 0; }}
  .diary-content h2 {{ font-size: 18px; margin-top: 28px; padding-bottom: 6px; border-bottom: 1px solid #e2e8f0; }}
  .diary-content h3 {{ font-size: 15px; margin-top: 20px; color: #334155; }}
  .diary-content p  {{ font-size: 14px; line-height: 1.65; }}
  .diary-content code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 3px;
                          font-size: 13px; }}
</style>
</head>
<body>
<header class="top">
  <h1>{title}</h1>
  <span class="sub">{subtitle}</span>
  <div class="actions">
    <button onclick="window.openDiary()">日记</button>
  </div>
</header>
{legend}
<main>{svg}</main>

<div id="modal-overlay" class="modal-overlay" onclick="window.closeModalIfBackdrop(event)">
  <div class="modal-card" id="modal-card" role="dialog" aria-modal="true">
    <button class="modal-close" onclick="window.closeModal()" aria-label="关闭">×</button>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<script>
const NODES = {nodes_json};
const NODES_BY_SHORT = Object.fromEntries(NODES.map(n => [n.short, n]));
const TYPE_ZH = {type_zh_json};
const STATUS_ZH = {status_zh_json};
const STATUS_BADGES = {status_badges_json};
const NODE_COLORS = {node_colors_json};
const DIARY_HTML = {diary_json};

function escapeHtml(s) {{
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}}

function renderNodeModal(n) {{
  const color = NODE_COLORS[n.type] || NODE_COLORS.unknown;
  const badge = STATUS_BADGES[n.status] || "·";
  const branchPills = (n.branches || []).map(b =>
    `<span class="branch-pill">${{escapeHtml(b)}}</span>`).join("");
  const reviews = (n.review_comments || []).length
    ? `<div class="reviews"><b>审阅</b><ul>${{
        n.review_comments.map(c => `<li>${{escapeHtml(c)}}</li>`).join("")
      }}</ul></div>`
    : "";
  const sec = (label, body) => body
    ? `<section><h3>${{label}}</h3><div class="body">${{escapeHtml(body)}}</div></section>`
    : "";
  return `
    <h2 style="border-left: 6px solid ${{color}}; padding-left: 12px;">
      ${{escapeHtml(n.claim || "")}}
    </h2>
    <div class="meta">
      <span class="badge">${{escapeHtml(badge)}}</span>
      <span class="short">${{escapeHtml(n.short)}}</span>
      <span><b>类型</b>: ${{escapeHtml(TYPE_ZH[n.type] || n.type)}}</span>
      <span><b>状态</b>: ${{escapeHtml(STATUS_ZH[n.status] || n.status)}}</span>
      ${{branchPills}}
    </div>
    ${{sec("预测", n.prediction)}}
    ${{sec("证据", n.evidence)}}
    ${{sec("备注", n.notes)}}
    ${{reviews}}
  `;
}}

window.openNode = function(short) {{
  const n = NODES_BY_SHORT[short];
  if (!n) return;
  const card = document.getElementById("modal-card");
  card.classList.remove("wide");
  document.getElementById("modal-body").innerHTML = renderNodeModal(n);
  document.getElementById("modal-overlay").classList.add("open");
}};

window.openDiary = function() {{
  const card = document.getElementById("modal-card");
  card.classList.add("wide");
  document.getElementById("modal-body").innerHTML =
    `<h2>研究日记 (FINDINGS.md)</h2><div class="diary-content">${{DIARY_HTML || "<em>暂无日记</em>"}}</div>`;
  document.getElementById("modal-overlay").classList.add("open");
}};

window.closeModal = function() {{
  document.getElementById("modal-overlay").classList.remove("open");
}};

window.closeModalIfBackdrop = function(event) {{
  if (event.target.id === "modal-overlay") window.closeModal();
}};

document.addEventListener("keydown", (e) => {{
  if (e.key === "Escape") window.closeModal();
}});
</script>
</body>
</html>
"""


def render_html(
    repo: ResearchRepo,
    output: Path,
    title: str = "研究 thesis 树",
    subtitle: str = "",
) -> None:
    output = Path(output)
    nodes = repo.all_nodes()
    branches = repo.all_branches()
    depth, lane = compute_layout(nodes)
    svg = _render_svg(nodes, depth, lane)
    payloads = [_node_payload(n, branches) for n in nodes]

    diary_path = repo.path / "FINDINGS.md"
    diary_md = diary_path.read_text() if diary_path.exists() else ""
    diary_html = _md_to_html(diary_md)

    if not subtitle:
        subtitle = f"{len(nodes)} 个节点 · {len(branches)} 个分支"

    html_doc = _TEMPLATE.format(
        title=html.escape(title),
        subtitle=html.escape(subtitle),
        svg=svg,
        legend=_legend_html(),
        nodes_json=json.dumps(payloads, ensure_ascii=False),
        type_zh_json=json.dumps(TYPE_ZH, ensure_ascii=False),
        status_zh_json=json.dumps(STATUS_ZH, ensure_ascii=False),
        status_badges_json=json.dumps(STATUS_BADGES, ensure_ascii=False),
        node_colors_json=json.dumps(NODE_COLORS, ensure_ascii=False),
        diary_json=json.dumps(diary_html, ensure_ascii=False),
    )
    output.write_text(html_doc)
