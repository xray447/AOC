"""V-10 探针后端：健康检查 + 采集器心跳 + 幂等批次入库（SQLite 持久化）。"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_START = time.time()
HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("AOC_PROBE_DB", HERE.parent / "out" / "state.db"))
STALE_AFTER_S = float(os.environ.get("AOC_PROBE_STALE", "1.0"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    fid       TEXT    NOT NULL,
    seq       INTEGER NOT NULL,
    n         INTEGER NOT NULL,
    t_first   REAL    NOT NULL,
    t_last    REAL    NOT NULL,
    PRIMARY KEY (fid, seq)
);
CREATE TABLE IF NOT EXISTS collector (
    session_id TEXT PRIMARY KEY,
    last_seen  REAL NOT NULL,
    ack_seq    INTEGER NOT NULL DEFAULT -1,
    buffered   INTEGER NOT NULL DEFAULT 0
);
"""


def _con() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=5.0)
    con.executescript(SCHEMA)
    return con


app = FastAPI(title="AOC V-10 probe backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Heartbeat(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    fid: str = Field(min_length=1, max_length=64)
    acked_seq: int = -1
    buffered: int = 0


class SamplePoint(BaseModel):
    t: float
    lat: float
    lon: float
    alt: float


class SampleBatch(BaseModel):
    seq: int = Field(ge=0)
    points: list[SamplePoint] = Field(min_length=1, max_length=5000)


@app.get("/health")
def health() -> dict:
    now = time.time()
    with _con() as con:
        batches, points = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(n), 0) FROM samples"
        ).fetchone()
        row = con.execute(
            "SELECT session_id, last_seen, ack_seq, buffered FROM collector"
            " ORDER BY last_seen DESC LIMIT 1"
        ).fetchone()
        sessions = con.execute("SELECT COUNT(*) FROM collector").fetchone()[0]
    age = round(now - row[1], 3) if row else None
    return {
        "ok": True,
        "uptime_s": round(now - APP_START, 3),
        "db": str(DB_PATH),
        "batches": batches,
        "points": points,
        "sessions": sessions,
        "collector": {
            "session_id": row[0] if row else None,
            "last_seen_age_s": age,
            "state": "online" if age is not None and age <= STALE_AFTER_S else "offline",
            "ack_seq": row[2] if row else None,
            "buffered": row[3] if row else None,
        },
    }


@app.post("/api/collector/heartbeat")
def heartbeat(hb: Heartbeat) -> dict:
    with _con() as con:
        con.execute(
            "INSERT INTO collector (session_id, last_seen, ack_seq, buffered)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            " last_seen=excluded.last_seen,"
            " ack_seq=MAX(collector.ack_seq, excluded.ack_seq),"
            " buffered=excluded.buffered",
            (hb.session_id, time.time(), hb.acked_seq, hb.buffered),
        )
        total = con.execute("SELECT COUNT(*) FROM samples WHERE fid=?", (hb.fid,)).fetchone()[0]
    return {"ok": True, "server_time": time.time(), "fid": hb.fid, "batches": total}


@app.post("/api/flights/{fid}/samples")
def ingest(fid: str, batch: SampleBatch) -> dict:
    if not fid or len(fid) > 64:
        raise HTTPException(status_code=422, detail="bad fid")
    n = len(batch.points)
    t_first = min(p.t for p in batch.points)
    t_last = max(p.t for p in batch.points)
    with _con() as con:
        before = con.total_changes
        con.execute(
            "INSERT OR IGNORE INTO samples (fid, seq, n, t_first, t_last) VALUES (?,?,?,?,?)",
            (fid, batch.seq, n, t_first, t_last),
        )
        accepted = con.total_changes - before
        total = con.execute("SELECT COUNT(*) FROM samples WHERE fid=?", (fid,)).fetchone()[0]
    return {"ok": True, "accepted": accepted, "dup": 1 - accepted, "total": total}


@app.get("/api/flights/{fid}")
def flight(fid: str) -> dict:
    with _con() as con:
        count, points, lo, hi = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(n),0), MIN(seq), MAX(seq) FROM samples WHERE fid=?",
            (fid,),
        ).fetchone()
    return {
        "fid": fid,
        "batches": count,
        "points": points,
        "min_seq": lo,
        "max_seq": hi,
        "contiguous": count > 0 and count == (hi - lo + 1),
    }


def main() -> None:
    global DB_PATH, STALE_AFTER_S
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--stale", type=float, default=STALE_AFTER_S)
    args = ap.parse_args()
    DB_PATH = Path(args.db).resolve()
    STALE_AFTER_S = args.stale
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
