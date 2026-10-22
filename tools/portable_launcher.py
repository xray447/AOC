"""便携包排障启动器（打包为 start.py，会显示控制台）。

正常使用请双击 `AOC-portable.exe`（托盘 + 无控制台 + 默认浏览器）。
这个脚本只在排障时用：同样优先起包内自包含的 `aoc-core\\aoc-core.exe`，
缺少 exe 时退回 Python 源码（要求本机有 Python 3.10+）。
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    home = Path(os.environ.get("AOC_HOME") or
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AOC")
    home.mkdir(parents=True, exist_ok=True)
    simlink = ROOT / "apps" / "simlink" / "aoc-simlink.exe"
    child = None
    if simlink.exists():
        args = [str(simlink), "--port", "0", "--home", str(home)]
        extra = os.environ.get("AOC_SIMLINK_ARGS", "").strip()
        if extra:
            args += shlex.split(extra)
        try:
            child = subprocess.Popen(args)
            print(f"SimLink started (pid {child.pid})")
        except OSError as exc:
            print(f"SimLink 启动失败：{exc}")
    else:
        print("未找到 apps/simlink/aoc-simlink.exe，遥测功能不可用。")

    core_exe = ROOT / "aoc-core" / "aoc-core.exe"
    if core_exe.exists():
        cmd = [str(core_exe)]
    else:
        print("未找到 aoc-core/aoc-core.exe，退回 Python 源码（需要 Python 3.10+）。")
        cmd = [sys.executable, "-X", "utf8", str(ROOT / "apps" / "aoc-core" / "main.py")]
    cmd += ["--port", "0", "--home", str(home), "--static-dir", str(ROOT / "app"), "--open"]
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130
    finally:
        if child is not None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
