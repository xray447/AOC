"""生成便携 ZIP：`AOC-portable.exe`（托盘启动器）+ 自包含 aoc-core + SimLink + 前端。

用法：
    python -X utf8 tools/make_portable.py [--build] [--no-simlink] [--no-core] [--no-launcher]

依赖：Node（构建前端）、Python（运行本脚本）、.NET 8 SDK（自包含发布 SimLink 与启动器）、
      打包 aoc-core 需要 PyInstaller（`--no-core` 时跳过，直接复用 out/core）。

产物：out/AOC-portable-<version>-win64.zip
目标机器不需要 Python / .NET / Node。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
OUT = ROOT / "out"
STAGE = OUT / f"AOC-portable-{VERSION}"
CORE_DIR = OUT / "core" / "aoc-core"

START_BAT = r"""@echo off
setlocal
cd /d "%~dp0"
if "%AOC_HOME%"=="" set "AOC_HOME=%LOCALAPPDATA%\AOC"
if not exist "%AOC_HOME%" mkdir "%AOC_HOME%"

rem Troubleshooting entry: shows a console window.
rem Normal use: double-click AOC-portable.exe (tray, no console).
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH; start.bat is only a troubleshooting entry.
  echo Double-click AOC-portable.exe instead.
  pause
  exit /b 1
)

python -X utf8 "%~dp0start.py"
if errorlevel 1 pause
"""

README = """AOC 模拟飞行运行中心 · M1 个人模式便携版
=========================================

启动：双击 AOC-portable.exe
  - 无控制台窗口，托盘出现 AOC 图标；
  - 健康检查通过后自动打开默认浏览器；
  - 托盘菜单：打开客户端 / 打开日志目录 / 退出（退出时结束 aoc-core 与 aoc-simlink）；
  - 关闭浏览器页面不会结束服务，需要退出请用托盘菜单。
依赖：Windows 10/11 x64，无需 Python / .NET / Node。在线底图需联网，设置里可切换离线底图。
数据：%LOCALAPPDATA%\\AOC（aoc.db / tracks / logs / backups）。
日志：%LOCALAPPDATA%\\AOC\\logs（core.log / simlink.log / aoc-core.log）。

首次运行：
1. 向导里选择 Little Navmap / Navigraph 的 SQLite（不提供也能飞，只是航路走 SimBrief）。
2. apps\\simlink\\aoc-simlink.exe 会自动拉起；没有模拟器时可在命令行运行：
   apps\\simlink\\aoc-simlink.exe --demo --home "%LOCALAPPDATA%\\AOC"
   然后刷新页面，演示会合成一次 ZBAA→ZSSS 并自动记录。
3. 「开始记录」需要 SimLink 在线；SimLink 也会在起飞 5 秒后自动开始。

排障：
- start.bat / start.py 是带控制台的旧入口（需要本机 Python），只在排障时用；
  它同样优先使用包内 aoc-core\\aoc-core.exe。
- navdata 不随包分发（许可与体积），请使用自己的 Little Navmap / Navigraph 数据。

航路：日本 AIP（jp-routes，启动时自动同步）→ 覆盖检查 → 本地航路图（用你的 navdata 现场建图）；
任何失败都会给 SimBrief 链接。
"""


def run(cmd: list[str], cwd: Path) -> bool:
    print("+", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=cwd, check=True, shell=os.name == "nt")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"失败：{exc}")
        return False


def build_frontend() -> None:
    client = ROOT / "apps" / "client"
    if not (client / "node_modules").exists():
        run(["npm.cmd" if os.name == "nt" else "npm", "install"], client)
    run(["npm.cmd" if os.name == "nt" else "npm", "run", "build"], client)


def build_core() -> bool:
    if not run(["python", "-X", "utf8", "tools/build_core_exe.py"], ROOT):
        return False
    return (CORE_DIR / "aoc-core.exe").exists()


def build_simlink(target: Path) -> bool:
    return run(["dotnet", "publish", "apps/simlink", "-c", "Release", "-r", "win-x64",
                "--self-contained", "true", "-o", str(target)], ROOT)


def build_launcher(target: Path) -> Path | None:
    tmp = OUT / "launcher"
    ok = run(["dotnet", "publish", "tools/portable-launcher", "-c", "Release", "-r", "win-x64",
              "--self-contained", "true", "-o", str(tmp)], ROOT)
    if not ok:
        return None
    exe = tmp / "AOC-portable.exe"
    if not exe.exists():
        return None
    shutil.copy2(exe, target / "AOC-portable.exe")
    return target / "AOC-portable.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="重新构建前端")
    ap.add_argument("--no-simlink", action="store_true", help="不打包 SimLink")
    ap.add_argument("--no-core", action="store_true", help="不重新打 aoc-core.exe（复用 out/core）")
    ap.add_argument("--no-launcher", action="store_true", help="不打包 AOC-portable.exe")
    args = ap.parse_args()

    if args.build or not (ROOT / "apps" / "client" / "dist" / "index.html").exists():
        build_frontend()

    if not args.no_core and not build_core():
        print("aoc-core.exe 打包失败（先 pip install pyinstaller，或用 --no-core 复用 out/core）")
        return 1
    if not (CORE_DIR / "aoc-core.exe").exists():
        print(f"缺少 {CORE_DIR / 'aoc-core.exe'}，先运行 tools/build_core_exe.py")
        return 1

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copytree(ROOT / "apps" / "client" / "dist", STAGE / "app")
    shutil.copytree(CORE_DIR, STAGE / "aoc-core")
    (STAGE / "start.bat").write_text(START_BAT, encoding="ascii", newline="\r\n")
    shutil.copy2(ROOT / "tools" / "portable_launcher.py", STAGE / "start.py")
    (STAGE / "README.txt").write_text(README, encoding="utf-8")

    if not args.no_simlink and not build_simlink(STAGE / "apps" / "simlink"):
        print("SimLink 未打包：便携包将没有遥测")
    if not args.no_launcher:
        if build_launcher(STAGE) is None:
            print("AOC-portable.exe 未打包：只能用 start.bat（需要 Python）")

    zip_path = OUT / f"AOC-portable-{VERSION}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in STAGE.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(STAGE))
    print(f"portable zip: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
