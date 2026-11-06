"""BeyondATC 本地 ATIS 端点模拟器（测试用，不是生产组件）。

背景：Fenix A320 的 MCDU 在 `NETWORK=BEYONDATC` 时会请本机取 ATIS ——
`GET http://localhost:57698/acars/atis/<ICAO>`，BATC 在跑时由它应答。
本脚本把自己绑到同一端口，用来验证 docs/12 §6.3.1 / §6.4 里那条「通道 A」：

  200 + 纯文本  → MCDU 显示
  404           → NO ATIS AVAILABLE
  没有服务        → INVALID ATIS MESSAGE

顺带当端点探针用（V-13）：**任何**打到本端口的请求都会记一行日志，
所以把机组各页都点一遍，就能看出机型到底请求了哪些路径。

用法：
  # 只看渲染出来什么（不占端口）
  python -X utf8 tools/batc_atis_sim.py --dry-run --icao ZBAA --stand G340

  # 起服务（Ctrl+C 停），然后在 Fenix MCDU：NETWORK=BEYONDATC → ATIS → ZBAA → SEND
  python -X utf8 tools/batc_atis_sim.py --stand G340

  # 只回 ZBAA，其它机场返回 404（验证 NO ATIS AVAILABLE）
  python -X utf8 tools/batc_atis_sim.py --icao ZBAA --stand G340

  # 收到第一条 ATIS 请求就退出（手测一次性的场合）
  python -X utf8 tools/batc_atis_sim.py --stand G340 --once

⚠️ 这是黑盒逆向出来的未公开接口：机型更新可能失效；**真 BATC 在跑时不要抢 57698**
（脚本会直接告诉你端口被占，按 D-1 此时应让位给 BATC）。
"""

from __future__ import annotations

import argparse
import errno
import json
import re
import socket
import socketserver
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "logs" / "batc-atis-sim.log"
DEFAULT_PORT = 57698           # Fenix 在 NETWORK=BEYONDATC 下请求的端口
COLS = 24                      # MCDU 可见列宽（实测）
LINES_PER_PAGE = 7             # 每页行数（实测）

ATIS_PATH = re.compile(r"^/acars/atis/([A-Za-z0-9]{4})/?$")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PORT = 3
EXIT_FAILED = 4


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- 文本处理
def sanitize(text: str) -> str:
    """MCDU 只认可打印 ASCII，且 '#' 显示不了（实测）→ 一律剔掉。"""
    keep = []
    for ch in text.replace("\r\n", "\n").replace("\r", "\n"):
        if ch == "\n":
            keep.append(ch)
        elif ch == "#" or ord(ch) < 32 or ord(ch) > 126:
            continue
        else:
            keep.append(ch)
    return "".join(keep)


def wrap(text: str, cols: int = COLS) -> list[str]:
    """按列硬折行，尽量在空格处断；超长 token 直接切。"""
    lines: list[str] = []
    for raw in sanitize(text).split("\n"):
        words = raw.split(" ")
        cur = ""
        for word in words:
            while len(word) > cols:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:cols])
                word = word[cols:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= cols:
                cur = f"{cur} {word}"
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return [ln.rstrip() for ln in lines]


def default_body(icao: str, stand: str | None) -> str:
    """一份「像 ATIS 但不是 ATIS」的模板，够用来验证显示与分页。"""
    rows = [
        f"{icao} ATIS INFO A 0350Z",
        "WIND 02003MPS VIS 9999",
        "CLOUD FEW3000 T12/03",
        "Q1015 RWY 36L",
    ]
    if stand:
        rows.append(f"ARR GATE {stand}")
    rows.append("GENERATED NOT OFFICIAL")
    return "\n".join(rows)


def render(icao: str, body: str, max_lines: int, do_wrap: bool) -> tuple[str, list[str]]:
    """→ (给机型的文本, 折行后的行列表)。"""
    lines = wrap(body, COLS) if do_wrap else sanitize(body).split("\n")
    warnings: list[str] = []
    if len(lines) > max_lines:
        warnings.append(f"折行后 {len(lines)} 行 > {max_lines} 行/页，超出部分可能看不到")
        lines = lines[:max_lines]
    return "\n".join(lines), warnings


# ---------------------------------------------------------------- HTTP 服务
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "batc-atis-sim"

    def log_message(self, *args):                      # 用我们自己的日志，不要 stderr 噪音
        pass

    def _send(self, status: int, body: bytes = b"", ctype: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):                                  # noqa: N802  (BaseHTTPRequestHandler 约定)
        self._handle("GET")

    def do_HEAD(self):                                 # noqa: N802
        self._handle("HEAD")

    def do_POST(self):                                 # noqa: N802
        # 目前已知的只有 GET；POST 也记下来，顺便当端点探针
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            try:
                self.rfile.read(min(length, 4096))
            except OSError:
                pass
        self._handle("POST")

    def _handle(self, method: str) -> None:
        ctx = self.server.ctx                           # type: ignore[attr-defined]
        path = self.path.split("?", 1)[0]
        match = ATIS_PATH.match(path)
        icao = match.group(1).upper() if match else None
        # --any-path：任何路径都回 200，用来判断「机型到底请求了什么路径」
        allow = bool(ctx.args.any_path) or bool(icao and ctx.allows(icao))
        body = b""
        if allow:
            text = ctx.body_for(icao or "ZZZZ")
            body = text.encode("ascii", "replace")
            self._send(200, body)
            status = 200
        else:
            self._send(404)
            status = 404
        ctx.record(method, path, icao, status, len(body), self.client_address[0],
                   host=self.headers.get("Host") or "",
                   ua=(self.headers.get("User-Agent") or "")[:80])
        if status == 200:
            ctx.on_served()


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False       # 开着会让第二个进程也能绑同一端口，抢端口检测不到（Windows）
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], ConnectionError):
            return                    # MCDU 不等了、直接断开，是常态
        super().handle_error(request, client_address)

    def server_bind(self):
        # 跳过 HTTPServer 里可能很慢的 getfqdn
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Server6(_Server):
    address_family = socket.AF_INET6


