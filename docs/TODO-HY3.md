# TODO-HY3 · 全项目静态审查台账

> **来源**：2026-11-07 全项目只读静态审查（HY3）。审查覆盖 `apps/server`、`apps/aoc-core`、`packages/*`（含 `aoc_core/ops`）、`apps/client`、`apps/admin-web`（含 `src-tauri`）、`apps/simlink`、`deploy/`、`.github/workflows/`、`tools/`、`tests/`、`docs/`。
> **边界**：除本文件外未改动任何文件；未运行 `pytest` / `tsc --noEmit` / `dotnet build` / 冒烟脚本（避免生成缓存与构建产物）。关键结论已回读源码抽验，其余为静态通读结论。
> **与 `docs/TODO.md` 的关系**：独立台账，沿用其复选框与编号风格，但**不改动**原 TODO 的 `§` / `T-xx` / `M-xx` 编号与状态；本文件用 `HY3-P0-xx` / `HY3-P1-xx` / `HY3-P2-xx` 独立编号。
> **标签**：`[确认]` 已逐行回读源码；`[静态]` 静态通读得出、未做运行时复现；`[风险]` 依赖部署方式/输入条件才触发。
> **优先级**：P0 建议先修 · P1 排期 · P2 一致性/低优先。
> **基线**：工作区干净、IDE 诊断 0 报错；最近提交 `f11436d`（2026-11-06「移除main推送时候的CI」）。

---

## 一、结论速览

| 领域 | 系统性结论 |
|---|---|
| 本地安全 | 鉴权基础件写得对，但被公开端点与宽松 CORS 自己架空 |
| 服务端 M3 | 认证/租户隔离扎实；**并发安全只在 SQLite 上成立**，PG 部署下有丢更新与 TOCTOU |
| 联机链路 | 服务端 outbox/幂等契约完整，**客户端未接完**，同步与刷新令牌不可靠 |
| 本地核心 M1/M2 | 规则快照/审计设计好；结算与真实飞行结果脱钩，SQLite 事务边界不足 |
| 航路 / navdata / SimLink | 建图与协议主体正确；高度约束、方向、轴序、缓存指纹、时钟存在确定性缺陷 |
| 文档 / CI / 测试 | 代码状态超前于文档，测试数量、CI 触发、版本要求、功能状态多处互相矛盾 |

**总体判断**：完成度高，无「推倒重来」级别的问题；优先堵安全边界与并发，再补联机链路与结算正确性，最后做文档/构建对齐。

---

## 二、P0 · 建议先修（8 条）

- [ ] **HY3-P0-01 [确认] 本地 token 可被任意本机调用者读取**
  - 证据：`apps/aoc-core/main.py:69` 把 `/local/runtime` 放进 `PUBLIC_PATHS`；`:249-251` 直接回 `runtime.json`；`:876-886` 写入的 `runtime.json` 含 `token` 与 SimLink token；`:220-237` `/local/bootstrap` 同样公开返回 token；`:169-185` 中间件不校验 `Host`/`Origin`、`OPTIONS` 直接放行、`:179` 用 `!=` 比较 token；`:163-166` CORS 放行本地 dev 源。
  - 影响：本机任意进程/页面（含 DNS rebinding）可拿到全权限 token，`X-AOC-Token` 体系形同虚设。
  - 动作：`/local/runtime` 移出公开路径或只返回非敏感字段；bootstrap token 改由 Tauri 注入而非 HTTP 下发；中间件校验 Host/Origin；`hmac.compare_digest`。

- [ ] **HY3-P0-02 [确认] SimLink 本地鉴权可用大小写绕过**
  - 证据：`apps/simlink/Program.cs:61-64` 用大小写敏感的 `StartsWith("/status"|"/samples"|"/events"|"/command"|"/latest")` 判定受保护路径，而 ASP.NET Core 路由匹配大小写不敏感；`:73-84` 映射了这些端点。
  - 影响：`GET /STATUS`、`GET /Latest`、`POST /Command` 可绕过 `X-SimLink-Token`，本机任意进程可读采样/事件并发控制命令。
  - 动作：改用 `StartsWith(..., StringComparison.OrdinalIgnoreCase)` 或基于 `Endpoint`/路径集合的统一鉴权，并补大小写回归测试。

