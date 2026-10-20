"""Volanta 已飞记录适配器。

定位：**可选数据补全**，不是权威记录（D-05）。三种来源：
1. 私有 Web API（用户粘贴浏览器会话 token，只在本次请求内使用，不落盘）；
2. 官方 CSV 导出；
3. 手动补录（由上层实现）。

Volanta 无公开 API，字段随版本变化，因此所有解析都是「尽力而为」：
解析不出的字段留空，不因为一个字段失败丢掉整条记录。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

ICAO_RE = re.compile(r"\b([A-Z]{4})\b")
DEFAULT_API = os.environ.get("AOC_VOLANTA_API", "https://api.volanta.app/api/v1/Flights")
# 可选：逐航班详情/轨迹接口模板（含 {id}），留空则只保存列表接口返回的原始数据
DETAIL_URL = os.environ.get("AOC_VOLANTA_FLIGHT_URL", "")

ORIGIN_KEYS = ("originicao", "origin", "from", "departure", "departureicao", "orig", "originairport")
DEST_KEYS = ("destinationicao", "destination", "to", "arrival", "arrivalicao", "dest", "destinationairport")
# offBlocksTime 是 Volanta 接口的推出时刻（航班日期就取自它）
DATE_KEYS = ("offblockstime", "date", "flightdate", "departuretime", "starttime",
             "takeofftime", "tookoffat", "created", "createdat")
# aircraftIcao 才是机型代码；`aircraft` 在接口里是嵌套对象（不能当机型）
TYPE_KEYS = ("aircrafticao", "aircrafttype", "actype", "aircraft", "type", "aircraftname")
DURATION_KEYS = ("duration", "durationminutes", "flighttime", "blocktime", "elapsed")
# 接口里的时长字段是秒
DURATION_SECOND_KEYS = ("realblocktime", "effectiveblocktime", "realflighttime", "effectiveflighttime")
LANDING_KEYS = ("landingrate", "touchdownvs", "landingvs", "landingratefpm", "touchdownrate")
CALLSIGN_KEYS = ("callsign", "flightnumber", "flightno", "flightnum", "flight", "ident")
REGISTRATION_KEYS = ("aircraftregistration", "registration", "aircraftreg", "tailnumber", "reg")
ID_KEYS = ("id", "flightid", "guid", "uuid")
# 注册号形如 B-323H / JA02XJ / F-WWOW：不含空格，且至少有一个数字或连字符；
# 接口里的 aircraftRegistration 有时是涂装名（"Airbus House Livery" / "Easyjet"），按格式过滤掉
REGISTRATION_RE = re.compile(r"(?=.*[\d-])[A-Z0-9][A-Z0-9-]{2,9}")


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (key or "").lower())


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    # 嵌套对象/数组不是标量字段：接口里的 `aircraft` 是对象，`flight` 也可能是对象
    norm = {_norm(k): v for k, v in row.items() if not isinstance(v, (dict, list))}
    for k in keys:
        if k in norm and norm[k] not in (None, ""):
            return norm[k]
    return None


def _icao(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).upper()
    m = ICAO_RE.search(text)
    return m.group(1) if m else None


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / (1000 if float(value) > 1e11 else 1),
                                          tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:19] if "T" in fmt or " " in fmt else text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def _duration_min(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        v = float(text)
        return int(round(v / 60)) if v > 600 else int(round(v))
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _callsign(row: dict[str, Any]) -> str | None:
    """航班号 / 呼号：CSV 与各版本接口的字段名都不一样，尽力而为，解析不出就留空。"""
    value = _pick(row, CALLSIGN_KEYS)
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip().upper()
    return text[:16] or None


def _aircraft_type(row: dict[str, Any]) -> str | None:
    value = _pick(row, TYPE_KEYS)
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip().upper()[:8]
    return text or None


def _registration(row: dict[str, Any]) -> str | None:
    """注册号（如 B-323H）；接口里的 aircraftRegistration 有时是涂装名，按格式过滤掉。"""
    value = _pick(row, REGISTRATION_KEYS)
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    return text if REGISTRATION_RE.fullmatch(text) else None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration(row: dict[str, Any]) -> int | None:
    minutes = _duration_min(_pick(row, DURATION_KEYS))
    if minutes:
        return minutes
    seconds = _float(_pick(row, DURATION_SECOND_KEYS))
    if seconds:
        return int(round(seconds / 60))
    # 有些记录 realBlockTime 是 0：用推出/停稳时刻自己算
    off = _datetime(_pick(row, ("offblockstime",)))
    on = _datetime(_pick(row, ("onblockstime",)))
    if off and on:
        try:
            delta = (on - off).total_seconds()
        except TypeError:  # 一边带时区一边不带
            return None
        if delta > 0:
            return int(round(delta / 60))
    return None


def _leg(row: dict[str, Any]) -> dict | None:
    dep = _icao(_pick(row, ORIGIN_KEYS))
    arr = _icao(_pick(row, DEST_KEYS))
    if not dep or not arr or dep == arr:
        return None
    return {
        "dep_icao": dep,
        "arr_icao": arr,
        "callsign": _callsign(row),
        "registration": _registration(row),
        "flight_date": _iso_date(_pick(row, DATE_KEYS)),
        "aircraft_type": _aircraft_type(row),
        "duration_min": _duration(row),
        "landing_rate_fpm": _float(_pick(row, LANDING_KEYS)),
        "source": "VOLANTA",
        "external_id": (str(_pick(row, ID_KEYS)) if _pick(row, ID_KEYS) else None),
    }


def parse_stored_flight(raw: Any) -> dict | None:
    """把库里存的原始数据重新解析成一条航段（用于补全旧数据里缺失/错误的字段）。"""
    if not isinstance(raw, dict):
        return None
    nested = raw.get("flight") if isinstance(raw.get("flight"), dict) else raw
    return _leg(dict(nested))


TRACK_KEYS = ("track", "trackpoints", "positions", "coordinates", "coords", "points", "path", "trail")
LAT_KEYS = ("lat", "latitude", "laty", "y")
LON_KEYS = ("lon", "lng", "longitude", "lonx", "x")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coords(items: Any) -> list[list[float]] | None:
    """把坐标数组规范成 [[lon, lat], ...]；无法识别返回 None。"""
    if not isinstance(items, (list, tuple)) or len(items) < 2:
        return None
    points: list[list[float]] = []
    known_order = False
    for item in items:
        if isinstance(item, dict):
            lat = lon = None
            for key, value in item.items():
                norm = _norm(key)
                if lat is None and norm in LAT_KEYS:
                    lat = _num(value)
                if lon is None and norm in LON_KEYS:
                    lon = _num(value)
            if lat is None or lon is None:
                return None
            points.append([lon, lat])
            known_order = True
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            first, second = _num(item[0]), _num(item[1])
            if first is None or second is None:
                return None
            points.append([first, second])
        else:
            return None
    if known_order:
        return points
    # 全是 [a, b]：纬度绝对值不会超过 90，用这一点判断哪儿是经度
    first_gt = any(abs(p[0]) > 90 for p in points)
    second_gt = any(abs(p[1]) > 90 for p in points)
    if second_gt and not first_gt:
        return [[p[1], p[0]] for p in points]
    return points


def extract_track(payload: Any, depth: int = 0) -> list[list[float]] | None:
    """从任意嵌套的 payload 里找航班轨迹，返回 [[lon, lat], ...]。"""
    if depth > 4 or payload is None:
        return None
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _norm(key) in TRACK_KEYS:
                coords = _coords(value)
                if coords:
                    return coords
        for value in payload.values():
            if isinstance(value, (dict, list)):
                coords = extract_track(value, depth + 1)
                if coords:
                    return coords
        return None
    if isinstance(payload, list):
        coords = _coords(payload)
        if coords:
            return coords
        for value in payload[:5]:
            coords = extract_track(value, depth + 1)
            if coords:
                return coords
    return None


def parse_api_flights(payload: Any) -> list[dict]:
    """解析航班列表，保留原始条目与轨迹（用于持久化，不做丢弃）。"""
    out: list[dict] = []
    for item in _find_flights(payload):
        row = item.get("flight") if isinstance(item, dict) and isinstance(item.get("flight"), dict) else item
        if not isinstance(row, dict):
            continue
        flat = dict(row)
        for side in ("origin", "destination", "departure", "arrival"):
            nested = row.get(side)
            if isinstance(nested, dict):
                code = nested.get("icaoCode") or nested.get("icao") or nested.get("ident")
                if code:
                    flat.setdefault(f"{side}Icao", code)
        leg = _leg(flat)
        if not leg:
            continue
        leg["track"] = extract_track(item)
        leg["raw"] = item
        out.append(leg)
    return out


def parse_csv(text: str) -> list[dict]:
    text = (text or "").lstrip("\ufeff")
    if not text.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    out: list[dict] = []
    for row in csv.DictReader(io.StringIO(text), dialect=dialect):
        raw = dict(row)
        leg = _leg(raw)
        if leg:
            leg["raw"] = raw
            out.append(leg)
    return out


def _find_flights(obj: Any) -> list[Any]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("flights", "Flights", "items", "data", "results"):
            value = obj.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = _find_flights(value)
                if nested:
                    return nested
    return []


def parse_api_payload(payload: Any) -> list[dict]:
    out: list[dict] = []
    for item in _find_flights(payload):
        row = item.get("flight") if isinstance(item, dict) and isinstance(item.get("flight"), dict) else item
        if not isinstance(row, dict):
            continue
        flat = dict(row)
        # 常见嵌套：origin/destination 对象里带 icaoCode
        for side in ("origin", "destination", "departure", "arrival"):
            nested = row.get(side)
            if isinstance(nested, dict):
                code = nested.get("icaoCode") or nested.get("icao") or nested.get("ident")
                if code:
                    flat.setdefault(f"{side}Icao", code)
        leg = _leg(flat)
        if leg:
            out.append(leg)
    return out


class VolantaClient:
    def __init__(self, token: str | None = None, api_url: str = DEFAULT_API, timeout: float = 15.0):
        self.token = token
        self.api_url = api_url
        self.timeout = timeout

    def _get_json(self, url: str) -> tuple[Any, str | None]:
        """GET 一个 JSON 接口；返回 (payload, error)。"""
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Cookie": f"token={self.token}",
            "User-Agent": "AOC/0.1 (personal local sync)",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace")), None
        except urllib.error.HTTPError as exc:
            return None, f"Volanta API HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"

    def fetch_raw(self) -> dict:
        """拉取原始航班列表，保留完整 payload（含轨迹字段），不做裁剪。"""
        if not self.token:
            return {"ok": False, "payload": None, "flights": [],
                    "diagnostic": "未提供 Volanta 会话 token",
                    "warnings": ["可在浏览器登录 Volanta 后复制会话 token，或改用 CSV 导入"]}
        payload, error = self._get_json(self.api_url)
        if error:
            return {"ok": False, "payload": None, "flights": [], "diagnostic": error,
                    "warnings": ["非官方接口可能已失效；可用 CSV 导入（CSV 不含轨迹）"]}
        flights = parse_api_flights(payload)
        return {
            "ok": True,
            "payload": payload,
            "flights": flights,
            "diagnostic": f"已解析 {len(flights)} 条航班",
            "warnings": [] if flights else ["接口返回成功，但没有解析出起降对（字段可能已变更）"],
        }

    def fetch_detail(self, external_id: str) -> tuple[Any, str | None]:
        """可选的逐航班详情/轨迹接口（用 AOC_VOLANTA_FLIGHT_URL 配置模板，含 {id}）。"""
        if not DETAIL_URL or not external_id:
            return None, None
        return self._get_json(DETAIL_URL.replace("{id}", str(external_id)))

    def fetch(self) -> dict:
        """兼容旧接口：只返回解析好的航段。"""
        resp = self.fetch_raw()
        legs = [{k: v for k, v in f.items() if k not in ("track", "raw")} for f in resp.get("flights", [])]
        return {
            "ok": resp["ok"],
            "legs": legs,
            "diagnostic": resp.get("diagnostic", ""),
            "warnings": resp.get("warnings", []),
        }
