"""本地数据目录与运行时文件。

默认 `%LOCALAPPDATA%/AOC`，可用环境变量 `AOC_HOME` 覆盖（测试/便携模式）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_home() -> Path:
    env = os.environ.get("AOC_HOME")
    if env:
        return Path(env).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return Path(base) / "AOC"


@dataclass(frozen=True)
class AppPaths:
    home: Path

    @classmethod
    def create(cls, home: str | Path | None = None) -> "AppPaths":
        root = Path(home).expanduser().resolve() if home else default_home()
        paths = cls(root)
        for d in (paths.home, paths.tracks, paths.cache, paths.logs, paths.backups):
            d.mkdir(parents=True, exist_ok=True)
        return paths

    @property
    def db(self) -> Path:
        return self.home / "aoc.db"

    @property
    def tracks(self) -> Path:
        return self.home / "tracks"

    @property
    def cache(self) -> Path:
        return self.home / "cache"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def runtime(self) -> Path:
        return self.home / "runtime.json"

    @property
    def lock(self) -> Path:
        return self.home / "aoc.lock"

    def resolve(self, relative: str | Path) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else self.home / p

    def relative(self, path: str | Path) -> str:
        p = Path(path)
        try:
            return str(p.resolve().relative_to(self.home))
        except ValueError:
            return str(p)
