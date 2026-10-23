"""PyInstaller 入口（D-30）：先固定资源根目录，再交给 `main.main()`。

打包时不带 Python 解释器与 `packages/` 源码目录，`data/` 随包发布；航路建图源码已在
`aoc_route.net`（随包进 exe），不再需要仓库外的 `Pre-train/src`。
`AOC_ROOT` 指向 PyInstaller 的 `_MEIPASS`（onedir 即 `_internal/`）。

冻结版是 `--noconsole`（没有控制台）：一旦有异常逃出脚本，PyInstaller 会弹一个**模态**
错误对话框等用户点确定。CI（`tools/build_core_exe.py --verify`）上没有桌面，进程就一直
挂到超时——这正是 `aoc-core.exe --help` 卡 1800s 的原因。所以这里兜住所有异常，改成
写崩溃日志 + 非零退出码。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

CRASH_LOG = Path(tempfile.gettempdir()) / "aoc-core-crash.log"

# CI 探活（tools/build_core_exe.py --verify）用：冻结版没有 stdout，只能把启动阶段
# 写进文件，才知道它是没进 Python、还是卡在 import / 卡在解析参数。
_PROBE = os.environ.get("AOC_PROBE_FILE")


def _mark(stage: str) -> None:
    if not _PROBE:
        return
    try:
        with open(_PROBE, "a", encoding="utf-8") as fh:
            fh.write(f"{stage}\n")
    except OSError:
        pass


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    return Path(__file__).resolve().parents[2]


def _report(exc: BaseException) -> None:
    """把未捕获异常落到文件（冻结版可能连 stderr 都是 None）。"""
    text = "".join(traceback.format_exception(exc))
    try:
        CRASH_LOG.write_text(text, encoding="utf-8")
    except OSError:
        pass
    stream = sys.stderr
    if stream is not None:
        try:
            stream.write(text)
            stream.flush()
        except (OSError, ValueError):
            pass


def _run() -> int:
    _mark("entry")
    base = _bundle_root()
    os.environ.setdefault("AOC_ROOT", str(base))

    # onedir 里若同时带了 packages 源码（老布局），优先用源码而不是打进 exe 的副本
    if getattr(sys, "frozen", False):
        for pkg in ("aoc_protocol", "aoc_core", "aoc_navdata", "aoc_route", "aoc_integrations"):
            candidate = base / "packages" / pkg
            if candidate.is_dir():
                sys.path.insert(0, str(candidate))

    _mark("main import pending")
    from main import main

    _mark("main imported")
    return main()


if __name__ == "__main__":
    try:
        code = _run()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 冻结版弹对话框会卡死 CI，只能吞掉
        _report(exc)
        code = 1
    _mark(f"exit={code}")
    raise SystemExit(code)
