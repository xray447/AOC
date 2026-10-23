"""用 PyInstaller 生成自包含的 aoc-core（D-30 / TODO §4）。

用法：
    python -X utf8 tools/build_core_exe.py [--verify] [--console]

产物：out/core/aoc-core/aoc-core.exe（onedir，含 _internal/）
启动参数与源码版一致：--port --token --home --static-dir。

前提：pip install pyinstaller（CI 里单独装，不进 requirements.txt）。
目标机器不需要 Python：numpy / scipy / tzdata 都在包内。

`--verify`：跑一次 `aoc-core.exe --version/--help`。产物是 `--noconsole`，没有
stdout/stderr，且**未捕获异常会让 PyInstaller 弹模态对话框**（无桌面的 runner 上等于
永久挂起，曾经把这一步拖到 1800s 超时）。所以探活给短超时；一旦超时/非零，再用
`--console` 打同一份代码把真实报错抓出来。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "core"
DIST = OUT
WORK = ROOT / "out" / "pyinstaller-build"
SPEC = ROOT / "out" / "pyinstaller-spec"
EXE = OUT / "aoc-core" / "aoc-core.exe"
VERIFY_DIR = ROOT / "out" / "core-verify"
PACKAGES = ["aoc_protocol", "aoc_core", "aoc_navdata", "aoc_route", "aoc_integrations"]
# 133MB onedir 首次启动会被 runner 上的 Defender 扫一遍，留足时间；但绝不再无限等
VERIFY_TIMEOUT = 300
# entry.py 写入的启动阶段 / 崩溃栈（%TEMP% 下，冻结版没有控制台只能落文件）
PROBE_FILE = Path(tempfile.gettempdir()) / "aoc-core-probe.txt"
CRASH_LOG = Path(tempfile.gettempdir()) / "aoc-core-crash.log"


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


def pyinstaller_args(console: bool, name: str = "aoc-core", distpath: Path = DIST) -> list[str]:
    args = [
        "--noconfirm", "--clean",
        "--onedir",
        "--name", name,
        "--distpath", str(distpath),
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


def build(console: bool, name: str = "aoc-core", distpath: Path = DIST) -> int:
    cmd = [sys.executable, "-m", "PyInstaller", *pyinstaller_args(console, name, distpath)]
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def _probe(exe: Path, flag: str) -> tuple[int | None, bytes, bytes]:
    """跑一次 `<exe> <flag>`，返回 (退出码 | 超时 None, stdout, stderr)。"""
    env = {**os.environ, "AOC_PROBE_FILE": str(PROBE_FILE)}
    try:
        probe = subprocess.run([str(exe), flag], capture_output=True, timeout=VERIFY_TIMEOUT,
                               stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        print(f"{exe.name} {flag} 超时（>{VERIFY_TIMEOUT}s）")
        return None, b"", b""
    except OSError as exc:
        print(f"{exe.name} {flag} 启动失败：{exc}")
        return None, b"", b""
    return probe.returncode, probe.stdout, probe.stderr


def _dump_logs() -> None:
    if PROBE_FILE.is_file():
        print(f"[probe] {PROBE_FILE}")
        print(PROBE_FILE.read_text(encoding="utf-8", errors="replace")[-2000:])
    if CRASH_LOG.is_file():
        print(f"[crash] {CRASH_LOG}")
        print(CRASH_LOG.read_text(encoding="utf-8", errors="replace")[-4000:])


def verify_exe() -> int:
    """探活冻结版；失败时用 --console 版复现并打印真实报错。"""
    for path in (PROBE_FILE, CRASH_LOG):
        path.unlink(missing_ok=True)
    failed = None
    for flag in ("--version", "--help"):
        code, _out, err = _probe(EXE, flag)
        if code != 0:
            failed = flag
            if err:
                print(err.decode("utf-8", "replace")[-2000:])
            break
    if failed is None:
        print("verify ok: aoc-core.exe --version / --help")
        return 0

    print(f"aoc-core.exe {failed} 失败")
    _dump_logs()
    # noconsole 版看不到 stderr：同一份代码再用 --console 打一次，让真实异常进 CI 日志
    print("\n[diagnose] 构建 --console 版复现（仅诊断，不用作发布产物）")
    shutil.rmtree(VERIFY_DIR, ignore_errors=True)
    if build(console=True, name="aoc-core-verify", distpath=VERIFY_DIR) != 0:
        print("--console 版构建失败")
        return 1
    console_exe = VERIFY_DIR / "aoc-core-verify" / "aoc-core-verify.exe"
    code, out, err = _probe(console_exe, "--version")
    if code == 0:
        print("--console 版探活正常：问题只出在 --noconsole（窗口化）产物上")
        return 1
    print(f"--console 版退出码 {code}")
    print(out.decode("utf-8", "replace")[-2000:])
    print(err.decode("utf-8", "replace")[-6000:])
    _dump_logs()
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="构建后跑一次 aoc-core.exe --version/--help")
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

    code = build(args.console)
    if code != 0:
        return code
    if not EXE.exists():
        print(f"未生成 {EXE}")
        return 1
    size_mb = sum(p.stat().st_size for p in EXE.parent.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"aoc-core onedir: {EXE} ({size_mb:.1f} MB)")

    if args.verify:
        return verify_exe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
