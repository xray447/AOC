"""AOC 客户端/服务端共享数据契约（pydantic → OpenAPI → TS）。"""

from .schemas import *  # noqa: F401,F403
from .schemas import SCHEMA_VERSION  # noqa: F401

__all__ = ["SCHEMA_VERSION"]
