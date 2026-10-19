"""V-10 采集器进程：合成轨迹 -> 分批上报 -> 心跳；后端不可用时重试不退出。"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

BATCH_SIZE = 20
DT = 0.125  # 8Hz 采样


def point(seq: int, i: int) -> dict:
    k = seq * BATCH_SIZE + i
    return {
        "t": round(k * DT, 3),
        "lat": round(35.55 + k * 1e-5, 6),
        "lon": round(139.78 + k * 1e-5, 6),
        "alt": round(4000 - k * 3.0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://127.0.0.1:8011")
    ap.add_argument("--fid", default="V10")
    ap.add_argument("--batches", type=int, default=14)
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--ack-file", default="")
    args = ap.parse_args()

    ack_path = Path(args.ack_file) if args.ack_file else OUT / f"ack_{args.fid}.json"
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    acked = -1
    if ack_path.exists():
        try:
            acked = int(json.loads(ack_path.read_text(encoding="utf-8")).get("acked_seq", -1))
        except Exception:
            acked = -1

    session = uuid.uuid4().hex[:12]
    state = {"acked": acked, "buffered": 0}
    stop = threading.Event()

    def beat() -> None:
        while not stop.is_set():
            try:
                httpx.post(
                    f"{args.backend}/api/collector/heartbeat",
                    json={
                        "session_id": session,
                        "fid": args.fid,
                        "acked_seq": state["acked"],
                        "buffered": state["buffered"],
                    },
                    timeout=2.0,
                )
            except Exception:
                pass
            stop.wait(0.3)

    threading.Thread(target=beat, daemon=True).start()

    def save_ack(seq: int) -> None:
        ack_path.write_text(
            json.dumps({"fid": args.fid, "acked_seq": seq, "session_id": session}),
            encoding="utf-8",
        )

    sent = 0
    dup = 0
    deadline = time.time() + 60.0
    try:
        for seq in range(acked + 1, args.batches):
            payload = {"seq": seq, "points": [point(seq, i) for i in range(BATCH_SIZE)]}
            while True:
                if time.time() > deadline:
                    print(f"timeout seq={seq}", file=sys.stderr, flush=True)
                    return 2
                try:
                    r = httpx.post(
                        f"{args.backend}/api/flights/{args.fid}/samples",
                        json=payload,
                        timeout=3.0,
                    )
                    if r.status_code == 200:
                        dup += int(r.json().get("dup", 0))
                        break
                except Exception:
                    state["buffered"] = BATCH_SIZE
                time.sleep(0.2)
            state["acked"] = seq
            state["buffered"] = 0
            sent += 1
            save_ack(seq)
            time.sleep(args.interval)
    finally:
        stop.set()

    print(
        json.dumps(
            {
                "session_id": session,
                "fid": args.fid,
                "resumed_from": acked,
                "sent": sent,
                "dup": dup,
                "acked_seq": state["acked"],
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
