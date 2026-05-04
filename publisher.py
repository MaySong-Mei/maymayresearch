"""Publish git-backed thesis state to Supabase via PostgREST.

git stays the source of truth. This module is a one-way mirror: read the
repo, upsert into Supabase. Stdlib-only (urllib) so no pip install needed.

Auth: service-role key (writes bypass RLS). Configure via env or .env file.

Typical use:
    repo = ResearchRepo(...)
    pub  = SupabasePublisher.from_env()
    pub.sync_repo(repo, repo_slug="agent_demo")

Or via a git post-commit hook installed by `harness install-hook`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .core import ResearchRepo


# ── env loading ────────────────────────────────────────────────────────────


def load_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    """Tiny .env loader (KEY=VALUE per line, # comments). No external deps."""
    if path is None:
        path = Path(__file__).resolve().parent / ".env"
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read env var, falling back to harness/.env file."""
    val = os.environ.get(key)
    if val:
        return val
    file_env = load_env_file()
    return file_env.get(key, default)


# ── HTTP helpers ───────────────────────────────────────────────────────────


HttpFn = Callable[[urllib.request.Request], Any]


def _default_http(req: urllib.request.Request, timeout: float = 15.0):
    return urllib.request.urlopen(req, timeout=timeout)


@dataclass
class PublishResult:
    table: str
    rows_sent: int
    status: int


# ── Publisher ──────────────────────────────────────────────────────────────


class SupabasePublisher:
    def __init__(
        self,
        url: str,
        service_key: str,
        http: Optional[HttpFn] = None,
    ):
        self.base = url.rstrip("/") + "/rest/v1"
        self.service_key = service_key
        self._http = http or _default_http

    @classmethod
    def from_env(cls, http: Optional[HttpFn] = None) -> "SupabasePublisher":
        url = env("SUPABASE_URL")
        key = env("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (env or harness/.env)"
            )
        return cls(url, key, http=http)

    # ── core HTTP ──────────────────────────────────────────────────────────

    def _post(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        *,
        on_conflict: Optional[str] = None,
    ) -> int:
        if not rows:
            return 204
        path = f"/{table}"
        if on_conflict:
            path += f"?on_conflict={on_conflict}"
        url = self.base + path
        body = json.dumps(rows).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "apikey": self.service_key,
                "Authorization": f"Bearer {self.service_key}",
                "Content-Type": "application/json",
                "Prefer": (
                    "resolution=merge-duplicates,return=minimal"
                    if on_conflict
                    else "return=minimal"
                ),
            },
        )
        try:
            resp = self._http(req)
            return getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Supabase POST {table} failed: HTTP {e.code} {detail}"
            ) from None

    def _delete(self, table: str, query: str) -> int:
        url = f"{self.base}/{table}?{query}"
        req = urllib.request.Request(
            url,
            method="DELETE",
            headers={
                "apikey": self.service_key,
                "Authorization": f"Bearer {self.service_key}",
                "Prefer": "return=minimal",
            },
        )
        try:
            resp = self._http(req)
            return getattr(resp, "status", 204)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Supabase DELETE {table} failed: HTTP {e.code} {detail}"
            ) from None

    # ── transforms ─────────────────────────────────────────────────────────

    @staticmethod
    def _node_to_row(repo_slug: str, n: dict) -> Dict[str, Any]:
        ts = n.get("timestamp")
        committed_at = (
            datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            if ts is not None
            else datetime.now(tz=timezone.utc).isoformat()
        )
        node_type = n.get("type") or "unknown"
        status = n.get("status") or "pending"
        return {
            "repo": repo_slug,
            "sha": n["sha"],
            "parents": list(n.get("parents") or []),
            "type": node_type,
            "status": status,
            "claim": n.get("claim") or "",
            "prediction": n.get("prediction") or "",
            "design": n.get("design") or "",
            "evidence": n.get("evidence") or "",
            "decision": n.get("decision") or "",
            "notes": n.get("notes") or "",
            "review_comments": list(n.get("review_comments") or []),
            "committed_at": committed_at,
        }

    # ── public sync API ────────────────────────────────────────────────────

    def upsert_nodes(
        self, repo_slug: str, nodes: Iterable[dict]
    ) -> PublishResult:
        rows = [self._node_to_row(repo_slug, n) for n in nodes]
        status = self._post("nodes", rows, on_conflict="repo,sha")
        return PublishResult("nodes", len(rows), status)

    def upsert_branches(
        self, repo_slug: str, branches: Dict[str, str]
    ) -> PublishResult:
        now = datetime.now(tz=timezone.utc).isoformat()
        rows = [
            {"repo": repo_slug, "name": name, "tip_sha": sha, "updated_at": now}
            for name, sha in branches.items()
        ]
        status = self._post("branches", rows, on_conflict="repo,name")
        return PublishResult("branches", len(rows), status)

    def prune_branches(
        self, repo_slug: str, keep_names: Iterable[str]
    ) -> PublishResult:
        keep_list = list(keep_names)
        if not keep_list:
            # nothing to keep — wipe all branches for this repo
            status = self._delete("branches", f"repo=eq.{repo_slug}")
            return PublishResult("branches", 0, status)
        # Delete branches whose name is NOT in keep_list
        names = ",".join(keep_list)
        status = self._delete(
            "branches",
            f"repo=eq.{repo_slug}&name=not.in.({names})",
        )
        return PublishResult("branches", len(keep_list), status)

    def sync_repo(
        self, repo: ResearchRepo, repo_slug: str
    ) -> Dict[str, PublishResult]:
        nodes = repo.all_nodes()
        branches = repo.all_branches()
        results = {
            "nodes": self.upsert_nodes(repo_slug, nodes),
            "branches": self.upsert_branches(repo_slug, branches),
        }
        # remove any branches that have been deleted locally
        results["pruned"] = self.prune_branches(repo_slug, branches.keys())
        return results
