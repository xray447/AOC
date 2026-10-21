"""AOC 联机模式服务端（M3）。

FastAPI + SQLAlchemy，开发/测试默认 SQLite，部署使用 PostgreSQL 16。
只提供 JSON API；网页管理端是独立 SPA（`apps/admin-web`）。
"""

__version__ = "0.1.0"
API_VERSION = "v1"
