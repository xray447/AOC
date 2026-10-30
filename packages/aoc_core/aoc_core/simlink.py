"""SimLink 本地 HTTP 客户端（127.0.0.1 + token）。

aoc-core 只读取采样/事件/状态并发送控制命令；不直接持有 SimConnect。

连接复用：每次新建 `httpx.AsyncClient` 在 Windows 上要重建 SSL 上下文（实测
约 0.5s/次），而轮询最短 1s、前端还有 2s 的 pulse/flight-status，按请求建客户端
会变成持续的 CPU 尖峰（D-27 残留）。这里对同一事件循环复用一条客户端。
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx


class SimLinkError(RuntimeError):
    pass


class SimLinkClient:
    def __init__(self, base_url: str, token: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        # 事件循环换了（测试里常见）/已关闭：重建，避免复用别的 loop 的连接池
        if self._http is None or self._http.is_closed or self._loop is not loop:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-SimLink-Token": self.token},
                timeout=httpx.Timeout(self.timeout, connect=1.5),
            )
            self._loop = loop
        return self._http

    async def aclose(self) -> None:
        """关闭连接池。旧事件循环已关闭时忽略（连接随进程/GC 释放）。"""
        http, self._http, self._loop = self._http, None, None
        if http is None or http.is_closed:
            return
        try:
            await http.aclose()
        except Exception:  # noqa: BLE001
            pass

    async def status(self) -> dict[str, Any]:
        r = await self._client().get("/status")
        r.raise_for_status()
        return r.json()

    async def latest_sample(self) -> dict[str, Any] | None:
        """最新一帧采样：优先 `/latest`（未开始记录时也能拿到实时值），退化到 `/samples` 末尾。"""
        c = self._client()
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
        r = await self._client().get("/samples", params={"since": since, "limit": limit})
        r.raise_for_status()
        data = r.json()
        return data.get("samples", data) if isinstance(data, dict) else data

    async def events(self, since: int = -1, limit: int = 500) -> list[dict[str, Any]]:
        r = await self._client().get("/events", params={"since": since, "limit": limit})
        r.raise_for_status()
        data = r.json()
        return data.get("events", data) if isinstance(data, dict) else data

    async def command(self, action: str, **kwargs: Any) -> dict[str, Any]:
        r = await self._client().post("/command", json={"action": action, **kwargs})
        r.raise_for_status()
        return r.json()