class AtisSim:
    """绑 127.0.0.1 + ::1（Fenix 实测走 ::1），单端口、可随时停。"""

    def __init__(self, port: int, ctx: "Context"):
        self.port, self.ctx = port, ctx
        self._servers: list[_Server] = []

    def start(self) -> str | None:
        """→ None 表示成功；否则是给人看的错误文字。"""
        servers: list[_Server] = []
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            cls = _Server if family == socket.AF_INET else _Server6
            try:
                srv = cls((host, self.port), _Handler)
            except OSError as exc:
                if family == socket.AF_INET6 and exc.errno in (
                        errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT, 10049, 10047):
                    continue          # 本机没有 IPv6，可以跳过
                for s in servers:
                    s.server_close()
                if exc.errno in (errno.EADDRINUSE, 10048):
                    return (f"端口 {self.port} 已被占用 —— 很可能 BeyondATC 正在运行。"
                            f"按 docs/12 §6.2/§6.4，此时应让位给 BATC（不要再起本模拟器）。")
                return f"端口 {self.port} 无法使用（{exc.strerror or exc}）"
            srv.ctx = self.ctx      # type: ignore[attr-defined]
            for k, v in self.ctx.attrs.items():
                setattr(srv, k, v)
            threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2},
                             daemon=True).start()
            servers.append(srv)
        self._servers = servers
        return None

    def stop(self) -> None:
        servers, self._servers = self._servers, []
        for srv in servers:
            srv.shutdown()
            srv.server_close()


class Context:
    """一次运行的可变状态：文本、允许的机场、日志、退出条件。"""

    def __init__(self, args: argparse.Namespace, body: str):
        self.args = args
        self.body = body
        self.icaos = {i.upper() for i in (args.icao or [])}
        self.attrs: dict = {}
        self.served_event = threading.Event()
        self._served = 0
        self._lock = threading.Lock()
        self.started = time.time()

    def allows(self, icao: str) -> bool:
        return not self.icaos or icao in self.icaos

    def body_for(self, icao: str) -> str:
        text, warnings = render(icao, self.body.replace("{ICAO}", icao),
                                self.args.max_lines, not self.args.no_wrap)
        for w in warnings:
            self._log({"ts": utcnow(), "warn": w})
        return text

    def record(self, method: str, path: str, icao: str | None, status: int,
               size: int, client: str, host: str = "", ua: str = "") -> None:
        entry = {"ts": utcnow(), "method": method, "path": path, "icao": icao,
                 "status": status, "bytes": size, "client": client,
                 "host": host, "ua": ua}
        self._log(entry)
        mark = "✅" if status == 200 else "✗"
        print(f"{mark} {entry['ts']}  {method:4} {path}  → {status} ({size}B)  "
              f"from {client}  host={host or '-'}  ua={ua or '-'}")
        if status == 200:
            print("   " + self.body_for(icao or "ZZZZ").replace("\n", "\n   "))

    def _log(self, entry: dict) -> None:
        path = self.args.log
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def on_served(self) -> None:
        """注意：这里在 HTTP 线程里，**不能**调 server.shutdown()（会自己等自己死锁）。"""
        with self._lock:
            self._served += 1
        self.served_event.set()


