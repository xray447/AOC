"""机型基础参数（个人模式航程/跑道估算用）。

完整公司机型模板在 M2 服务端；这里只保留推荐与航路需要的少量字段。
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT = [
    # 通航
    {"icao": "C172", "name": "Cessna 172", "cruise_speed_kt": 115, "cruise_fl": 90,
     "min_runway_m": 700, "range_nm": 640, "category": "ga"},
    {"icao": "B350", "name": "Beechcraft King Air 350", "cruise_speed_kt": 270, "cruise_fl": 280,
     "min_runway_m": 1000, "range_nm": 1500, "category": "ga"},
    {"icao": "C25C", "name": "Cessna Citation CJ4", "cruise_speed_kt": 400, "cruise_fl": 410,
     "min_runway_m": 1100, "range_nm": 1900, "category": "ga"},
    # 支线
    {"icao": "AT76", "name": "ATR 72-600", "cruise_speed_kt": 275, "cruise_fl": 240,
     "min_runway_m": 1300, "range_nm": 900, "category": "regional"},
    {"icao": "CRJ9", "name": "Bombardier CRJ-900", "cruise_speed_kt": 440, "cruise_fl": 370,
     "min_runway_m": 1700, "range_nm": 1500, "category": "regional"},
    {"icao": "E190", "name": "Embraer E190", "cruise_speed_kt": 440, "cruise_fl": 370,
     "min_runway_m": 1500, "range_nm": 2400, "category": "regional"},
    # 窄体
    {"icao": "A320", "name": "Airbus A320", "cruise_speed_kt": 440, "cruise_fl": 350,
     "min_runway_m": 1600, "range_nm": 3300, "category": "narrow"},
    {"icao": "A321", "name": "Airbus A321", "cruise_speed_kt": 440, "cruise_fl": 350,
     "min_runway_m": 1700, "range_nm": 3200, "category": "narrow"},
    {"icao": "B738", "name": "Boeing 737-800", "cruise_speed_kt": 445, "cruise_fl": 350,
     "min_runway_m": 1600, "range_nm": 2900, "category": "narrow"},
    # 宽体
    {"icao": "A333", "name": "Airbus A330-300", "cruise_speed_kt": 470, "cruise_fl": 370,
     "min_runway_m": 2200, "range_nm": 6300, "category": "wide"},
    {"icao": "A343", "name": "Airbus A340-300", "cruise_speed_kt": 470, "cruise_fl": 370,
     "min_runway_m": 2400, "range_nm": 7100, "category": "wide"},
    {"icao": "B77W", "name": "Boeing 777-300ER", "cruise_speed_kt": 480, "cruise_fl": 370,
     "min_runway_m": 2400, "range_nm": 7300, "category": "wide"},
]


class AircraftCatalog:
    def __init__(self, path: str | Path | None = None):
        self.items = [dict(x) for x in DEFAULT]
        if path and Path(path).exists():
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.items = data
            except (OSError, json.JSONDecodeError):
                pass

    def list(self) -> list[dict]:
        return list(self.items)

    def get(self, icao: str | None) -> dict:
        key = (icao or "A320").upper()
        for item in self.items:
            if item.get("icao", "").upper() == key:
                return item
        # 未知机型回退到窄体基准 A320（而不是目录第一条，避免落到通航机型）
        for item in self.items:
            if item.get("icao", "").upper() == "A320":
                return item
        return self.items[0]
