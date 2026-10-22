"""飞行记录编排：SimLink 采样 → 自动开始/结束 → 落地评估 → 轨迹分段 → 日志。

个人模式只记录与提示异常，不做经济惩罚（P-04 / P-06）。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from aoc_navdata import NavData
from aoc_protocol.schemas import Phase, RecordingStatus

from .db import Database, utcnow
from .landing import evaluate, rating_thresholds
from .paths import AppPaths
from .track import SamplingConfig, fidelity_m, select_saved, write_chunks

ACTIVE_KEY = "active_recording"
AUTO_TAKEOFF_AGL_FT = 50.0
AUTO_TAKEOFF_GS_KT = 40.0
AUTO_STOP_GS_KT = 5.0
AUTO_STOP_HOLD_S = 30.0
FRAME_GAP_S = 3.0


def _iso_add(iso: str, seconds: float) -> str:
    try:
        base = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        base = datetime.now(timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm_sample(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat, lon = float(raw.get("lat")), float(raw.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    def num(key: str, alt: str | None = None, default: float = 0.0) -> float:
        v = raw.get(key, raw.get(alt) if alt else None)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "t": num("t"),
        "lat": lat, "lon": lon,
        "alt_ft": num("alt_ft", "alt"),
        "agl_ft": num("agl_ft", "agl"),
        "gs_kt": num("gs_kt", "gs"),
        "vs_fpm": num("vs_fpm", "vs"),
        "hdg_true": num("hdg_true", "hdg_deg"),
        "ias_kt": num("ias_kt", "ias"),
        "pitch_deg": num("pitch_deg", "pitch"),
        "bank_deg": num("bank_deg", "bank"),
        "fuel_kg": num("fuel_kg", "fuel"),
        "g": num("g", "g_force", 1.0),
        "on_ground": bool(raw.get("on_ground")),
        "paused": bool(raw.get("paused")),
        "sim_rate": num("sim_rate", default=1.0),
        "gear": raw.get("gear"),
        "flaps": raw.get("flaps"),
        "mode": raw.get("mode"),
    }


class FlightRecorder:
    def __init__(self, flight_id: str, started_at: str, paths: AppPaths):
        self.flight_id = flight_id
        self.started_at = started_at
        self.paths = paths
        self.samples: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.last_seq = -1
        self.last_t = -1.0
        self.airborne_since: float | None = None
        self.touchdown_t: float | None = None
        self.on_ground_since: float | None = None
        self.phase = Phase.PREFLIGHT
        self.seen_airborne = False
        self._last_state: dict[str, Any] | None = None
        self._raw = self.paths.tracks / flight_id / "raw.jsonl.gz"
        self._raw.parent.mkdir(parents=True, exist_ok=True)
        self._raw_writer = gzip.open(self._raw, "at", encoding="utf-8")

    def add_event(self, t: float, kind: str, payload: dict | None = None) -> None:
        self.events.append({"t": float(t), "type": kind, "payload": payload or {}})

    def ingest(self, raw: dict[str, Any]) -> None:
        sample = _norm_sample(raw)
        if sample is None:
            return
        seq = raw.get("seq")
        if isinstance(seq, int):
            if seq <= self.last_seq:
                return
            self.last_seq = seq
        if sample["t"] < self.last_t - 1e-6:
            return
        self._update_events(sample)
        self.samples.append(sample)
        self.last_t = sample["t"]
        self._raw_writer.write(json.dumps(sample, ensure_ascii=False) + "\n")
        self._raw_writer.flush()
        self._last_state = sample

    def _update_events(self, s: dict[str, Any]) -> None:
        t = float(s["t"])
        prev = self._last_state
        if prev is not None:
            gap = t - float(prev["t"])
            if gap > 300:
                self.add_event(t, "data_gap", {"seconds": round(gap, 1)})
            if prev.get("gear") is not None and s.get("gear") is not None and prev["gear"] != s["gear"]:
                self.add_event(t, "gear", {"state": s["gear"]})
            if prev.get("flaps") is not None and s.get("flaps") is not None and prev["flaps"] != s["flaps"]:
                self.add_event(t, "flaps", {"index": s["flaps"]})
            if not prev.get("paused") and s.get("paused"):
                self.add_event(t, "pause", {"paused": True})
            if prev.get("paused") and not s.get("paused"):
                self.add_event(t, "pause", {"paused": False})
            if abs(float(prev.get("sim_rate") or 1) - float(s.get("sim_rate") or 1)) > 0.01:
                self.add_event(t, "sim_rate", {"from": prev.get("sim_rate"), "to": s.get("sim_rate")})

        if not s["on_ground"]:
            self.seen_airborne = True
        if s["on_ground"]:
            self.on_ground_since = t if self.on_ground_since is None else self.on_ground_since
            if self.airborne_since is not None:
                # 接地：从空中转为地面
                if prev is not None and not prev["on_ground"]:
                    self.touchdown_t = t
                    self.add_event(t, "landing", {"vs_fpm": s.get("vs_fpm"), "g": s.get("g")})
                    self.phase = Phase.LANDING
                    self.airborne_since = None
            elif self.phase == Phase.PREFLIGHT:
                self.phase = Phase.TAXI if float(s.get("gs_kt") or 0) < 40 else Phase.TAXI
        else:
            self.on_ground_since = None
            if self.airborne_since is None:
                self.airborne_since = t
                if prev is not None and prev["on_ground"]:
                    self.add_event(t, "takeoff", {"runway": None})
                    self.phase = Phase.TAKEOFF
            if self.phase not in (Phase.APPROACH, Phase.LANDING):
                agl, vs = float(s.get("agl_ft") or 0), float(s.get("vs_fpm") or 0)
                if agl < 3000 and vs < 0:
                    self.phase = Phase.APPROACH
                elif abs(vs) > 800:
                    self.phase = Phase.CLIMB if vs > 0 else Phase.DESCENT
                elif float(s.get("vs_fpm") or 0) > -200 and agl > 5000:
                    self.phase = Phase.CRUISE
        if self.touchdown_t is not None and s["on_ground"] and self.phase == Phase.LANDING:
            if float(s.get("gs_kt") or 0) < 5:
                self.phase = Phase.TAXI_IN

    def should_auto_stop(self, auto_stop: bool) -> bool:
        if not auto_stop or self.airborne_since is not None or self.on_ground_since is None:
            return False
        if self._last_state is None:
            return False
        if float(self._last_state.get("gs_kt") or 0) >= AUTO_STOP_GS_KT:
            return False
        # 记录器可能是在起飞后才接入（SimLink 自动开始），用「见过空中状态」代替 takeoff 事件
        return self.seen_airborne and float(self._last_state["t"]) - self.on_ground_since >= AUTO_STOP_HOLD_S

    @property
    def raw_points(self) -> int:
        return len(self.samples)

    def close(self) -> None:
        try:
            self._raw_writer.close()
        except Exception:  # noqa: BLE001
            pass


class FlightService:
    def __init__(self, db: Database, paths: AppPaths,
                 nav_provider: Callable[[], NavData | None],
                 settings_provider: Callable[[], dict[str, Any]],
                 aircraft_type: Callable[[], str] | None = None,
                 callsign: Callable[[], str] | None = None):
        self.db = db
        self.paths = paths
        self._nav = nav_provider
        self._settings = settings_provider
        self._aircraft_type = aircraft_type or (lambda: "A320")
        self._callsign = callsign or (lambda: "AOC001")
        self.recorder: FlightRecorder | None = None
        # M2 运营模式钩子：开始录制时读取任务上下文（班表航段/自由飞），落地后交给结算
        self.ops_context: Callable[[], dict[str, Any] | None] | None = None
        self.on_finalized: Callable[[dict[str, Any]], Any] | None = None
        self.simlink_connected = False
        self.sim_connected = False
        self.simlink_version: str | None = None
        self.aircraft_title: str | None = None
        self.last_error: str | None = None
        # 记录状态展示用的计时（口径见 P-04），由 SimLink 下发、只展示不结算
        self.engine_seconds = 0
        self.flight_seconds = 0
        self.engine_estimated = False
        self._persisted = self._load_persisted()

    # -- 持久化 -----------------------------------------------------------
    def _load_persisted(self) -> dict | None:
        try:
            return self.db.setting_get(ACTIVE_KEY)
        except Exception:  # noqa: BLE001
            return None

    def _save_persisted(self) -> None:
        if self.recorder is None:
            self.db.setting_set(ACTIVE_KEY, None)
            return
        self.db.setting_set(ACTIVE_KEY, {
            "flight_id": self.recorder.flight_id,
            "started_at": self.recorder.started_at,
            "last_seq": self.recorder.last_seq,
        })

    def resume(self) -> None:
        data = self._persisted
        if not data:
            return
        raw = self.paths.tracks / data["flight_id"] / "raw.jsonl.gz"
        if not raw.exists():
            self.db.setting_set(ACTIVE_KEY, None)
            return
        rec = FlightRecorder(data["flight_id"], data.get("started_at") or utcnow(), self.paths)
        try:
            with gzip.open(raw, "rt", encoding="utf-8") as f:
                for line in f:
                    try:
                        sample = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rec.samples.append(sample)
                    rec.last_t = max(rec.last_t, float(sample.get("t", 0)))
                    rec._last_state = sample
        except OSError:
            rec.close()
            return
        rec.last_seq = int(data.get("last_seq", -1))
        rec.add_event(rec.last_t, "resumed", {"flight_id": rec.flight_id})
        self.recorder = rec
        # 如果记录已被标记完成，清掉残留
        existing = self.db.get_flight(rec.flight_id)
        if existing and existing.get("status") != "RECORDING":
            self.recorder = None
            rec.close()
            self.db.setting_set(ACTIVE_KEY, None)

    # -- 控制 -------------------------------------------------------------
    def start(self, flight_id: str | None = None, started_at: str | None = None,
              manual: bool = True) -> RecordingStatus:
        if self.recorder is not None:
            return self.status()
        ctx = self.ops_context() if self.ops_context else None
        fid = (ctx or {}).get("flight_record_id") or flight_id or str(uuid.uuid4())
        started = started_at or utcnow()
        existing = self.db.get_flight(fid)
        if existing is not None and existing.get("status") != "RECORDING":
            # SimLink 已收尾或重复轮询，不要重复建档
            return self.status()
        self.recorder = FlightRecorder(fid, started, self.paths)
        self.recorder.add_event(0.0, "recording_started", {"manual": manual})
        actual_zfw = (ctx or {}).get("actual_zfw_kg")
        zfw_delta = (ctx or {}).get("zfw_delta_kg")
        if actual_zfw is not None:
            # 推出前 ZFW 校验结果：写进事件，供日志详情核对（字段同时落库）
            self.recorder.add_event(0.0, "zfw_check", {
                "actual_zfw_kg": actual_zfw, "delta_kg": zfw_delta,
            })
        if existing is None:
            record: dict[str, Any] = {
                "id": fid, "mode": "PERSONAL", "status": "RECORDING",
                "callsign": self._callsign(), "aircraft_type": self._aircraft_type(),
                "aircraft_title": self.aircraft_title, "block_off_utc": started,
                "created_at": started,
            }
            if ctx:
                record.update({
                    "mode": "ROSTER" if ctx.get("kind") == "ROSTER" else "FREE",
                    "roster_leg_id": ctx.get("roster_leg_id"),
                    "flight_instance_id": ctx.get("flight_instance_id"),
                    "aircraft_id": ctx.get("aircraft_id"),
                    "callsign": ctx.get("callsign") or record["callsign"],
                    "aircraft_type": ctx.get("aircraft_type") or record["aircraft_type"],
                    "dep_icao": ctx.get("dep_icao"), "arr_icao": ctx.get("arr_icao"),
                    "mission_type": ctx.get("mission_type") or "SCHEDULED",
                    "scheduled_dep_utc": ctx.get("scheduled_dep_utc"),
                    "actual_zfw_kg": actual_zfw, "zfw_delta_kg": zfw_delta,
                })
            self.db.insert_flight(record)
        self._save_persisted()
        return self.status()

    def stop(self, abort: bool = False) -> dict[str, Any] | None:
        if self.recorder is None:
            return None
        rec = self.recorder
        rec.add_event(rec.last_t, "recording_stopped", {"abort": abort})
        rec.close()
        flight = None if abort else self._finalize(rec)
        if flight is None:
            record = self.db.update_flight(rec.flight_id, {"status": "ABORTED"})
            # 中止也要走运营钩子，否则任务/飞机锁会一直挂着无法取消
            if record and self.on_finalized is not None:
                try:
                    self.on_finalized(record)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"运营中止失败: {type(exc).__name__}: {exc}"
        self.recorder = None
        self.db.setting_set(ACTIVE_KEY, None)
        raw = rec._raw
        if raw.exists():
            try:
                raw.unlink()
            except OSError:
                pass
        return flight

    def auto_stop(self) -> dict[str, Any] | None:
        return self.stop(abort=False)

    # -- 采样 -------------------------------------------------------------
    def ingest(self, raw_samples: list[dict[str, Any]], events: list[dict[str, Any]] | None = None,
               recording_id: str | None = None, recording_started_at: str | None = None,
               auto_ingest: bool = True) -> None:
        if self.recorder is None and auto_ingest:
            if recording_id:
                self.start(recording_id, recording_started_at, manual=False)
            elif raw_samples:
                self.start(manual=False)
        if self.recorder is None:
            return
        for ev in events or []:
            payload = ev.get("data") or ev.get("detail") or {}
            if not isinstance(payload, dict):
                payload = {"value": payload}
            self.recorder.add_event(float(ev.get("t", 0)), ev.get("type", "event"), payload)
        for raw in raw_samples:
            self.recorder.ingest(raw)
        if self.recorder.samples:
            settings = self._settings()
            if self.recorder.should_auto_stop(bool(settings.get("auto_stop", True))):
                self.auto_stop()

    # -- 完成 -------------------------------------------------------------
    def _anomalies(self, samples: list[dict[str, Any]]) -> list[str]:
        flags: list[str] = []
        if not samples:
            return ["NO_TRACK"]
        gaps = sum(max(0.0, b["t"] - a["t"] - 5.0) for a, b in zip(samples, samples[1:]))
        if gaps > 60:
            flags.append("DATA_GAP")
        if any(float(s.get("sim_rate") or 1) > 4 for s in samples):
            flags.append("SIM_RATE")
        if sum(1 for s in samples if s.get("paused")) / max(1, len(samples)) > 0.2:
            flags.append("PAUSE")
        # 时间加速下「位移/时间」无法区分加速与瞬移；加速由 SIM_RATE 策略单独处理
        accelerated = any(float(s.get("sim_rate") or 1) > 1.5 for s in samples)
        if not accelerated:
            for a, b in zip(samples, samples[1:]):
                dt = b["t"] - a["t"]
                if dt <= 0:
                    continue
                dist = math.hypot((b["lat"] - a["lat"]) * 60,
                                  (b["lon"] - a["lon"]) * 60 * math.cos(math.radians(a["lat"])))
                if dist / (dt / 3600.0) > 900:
                    flags.append("TELEPORT")
                    break
        return flags

    def _finalize(self, rec: FlightRecorder) -> dict[str, Any] | None:
        points = rec.samples
        if not points:
            return None
        settings = self._settings()
        nav = self._nav()
        result = evaluate(points, nav, rating_thresholds(settings), self._aircraft_type())
        takeoff_idx = result.get("takeoff_index")
        landing_idx = result.get("landing_index")
        if takeoff_idx is None:
            return None
        status = "COMPLETED" if landing_idx is not None else "ABORTED"
        if landing_idx is None:
            status = "ABORTED"
        metrics = result.get("landing") or {}
        dep = result.get("dep_icao")
        arr = result.get("arr_icao")
        if landing_idx is None:
            arr = arr or dep

        cfg = SamplingConfig(
            max_gap_s=float(settings.get("max_gap_s", 45)),
            turn_enter_dps=float(settings.get("turn_threshold_dps", 4.0)),
        )
        event_times = [e["t"] for e in rec.events if e["type"] in ("takeoff", "landing", "data_gap", "pause", "sim_rate")]
        saved, _reasons, segments = select_saved(
            points, cfg, event_times, density=str(settings.get("density", "adaptive")))
        flight_dir = self.paths.tracks / rec.flight_id
        chunks = write_chunks(points, saved, segments, flight_dir, self.paths) if saved else []
        if chunks:
            self.db.add_chunks(rec.flight_id, chunks)
        if rec.events:
            self.db.add_events(rec.flight_id, [
                {"t_offset_ms": int(e["t"] * 1000), "type": e["type"], "payload": e["payload"]}
                for e in rec.events
            ])

        block_off = rec.started_at
        block_on = _iso_add(rec.started_at, result.get("block_on_t") or 0)
        takeoff_utc = _iso_add(rec.started_at, result["takeoff_t"]) if result.get("takeoff_t") is not None else None
        landing_utc = _iso_add(rec.started_at, result["landing_t"]) if result.get("landing_t") is not None else None
        block_minutes = round(((result.get("block_on_t") or 0) - (result.get("block_off_t") or 0)) / 60.0, 1)
        anomalies = self._anomalies(points)
        profile = {
            "profile": "adaptive_v2", "base_hz": 1, "encoding": "BIN_V2",
            "max_gap_s": cfg.max_gap_s, "straight_interval_s": 20, "turn_interval_s": 2,
            "turn_threshold_deg_s": cfg.turn_enter_dps, "turn_exit_deg_s": 1.5,
            "climb_descent_interval_s": 5, "taxi_interval_s": 10,
            "approach_hz": 1, "runway_hz": 10,
            "target_size_kb": 500, "fidelity_m": 30,
            "raw_points": len(points), "saved_points": len(saved), "segments": len(segments),
        }
        update: dict[str, Any] = {
            "status": status,
            "dep_icao": dep, "arr_icao": arr,
            "block_off_utc": block_off, "block_on_utc": block_on,
            "takeoff_utc": takeoff_utc, "landing_utc": landing_utc,
            "block_minutes": block_minutes,
            "distance_nm": result.get("distance_nm"),
            "fuel_start_kg": result.get("fuel_start_kg"),
            "fuel_end_kg": result.get("fuel_end_kg"),
            "fuel_used_kg": (round((result.get("fuel_start_kg") or 0) - (result.get("fuel_end_kg") or 0), 1)
                             if result.get("fuel_start_kg") is not None and result.get("fuel_end_kg") is not None else None),
            "max_g_flight": metrics.get("max_g_flight") or result.get("max_g_flight"),
            "max_g_landing": metrics.get("max_g_landing"),
            "touchdown_g": metrics.get("touchdown_g"),
            "touchdown_vs_fpm": metrics.get("touchdown_vs_fpm"),
            "touchdown_lat": metrics.get("touchdown_lat"),
            "touchdown_lon": metrics.get("touchdown_lon"),
            "runway_ident": metrics.get("runway_ident"),
            "threshold_distance_m": metrics.get("threshold_distance_m"),
            "displaced_threshold_m": metrics.get("displaced_threshold_m"),
            "centerline_offset_m": metrics.get("centerline_offset_m"),
            "bounce_count": metrics.get("bounce_count"),
            "landing_distance_m": metrics.get("landing_distance_m"),
            "landing_rating": metrics.get("landing_rating") or "UNKNOWN",
            "track_profile_json": profile,
            "track_points": len(saved),
            "track_bytes": sum(int(c.get("bytes") or 0) for c in chunks),
            "track_fidelity_m": fidelity_m(points, saved),
            "track_sha256": hashlib.sha256(
                "".join(c["sha256"] for c in chunks).encode()).hexdigest() if chunks else None,
            "data_gap_seconds": result.get("data_gap_seconds"),
            "validation_status": "SUSPECT" if anomalies else "VALID",
            "anomaly_flags_json": anomalies,
            "airac": nav.airac if nav else None,
        }
        flight = self.db.update_flight(rec.flight_id, update)
        if flight and status in ("COMPLETED", "DIVERTED") and dep and arr:
            self.db.add_flown_leg({
                "dep_icao": dep, "arr_icao": arr,
                "flight_date": (block_off or "")[:10] or None,
                "aircraft_type": self._aircraft_type(),
                "duration_min": int(round(block_minutes)),
                "landing_rate_fpm": metrics.get("touchdown_vs_fpm"),
                "source": "AOC", "external_id": rec.flight_id,
            })
        if flight and self.on_finalized is not None:
            try:
                self.on_finalized(flight)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"运营结算失败: {type(exc).__name__}: {exc}"
        return flight

    # -- 状态 -------------------------------------------------------------
    def status(self) -> RecordingStatus:
        rec = self.recorder
        return RecordingStatus(
            active=rec is not None,
            flight_id=rec.flight_id if rec else None,
            started_at=rec.started_at if rec else None,
            samples=len(rec.samples) if rec else 0,
            phase=rec.phase if rec else Phase.PREFLIGHT,
            engine_seconds=self.engine_seconds if rec else 0,
            flight_seconds=self.flight_seconds if rec else 0,
            engine_estimated=bool(self.engine_estimated and rec),
            simlink_connected=self.simlink_connected,
            simlink_version=self.simlink_version,
            sim_connected=self.sim_connected,
            aircraft_title=self.aircraft_title,
            last_error=self.last_error,
        )