# ---------------------------------------------------------------- CLI
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="模拟 BeyondATC 的本地 ATIS 端点（测试 Fenix 的 BEYONDATC 通道）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python -X utf8 tools/batc_atis_sim.py --stand G340")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"监听端口（默认 {DEFAULT_PORT}，即 Fenix 请求的端口）")
    p.add_argument("--icao", action="append",
                   help="只回这些机场（可重复）；不填=任何 4 位 ICAO 都回")
    p.add_argument("--text", help="自定义 ATIS 正文；用 {ICAO} 占位机场码")
    p.add_argument("--text-file", type=Path, help="从文件读 ATIS 正文（优先于 --text）")
    p.add_argument("--stand", help="在模板里追加一行 `ARR GATE <机位>`；只影响默认模板")
    p.add_argument("--max-lines", type=int, default=LINES_PER_PAGE,
                   help=f"最多返回多少行（默认 {LINES_PER_PAGE}，实测每页行数）")
    p.add_argument("--no-wrap", action="store_true", help="不按 24 列折行（原样发）")
    p.add_argument("--any-path", action="store_true",
                   help="任何路径都回 200（诊断用：机型换了路径也能看出来）")
    p.add_argument("--once", action="store_true", help="服务完第一条 200 就退出")
    p.add_argument("--dry-run", action="store_true", help="只打印渲染结果，不监听端口")
    p.add_argument("--self-test", action="store_true",
                   help="自检：临时端口跑一遍 200/404/未知路径/抢端口")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG, help="请求日志（JSON Lines）")
    return p.parse_args(argv)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def self_test() -> int:
    """不依赖模拟器：起一个临时端口，自检 200 / 404 / 未知路径 / 抢端口。"""
    import tempfile
    import urllib.error
    import urllib.request

    port = _free_port()
    log = Path(tempfile.gettempdir()) / "batc-atis-selftest.log"
    args = parse_args(["--port", str(port), "--icao", "ZBAA", "--stand", "G340",
                       "--log", str(log)])
    ctx = Context(args, default_body("{ICAO}", args.stand))
    sim = AtisSim(port, ctx)
    error = sim.start()
    if error:
        print(f"FAIL 起服务：{error}")
        return EXIT_FAILED

    def get(path: str) -> tuple[int, str]:
        url = f"http://127.0.0.1:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.status, resp.read().decode("ascii", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, ""

    failures = 0
    try:
        status, text = get("/acars/atis/ZBAA")
        ok = status == 200 and "ARR GATE G340" in text
        print(f"{'PASS' if ok else 'FAIL'}  ZBAA → {status}, 含机位行：{ok}")
        failures += 0 if ok else 1

        status, _ = get("/acars/atis/EGLL")
        ok = status == 404
        print(f"{'PASS' if ok else 'FAIL'}  EGLL（不在 --icao 列表）→ {status}")
        failures += 0 if ok else 1

        status, _ = get("/acars/wx/ZBAA")
        ok = status == 404
        print(f"{'PASS' if ok else 'FAIL'}  未知路径 /acars/wx/ZBAA → {status}（应记日志）")
        failures += 0 if ok else 1

        conflict = AtisSim(port, ctx).start()
        ok = bool(conflict) and "占用" in str(conflict)
        print(f"{'PASS' if ok else 'FAIL'}  抢同一端口 → {conflict}")
        failures += 0 if ok else 1
    finally:
        sim.stop()

    total = 4
    print(f"\n{total - failures}/{total} 项通过")
    return EXIT_OK if failures == 0 else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    if args.text_file:
        try:
            body = args.text_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"读不了 --text-file：{exc}", file=sys.stderr)
            return EXIT_USAGE
    else:
        body = args.text or default_body("{ICAO}", args.stand)

    if args.dry_run:
        probe = (args.icao or ["ZBAA"])[0].upper()
        text, warnings = render(probe, body.replace("{ICAO}", probe),
                                args.max_lines, not args.no_wrap)
        print(f"DRY-RUN  {probe}  →  {COLS} 列 × {args.max_lines} 行")
        for line in text.split("\n"):
            print(f"  |{line}")
        for w in warnings:
            print(f"⚠️ {w}", file=sys.stderr)
        if not args.stand and not args.text and not args.text_file:
            print("（当前没有 --stand，报文里不会有机位行）", file=sys.stderr)
        return EXIT_OK

    ctx = Context(args, body)
    sim = AtisSim(args.port, ctx)
    error = sim.start()
    if error:
        print(error, file=sys.stderr)
        return EXIT_PORT

    print(f"ATIS 模拟器已启动：http://localhost:{args.port}/acars/atis/<ICAO>")
    print(f"  只回 ICAO  {', '.join(sorted(ctx.icaos)) or '任意 4 位'}")
    print(f"  列宽 {COLS} · 最多 {args.max_lines} 行 · 日志 {args.log}")
    print("  Fenix：MCDU → NETWORK=BEYONDATC → ATIS 页输入 ICAO → SEND")
    print("  顺带当端点探针：任何请求路径都会记一行（V-13）。Ctrl+C 退出。")

    def _watchdog() -> None:
        time.sleep(30)
        if not ctx.served_event.is_set():
            print("⚠️ 30s 内一条请求都没收到：机型根本没连过来。"
                  "常见原因：① 机上 NETWORK 不是 BEYONDATC；② 该机型没装/没跑 BATC 时不发这个请求；"
                  "③ 端口或路径变了（用 --any-path 再试）；④ ATIS 页只按 SEND 才请求。")

    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        if args.once:
            # 在主线程等，绝不能在 HTTP 线程里 shutdown（会死锁）
            if not ctx.served_event.wait(timeout=300):
                print("300s 内没有收到任何 200 请求，退出", file=sys.stderr)
                return EXIT_FAILED
            time.sleep(0.3)                     # 让响应真正写回再收摊
        else:
            while True:
                time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n停止")
    finally:
        sim.stop()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
