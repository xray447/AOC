"""PyInstaller 入口（D-30）：先固定资源根目录，再交给 `main.main()`。

打包时不带 Python 解释器与 `packages/` 源码目录，`data/` 随包发布；航路建图源码已在
`aoc_route.net`（随包进 exe），不再需要仓库外的 `Pre-train/src`。
`AOC_ROOT` 指向 PyInstaller 的 `_MEIPASS`（onedir 即 `_internal/`）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    return Path(__file__).resolve().parents[2]


_base = _bundle_root()
os.environ.setdefault("AOC_ROOT", str(_base))

# onedir 里若同时带了 packages 源码（老布局），优先用源码而不是打进 exe 的副本
if getattr(sys, "frozen", False):
    for pkg in ("aoc_protocol", "aoc_core", "aoc_navdata", "aoc_route", "aoc_integrations"):
        candidate = _base / "packages" / pkg
        if candidate.is_dir():
            sys.path.insert(0, str(candidate))

from main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
