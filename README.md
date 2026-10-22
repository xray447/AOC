# AOC · 模拟飞行运行中心

个人模式（M1）：推荐机场 → 生成航路 → 记录飞行 → 回放与落地评估。
单机运营模式（M2）：机队 → 航线/班期 → 抽班/自由飞 → 配载 → 结算 → 账本，外加应用内「运营规则」与复核队列；**无服务端、无账号、可断网**。
联机模式（M3）：`aoc-server`（FastAPI + PostgreSQL/SQLite）+ 账号/公司/角色/邀请码 + 并发锁 + 离线补传 + 独立网页管理端（`apps/admin-web`）；桌面客户端新增「联机模式」入口。

## 快速开始

### 联机模式（M3，推荐先看）

```powershell
# 1) 起服务端（首次建公司/管理员/机场/机型；--demo 追加演示机队与 7 天航班）
python apps/server/main.py --port 8080 --demo
# 默认管理员 admin / aoc-admin-2026（用 AOC_BOOTSTRAP_PASSWORD 覆盖）

# 2) 浏览器打开管理端
start http://127.0.0.1:8080/admin

# 3) 客户端
cd apps/client; npm install; npm run build; cd ../..
python -X utf8 apps/aoc-core/main.py --port 0 --static-dir apps/client/dist --open
# 侧栏「运营模式 → 联机模式」填 http://127.0.0.1:8080 登录

# 4) 管理端建飞行员账号/邀请码 → 客户端抽班 → 同步
```

Docker Compose：

```bash
cd deploy
cp .env.example .env   # 修改 POSTGRES_PASSWORD / AOC_SECRET / AOC_BOOTSTRAP_PASSWORD
docker compose up -d --build
# http://<host>:8080/admin
```

管理端热更新：`cd apps/admin-web; npm install; npm run dev` → `http://127.0.0.1:5174/admin`（Vite 代理 `/api` 到 8080）。

### 单机（M1 + M2）

Tauri 安装包（推荐）：

1. 运行 `out/AOC-0.1.0-x64-setup.exe`（NSIS）或 `out/AOC-0.1.0-x64.msi`（MSI）。
2. 从开始菜单启动 AOC；应用会拉起 aoc-core 与 SimLink。
3. 首次向导选择 Little Navmap / Navigraph SQLite（默认会尝试 `%APPDATA%\ABarthel\little_navmap_db\little_navmap_navigraph.sqlite`）；没有模拟器时启动 demo：
   `apps\simlink\aoc-simlink.exe --demo --home "%LOCALAPPDATA%\AOC"`。
4. 运营模式：侧栏「运营概览」→「生成演示数据」（5 架飞机、12 条航线、未来 7 天航班实例），然后「抽班 → 确认 → 开始本段 → 配载与执行 → 落地自动结算」。

需要 Python 3.10+ 在 PATH 中（安装包暂不内置解释器）。

便携包：

1. 解压 `out/AOC-portable-0.1.0-win64.zip`。
2. 双击 `start.bat`。
3. 首次向导同上。

开发：

```powershell
cd apps/client; npm install; npm run build; cd ../..

# SimLink（.NET 8；不带 --demo 即真实 SimConnect）
dotnet build apps/simlink -c Debug
apps\simlink\bin\Debug\net8.0\aoc-simlink.exe --demo --home "$env:LOCALAPPDATA\AOC"

# 本地 API + 前端
python -X utf8 apps/aoc-core/main.py --port 0 --home "$env:LOCALAPPDATA\AOC" --static-dir apps/client/dist --open
```

或一键开发：`powershell -File tools/dev.ps1`（构建前端 → demo SimLink → 起 aoc-core 并开浏览器）。

一键完整编译：`powershell -ExecutionPolicy Bypass -File tools/build.ps1`（或双击 `tools\build.cmd`）——Python 依赖 → 客户端 → 管理端 → SimLink publish → Tauri NSIS/MSI → 便携 ZIP → ruff/pytest，产物落在 `out/`；可加 `-SkipTauri`、`-SkipTests`、`-SkipDocker`、`-Clean` 等裁剪，日志写到 `out/build-<时间戳>.log`。