- [ ] **HY3-P0-03 [确认] M3 服务端三个可直接利用的口子**
  - 证据：`apps/server/aoc_server/security.py:150-154` 限流 IP 直接信任 `X-Forwarded-For`，`routers/auth.py:74-79`、`routers/admin_auth.py:35-44` 用它拼限流键（`security.py:101-127` 还是进程内字典）；`services/bootstrap.py:17,42,51-53,66` 硬编码 `aoc-admin-2026`、明文进日志与 `app.state.bootstrap_info`、无首次改密；`main.py:82-90` 的 `allow_origin_regex` 无法关闭，`allow_credentials=True`，任意 `http://localhost:<port>` 都放行。
  - 影响：爆破可无限重试；读过源码/日志即可登录 ADMIN；本机恶意页面可用管理员 Cookie 读审计/用户等 GET 接口（GET 不校验 CSRF，`security.py:195-198`）。
  - 动作：可信代理白名单解析客户端 IP、限流外置；去掉默认口令或强制首次改密并禁止日志明文；localhost 正则改为可配置且默认关闭；容器部署置 `AOC_COOKIE_SECURE=1`。

- [ ] **HY3-P0-04 [确认] PostgreSQL 下的丢失更新与并发抽班竞态**
  - 证据：`apps/server/aoc_server/db.py:104-106` SQLite 用 `BEGIN IMMEDIATE` 全事务串行化；但 `deploy/docker-compose.yml` 实际用 PG。`services/ops.py:780-786,814-849`、`routers/admin_core.py:131-134` 对 `company.balance` 读-改-写无 `with_for_update()`；`ops.py:422-489` 抽班对 `FlightInstance`/`RosterLeg` 无锁（只有 `:374-375` 对 Aircraft 加 `SKIP LOCKED`）；`routers/auth.py:125-141` 邀请码 `used_count` 是 TOCTOU。
  - 影响：并发结算/预付款/复核丢更新且 `balance_after` 失真；同一航班被两人抽走；`max_uses=1` 的邀请码（可含 ADMIN 角色）被超用。`tests/test_server.py:22,213,352` 全部跑 SQLite，这些竞态从未被验证。
  - 动作：给 `Company`/`FlightInstance`/`InviteCode` 加行锁或 `UPDATE ... WHERE` 条件写 + 唯一约束；补 PostgreSQL 容器并发测试（20 并发抽班）。

- [ ] **HY3-P0-05 [确认] 联机刷新令牌并发竞争必然失败**
  - 证据：`apps/client/src/pages/Online.tsx:76-79` `Promise.all` 并发 `onlineFlights` + `onlineCurrentRoster`；`apps/client/src/online.ts:138-151` 各自在 401 时调 `/auth/refresh`；`apps/server/aoc_server/routers/auth.py:102-104` 刷新即 `row.revoked = True` 并轮换 refresh token。
  - 影响：第二个请求必得 `REFRESH_INVALID`，整个 `Promise.all` 失败；无 single-flight、无重试。
  - 动作：refresh 做 single-flight（共享 in-flight Promise）并串行重放原请求；服务端可考虑短时宽限旧 refresh token。

- [ ] **HY3-P0-06 [确认/静态] 离线补传未接通、增量同步不可靠**
  - 证据：服务端 `apps/server/aoc_server/routers/sync.py:45-94` 有完整 `/api/v1/sync/batch`，但 `apps/client/src` 与 `apps/admin-web/src` 全库无调用；`apps/client/src/online.ts:175-181` 声明 `has_more` 却不读取、固定 `limit=100` 只拉一页；`pages/Online.tsx:82-85,136-139` 无条件覆盖 cursor 且 `slice(-20)` 丢弃最多 80 条事件；`online.ts:61-63` `saveOnline(null)` 不清 `CURSOR_KEY`，`pages/Online.tsx:161-170` 退出亦不清。
  - 影响：断网重连不补传；历史事件被跳过或重复；换服务器/公司后沿用旧 cursor。
  - 动作：实现本地持久化 outbox（重试/退避/去重键），按 `has_more` 循环拉全，退出与登录时重置 cursor，cursor 更新加请求序号防旧响应覆盖。

- [ ] **HY3-P0-07 [确认/静态] M2 结算与真实飞行结果脱钩**
  - 证据：`packages/aoc_core/aoc_core/ops/economy.py:443-469` 收入/成本只取 `load_sheet` 的 `pax_*`/`cargo_kg`；`ops/service.py:2984-2990` 原样传入；`flights.py:606` 只产生 `COMPLETED`/`ABORTED`，全库无 `DIVERTED` 生成点，导致 `diversion_revenue_factor` / `cancel_cost_factor` / `PENALTY_DIVERSION` 是死配置；`economy.py:482-492` `delta = abs(...)`，且 `>180min → 0.97` 比 `60–180min → 0.95` 更划算；`ops/service.py:2989` 用起飞时刻对比计划推出时刻。
  - 影响：空机、错机场、备降都能拿全额收入；早到 4h 与晚到 4h 同罚；「越离谱越划算」。
  - 动作：结算引入实际 ZFW/载重、到达机场与备降判定；准点系数改有符号偏差并让惩罚单调；统一时刻口径。

