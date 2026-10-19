"""打包 AOC 轨迹回放探针便携版：dist + 本地服务 + 启动脚本 → zip。

    python tools/make_portable.py            # 生成 out/AOC-Map-Probe-portable-0.1.0.zip
    python tools/make_portable.py --keep     # 同时保留下载 staging 目录
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PORTABLE = ROOT / "portable"
STAGE = ROOT / "out" / "portable-stage" / "AOC-Map-Probe"
OUT_DIR = ROOT / "out"

NAME = "AOC-Map-Probe"
VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留 staging 目录")
    args = ap.parse_args()

    if not (DIST / "index.html").is_file():
        raise SystemExit("dist/index.html 不存在，请先执行 npm run build")

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    shutil.copytree(DIST, STAGE / "app")
    for name in ("server.py", "start.bat", "README.txt"):
        shutil.copy2(PORTABLE / name, STAGE / name)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUT_DIR / f"{NAME}-portable-{VERSION}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(STAGE.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(STAGE.parent))

    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    raw = sum(p.stat().st_size for p in files)
    print(f"files={len(files)} raw={raw / 1024:.1f}KB zip={zip_path.stat().st_size / 1024:.1f}KB")
    print(f"zip={zip_path}")
    if not args.keep:
        shutil.rmtree(STAGE.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