## 测试

```powershell
python -m pytest                        # 98 项（M1 55 + M2 24 + M3 19）
python -m ruff check packages apps tests tools --select F,E9
python -X utf8 tools/smoke_m1.py        # SimLink demo → aoc-core 自动记录
python -X utf8 tools/smoke_m2.py        # 抽班 → 开始航段 → SimLink demo → 自动结算 → 账本对账
python -X utf8 tools/smoke_m3.py        # 服务端 HTTP：建号 → 抽班 → 结算 → 复核 → 同步 → 管理端
python -X utf8 tools/admin_ui_smoke.py  # 管理端登录 + 10 页（先 playwright install chromium）
python -X utf8 tools/ui_smoke.py        # Playwright 页面/航路/回放/运营页面冒烟
python -X utf8 tools/make_portable.py --build   # 重新生成便携 ZIP
python -X utf8 tools/smoke_portable.py  # 便携包端到端
```

管理端构建：`cd apps/admin-web; npm install; npm run build`（产物 `apps/admin-web/dist`，服务端默认从这里托管 `/admin`）。

## 目录

- `packages/aoc_protocol`：Pydantic 数据契约
- `packages/aoc_navdata`：navdata 读取、跑道匹配、高空覆盖索引
- `packages/aoc_route`：航路引擎 —— 日本 AIP（jp-routes 自动同步）→ 覆盖检查 → 本地建图，SimBrief / `.pln`
- `packages/aoc_core`：SQLite、推荐、记录、落地、自适应轨迹、Volanta、统计；`aoc_core/ops/` 为 M2 运营领域层（机队/班期/抽班/配载/结算/账本/规则版本/审计）
- `packages/aoc_integrations`：Volanta（非官方）适配器
- `apps/aoc-core`：FastAPI sidecar（token + 127.0.0.1；`/local/*` 个人模式 + `/local/ops/*` 运营模式）
- `apps/client`：React SPA；`src-tauri` 为 Tauri 2 外壳源码；`src/online.ts` 为 M3 联机通道
- `apps/simlink`：.NET 8 SimConnect / demo / replay
- `apps/server`：M3 服务端（FastAPI + SQLAlchemy + Alembic 基线；`/api/v1` 玩家、`/api/v1/admin` 管理；Docker Compose 见 `deploy/`）
- `apps/admin-web`：M3 独立网页管理端（React 19 + TypeScript + Vite + Ant Design，`base=/admin/`）
- `deploy/`：Dockerfile、docker-compose、环境变量样例
- `tools/`：构建、便携包与冒烟脚本（`dev.ps1`、`make_portable.py`、`smoke_m1.py`、`smoke_m2.py`、`smoke_m3.py`、`ui_smoke.py`）
- `data/`：机型模板与 AIP fixture（`aip_routes_sample.csv`）
- `Pre-train/`：航路图算法（`src/network.py` 用 navdata 建图）；运行时只随包分发 `src`，不带宽 59MB 的 `network.pkl` 与模型权重
- `docs/`：需求、架构、路线图与交付说明（`09-M1`、`10-M2`、`11-M3`）

## 状态

M1 验收项 A-01~A-04、A-21~A-26、A-30 已有自动化/端到端证据；Tauri 2 + MSVC 已编译，NSIS 与 MSI 安装包、便携 ZIP 均已生成。
M2 验收项 A-05~A-08、A-14~A-19、A-27~A-29 已有自动化/端到端证据；形态为单应用 + 本机档案，单实例锁阻止重复占用。
M3 验收项 A-09~A-13、A-20 已有自动化/端到端证据：并发抽班、离线补传、配置版本冲突/回滚、CSRF/角色、飞行员覆盖、复核写账本、审计与 SPA 加载；`pytest` 98 项、`ruff` 通过、`tools/smoke_m3.py` 全链路通过、`tools/admin_ui_smoke.py` 管理端 10 页无 JS 异常。已知限制（客户端 SimLink → 服务端 outbox 直连、M2 数据导入、CPDLC 等）见 `docs/09-M1交付说明.md` §5、`docs/10-M2交付说明.md` §5 与 `docs/11-M3交付说明.md` §7。