- [ ] **HY3-P0-08 [确认] 本地 SQLite 余额读-改-写不在事务内**
  - 证据：`packages/aoc_core/aoc_core/db.py:216-225` 用 pysqlite 默认隐式 BEGIN，`:238-255` `session()` 只在最外层 `commit()`，不发 `BEGIN`；`ops/service.py:3310-3324` 先 `SELECT balance` 再 `INSERT ledger_entry` / `UPDATE ops_profile`；`:222` 只设 `busy_timeout=5000` 且无重试。
  - 影响：两线程交错时后者用旧余额覆盖前者，账本 `balance_after` 失真；WAL 升级写还可能 `SQLITE_BUSY_SNAPSHOT`。
  - 动作：仿 `apps/server/aoc_server/db.py` 加 `BEGIN IMMEDIATE`，或对余额更新用单条 `UPDATE ... SET balance = balance + ?`；金额全面改整数分。

---

## 三、P1 · 分领域排期

### 3.1 服务端（`apps/server` / `deploy`）

- [ ] **HY3-P1-01 [静态] 两个端点漏鉴权**：`routers/player.py:91-99`、`routers/admin_network.py:57-64` 函数签名无 `Depends(current_user)` / `Depends(require_admin_or_dispatcher)`，未登录可调。
- [ ] **HY3-P1-02 [静态] Alembic 基线不是冻结 schema**：`alembic/versions/0001_baseline.py:20-25` 用 `create_all` / `drop_all`（downgrade 删全表）；`main.py:63` 每次启动 `create_all()`；`deploy/Dockerfile:24` 启动不跑 alembic，`docs/11-M3交付说明.md:13,203,215` 却称生产走 `alembic upgrade head`。改成冻结 DDL + 逐表可回滚迁移，并移除启动期 `create_all`。
- [ ] **HY3-P1-03 [静态] 幂等键缺陷群**：`services/store.py:146-166` 查→业务→插入无锁（并发同键 409 而非回放），只比 `path` 不比请求体，`models.py:488` 长度 120 无校验会 500，`IdempotencyKey` 无 TTL 无限增长。改 UPSERT + 请求体指纹 + 过期清理。
- [ ] **HY3-P1-04 [静态] `/sync/batch` 缺陷群**：`routers/sync.py:53-55,56-61` 取字段/查幂等在 `try` 外（整批 500）；`:52` 静默截断 200 条；`:73-75` 回显异常原文且一律 `retryable: True`；补传不携带 `economy_version`/`policy_version`（`ops.py:522-533` 在补传时刻抓当前配置，与客户端本地结算不一致）；`ops.py:924-955` 的 ABANDON 非幂等；`ops.py:649-672` 轨迹不校验航班状态；`models.py:455-464` 快照无唯一约束会 `MultipleResultsFound`。
- [ ] **HY3-P1-05 [静态] 审计可信度**：`main.py:94` 生成的可信 `request.state.request_id` 无人使用，实际取客户端可控的 body/header（`ops.py:501`、`admin_config.py:65,101,133,155`）；`admin_auth.py:38-40` 未知用户名的失败登录记 `company_id=None`，`admin_core.py:315` 按公司过滤审计 → 爆破不可见；`store.py:117-133` 回滚产生同版本两条矛盾历史且无 `CONFIG_ROLLBACK` 审计。
- [ ] **HY3-P1-06 [静态] 输入校验**：`admin_config.py:59,98,110`、`admin_core.py:283-285`、`admin_network.py:84-85,177,303-308,417,419` 等用裸 `dict` + `int()`/`float()`/`datetime.fromisoformat()`，畸形输入落通用 500；`admin_network.py:206-214` 校验在 `setattr` 之后。改 Pydantic 模型。
- [ ] **HY3-P1-07 [静态] 部署**：`deploy/docker-compose.yml:26` 数据库 URL 未编码（密码含 `@ : / %` 起不来，`alembic/env.py:28-29` 还会插值报错）；`docker-compose.yml:39` 绑所有网卡且 `AOC_COOKIE_SECURE=0`；`Dockerfile:9-24` 以 root 运行、api 无 healthcheck（`/healthz` 已存在）；`routers/admin_core.py:321-329` 审计 CSV 有公式注入。
- [ ] **HY3-P1-08 [风险] 访问令牌不可撤销**：`routers/auth.py:107-115` logout 只撤 refresh；`security.py:77-97` 令牌无 `jti`/版本，`current_user` 不比 `role`，改密/降级后旧 access token 在默认 120 分钟内仍有效。
- [ ] **HY3-P1-09 [风险] 其他**：`config.py:74-77` `AOC_SECRET` 回退值可由路径推导；`admin_core.py:284` 邀请码裁剪到 12 字符且可建 ADMIN 邀请；`require_admin_or_dispatcher` 权限过宽（财务/运行未分离）；`sync.py:28-42` 把全公司事件与余额下发给任意飞行员；金额字段全为 `Float`；`admin_ops.py:34-35` / `admin_network.py:309-310` 分页 `total` 忽略筛选。

