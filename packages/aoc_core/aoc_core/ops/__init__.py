"""M2 单机运营模式领域层（机队/班表/结算/账本/规则版本）。"""
from .service import OpsError, OpsService

__all__ = ["OpsError", "OpsService"]
