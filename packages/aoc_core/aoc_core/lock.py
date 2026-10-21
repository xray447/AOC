"""单实例锁（M2 §4.1：同一时刻只允许一个实例写库）。

用操作系统文件区域锁：进程退出/崩溃时由内核释放，不会留下「僵尸锁」。
设置 `AOC_SINGLE_INSTANCE=0` 可关闭（CI/冒烟脚本需要并行时）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

WINDOWS = os.name == "nt"


class InstanceLocked(RuntimeError):
    def __init__(self, path: Path):
        super().__init__(
            f"另一个 AOC 实例正在使用本机数据目录（{path.parent}）。"
            "请关闭已打开的 AOC 客户端后重试；同一架飞机不能被两个窗口同时占用。")
        self.path = path


class SingleInstance:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def acquire(self, retries: int = 20, delay: float = 0.1) -> None:
        if os.environ.get("AOC_SINGLE_INSTANCE", "1") in ("0", "false", "False"):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(retries):
            handle = open(self.path, "a+", encoding="utf-8")
            try:
                if WINDOWS:
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                if attempt == retries - 1:
                    raise InstanceLocked(self.path) from None
                time.sleep(delay)
                continue
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            self._handle = handle
            return

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if WINDOWS:
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