### 3.2 本地核心（`apps/aoc-core` / `packages/aoc_core`）

- [ ] **HY3-P1-10 [静态] 崩溃恢复绕过复核**：`flights.py:381-417` 只存/恢复 `flight_id/started_at/last_seq`，丢掉 `partial`、`late_join`、`phase`、事件与重锚状态；重启后残记录被当完整记录写 `flown_leg` 并按 COMPLETED 结算，绕过 `ops/service.py:2996-3002` 的 REVIEW 闸门；`flights.py:526-531` 在 `_finalize` 异常时仍删原始轨迹。
- [ ] **HY3-P1-11 [静态] 状态/资金绕道**：`ops/service.py:960-980` `release_aircraft` 免罚取消且不清 `ACTIVE_TASK_KEY`（对比 `:2069-2114` 正常取消会收费）；`:3379-3389` `resolve_review(payout_factor)` 只在 `settle_flight` 后改字段，金额与账本不变，且无 0–1 校验。
- [ ] **HY3-P1-12 [静态] 账本 0.01 差异**：`ops/service.py:3034` 与 `:3285-3297` 两次取整顺序不同（`revenue_total` vs 逐笔收入 + `POLICY_ADJUSTMENT`），明细与账本可差 1 分；全链路 `REAL`。
- [ ] **HY3-P1-13 [静态] 配置版本与审计**：`ops/schema.py:290-297` `ops_config_version.version` 无唯一约束，`ops/service.py:2362-2387` 的 `max(version)` 检查在事务外；`:2389-2395` 回滚不传 `expected_version` 会静默覆盖并发发布；`:3623-3634` `reset()` 直接删光 `ops_audit`；`:2752-2763` `set_actual_zfw` 不写审计。
- [ ] **HY3-P1-14 [静态] 异常被吞导致状态卡死**：`flights.py:717-721,519-523` 结算/中止钩子异常只写 `last_error`，飞行已 COMPLETED 但账本、飞机、任务未推进且 HTTP 200；`ops/service.py:2961-2971` `settle_flight` 缺快照时 `return None` 被 `:2926-2933` 忽略；`:3512-3516,3556-3557` 锁过期/补班次整体 `except: return` 无日志。
- [ ] **HY3-P1-15 [静态] 轨迹与回放**：`track.py:140-143,161,179` 把「事件秒数」集合与「样本下标」比较（仅 1Hz 且 t 从 0 起时巧合成立）；`:288` 写入 sha256 但 `:293-305` 解码从不校验，坏块静默跳过；`:236-247` 时间/燃油/垂速静默 clamp；`:256` 尾部非整块字节丢弃。
- [ ] **HY3-P1-16 [静态] 配载与时区**：`economy.py:266-292` 超重削减只砍经济舱，经济舱不足时四舱合计 > `pax_total`；`:305` 用出发时刻判到达夜间费；`:387-388` 起降费按 MTOW；`economy.py:32-39,66-73,104-112` 固定偏移无 DST、非法时间静默回「现在」；`aoc_protocol/schemas.py:352` 默认 `BIN_V1` 而实际写 `BIN_V2`。
- [ ] **HY3-P1-17 [静态] 并发 TOCTOU**：`ops/service.py:2471-2604,2617-2723` 前置检查在 `_tx()` 外，可双任务；`:848-895` `update_aircraft` 的 version 检查在写事务之前；`:675-698` 机型去重查询在事务外，撞唯一约束直接 500。
- [ ] **HY3-P1-18 [风险] DB 韧性**：`db.py:257-264` 无 `integrity_check`、无损坏兜底；`:227-236` `close()` 只关当前线程；`ops/schema.py` 无外键但 `db.py:221` 开了 `foreign_keys=ON`；`schema_meta` 只写不读、无迁移检查；`service.py:1317` 导入档案后未停其它线程的常驻连接。
- [ ] **HY3-P1-19 [风险] 静态托管细节**：路径穿越防护本身正确（`main.py:858-859`），但 `main.py:361,410` 的下载 `filename` 未清洗引号/CRLF；`:254-265` `open_external` 只校验 scheme 前缀；`lock.py:28-30` `AOC_SINGLE_INSTANCE=0` 可完全关闭单实例锁。

