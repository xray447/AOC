"""生成 M1 便携 ZIP：前端 dist + aoc-core 源码 + SimLink + 启动脚本。

用法：
    python -X utf8 tools/make_portable.py [--build] [--no-simlink]

依赖：Node（构建前端）、Python 3.10+（运行）、.NET 8（可选，构建 SimLink）。
输出：out/AOC-portable-<version>-win64.zip
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

START_BAT = r"""@echo off
setlocal
cd /d "%~dp0"
if "%AOC_HOME%"=="" set "AOC_HOME=%LOCALAPPDATA%\AOC"
if not exist "%AOC_HOME%" mkdir "%AOC_HOME%"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ was not found on PATH.
  echo Install Python from https://www.python.org/downloads/windows/ and try again.
  pause
  exit /b 1
)

python -X utf8 "%~dp0start.py"
if errorlevel 1 pause
"""

README = """AOC 模拟飞行运行中心 · M1 个人模式便携版
=========================================

启动：双击 start.bat（不要用 python start.bat）。
依赖：Windows 10/11 x64 + Python 3.10+（需在 PATH 中）；在线底图需联网，设置里可切换离线底图。
数据：%LOCALAPPDATA%\\AOC（aoc.db / tracks / logs / backups）。

首次运行：
1. 向导里选择 Little Navmap / Navigraph 的 SQLite（不提供也能飞，只是航路走 SimBrief）。
2. 若有 aoc-simlink.exe，start.bat 会自动拉起；没有模拟器时可在命令行运行：
   apps\\simlink\\aoc-simlink.exe --demo --home "%LOCALAPPDATA%\\AOC"
   然后刷新首页，演示会合成一次 ZBAA→ZSSS 并自动记录。
3. 首页「开始记录」需要 SimLink 在线；SimLink 也会在起飞 5 秒后自动开始。

航路：日本 AIP（jp-routes，启动时自动同步）→ 覆盖检查 → 本地航路图（用你的 navdata 现场建图）；任何失败都会给 SimBrief 链接。
navdata 不随包分发（许可与体积），请使用自己的 Little Navmap / Navigraph 数据。
首次启动会用 navdata 建一次图（约 15 秒，后台进行），缓存在 %LOCALAPPDATA%\\AOC\\cache。

已知限制（M1）：
- 不是 Tauri 安装包，是浏览器 + 本地 Python 服务；Tauri 外壳源码在 apps/client/src-tauri。
- 无网络时 AIP 回退到本地缓存；从未联网过则只有内置样例（fixture）。
- 建图需要 scipy（requirements.txt 已包含）。
- Volanta 使用非官方接口，可能失效；CSV 导入与手动补录可用。
"""


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, shell=os.name == "nt")


def build_frontend() -> None:
    client = ROOT / "apps" / "client"
    if not (client / "node_modules").exists():
        run(["npm.cmd" if os.name == "nt" else "npm", "install"], client)
    run(["npm.cmd" if os.name == "nt" else "npm", "run", "build"], client)


def build_simlink(target: Path) -> bool:
    proj = ROOT / "apps" / "simlink"
    try:
        run(["dotnet", "publish", str(proj), "-c", "Release", "-r", "win-x64",
             "--self-contained", "false", "-o", str(target)], ROOT)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"SimLink 未打包：{exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="重新构建前端")
    ap.add_argument("--no-simlink", action="store_true", help="不打包 SimLink")
    args = ap.parse_args()

    if args.build or not (ROOT / "apps" / "client" / "dist" / "index.html").exists():
        build_frontend()

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copytree(ROOT / "apps" / "client" / "dist", STAGE / "app")
    shutil.copytree(ROOT / "packages", STAGE / "packages",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "apps" / "aoc-core", STAGE / "apps" / "aoc-core",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "data", STAGE / "data")
    # 建图脚本（只读导航库，不需要模型权重）；首次运行会用用户 navdata 现场建图并缓存
    shutil.copytree(ROOT / "Pre-train" / "src", STAGE / "Pre-train" / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (STAGE / "start.bat").write_text(START_BAT, encoding="ascii", newline="\r\n")
    shutil.copy2(ROOT / "tools" / "portable_launcher.py", STAGE / "start.py")
    (STAGE / "README.txt").write_text(README, encoding="utf-8")

    if not args.no_simlink:
        build_simlink(STAGE / "apps" / "simlink")

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
