"""V-10 前端静态服务 + 同源反代（/api/* 与 /health 转发到后端），模拟桌面壳的同源形态。"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
BACKEND = "http://127.0.0.1:8011"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/health" or self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def _proxy(self, method: str) -> None:
        url = BACKEND.rstrip("/") + self.path
        body = None
        headers = {}
        if method in ("POST", "PUT"):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status, data = resp.status, resp.read()
                ctype = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            status, data, ctype = exc.code, exc.read(), "application/json"
        except Exception as exc:  # backend 不可达
            status = 502
            data = json.dumps({"ok": False, "error": f"upstream: {exc}"}).encode()
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError):
            pass


def main() -> None:
    global BACKEND
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8012)
    ap.add_argument("--backend", default=BACKEND)
    args = ap.parse_args()
    BACKEND = args.backend
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