### 3.3 前端 / Tauri（`apps/client` / `apps/admin-web`）

- [ ] **HY3-P1-20 [确认/静态] CSP 关闭 + 长期 token 明文落盘**：`apps/client/src-tauri/tauri.conf.json:26-28` `"csp": null`；`apps/client/src/online.ts:49-64,115-119` 把 access/refresh token（服务端 `auth.py:61` 有效期 30 天）写入 localStorage；`client/src/basemap.ts:22-42` 加载外部瓦片域。任意 XSS 即可读长期令牌。
- [ ] **HY3-P1-21 [确认] 管理端会话与路由**：`apps/admin-web/src/App.tsx:127-137` 任何网络错误都 `setAuth(null)` 跳登录；`:154-161` 登出 `try/finally` 无 catch，服务端会话仍有效且产生未处理拒绝；`:163-182` 路由无角色守卫（菜单过滤不等于权限控制），DISPATCHER 可直接进 `/users`。
- [ ] **HY3-P1-22 [静态] 分页与导出**：`admin-web/src/pages/Ops.tsx:32` 固定 `page_size=100` 且不传 `page`，客户端却分页显示（第 101 条永远取不到）；`pages/Audit.tsx:26-39` 裸 `fetch` 忽略 `action/actor` 筛选、硬编码 `limit=1000`、`link.click()` 后立即 `revokeObjectURL`；`pages/Network.tsx:28-44` 的 `load()` 复位筛选状态，`:46-50` 无错误处理。
- [ ] **HY3-P1-23 [静态] 请求可靠性**：`online.ts:102,108,125,142,155`、`client/src/api.ts:10,31,91`、`admin-web/src/api.ts:31` 全无超时/取消，请求挂起时 `Online.tsx:73,94` 的 `busy` 永不复位；`online.ts:85-94` 对非 JSON 错误体 `JSON.parse` 抛 `SyntaxError` 导致错误码丢失；`:163-168` 幂等键用 `Date.now()` 只在本调用内稳定；`admin-web/src/api.ts:28-30` CSRF 为空时静默不带头、无 403 恢复。
- [ ] **HY3-P1-24 [静态] Tauri 外壳**：`src-tauri/src/main.rs:232-246` dev 下无条件 navigate 覆盖 `devUrl`（HMR 失效）；`:136-146,211-214` 只在托盘「退出」清理 sidecar，无 `RunEvent::Exit` 守卫；`:24-29` `free_port()` 有 TOCTOU、失败回退 8765 与 vite 代理不一致；`:81,92,108,131` token 作为子进程命令行参数传递；无 updater/代码签名配置。
- [ ] **HY3-P1-25 [风险] 竞态与 UI 细节**：`Online.tsx:72-96`、`admin-web/src/pages/Overview.tsx:11-27`、`client/src/pages/ops/OpsExecute.tsx:230-246`、`AirportSelect.tsx:42-63`、`RoutePlanner.tsx:70-83` 等无 AbortController/请求序号，旧响应可覆盖新结果；`RoutePlanner.tsx:85-88` 清旧航路依赖缺 `cruiseFl`；`Logs.tsx:95-101` `useMemo` 依赖写错；`Online.tsx:86-95` 断网后健康标签不转离线；`OpsExecute.tsx:235-238` 卸载后仍弹 message；`Policy.tsx:110-112` 缺 `CONFIG_VERSION_CONFLICT` 分支。
- [ ] **HY3-P1-26 [风险] 构建配置**：`client/tsconfig.json:15-16` 关掉 `noUnusedLocals`（admin 为 true）；`client/vite.config.ts:19` 把 chunk 警告抬到 2500KB 而非分包；`admin-web/package.json:15` `dayjs`、`src-tauri/Cargo.toml:13-14` `serde/serde_json` 未被使用；`@ant-design/icons ^5.6.1` 与 React 19 的 peer 兼容性待验证。

### 3.4 航路 / navdata / SimLink / 集成

