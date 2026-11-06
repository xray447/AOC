"""Hoppie ACARS 最小发报脚本（仅标准库）。

用途：给 docs/12 §6.1 / V-8 / V-14 做实测 —— 以「公司签派站」身份发一条 telex 给机组呼号，
看它会不会进机载 ACARS（Fenix DCDU / PMKF ACARS / iniBuilds A350 Mailbox）。

接口按 Hoppie 官方 API（https://www.hoppie.nl/acars/system/tech.html）：
  POST connect.html  logon / from / to / type / packet
  · 存储转发，队列 24h；没有正式 ACK，只能确认「已交网络」
  · 不要 2s 内连发两条；HTTP 超时按 15s
  · `@` 表示换行（本脚本原样透传，不做转换）

用法：
  # 先验 logon 通不通（type=ping，返回 OK）
  python -X utf8 tools/hoppie_telex.py --probe --logon gXXXX --from AOCDISP

  # 发机位报文
  python -X utf8 tools/hoppie_telex.py --logon gXXXX --from AOCDISP --to AOC1234 \
      --packet "AOC ARR GATE G340 JETWAY ETA 1842Z"

  # 只看会发什么，不联网
  python -X utf8 tools/hoppie_telex.py --dry-run --from AOCDISP --to AOC1234 --packet "TEST"

logon 也可以用环境变量 HOPPIE_LOGON 提供，避免进 shell 历史。
日志默认写 logs/hoppie-telex.log（相对仓库根）；logon 一律打码。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "http://www.hoppie.nl/acars/system/connect.html"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "logs" / "hoppie-telex.log"
TIMEOUT_S = 15.0          # Hoppie 文档建议的 HTTP 超时
MIN_GAP_S = 2.0           # 文档：不要在 2s 内连发两条

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NETWORK = 3
EXIT_SERVER = 4
EXIT_REJECTED = 5


def mask(secret: str | None) -> str:
    """logon 打码：只留首尾各 2 个字符。"""
    if not secret:
        return "-"
    if len(secret) <= 6:
        return "*" * len(secret)
    return f"{secret[:2]}***{secret[-2:]}({len(secret)})"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_log(path: Path, entry: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:                                  # 日志写不进去不该让发报失败
        print(f"⚠️ 日志写入失败: {exc}", file=sys.stderr)


def enforce_gap(path: Path) -> float:
    """按 Hoppie 的要求保证两条报文间隔 ≥2s（读日志最后一条的时间戳）。→ 实际等待秒数。"""
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return 0.0
    if not lines:
        return 0.0
    try:
        last = json.loads(lines[-1]).get("ts", "")
        delta = time.time() - datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
    except (ValueError, KeyError, TypeError):
        return 0.0
    wait = MIN_GAP_S - delta
    if wait > 0:
        print(f"⏳ 距上一条仅 {delta:.1f}s，按 Hoppie 建议等 {wait:.1f}s", file=sys.stderr)
        time.sleep(wait)
        return wait
    return 0.0


def classify(body: str) -> tuple[str, int]:
    """Hoppie 没有正式的响应规范，这里只做保守判断，原文照打。"""
    text = (body or "").strip()
    low = text.lower()
    if not text:
        return "EMPTY", EXIT_SERVER
    if low.startswith("ok") or low == "ok":
        return "OK", EXIT_OK
    if "error" in low or "invalid" in low or "already in use" in low or "unknown" in low:
        return "REJECTED", EXIT_REJECTED
    return "UNKNOWN", EXIT_OK                             # 有内容但认不出来 → 不算失败


def build_form(args: argparse.Namespace) -> dict[str, str]:
    if args.probe:
        return {"logon": args.logon or "", "from": args.from_, "to": "SERVER",
                "type": "ping", "packet": ""}
    return {"logon": args.logon or "", "from": args.from_, "to": args.to or "",
            "type": args.type, "packet": args.packet or ""}


def send(form: dict[str, str], timeout: float) -> tuple[int | None, str, float, str | None]:
    """→ (HTTP 状态, 响应体, 耗时 ms, 错误描述)。不改动任何本地状态。"""
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 # 表明身份，出问题好排查（Hoppie 是个人业余服务，别当匿名爬虫）
                 "User-Agent": "AOC-hoppie-telex/1.0 (+flightsim probe)"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = raw.decode("utf-8", "replace").strip()
            return resp.status, body, (time.perf_counter() - started) * 1000.0, None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace").strip()
        except OSError:
            pass
        return exc.code, body, (time.perf_counter() - started) * 1000.0, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, "", (time.perf_counter() - started) * 1000.0, f"{type(exc).__name__}: {exc}"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Hoppie ACARS 最小发报（telex / ping），只发不收。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python -X utf8 tools/hoppie_telex.py --logon gXXXX --from AOCDISP "
               "--to AOC1234 --packet \"AOC ARR GATE G340\"")
    p.add_argument("--logon", default=os.environ.get("HOPPIE_LOGON"),
                   help="站点 logon code（也可用环境变量 HOPPIE_LOGON）")
    p.add_argument("--from", dest="from_", required=True,
                   help="发报方呼号，如 AOCDISP（公司签派站）")
    p.add_argument("--to", help="收报方呼号，必须与机上 FLT NO / Hoppie ID 完全一致")
    p.add_argument("--type", default="telex", choices=("telex", "cpdlc", "progress", "ping"),
                   help="报文类型，默认 telex（cpdlc 属管制语义，别拿它发机位）")
    p.add_argument("--packet", help="报文正文；`@` 表示换行。建议 ≤200 字符、全大写")
    p.add_argument("--probe", action="store_true", help="只测链路：type=ping 到 SERVER，应回 OK")
    p.add_argument("--dry-run", action="store_true", help="不联网，只打印将发送的内容")
    p.add_argument("--timeout", type=float, default=TIMEOUT_S, help=f"HTTP 超时秒（默认 {TIMEOUT_S:g}）")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG, help="日志文件（JSON Lines）")
    p.add_argument("--json", action="store_true", help="stdout 只输出一行 JSON（便于脚本串联）")
    args = p.parse_args(argv)

    if not args.probe:
        if not args.to:
            p.error("缺少 --to（收报方呼号）")
        if not args.packet:
            p.error("缺少 --packet（报文正文）")
    if len(args.packet or "") > 220:
        print("⚠️ 报文超过 220 字符，Hoppie 侧与机型侧都可能截断", file=sys.stderr)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    form = build_form(args)
    form["logon"] = args.logon or ""

    if not args.dry_run and not form["logon"]:
        print("缺少 logon：用 --logon 或环境变量 HOPPIE_LOGON", file=sys.stderr)
        return EXIT_USAGE

    preview = {**form, "logon": mask(form["logon"]),
               "packet": (form["packet"][:80] + "…") if len(form["packet"]) > 80 else form["packet"]}
    if args.dry_run:
        print("DRY-RUN 将 POST", ENDPOINT)
        for k, v in preview.items():
            print(f"  {k:7} = {v}")
        return EXIT_OK

    waited = enforce_gap(args.log)
    status, body, elapsed_ms, error = send(form, args.timeout)
    verdict, code = classify(body) if status == 200 else ("HTTP_ERROR", EXIT_SERVER)
    if status is None:
        verdict, code = "NETWORK_ERROR", EXIT_NETWORK

    entry = {
        "ts": utcnow(), "endpoint": ENDPOINT, "type": form["type"],
        "from": form["from"], "to": form["to"], "packet_len": len(form["packet"]),
        "packet": form["packet"], "logon": mask(form["logon"]),
        "http_status": status, "verdict": verdict, "body": body[:500],
        "elapsed_ms": round(elapsed_ms, 1), "gap_wait_s": round(waited, 1), "error": error,
    }
    write_log(args.log, entry)

    if args.json:
        print(json.dumps({k: entry[k] for k in
                          ("ts", "type", "from", "to", "http_status", "verdict", "body",
                           "elapsed_ms", "error")}, ensure_ascii=False))
        return code

    print(f"[{entry['ts']}] {form['type'].upper()} {form['from']} → {form['to']}")
    print(f"  logon   {mask(form['logon'])}")
    print(f"  packet  {form['packet']}")
    print(f"  HTTP    {status if status is not None else '—'}  ({elapsed_ms:.0f} ms)")
    print(f"  判定    {verdict}" + (f"  ·  {error}" if error else ""))
    if body:
        print(f"  响应    {body}")
    print(f"  日志    {args.log}")
    if verdict in ("OK", "UNKNOWN"):
        print("注意：OK 只代表「已交网络」，Hoppie 没有回执；机组是否看到要回到机上确认。")
    if verdict == "REJECTED" and "already in use" in body.lower():
        print("提示：呼号被别的 logon 锁着（锁 100s），换呼号或等 100s 再发。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
