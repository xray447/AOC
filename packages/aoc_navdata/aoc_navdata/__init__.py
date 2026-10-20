"""导航数据（Little Navmap / Navigraph SQLite）。

对外只暴露只读查询；navdata 缺失时由上层降级到 SimBrief，不在这里伪造数据。
"""

from .navdata import NavData, NavDataError, haversine_nm, intermediate  # noqa: F401

__all__ = ["NavData", "NavDataError", "haversine_nm", "intermediate"]
