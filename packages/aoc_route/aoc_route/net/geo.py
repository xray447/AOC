"""大圆几何 + 经纬度网格索引（只依赖标准库）。"""

import math

EARTH_RADIUS_NM = 3440.065          # 地球平均半径（海里）
NM_PER_DEG_LAT = 60.0               # 1 度纬度 ≈ 60 海里


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点间大圆距离（海里）。"""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam * 0.5) ** 2
    return 2.0 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """初始方位角，单位度，0~360。"""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class GridIndex:
    """经纬度分桶的最近邻索引。

    数据规模是 4.7 万个航路点，分桶后单次半径查询只扫几十个桶，足够快，
    也避免引入 scipy / networkx 这类额外依赖。
    """

    def __init__(self, points, cell_deg: float = 1.0):
        """points: 可迭代的 (key, lat, lon)。"""
        self.cell = float(cell_deg)
        self._cells = {}
        self._pts = []
        for key, lat, lon in points:
            idx = len(self._pts)
            self._pts.append((key, lat, lon))
            self._cells.setdefault(self._cell_of(lat, lon), []).append(idx)

    def _cell_of(self, lat: float, lon: float):
        return (int(math.floor(lat / self.cell)), int(math.floor(lon / self.cell)))

    def query_radius(self, lat: float, lon: float, radius_nm: float):
        """返回半径内所有点：[(key, dist_nm), ...]（未排序）。"""
        dlat_cells = int(math.ceil(radius_nm / (NM_PER_DEG_LAT * self.cell))) + 1
        coslat = max(0.05, math.cos(math.radians(lat)))
        dlon_cells = int(math.ceil(radius_nm / (NM_PER_DEG_LAT * self.cell * coslat))) + 1
        clat, clon = self._cell_of(lat, lon)
        out = []
        for i in range(clat - dlat_cells, clat + dlat_cells + 1):
            for j in range(clon - dlon_cells, clon + dlon_cells + 1):
                bucket = self._cells.get((i, j))
                if not bucket:
                    continue
                for idx in bucket:
                    key, plat, plon = self._pts[idx]
                    d = haversine_nm(lat, lon, plat, plon)
                    if d <= radius_nm:
                        out.append((key, d))
        return out
