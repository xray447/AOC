"""用 PyInstaller 生成自包含的 aoc-core（D-30 / TODO §4）。

用法：
    python -X utf8 tools/build_core_exe.py [--verify] [--console]

产物：out/core/aoc-core/aoc-core.exe（onedir，含 _internal/）
启动参数与源码版一致：--port --token --home --static-dir。

前提：pip install pyinstaller（CI 里单独装，不进 requirements.txt）。
目标机器不需要 Python：numpy / scipy / tzdata 都在包内。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "core"
DIST = OUT
WORK = ROOT / "out" / "pyinstaller-build"
SPEC = ROOT / "out" / "pyinstaller-spec"
EXE = OUT / "aoc-core" / "aoc-core.exe"
PACKAGES = ["aoc_protocol", "aoc_core", "aoc_navdata", "aoc_route", "aoc_integrations"]


def data_args() -> list[str]:
    """按目录是否存在拼 `--add-data`。

    航路建图 / Dijkstra 源码已内置在 `packages/aoc_route/aoc_route/net`（随
    `--hidden-import aoc_route` 进包），产物只需要 `data/`；目录缺失时跳过而不是让
    PyInstaller 直接 ERROR（干净 checkout 上曾有 `Unable to find ... when adding`）。
    """
    pairs = [(ROOT / "data", "data")]
    args: list[str] = []
    for src, dest in pairs:
        if not src.is_dir():
            print(f"[warn] 跳过 --add-data：{src} 不存在（产物里没有 {dest}）")
            continue
        args += ["--add-data", f"{src};{dest}"]
    return args


def pyinstaller_args(console: bool) -> list[str]:
    args = [
        "--noconfirm", "--clean",
        "--onedir",
        "--name", "aoc-core",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(SPEC),
        *data_args(),
        "--paths", str(ROOT / "apps" / "aoc-core"),
        # 建图在运行时用 sys.path 动态导入网络模块，静态分析看不到
        "--hidden-import", "numpy",
        "--hidden-import", "scipy",
        "--hidden-import", "scipy.sparse",
        "--hidden-import", "scipy.spatial",
        "--collect-submodules", "uvicorn",
        "--collect-all", "tzdata",
        # 这些是开发机 site-packages 里的无关大件（torch 315MB / pandas / PIL …）；
        # AOC 运行时只依赖 fastapi/uvicorn/pydantic/httpx/numpy/scipy/tzdata。
        "--exclude-module", "torch",
        "--exclude-module", "functorch",
        "--exclude-module", "pandas",
        "--exclude-module", "PIL",
        "--exclude-module", "matplotlib",
        "--exclude-module", "tkinter",
        "--exclude-module", "PyQt5",
        "--exclude-module", "sklearn",
        "--exclude-module", "IPython",
        "--exclude-module", "pytest",
    ]
    for pkg in PACKAGES:
        args += ["--paths", str(ROOT / "packages" / pkg)]
        args += ["--hidden-import", pkg]
    # 航路图内核（建图 + Dijkstra）在 graph.py 里函数内惰性 import，显式收集避免漏包
    args += ["--collect-submodules", "aoc_route"]
    args.append("--noconsole" if not console else "--console")
    args.append(str(ROOT / "apps" / "aoc-core" / "entry.py"))
    return args


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="构建后跑一次 aoc-core.exe --help")
    ap.add_argument("--console", action="store_true", help="保留控制台（排障用）")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller：pip install pyinstaller")
        return 2

    for folder in (OUT, WORK, SPEC):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

    cmd = [sys.executable, "-m", "PyInstaller", *pyinstaller_args(args.console)]
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    if not EXE.exists():
        print(f"未生成 {EXE}")
        return 1
    size_mb = sum(p.stat().st_size for p in EXE.parent.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"aoc-core onedir: {EXE} ({size_mb:.1f} MB)")

    if args.verify:
        probe = subprocess.run([str(EXE), "--help"], capture_output=True, timeout=180)
        if probe.returncode != 0:
            print(probe.stderr.decode("utf-8", "replace")[-2000:])
            print("aoc-core.exe --help 失败")
            return 1
        print("verify ok: aoc-core.exe --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
