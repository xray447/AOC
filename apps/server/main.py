"""开发入口：python apps/server/main.py --port 8080 --demo"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for pkg in (ROOT / "packages" / "aoc_core", HERE):
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))

from aoc_server.main import main  # noqa: E402

if __name__ == "__main__":
    main()
