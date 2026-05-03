"""Stdlib-only HTTP dashboard for a research repo.

GET /         — re-renders the thesis tree on every request
GET /version  — hash of all branch tips; client polls this for live reload
GET /diary    — raw FINDINGS.md as text/markdown

Auto-refresh: the rendered HTML embeds the current version and a tiny JS
poller. When the server's version changes (a new commit / branch / merge),
the client reloads. No external libraries.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import tempfile
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .core import ResearchRepo
from .render import render_html


_AUTO_REFRESH_JS = """
<script>
(function() {
  const VERSION = window.__SERVER_VERSION__;
  let known = VERSION;
  async function poll() {
    try {
      const r = await fetch('/version', { cache: 'no-store' });
      if (!r.ok) return;
      const j = await r.json();
      if (j.version && j.version !== known) {
        known = j.version;
        location.reload();
      }
    } catch (_) {}
  }
  setInterval(poll, 2000);
})();
</script>
"""


def _compute_version(repo: ResearchRepo) -> str:
    branches = repo.all_branches()
    h = hashlib.sha1()
    for name in sorted(branches.keys()):
        h.update(name.encode())
        h.update(b"\0")
        h.update(branches[name].encode())
        h.update(b"\0")
    return h.hexdigest()[:12]


def _render_live_html(repo: ResearchRepo, version: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as fh:
        tmp = Path(fh.name)
    try:
        nodes = len(repo.all_nodes())
        branches = len(repo.all_branches())
        render_html(
            repo,
            tmp,
            title="Research Thesis Tree (live)",
            subtitle=f"version {version} · {nodes} nodes · {branches} branches · auto-refresh",
        )
        html = tmp.read_text()
    finally:
        tmp.unlink(missing_ok=True)
    inject = f'<script>window.__SERVER_VERSION__ = "{version}";</script>{_AUTO_REFRESH_JS}'
    return html.replace("</body>", inject + "</body>").encode("utf-8")


class _Handler(http.server.BaseHTTPRequestHandler):
    repo: Optional[ResearchRepo] = None  # set per-instance via factory

    # Suppress default access log to keep stderr clean during tests
    def log_message(self, format, *args) -> None:  # noqa: A002 - stdlib signature
        pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._serve_html()
            elif path == "/version":
                self._serve_json({"version": _compute_version(self.repo)})
            elif path == "/diary":
                self._serve_diary()
            elif path == "/health":
                self._serve_json({"ok": True})
            else:
                self.send_error(404, "not found")
        except Exception as exc:  # surface errors as 500 rather than crashing thread
            self.send_error(500, f"render error: {exc}")

    def _serve_html(self) -> None:
        version = _compute_version(self.repo)
        body = _render_live_html(self.repo, version)
        self._send(200, "text/html; charset=utf-8", body)

    def _serve_json(self, obj) -> None:
        body = json.dumps(obj).encode("utf-8")
        self._send(200, "application/json", body)

    def _serve_diary(self) -> None:
        diary = self.repo.path / "FINDINGS.md"
        if not diary.exists():
            self.send_error(404, "no diary yet")
            return
        body = diary.read_text().encode("utf-8")
        self._send(200, "text/markdown; charset=utf-8", body)

    def _send(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class ResearchServer:
    """Threaded HTTP server that lives until .stop() is called."""

    def __init__(self, repo: ResearchRepo, host: str = "127.0.0.1", port: int = 0):
        self.repo = repo
        self.host = host
        self.port = port
        self._httpd: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "ResearchServer":
        handler_cls = type(
            "BoundHandler",
            (_Handler,),
            {"repo": self.repo},
        )
        self._httpd = http.server.ThreadingHTTPServer(
            (self.host, self.port), handler_cls
        )
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "ResearchServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