- [ ] **HY3-P1-27 [确认/静态] 巡航高度完全没进图**：`packages/aoc_route/aoc_route/net/network.py:882` 的 `plan()` 无 `cruise_fl` 参数，`graph.py:286-289` 每次先抛 `TypeError` 再回退（还会吞掉 plan 内部真正的 TypeError）；`net/db.py:61-86` 读了 `min_alt/max_alt`，`network.py` 全文件未引用；`navdata.py:763-781` 用集合比较航段端点，把 `A→B` 与 `B→A` 视为同一段，单向航路反向飞也判高度合法。
- [ ] **HY3-P1-28 [静态] 缓存与覆盖**：`packages/aoc_route/aoc_route/service.py:121-123` 缓存键漏 `force_graph`（`:186-198` 缓存了 `REQUIRES_SIMBRIEF` 后强制建图永久失效）；`graph.py:65-74` 图缓存指纹不含建图配置/算法版本；`net/geo.py:46-57`、`navdata.py:107-144,689-703` 网格/覆盖索引不处理 180° 经线环绕；`navdata.py:90-91` 覆盖只认 J/B 且 ≥18000ft，FL090 被判无覆盖。
- [ ] **HY3-P1-29 [静态] 导出与集成数据**：`packages/aoc_integrations/aoc_integrations/volanta.py:236-243` 轴序在 |lon|≤90 时判错（测试只用日本坐标掩盖）；`:83` 把 >600 的「分钟」当秒；`:186-191` 不展开嵌套 origin/destination 导致历史修复失败；`:80-87` 日期 `d/m` 优先、`:390-394` `fetch_detail` 不编码 id；`aoc_route/service.py:493-541` `.pln` 属性转义不全（`saxutils.escape` 不转义 `"`）、缺 `<ICAO>` 块、`WorldPosition` 高度恒 0、`RouteType` 恒 `HighAlt`；`:130-133,338,403,417-418` `generate()` 成功路径丢机型/ZFW/呼号。
- [ ] **HY3-P1-30 [风险] 外部输入**：`packages/aoc_route/aoc_route/aip.py:127-129` `aip_url` 无 scheme/主机白名单（`file://`、SSRF 可达），`:129,162,189` 只认 `utf-8-sig` 无 CP932 兜底、无重试/大小上限；`net/network.py:580-589` 对用户可配路径直接 `pickle.load`（等价任意代码执行）；`aip.py:148,190-220` 本地路径与 CSV token 无消毒。
- [ ] **HY3-P1-31 [静态] SimLink 协议/时钟**：`apps/simlink/SimConnectSource.cs:340` 采样 `T` 是墙钟，而 `Engine.cs:548-550` 的 `_simClock` 是模拟时间，加速倍率下轨迹时长/速度与 Python 侧推导不一致；Python 侧从未调用 `set_rate`（`aoc_core/service.py:1008-1029`），前端 2Hz 设置无效；`Program.cs:147-148` `runtime.json` 非原子写且退出不清理；`Engine.cs:40,332-335` `_events` 无上限；`Sources.cs:165-180` replay 文件缺失会在构造期带崩启动。
- [ ] **HY3-P1-32 [风险] navdata 细节**：`navdata.py:88-104` 未防 NULL `minimum_altitude`（`np.array(..., float64)` 会崩）；`:159` `check_same_thread=False` 但多数查询不加锁，后台建图线程与 HTTP 线程共享连接；`:670-687` 同名航路点无 region 过滤任意取最后一条；`:260,720` 完全未处理磁差；`:315-326,342,356,369` 单位靠硬编码阈值猜测。

---

## 四、P2 · 构建 / 文档 / 测试一致性

