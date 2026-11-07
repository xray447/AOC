"""Hoppie ACARS telex 投递（docs/12 §6.1 / Q-2 ③ / P2.5）。仅标准库。

设计要点（与文档一致）：
* 只有 `type=telex`：机位是公司信息，不是管制指令，**不要用 cpdlc**；
* `SENT` 只代表「已交网络」，Hoppie 没有 ACK —— 界面文案不写「已送达」；
* 发送侧限流：两条报文间隔 ≥2 s；
* `logon` 在 Windows 上用 DPAPI 加密后落库（与 SWIM 账号同一套做法），
  不可用时退回 base64（仍然只在本地库，不进日志/导出）。
"""
from __future__ import annotations

import base64
import ctypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "http://www.hoppie.nl/acars/system/connect.html"
TIMEOUT_S = 15.0
MIN_GAP_S = 2.0
# 显示/审计里一律打码：只留首尾各 2 位
_last_sent_at = 0.0


def mask(secret: str | None) -> str:
    if not secret:
        return ""
    if len(secret) <= 6:
        return "*" * len(secret)
    return f"{secret[:2]}***{secret[-2:]}"


def wait_gap() -> float:
    """按 Hoppie 建议保证两条报文间隔 ≥2 s；返回实际等待秒数。"""
    wait = MIN_GAP_S - (time.monotonic() - _last_sent_at)
    if wait > 0:
        time.sleep(wait)
        return round(wait, 2)
    return 0.0


def classify(body: str) -> str:
    """Hoppie 没有正式响应规范：只做保守判断（正文原样返回给调用方审计）。"""
    text = (body or "").strip()
    low = text.lower()
    if not text:
        return "EMPTY"
    if low.startswith("ok"):
        return "OK"
    if "error" in low or "invalid" in low or "already in use" in low or "unknown" in low:
        return "REJECTED"
    return "UNKNOWN"


def send_telex(logon: str, from_: str, to: str, packet: str, *,
               timeout: float = TIMEOUT_S, gap: bool = True) -> dict:
    """发一条 telex。→ {ok, verdict, http_status, body, elapsed_ms, error, gap_wait_s}"""
    global _last_sent_at
    if not logon or not from_ or not to:
        return {"ok": False, "verdict": "NOT_CONFIGURED", "http_status": None, "body": "",
                "elapsed_ms": 0.0, "error": "缺少 logon / from / to", "gap_wait_s": 0.0}
    waited = wait_gap() if gap else 0.0
    form = {"logon": logon, "from": from_, "to": to, "type": "telex", "packet": packet}
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "AOC-client/1.0 (hoppie telex)"})
    started = time.perf_counter()
    status: int | None = None
    body = ""
    error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read().decode("utf-8", "replace").strip()
        except OSError:
            body = ""
        error = f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        _last_sent_at = time.monotonic()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    verdict = classify(body) if status == 200 else ("NETWORK_ERROR" if status is None else "HTTP_ERROR")
    return {
        "ok": verdict in ("OK", "UNKNOWN"), "verdict": verdict, "http_status": status,
        "body": body[:500], "elapsed_ms": round(elapsed_ms, 1), "error": error,
        "gap_wait_s": waited,
    }


# ------------------------------------------------------------------ DPAPI ----
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def protect(secret: str) -> str:
    """logon 加密：Windows 用 DPAPI（`dpapi:`），其它平台退回 base64（`plain:`）。"""
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        try:
            blob_in, _keep = _blob(raw)
            blob_out = _DataBlob()
            ok = ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
            if ok:
                try:
                    data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                finally:
                    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return "dpapi:" + base64.b64encode(data).decode("ascii")
        except (AttributeError, OSError):
            pass
    return "plain:" + base64.b64encode(raw).decode("ascii")


def unprotect(blob: str) -> str:
    value = str(blob or "")
    if not value:
        return ""
    try:
        if value.startswith("dpapi:"):
            data = base64.b64decode(value[6:])
            blob_in, _keep = _blob(data)
            blob_out = _DataBlob()
            description = ctypes.c_wchar_p()
            ok = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), ctypes.byref(description), None, None, None, 0,
                ctypes.byref(blob_out))
            if not ok:
                return ""
            try:
                return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8", "replace")
            finally:
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        if value.startswith("plain:"):
            return base64.b64decode(value[6:]).decode("utf-8", "replace")
    except (ValueError, OSError, AttributeError):
        return ""
    return ""
