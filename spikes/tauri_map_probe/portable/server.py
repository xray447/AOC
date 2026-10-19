"""AOC 轨迹回放探针 - 便携版本地静态服务（仅标准库）。

双击 `启动探针.bat` 即可；也可手动：
    python server.py [--port 5199] [--no-browser]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "app"


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".wasm": "application/wasm",
    }

    def log_message(self, fmt: str, *args) -> None:  # 静音逐条访问日志
        pass

    def end_headers(self) -> None:
        # 便携包要能被直接刷新/回退，不影响缓存语义
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"127.0.0.1:{preferred}~{preferred + 19} 都被占用，请用 --port 指定端口")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5199)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not (ROOT / "index.html").is_file():
        print(f"[错误] 找不到 {ROOT / 'index.html'}，压缩包可能解压不完整。")
        return 2

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/index.html"
    handler = functools.partial(Handler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True

    print(f"AOC 轨迹回放探针已启动：{url}")
    print("关闭本窗口或按 Ctrl+C 结束。")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
