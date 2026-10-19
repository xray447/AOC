"""自适应采样器：模式判定 + 滞回 + 强制保存 + 最大间隔（V-03）。"""
from __future__ import annotations

from dataclasses import dataclass, field

from model import Mode, Sample


@dataclass
class SamplingConfig:
    turn_enter_dps: float = 4.0
    turn_exit_dps: float = 1.5
    turn_exit_hold_s: float = 4.0
    climb_vs_fpm: float = 1000.0
    taxi_gs_kt: float = 40.0
    approach_agl_ft: float = 3000.0
    max_gap_s: float = 45.0
    force_hdg_deg: float = 3.0
    force_alt_ft: float = 300.0
    force_dist_nm: float = 2.0
    force_vs_fpm: float = 800.0
    event_pad_s: float = 2.0
    interval_s: dict = field(default_factory=lambda: {
        Mode.STRAIGHT: 20.0, Mode.TURN: 2.0, Mode.CLIMB_DESCENT: 5.0,
        Mode.APPROACH: 1.0, Mode.TAXI: 10.0,
    })


def ang_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def dist_nm(a: Sample, b: Sample) -> float:
    import math
    mlat = math.radians((a.lat + b.lat) / 2.0)
    dx = math.radians(b.lon - a.lon) * math.cos(mlat) * 6371000.0
    dy = math.radians(b.lat - a.lat) * 6371000.0
    return math.hypot(dx, dy) / 1852.0


class AdaptiveSampler:
    def __init__(self, cfg: SamplingConfig | None = None):
        self.cfg = cfg or SamplingConfig()
        self.mode = Mode.TAXI
        self._turn_below_since = None

    def _detect_mode(self, s: Sample, turn_rate: float) -> str:
        cfg = self.cfg
        # 终端区：低高度且在下高（爬升穿越 3000ft 不算进近）
        if not s.on_ground and s.agl_ft < cfg.approach_agl_ft and s.vs_fpm < 0:
            return Mode.APPROACH
        if turn_rate > cfg.turn_enter_dps:
            self._turn_below_since = None
            return Mode.TURN
        if self.mode == Mode.TURN:
            if abs(turn_rate) < cfg.turn_exit_dps:
                if self._turn_below_since is None:
                    self._turn_below_since = s.t
                    return Mode.TURN
                if s.t - self._turn_below_since < cfg.turn_exit_hold_s:
                    return Mode.TURN
            else:
                self._turn_below_since = None
                return Mode.TURN
            self._turn_below_since = None
        if s.on_ground:
            return Mode.TAXI if s.gs_kt < cfg.taxi_gs_kt else Mode.STRAIGHT
        if abs(s.vs_fpm) > cfg.climb_vs_fpm:
            return Mode.CLIMB_DESCENT
        return Mode.STRAIGHT

    def run(self, samples: list[Sample], event_times: list[float] | None = None):
        """返回 (saved, reasons, segments)。saved 是 [(idx, mode)]，按时间升序。"""
        cfg = self.cfg
        event_window = set()
        for et in event_times or []:
            for d in range(-int(cfg.event_pad_s), int(cfg.event_pad_s) + 1):
                event_window.add(round(et + d))

        saved: list[tuple[int, str]] = []
        reasons: dict[int, list[str]] = {}
        last_saved = None
        prev = None

        def mark(i: int, why: str, mode: str):
            reasons.setdefault(i, []).append(why)
            if not saved or saved[-1][0] != i:
                saved.append((i, mode))

        for i, s in enumerate(samples):
            if i == 0:
                mark(0, "first", self.mode)
                last_saved = s
                prev = s
                continue

            dt = max(1e-6, s.t - prev.t)
            rate = abs(ang_diff(s.hdg_deg, prev.hdg_deg)) / dt
            new_mode = self._detect_mode(s, rate)

            if new_mode != self.mode:
                mark(i, f"mode:{self.mode}->{new_mode}", new_mode)
                self.mode = new_mode
                last_saved = s
                prev = s
                continue

            if i in event_window:
                mark(i, "event", new_mode)
                last_saved = s
                prev = s
                continue

            force = None
            if last_saved is not None:
                if abs(ang_diff(s.hdg_deg, last_saved.hdg_deg)) >= cfg.force_hdg_deg:
                    force = "hdg"
                elif abs(s.alt_ft - last_saved.alt_ft) >= cfg.force_alt_ft:
                    force = "alt"
                elif dist_nm(last_saved, s) >= cfg.force_dist_nm:
                    force = "dist"
                elif abs(s.vs_fpm - last_saved.vs_fpm) >= cfg.force_vs_fpm:
                    force = "vs"
                elif s.t - last_saved.t >= cfg.max_gap_s:
                    force = "max_gap"
                elif s.t - last_saved.t >= cfg.interval_s.get(new_mode, 20.0):
                    force = f"interval:{new_mode}"

            if force:
                mark(i, force, new_mode)
                last_saved = s
            prev = s

        if samples and saved[-1][0] != len(samples) - 1:
            mark(len(samples) - 1, "last", self.mode)

        return saved, reasons, self._segment(samples, saved)

    @staticmethod
    def _segment(samples: list[Sample], saved: list[tuple[int, str]]):
        segments, cur = [], None
        for idx, mode in saved:
            if cur is None or cur["mode"] != mode:
                cur = {"mode": mode, "start_idx": idx, "end_idx": idx,
                       "start_t": samples[idx].t, "end_t": samples[idx].t, "indices": [idx]}
                segments.append(cur)
            else:
                cur["end_idx"] = idx
                cur["end_t"] = samples[idx].t
                cur["indices"].append(idx)
        return segments

    @staticmethod
    def max_gap(samples: list[Sample], saved: list[tuple[int, str]]) -> float:
        return max((samples[saved[i + 1][0]].t - samples[saved[i][0]].t
                    for i in range(len(saved) - 1)), default=0.0)
