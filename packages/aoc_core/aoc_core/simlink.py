"""SimLink 本地 HTTP 客户端（127.0.0.1 + token）。

aoc-core 只读取采样/事件/状态并发送控制命令；不直接持有 SimConnect。
"""
from __future__ import annotations

from typing import Any

import httpx


class SimLinkError(RuntimeError):
    pass


class SimLinkClient:
    def __init__(self, base_url: str, token: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-SimLink-Token": self.token},
            timeout=httpx.Timeout(self.timeout, connect=1.5),
        )

    async def status(self) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get("/status")
            r.raise_for_status()
            return r.json()

    async def latest_sample(self) -> dict[str, Any] | None:
        """最新一帧采样：优先 `/latest`（未开始记录时也能拿到实时值），退化到 `/samples` 末尾。"""
        async with self._client() as c:
            try:
                r = await c.get("/latest")
                if r.status_code == 200:
                    data = r.json()
                    sample = data.get("sample") if isinstance(data, dict) else None
                    if sample:
                        return sample
            except Exception:  # noqa: BLE001 - 老版本 SimLink 没有 /latest
                pass
            r = await c.get("/samples", params={"since": -1, "limit": 3000})
            r.raise_for_status()
            data = r.json()
            samples = data.get("samples", data) if isinstance(data, dict) else data
            return samples[-1] if samples else None

    async def samples(self, since: int = -1, limit: int = 3000) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get("/samples", params={"since": since, "limit": limit})
            r.raise_for_status()
            data = r.json()
            return data.get("samples", data) if isinstance(data, dict) else data

    async def events(self, since: int = -1, limit: int = 500) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get("/events", params={"since": since, "limit": limit})
            r.raise_for_status()
            data = r.json()
            return data.get("events", data) if isinstance(data, dict) else data

    async def command(self, action: str, **kwargs: Any) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.post("/command", json={"action": action, **kwargs})
            r.raise_for_status()
            return r.json()