- [ ] **HY3-P2-01 [确认] 测试数量文档全面过期**：`README.md:84,119` 写「98 项」，静态计数 `tests/` 为 **185 个 `def test_` + 1 处 2 参数 parametrize = 186**（与 `docs/TODO.md:6` 一致）；`docs/09:18,52`（42 项）、`docs/10:67`（130）、`docs/11:149`（98）、`docs/02:138`（42）都是历史快照。
- [ ] **HY3-P2-02 [确认] CI 触发条件与文档不符，但属文档过期**：`.github/workflows/build.yml:10-13` 只有 `push.tags: ["v*"]` + `pull_request` + `workflow_dispatch`；最近提交 `f11436d` 明确是「移除main推送时候的CI」，所以**这是有意改动**，需要同步的是 `docs/08:231`、`docs/TODO.md:365` 与 README 徽章说明，而非改回 CI。
- [ ] **HY3-P2-03 [确认] 状态声明高估**：`README.md:117-119` 称 M1/M2/M3 验收项「已有自动化/端到端证据」，但 `docs/TODO.md:40-77` 仍有 4 组人工测试未完成、`:74` 明确「2026-11-06 之后的改动没有跑过」，`:83,89,99-127` 还有 C-01 / S-01 / 管理端 M-01–M-08 共 10 项（`apps/admin-web` 一行未改）；`docs/11:206-217` 实有 10 条限制，README 用「等」略过。
- [ ] **HY3-P2-04 [静态] 单位与功能状态互相矛盾**：SimBrief `manualzfw` 实现/测试是「吨」（`aoc_route/simbrief.py:8-16`、`tests/test_route.py:172-175`、`docs/TODO.md:141-146` 记录了 17% 配载误差事故），`docs/10:118`、`docs/02:591`、`docs/README.md:67` 仍写「千磅」；自包含打包已完成（`tools/build_core_exe.py`、`tauri.conf.json:44-48`），`README.md:56`、`docs/09:78,93`、`docs/08:37` 仍称「需要系统 Python / 不内置解释器」；CPDLC 在 `docs/README.md:3,65-67` 写成已交付，`docs/11:210` 与 `README.md:119` 明确未实现。
- [ ] **HY3-P2-05 [静态] 版本与依赖四处冲突**：Python `README.md:56` / `build.ps1:234,237` = 3.10+、`pyproject.toml:17` = py312、CI = 3.12、`Dockerfile:9` = 3.13（且 `pyproject.toml` 无 `requires-python`）；Node `build.ps1:242` = 18+、CI = 26、`Dockerfile:2` = 20，两个 `package.json` 无 `engines`；`requirements*.txt` 全部 `>=` 无上限，无 lock/constraints，CI 动态装最新 ruff/pyinstaller；actions 用浮动大版本标签。
- [ ] **HY3-P2-06 [静态] CI 与本地构建不等价**：`README.md:13` 称「本地等价流程」，但 CI 不构建 `apps/admin-web`、不构建 Docker 镜像、不跑 README 列出的 6 个冒烟；`build.yml:198-200` 上传 Tauri 原始产物名，而 `README.md:50` 让用户运行 `build.ps1:385-400` 改名后的 `out/AOC-*-x64-setup.exe/.msi`；`build.yml:239` `--no-core` 复用 artifact，本地 `make_portable.py:128-130` 会再跑一次 `build_core_exe.py`（其 `:177-179` 每次无条件删 `out/core` 重建）。
- [ ] **HY3-P2-07 [静态] 破坏性操作清单**：`tools/build_core_exe.py:177-179`、`tools/make_portable.py:135-137,151-152`、`tools/build.ps1:271-290`（`-Clean`）会删目录/覆盖产物；`alembic/versions/0001_baseline.py:24-25` downgrade 删全表；`packages/aoc_core/aoc_core/service.py:634-635,1319-1320` 档案导入会 `rmtree` 覆盖本地库（仅前端 Popconfirm 保护）。
- [ ] **HY3-P2-08 [静态] 测试与证据链**：`tests/test_server.py:16-36,213-215` 并发测试只用 SQLite 双线程断言 `[200,409]`（潜在 flaky）；`docs/05:225` 要求的「pytest + PostgreSQL 容器、20 并发抽班」从未落地；`tests/test_recovery.py:18-55`、`tests/test_server.py:102-127` 有浅断言；`tests/test_ops.py:604-605` 依赖 `datetime.now()`。`.gitignore:20` 忽略整个 `out/`，而 `docs/07:10,17`、`docs/08:247` 把 `out/` 内安装包/日志/截图当验收证据引用，其中 `out/portable_smoke.json` 实测不存在。
- [ ] **HY3-P2-09 [静态] README 命令细节**：`README.md:79` 漏 PyInstaller/Docker 步骤；`:91` 把 `make_portable.py:119` 的 `--build`（重新构建前端）注释成「重新生成便携 ZIP」；`:28,44,95` 用 `npm install` 而 CI/Docker 用 `npm ci`；`:112` 把不入库的 `Pre-train/` 列为目录。
- [ ] **HY3-P2-10 [风险] Windows 与仓库卫生**：`tools/build.ps1:319` 中文输出 + `Start-Transcript` 在 PS 5.1/GBK 下可能乱码；`tools/make_portable.py:22` 版本号 `0.1.0` 硬编码与 `build.ps1:105-107` 从 tauri 读取不一致；`.gitignore` 未忽略 `*.exe/*.dll/*.msi` 等二进制后缀（仅靠目录规则）；`spikes/simconnect_probe/data/final_approach_rjtt34r.jsonl` 真实采集数据位于 `data/` 且未被忽略；`out/flow_m3.py:16,20` 含演示账号口令（该目录整体被忽略）。

