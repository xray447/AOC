"""便携包启动器（打包为 start.py）。

不使用 cmd 的 `start` 内建命令：先拉起 SimLink（可选），再启动 aoc-core。
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

    core = ROOT / "apps" / "aoc-core" / "main.py"
    cmd = [sys.executable, "-X", "utf8", str(core), "--port", "0", "--home", str(home),
           "--static-dir", str(ROOT / "app"), "--open"]
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