---

## 五、确认做对、不要误改的部分

- `apps/server/aoc_server/security.py:35-57`：scrypt 加盐 + `compare_digest`、只存 token 哈希；`admin_auth.py:72-77` HttpOnly/SameSite Cookie；`security.py:195-198` 非 GET 全量 CSRF；`current_user` 每次重查公司与 active，租户隔离到位。
- `apps/server/aoc_server/models.py:191-198,298-304`：活动锁与每用户 ACTIVE 班表的部分唯一索引是真防重；`routers/sync.py:62-69`、`admin_network.py:251-283` 逐条 savepoint 隔离；`services/ops.py:522-533` 开段时固化经济/策略快照以支持可复算结算。
- `apps/aoc-core/main.py:976`（仅绑 127.0.0.1）、`:858-859`（`.resolve()` 防路径穿越）、`:855-856`（`/local/*` 未匹配统一 404）；`packages/aoc_core/aoc_core/ops/service.py:1848-1866` HMAC 抽班令牌；`:2520-2685` 规则版本固化；`:3123-3159` 作废重飞全量冲销；`db.py:675-698` 用 SQLite backup API 而非文件复制。
- `apps/client/src/api.ts:3,13,29` 本地 token 只在内存；两端 `main.tsx:1` 已打 React 19 补丁、`strict: true`、`/admin/` 三处 base 对齐；`client/src/App.tsx:274-278` 等定时器/监听器清理完整，未发现 token 进日志。
- `packages/aoc_route/aoc_route/net/network.py:892-898` 与 `service.py:208-215`：无解时正确回落 `REQUIRES_SIMBRIEF` 且保留链接，不伪造航路；`aip.py` 的 TTL + 原子替换 + 失败回退旧缓存；SimLink 与 Python 的采样字段/单位契约逐项对齐、端口 0 发现链路成立。
- `tests/conftest.py:11-17` autouse 关闭网络/建图以保证离线；全库无 `skip`/`xfail`。

---

## 六、建议修复顺序与验收

1. **安全边界**：HY3-P0-01 → 02 → 03；配套补「大小写路径」「`/local/runtime` 不含 token」「XFF 伪造限流」「localhost CORS」四项回归测试。
2. **并发正确性**：HY3-P0-04 + 08；起 PostgreSQL 容器跑 20 并发抽班 / 结算 / 邀请码用例，并给 `company.balance` 加条件 UPDATE 或行锁。
3. **联机链路**：HY3-P0-05 + 06；补 single-flight 刷新、outbox 持久化重放、`has_more` 循环、cursor 生命周期，并用 `tools/smoke_m3.py` 验证断网补传。
4. **资金与状态**：HY3-P0-07 + HY3-P1-10~14；金额改整数分，补「备降/错机场/复核 payout_factor/结算异常」用例。
5. **数据与协议**：HY3-P1-27~32；补跨 180°、|lon|≤90 轴序、FL090、单向航路反向、CP932 等边界测试。
6. **一致性收口**：HY3-P2-01~09；同步 README / `docs/08` / `docs/TODO.md` / `docs/README.md`，统一 Python 与 Node 版本、锁定依赖，必要时把 CI 触发说明写清楚（当前为有意只在 tag/PR 触发）。

**验收建议**：先补一组 PostgreSQL 并发测试与一组本地 token 越权测试（这两类问题现有测试集完全覆盖不到），再跑 `python -m pytest`（应为 186 项）、`ruff check packages apps tests tools --select F,E9`、两端 `tsc --noEmit` + `npm run build`、`dotnet build`，最后按 `docs/TODO.md:42-77` 完成干净 Windows 与 MSFS 2024 实机回归。

---

## 七、审查边界（避免把推断当结论）

- 全部结论来自静态阅读；**未执行任何测试、构建、HTTP 请求或 git 写操作**。
- PG 竞态、SSRF/`file://` 可利用性、DNS rebinding、`pickle.load` 可达性属于「代码层面成立、未做运行时复现」；建议按第六节补复现用例后再定级。
- `read_lints` 对 `packages`、`apps/server`、`apps/aoc-core`、`tests` 返回 0 条诊断；`git status --short` 为空。`ruff`/`pytest`/前端构建是否全绿**未实际验证**。
- 仓库卫生中「哪些产物已被 git 跟踪」未用 git 索引逐项核对，凡按 `.gitignore` 应忽略但工作区存在的，均按「本地产物 / 若为历史遗留则 .gitignore 无效」表述。
