# TODO

> **当前状态（2026-11-06）**：`§1`–`§47` 全部实现，前端走查 `UI-01`–`UI-19` 与信息架构 `IA-01`–`IA-12` 的**客户端侧已全部处置**（§44 / §46 / §47）。
> **文档分工**：「一、待办」只放未完成项，按 **需要测试 / 客户端 / 服务端** 三类；「二～八」是已完成功能项（§1–§47）；「九」是已收口的走查台账（`UI-xx` / `IA-xx` 逐条明细；其中管理端的 4 条只留指针，正文在 1.3.2）。
> **剩余量**：测试 4 组（真机 / 干净环境 / 低配机 + 1 组本机冒烟）；客户端 1 条可选（D-10 降级）；服务端 1 条规则 + 管理端 8 条（`M-01`–`M-08`）。
> 验证：`pytest` 186 项、`tsc --noEmit` + `npm run build` 全绿；`dotnet build` 最近一次通过为 2026-11-05（之后未改 C#）。
>
> 约定：`§编号` 与历史测试编号（`T-xx` / `A-xx`）沿用旧值、**不重排**（文档、提交记录和历史对话都在引用）；
> 本轮新增的待办用 `C-`（客户端）/ `S-`（服务端规则）/ `M-`（管理端）前缀，测试项直接沿用原条目标题。
> 记录格式：每条实现 = 「落地（改了什么）」+「背景（为什么/怎么发现的）」+「关联」；原始实测数据集中附录 B，决策集中附录 A。

## 目录

| 章节 | 内容 |
|---|---|
| 一、待办 | **1.1 需要测试**（⏳ 4 组）· **1.2 客户端**（1 条可选）· **1.3 服务端**（1 条规则 + 管理端 `M-01`–`M-08`） |
| 二、已完成 · 2026-11-02 ~ 11-03 | §31–§37（收尾批次：幽灵机、合计航时、推出定稿、SimBrief 单位、快速调机、场景库跑道、CI Node 升级） |
| 三、已完成 · 2026-10-30 | §23–§30（功能改进） |
| 四、已完成 · 2026-10-24 及更早 | §1–§22（含性能修复 D-26/D-27） |
| 五、已完成 · 2026-11-04 | §38–§40（翼展真值同步 / 遵循航线查跑道、发动机启动即推出、ZFW 差异归一） |
| 六、已完成 · 2026-11-05 | §41（自动开录抢先建档 → 班表航段落成自由飞行：无主录制改绑 + 已绑他处拒绝 + 班表过期拦截） |
| 七、已完成 · 2026-11-06（第一批） | §42–§45（§41 三项遗留 / 原 `1.4` 三项遗留 / `UI-01`–`UI-06` / `IA-01·02·04·07·09`） |
| 八、已完成 · 2026-11-06（第二批） | §46–§47（`UI-01` 口径修订 + 客户端 `UI-07`–`UI-19` 收口 / `IA-03·05·10`；管理端只留文档） |
| 九、已完成台账 | 走查清单 `UI-01`–`UI-19` / `IA-01`–`IA-12` 逐条明细（全部已处置，原「1.7 / 1.8」） |
| 附录 A | 决策记录 D-1～D-11 |
| 附录 B | 验证记录 V-1～V-6（含探针工具与最近一次回归） |

---

## 一、待办

> 见「二～八」= 已完成功能项；「九」= 已收口的走查台账（`UI-xx` / `IA-xx`）。这里只剩三类未完成项：

| 分类 | 条目 | 备注 |
|---|---|---|
| 1.1 需要测试 | 4 组 | 真机 / 干净 Windows / 低配机；1.1.4 在本机就能跑 |
| 1.2 客户端 | 1 项（可选） | `apps/client` 功能项已清空，只剩一条按 D-10 降级的布局项 |
| 1.3 服务端 | 1 + 8 项 | `aoc-core` 规则 1 项；管理端 `apps/admin-web` 8 项（`M-07` 需先拍板） |

### 1.1 需要测试（真机 / 干净环境 / 低配机）

#### 1.1.1 人工验收（干净 Windows，无 Python / .NET / Node）

- [ ] **T-01 / T-06a**：`out/AOC-0.1.0-x64-setup.exe`、`*.msi`、`AOC-portable-*-win64.zip` 各跑一次：双击无控制台窗口、托盘出现、单实例、关闭窗口最小化、托盘「退出」后无残留进程。
- [ ] **体积回填**：自包含改造后重新生成便携包 / 安装包，把实测值回填 `08` §2 / §4.4（`aoc-core` onedir 已实测 134 MB）。
- [ ] **Authenticode 签名**：等证书，签 `AOC.exe`、`AOC-portable.exe` 与安装包。

> 已通过：**T-21 / A-32**（2026-10-24，安装版 + 便携版）—— 无控制台、托盘、直开窗口、退出无残留，详见 §10。

#### 1.1.2 实机复测（需 MSFS 2024）

- [ ] **§33 幽灵机 / 瞬移**：
  ① 冷启动 MSFS → 连上 SimLink → 进飞行瞬移到基地 → 抽班「开始本段」→「开始记录」：应正常停在「记录中」，不再立刻「已完成」；
  ② 先抽班再进游戏：新记录首帧应落在真实机位（KBFI 幽灵帧被截断），`block_off_source=preroll`；
  ③ 先开 MSFS 停在出发机场并启动发动机 → 再启动 AOC：10s 内自动开录，`block_off_source=connect`；
  ④ 已在空中才开 AOC：位置闸拦住并提示，确认后 `partial=1`，结算 `HELD` + `PENDING`、航段不置 `COMPLETED`。
- [ ] **§33 本段作废重飞**：对一条已 `COMPLETED` 的航段点「作废重飞」→ 航段回 `PLANNED`、`settlement` 置 `VOID`、账本出现反向条目、飞机位置/小时/循环回滚。
- [ ] **§32 推出快照**：开录 → 推出（GS ≥5kt 持续 3s）→ `/local/recording/status` 的 `zfw_at_pushback`/`fuel_at_pushback` 有值、`pushback` 事件出现；推出前继续加油加货不影响取值；地面已在滑行才开录时 `pushback_source=start`；空中接入为 null。
- [ ] **§39 点火即推出（engine 判据）**：冷舱点火后 10s 内 `zfw_at_pushback`/`fuel_at_pushback` 有值且 `pushback_source=engine`；用拖车推出（GS <5 kt）仍能由 `gs` 判据定稿；中途接入（已在滑行/空中才开 AOC）保持 `start`。
- [ ] **§36 场景库**：设置页填 `%APPDATA%/ABarthel/little_navmap_db/little_navmap_msfs24.sqlite` → `GET /local/airports/WMKN` 返回 `runway_source=scenery`、长度 ≈3060 m（现实 navdata 3480 m）、接地区视图出现「游戏内 / 现实」对照提示。
- [ ] **SimLink 自动重连**：先开 AOC 再开 MSFS，10s 内 `sim_connected=true`；飞行中退出再进，`/events` 有 `sim_disconnected`/`sim_connected`、记录不重复；重连后发动机仍在转时 10s 内自动开录（§33 顺带修复）。
- [ ] **§41 录制早于任务（自动开录抢跑）**：
  ① 先进 MSFS 起动发动机，等 SimLink 自动开录（10s）→ 再点「开始本段」：应弹「已经在录制中」确认，确认后航段记入班表、日志 `mode=ROSTER`、呼号是本段呼号；
  ② 一段自由飞没结束又去点「开始本段」：应 409 `RECORDING_IN_PROGRESS`，航段保持 `PLANNED`；
  ③ 过期班表点「开始本段」：应 409 `ROSTER_EXPIRED`。

#### 1.1.3 性能复核（需低配机）

- [ ] **SimLink 内存（D-26）**：`python tools/simlink_mem_probe.py --minutes 30 --interval 60`；判据：未连接 <60 MB、连上未录制 <80 MB、录制稳态 <100 MB 且 |趋势| ≤5 MB/h。
- [ ] **aoc-core 空闲 CPU（D-27）**：开发机已实测空闲平均 **0.130%**、峰值 1.378%（见 §22）；待低配机复核：空闲 5 min 平均 <0.3%（单核）、录制中 <1.5%。`python tools/core_cpu_probe.py --minutes 5`。

#### 1.1.4 前端冒烟脚本（本机可跑，需浏览器 + 运行中的 core）

> `tools/ui_smoke.py` 覆盖首页 / 日志 / 地图 / 航路 / 运营各页与抽班-执行流程，2026-11-06 之后的改动（合并页、结算组件、错误态、文案）**没有跑过**。

- [ ] **跑一遍全流程**：`python tools/ui_smoke.py`（会启临时数据目录与 core）；重点看 `抽班 → 开始本段 → 取消本次航班`、`/ops/review` 深链是否落到财务「待复核」页签、结算抽屉标题是否仍含 `AOC`。
- [ ] **按现状补断言**：抽班按钮文案已区分「抽班 / 重抽（替换当前班表）」，若脚本的 `button:has-text('抽班')` 在有班表时选不中，改成 `:has-text('重抽')` 或按 `data-testid`。

### 1.2 客户端（`apps/client`）

> `UI-01`–`UI-19`、`IA-01`–`IA-12` 的客户端侧已全部落地（§44 / §46 / §47），**没有功能遗留**。只剩一条被明确降级为「不投工作量」的项：

- [ ] **C-01 窄窗口挤压（可选，D-10 ③）**：顶栏 `height:60px` + `Space wrap` 溢出、侧栏 216px 无 `breakpoint`、机队表 8 列无横向滚动、执行页 `Col span={6}` / `Descriptions column={3}` 挤压。1440 宽下正常，D-10 已定「只保证 1440」→ 仅记录，明细见「九、`UI-07`」。

### 1.3 服务端（`aoc-core` / `packages` / 管理端）

#### 1.3.1 运营规则（`aoc-core`）

- [ ] **S-01 翼展上限阈值语义（可选）**：`WINGSPAN_BY_WIDTH = (<45 → 36, <60 → 52, ≥60 → 80)`，CYXY 45.1 m 落在「52 m」档；而 ICAO 代码 E 的跑道标准宽度本就是 45 m（对应 52–65 m 翼展），即本规则把 45 m 跑道按 D 类处理。要放宽到「≥45 → 65」需先定清语义是「场道等级」还是「滑行道/停机位约束」，目前按保守值保留。
  - 落点：`packages/aoc_core/aoc_core/ops/`（翼展档位常量）、§38。

#### 1.3.2 管理端（`apps/admin-web`，`M-01`–`M-08`）

> 2026-11-06 这两轮只动客户端（`apps/client` + 必要 `aoc-core` 支撑），`apps/admin-web` 一行未改。
> 条目来自「九」的 `UI-07/09/11/12/15` 与 `IA-06/08/11/12`，`M-xx` 为排期编号，括号里保留原编号便于对照。
> **建议顺序**：先 `M-05`（共享封装：`money` / 时间 / 枚举 / 请求），再 `M-02`、`M-06`（都是从客户端直接搬组件），
> 其余 UI 项随后；`M-07` 需先拍板。否则同样的改动要在两端各写一遍。

- [ ] **M-01（原 `UI-07`）管理端 sider 底部信息绝对定位**
  - 现状：`.admin-sider-foot` 绝对定位在底部，菜单在 ~768px 高度以下会被遮住且没有滚动区。
  - 落点：`apps/admin-web/src/styles.css:58-66`。
- [ ] **M-02（原 `UI-09`）`Network.loadFlights()` 没有 try/catch**
  - 现状：筛选/翻页失败是静默 unhandled rejection，页面停在旧数据上。
  - 落点：`apps/admin-web/src/pages/Network.tsx:46-50`（客户端已统一成 `components/LoadError.tsx`，可直接搬）。
- [ ] **M-03（原 `UI-11`）高影响操作缺少二次确认**
  - 用户「角色」下拉即时生效、启用开关即时生效（可能把自己降权）；邀请码只在 `message.success` 里出现一次（关掉找不回、无复制按钮）；航班实例「取消」无确认；策略/经济「回滚」无确认。
  - 落点：`apps/admin-web/src/pages/Users.tsx:90,121-128`、`Network.tsx:174`、`Policy.tsx:258-260`、`Economy.tsx:198-200`。
- [ ] **M-04（原 `UI-12`）公司基地 / 航线机场仍是自由文本**
  - 现状：管理员输入 ICAO 手打，错了只能等后端报错；没有 `AirportSelect` 等价物。
  - 建议：把客户端的 `AirportSelect` 抽到共享层（与 `M-05` 同批）。
  - 落点：`apps/admin-web/src/pages/Company.tsx:82-84`、`Network.tsx:184-185,201`。
- [ ] **M-05（原 `IA-08` + `UI-13`）共享「钱 / 时间 / 枚举 / 请求」封装**
  - 现状：同一个余额客户端 `$1,234.56`、管理端 `USD 1,234.56`；时间一边自写 `fmtUtc`、一边 `toLocaleString()`；状态枚举一边有 `*Labels`、一边直接打印 `SETTLED/ACCEPT`。
  - 客户端侧已集中（`apps/client/src/ops.ts` 的 `money`/`fmtUtc*`/`*Labels`/`eventLabel`、`utils.ts` 的时间与单位格式化），**跨端共享包（`packages/ui-shared`）与 admin 迁移未做**。
  - 建议：抽 `packages/ui-shared`（或至少共享 `money` / `fmtTime` / enum labels），两端只保留自己的传输层；能顺带消掉 `UI-13` 在管理端的那一半。
  - 落点：`apps/client/src/ops.ts:36-74`、`apps/admin-web/src/api.ts:52-61`、两端 `types.ts`。
- [ ] **M-06（原 `UI-15`）管理端根组件没有 ErrorBoundary**
  - 客户端已加 `apps/client/src/components/ErrorBoundary.tsx`，可直接搬到 `apps/admin-web/src/App.tsx` 根部。
- [ ] **M-07（原 `IA-06`，待拍板）管理端「经济参数」+「结算策略」是否合成一页 3 页签**
  - 现状：同一领域两种拆法。客户端 `OpsRules` 用 Tabs（经济 / 策略 / 版本与审计）一页装完；管理端拆成 `Economy` 与 `Policy` 两个一级菜单，各自一套 preview / publish / versions / rollback，两套版本抽屉、发布弹窗与预览结果各写一遍，字段和文案已开始漂移；客户端把审计表塞进「版本与审计」页签，管理端另有独立 `Audit` 页。
  - 建议：定一种拆法（推荐「一页 3 页签」，管理端菜单本来就偏多），把「参数表格」「策略规则表」「版本/回滚」抽成共用组件；审计只保留管理端 `Audit`，客户端只留「版本」。
  - 收益：管理端一级菜单 10 → 9；重复实现 2 套 → 1 套。
  - 待拍板后再动，落点：`apps/admin-web/src/pages/Economy.tsx`、`Policy.tsx`、`App.tsx:50-61`、`apps/client/src/pages/ops/OpsRules.tsx`。
- [ ] **M-08（原 `IA-11` / `IA-12`）概览去重 + 一级菜单归组（可选）**
  - 现状：`Overview` 的「待复核」表与 `Ops` 复核页签同数据（前者不能操作），「最近航班」与 `Ops` 航班表同数据；`System` 又重复展示公司名 / 余额 / 经济与策略版本（`Company` 已有一半）。一级菜单 10 项平铺，其中「公司档案 + 经济参数 + 结算策略 + 系统 + 用户 + 审计」本质都是「设置」。
  - 建议：`Overview` 只留「今天该处理的异常与待办」（待复核、锁、取消），只读信息删掉；`System` 只留服务/数据库/计数，公司信息归 `Company`（两页可合成「公司」）。菜单分 4 组：概览 / 运行（监控·机队·网络）/ 财务（待复核）/ 设置（公司·经济·策略·用户·审计·系统）；配合 `M-07` 可到 8 项以内。
  - 落点：`apps/admin-web/src/pages/Overview.tsx:49-88`、`Ops.tsx:120-150`、`System.tsx:41-49`、`Company.tsx:69-73`、`App.tsx:50-61`。

#### 1.3.3 跨端共享封装（`packages/ui-shared`）

> 由 `M-05` 承载，这里单列是因为它不属于管理端 UI：新建共享包后，客户端 `ops.ts` / `utils.ts` 与管理端 `api.ts` 都要改成引用它。

---

## 二、已完成 · 2026-11-02 ~ 2026-11-03（§31–§37）

> 本批按「止血 → 协议 → 小改 → 新功能 → 大改」排序落地：§33（P0 假起降）→ §34（抽班下限）→ §32（推出定稿）→ §31（单位换算）→ §35（快速调机）→ §36（场景库跑道）。
> 测试：`pytest` 166 项、`ruff F,E9`、`tsc --noEmit`、`dotnet build` 全绿。
> §37（2026-11-03 追加）不是功能项，是 CI 运行时维护（Node 20 → 26）。

### 31. SimBrief `manualzfw` 换算错误（单位是「吨」不是千磅）

- **落地**：`aoc_route/simbrief.py::_manualzfw` 改为 `ZFW ÷ 1000`（3 位小数），删掉 `KG_TO_LB`；`build_url`/`simbrief_context`/`main.py::route_simbrief`/`tools/ui_smoke.py` 的「千磅」文案改「吨」；`tests/test_route.py` 断言 `6120 kg → 6.120`，`tests/test_ops.py` 两处换算同步；顺带更正 §2 的旧结论（原文「× 2.2046226 ÷ 1000 = 千磅」是错的）。
- **背景**：配载单 ZFW 166714 kg → 链接生成 `manualzfw=367.542`（按千磅换算），SimBrief 出 195700 kg，差 28986 kg（≈17%）。
- **结论（V-2）**：`manualzfw` 单位是 ton。`367.542` 被当成 367.542 t 超 A350 MTOW → SimBrief 丢弃并自算 payload。正确值 = `166.714`；补充例：`manualzfw=182.555` = 182555 kg。
- **关联**：§2（配载改用 `manualzfw`）、`aoc_core/service.py::simbrief_url`。

### 32. 推出后定稿 ZFW / 油量（方案 B）

- **落地**：
  1. SimLink `Engine.TrackPushback()` 按 V-5 口径（`GS≥5kt` 连续 3s、最近 5 帧中位数、跳变 >10% 继续等）产出 `zfw_at_pushback`/`fuel_at_pushback`/`pushback_utc`/`pushback_source`，随 `/status` 透出并写 `pushback` 事件；地面晚接入取开录首帧（`source=start`），空中接入留 null。
  2. core `poll_simlink_once()` 读到后调 `OpsService.set_actual_zfw(..., source="pushback", final=True)`：覆盖 `flight_record` 并补 `zfw_check(source=pushback, final=true)` 事件。
  3. 油量：`landing.evaluate(fuel_start_kg=...)` 改用推出油量；`flights._finalize()` 对「起始−结束 < 0」记 0 并标 `FUEL_ANOMALY`，不生成负燃油成本；`block_off` 仍取首帧，只改油量取点。
  4. 协议/前端：`POST /local/recording/start` **彻底移除** `actual_zfw_kg`（单一来源）；`/local/ops/flight-status` 加 `planned_zfw_kg`/`planned_fuel_kg`/`fuel_at_pushback`/`zfw_source`/`zfw_state`/`zfw_warnings`；执行页改为实时展示「实际 ZFW（推出后定稿）/ 配载单 / 差异」与「实际滑出油量 / 计划油量」，偏低只在推出时推一次 `message.warning`，不再拦开录。
- **背景（旧行为的两个坑）**：ZFW 只在点「开始记录」那刻取快照，而开录已提前到发动机启动（§27）→ 记的是半载值（偏低误报漏装、偏高漏报）；`fuel_start_kg` 取首帧油量，推出前加满会让 `fuel_used_kg` 变负 → 负燃油成本，而回写机队的油量又是真实剩余值，两头对不上。
- **取舍**：曾评估方案 A（滑动中位数 + 推出时重算，保留开录快照），最终选 B —— 单一来源更干净，代价是动 SimLink 协议与录制时序（与 §33 同批只发一次版）。
- **V-5 实现要点**：① `_pushbackSince` 从候选帧起表、等 `t − since ≥ 3s` 再取值（不能用「3s 窗口内全满足」，实测帧间隔 0.98–2.0s 会漏判）；② 只在 `on_ground && !_hasTakeoff` 计时（空中接入不能把巡航重量当 ZFW）；③ 兜底：地面晚接入取首帧标 `source=start`、空中接入写 null。
- **测试**：`tests/test_ops.py::test_pushback_zfw_is_final`、`::test_fuel_start_uses_pushback_value_and_never_negative`。
- **关联**：§4（推出前 ZFW 提示）、§27（开录提前到发动机启动）。

### 33. 抽班点「开始」后直接变「已完成」（KBFI 幽灵机 + 瞬移）

- **落地（四道闸 + 作废重飞）**：
  1. **开录位置闸**：`PersonalService.position_gate()`（`aoc_core/service.py`）用 navdata 算最新帧到出发机场距离；`poll_simlink_once()` 闸门未过时**不建 recorder、不喂帧**，只推进游标（`_advance_cursor`），开录用 `skip_seq` 一次性跳过闸前帧；手动开录越闸返回 409 `POSITION_GATE`（`PositionGateError`）；出发机场由 `OpsService.recording_departure()` 给出（任务 → 已锁班表首段 → 自由飞）。navdata 缺失 / 查不到机场 → 只做瞬移断点、不拦录制。
  2. **预录截断**：`Engine.TrimPreRoll()`（`apps/simlink/Engine.cs`）回扫 600s 预录，命中「速度 >900kt / `dt>30s` 且位移 >10NM / 低空且远离出发机场」就只保留最后一次跳变之后的帧；出发机场坐标由 core 用 `set_dep_airport` 下发。
  3. **瞬移 = 重置**：core `FlightRecorder._reset_after_teleport()` 丢弃跳变前轨迹、重锚 `started_at` 与时间轴（`t_offset`）、重置状态机并写 `teleport` 事件；SimLink 同步清 `_hasTakeoff`/`_landed` 与推出快照。同一处重置也用于 `sim_disconnected`/`sim_connected` 与 `dt>30s`。
  4. **收尾门槛**：`landing.evaluate()` 丢弃「首点在空中但不满足 ≥60s 或爬升 ≥500ft」的幽灵前缀；`flights._finalize()` 里带 `TELEPORT` 且 block <2min / 距离 <5NM → `ABORTED`，绝不置 `COMPLETED`。
  5. **本段作废重飞**：`OpsService.void_leg()` + `POST /local/ops/rosters/{id}/legs/{seq}/void` —— 航段退回 `PLANNED` 并清 `flight_record_id`、`settlement` 置 `VOID`、账本按原条目逐条反向（同 `entry_type`、金额取负，仅冲销有 `settlement_id` 的条目）、飞机位置回滚到本段出发机场且小时/循环减回、`flown_leg` 删除、航班记录留档为 `ABORTED`、飞机锁退回 `HELD`、实例回 `SCHEDULED`、班表回 `IN_PROGRESS`；班表页每段都有按钮。
  6. **前端**：`/local/ops/flight-status` 补 `dep_icao`/`dep_distance_nm`/`position_ok`/`partial_allowed`；位置不符时禁用「开始记录」并提示，已在空中时弹「按部分记录开始」（`partial=true` → `settlement.status=HELD`、`review_status=PENDING`、任务 `finished` 但不置航段 `COMPLETED`）。
  7. **重连不重置状态机（V-1 顺带发现）**：SimLink 重连/切场景时重置 `_engineRunning`/`_engineOnSince`/`_hasTakeoff`/`_landed` 并重新点亮发动机边沿，修复「发动机在转却不自动开录」。
- **背景（根因）**：MSFS 启动时先在 **KBFI** 生成幽灵飞机，进飞行才瞬移；采样里出现「空中帧 → 地面帧」的假起降。**旧判据**是「首点不在地面就取 `takeoff_index=0`」（现在要先过 `_sustained_airborne`：空中 ≥60s 或爬升 ≥500ft），之后**任意**地面帧即算落地 → `_finalize()` 判 `COMPLETED` → `settle_flight()` 把 `roster_leg` 置 `COMPLETED`，而 SimLink 还在录 → 界面同时出现「已完成 + 记录中」。`should_auto_stop()` 的 `seen_airborne` 也会被这帧点亮，叠加 §30 的静止/停机刹判定会提前收尾；`TELEPORT` 异常只在收尾扣罚，不影响「是否已完成」。
- **现场证据（`aoc.db`，2026-11-02）**：污染记录 `e307baee`（VHHH→WMKN）`block_minutes=1.9`、`distance_nm=7493.7`，`settlement` 已 `SETTLED`、`policy_action=REJECT`、`revenue_total=0`、`cost_total=−67,267.73`、`profit=+67,267.73`（**负成本反而白赚**）；`roster_leg 1c06d706` 已是 `COMPLETED` 而 `roster f7c357db` 仍 `IN_PROGRESS`；同一次污染把 `B-1090` 挪到了 KBFI。
- **测试**：`tests/test_landing.py::test_ghost_airborne_prefix_is_trimmed`、`tests/test_api.py::test_recorder_resets_on_teleport` / `::test_position_gate_blocks_outside_departure`、`tests/test_ops.py::test_void_leg_reverts_settlement_and_position` / `::test_partial_recording_goes_to_review`。
- **关联**：§27（自动开录）、§30（自动收尾）、§6；`landing.py::evaluate`、`flights.py::_anomalies/_finalize/should_auto_stop`、`ops/service.py::on_flight_finalized/settle_flight`。

### 34. 抽班「合计航时」加下限（默认 上限 − 25%，可填）

- **落地**：`_constraints()` 新增 `min_total_block_minutes`（留空 = `max(30, 上限×0.75)`；手填 30–上限；`0` = 关闭下限，供放宽阶梯与探针用；越界 `PARAM_OUT_OF_RANGE` + `details.key`）。`_build_chains`/`_virtual_chains` 入候选改为 `block_total >= total_min`，并按「剩余航段全取最长也补不到下限」提前剪枝（否则 200/60 条候选上限会被不达标的前缀链占满）。`draw()` 抽出 `_collect_candidates()` + `_relax_attempts()` 阶梯放宽（先只保上限 → 每程最长 ×1.2），每步返回 `warnings[]` + `relaxed`，不静默降级。
- **前端**：`OpsRoster.tsx` 新增「最少合计航时」输入（占位显示默认值、实时提示「可接受 360–480 min」），约束摘要行改成 `合计 360–480 min`，候选卡片上方展示放宽提示。
- **背景**：原来 `max_block_minutes` 只做上限判断，而 `walk()` 里每条前缀链都入候选 → 1 段 90 min 也能成候选，与玩家填的「合计 480」不符。
- **V-4 结论**：真实机队上 480 上限 + 360 下限时遵循航线**达标 0 条（全灭）**，所以「放宽一次 + warnings」是必需路径而非可选项。
- **兼容**：老班表 `constraints` 无该字段 → 读取时按「上限 × 0.75」推导，不写库、不报错。
- **测试**：`tests/test_ops.py` 覆盖「合计 480 留空 → 只返回 ≥360」「上限 120 → 默认 90」「上限 30 → 钳到 30」「手填 300 优先」「不达标先放宽并带 warnings」「`follow_routes=false` 同样生效」。
- **关联**：§19、`ops/service.py::_constraints/_build_chains/_virtual_chains/_no_candidate_reason`、`tools/v4_draw_probe.py`。

### 35. 快速调机（付费把飞机调到别的机场）

- **落地**：`OpsService.fast_ferry(aircraft_id, to_icao, hold=None)` —— 前置校验（`ACTIVE`、未锁、无 `active_task`、班表非 `IN_PROGRESS`、目标 ≠ 当前且 navdata 可查）→ 改 `aircraft.current_airport_icao`、账本记 `COST_FERRY`、审计 `AIRCRAFT_FERRY`（from/to/distance/fee/hold）、返回 `{aircraft, distance_nm, fee, currency, hold, warnings}`。费用 `fixed + 距离 × per_nm`；`default_economy` 新增 `fast_ferry_fee_per_nm=12`/`fast_ferry_fixed_fee=1000`/`fast_ferry_hold=false`（前两个进 `PARAM_SCHEMA`，运营规则页可改）；`fast_ferry_hold` 打开时建 `aircraft_lock(HELD)`，`_expire_locks()` 到点自动释放（含 `aircraft` 状态回 `ACTIVE`）；**允许透支**，不拦负余额。接口 `POST /local/ops/fleet/{id}/ferry`。
- **前端**：机队页每架可调机的飞机加「快速调机」弹窗（`AirportSelect` + 距离/费用预览 + 「模拟器里不会搬飞机」提示）；班段开始的 `AIRCRAFT_NOT_AT_DEPARTURE` 错误改为弹「去快速调机」。
- **语义**：只改 AOC 侧位置 + 收费 + 审计；模拟器里不搬飞机，必须提示「请在 MSFS 里于目标机场重新进入飞行」，并由 §33 的位置闸兜底（位置不符不开录）。真实转场仍用自由飞（落地自然更新位置）。
- **不做**：`mission_type=FERRY`、零客货配载单、调机结算/复核、班表 leg。
- **测试**：`tests/test_ops.py::test_fast_ferry_moves_aircraft_charges_and_audits` / `::test_fast_ferry_rejects_invalid_cases` / `::test_fast_ferry_hold_expires`。
- **关联**：§33（位置闸）、§32（真实转场走自由飞时照常按推出定稿油量）、`ops/service.py::update_aircraft/_expire_locks`、`ops/economy.py::default_economy`。

### 36. 跑道信息改用游戏内数据（场景库优先）

- **落地**：
  1. `NavData(path, scenery_path=..., runway_source=auto|navdata|scenery)` 增加第二数据源（Little Navmap `little_navmap_msfs24.sqlite`）；`runways()` 命中场景库时返回 `source=scenery` 的几何并同步 `longest_runway_m`（影响「跑道够不够长」与 §26 翼展推断）；`navdata_runways()` 提供现实对照；`find_runway()` 带 `runway_source`/`width_m`。
  2. 设置新增 `scenery_navdata_path` + `runway_data_source`（默认 `auto`；未配置时探测 `%APPDATA%/ABarthel/little_navmap_db`，单测用 `AOC_NO_SCENERY=1` 关掉）；改这两项会重建 `NavData`。
  3. 接口：`GET /local/navdata/status` 透出 `scenery_path`/`scenery_available`/`runway_data_source`；`GET /local/airports/{icao}` 每条跑道带 `source` 与 `length_reference_m`（现实对照长度）。
  4. 数据/展示：`flight_record` 新增 `runway_length_m`/`runway_source`（老库自动补列、不回溯老记录）；`RunwayTouchdown` 在长度差 >5% 或 >100 m 时标「跑道长度 游戏内 X m / 现实 Y m（来源 …）」，日志详情加「跑道数据」行；设置页加路径与来源下拉。
- **背景**：WMKN 现实跑道 3480 m，游戏内只有 3060 m（差 420 m ≈12%）。AOC 用现实 navdata → 接地区俯视图的跑道长度、刻度、内移段、中线偏差全按 3480 m 画，接地点对不上；长度差还会影响「跑道够不够长」与翼展推断。
- **路线（D-7 改判）**：V-3 证明 SimConnect 设施 API 存在但字段名需官方 `FacilityDataDefinitionFlightsim.csv`（猜的名字全 `DATA_ERROR(20)`），而 LNM 从场景扫出的 msfs24 库 WMKN 正好 10,041 ft = 3060.5 m、入口与 navigraph 差 ~2.2 km → **场景库优先**，缺失回落 navdata，SimConnect 降为后续可选。兜底 C（手工覆盖表）见「1.4 遗留小项」。
- **测试**：`tests/test_landing.py::test_scenery_runway_geometry_preferred` / `::test_runway_data_source_navdata_ignores_scenery` / `::test_landing_metrics_carry_runway_source_and_length`。
- **关联**：§7（接地区俯视图）、§9（内移入口）、§16（跑道标志/宽度）、§26（跑道宽度→翼展）、`aoc_navdata/navdata.py::_load_runways_for/_runway_length_m/find_runway`、`aoc_core/landing.py`。

### 37. CI 的 Node 停在 20（已升到最新 LTS 26）

- **落地**：`.github/workflows/build.yml` 三处 `actions/setup-node` 的 `node-version` 由 `"20"` 改为 `"26"`（`test` / `app` / `portable` 作业；`test` 处留注释说明）；`docs/08` §4.7 的 `test` 作业说明补「Node 26（`setup-node`，LTS）」。前端代码零改动（Vite 6 / `@tauri-apps/cli` 2.x / TS 5.7 对 Node 26 无兼容问题）。
- **背景**：Node 20（Iron）已于 **2026-04** 结束 LTS 维护（末版 v20.20.2 / 2026-03-24），CI 还在用一个不再收安全更新的运行时打包产物；本机开发环境 Node 22 与 CI 也不一致，容易出现「本地过、CI 挂」。当前最新 **LTS 是 26（Lithium，2026-10-28 发布，v26.13.0）**，27 仍是 alpha。
- **取舍（D-8）**：选**最新 LTS 26**而不是 Current/alpha —— CI 要可复现、不追 nightly；同时不做「锁到 26.x.y 精确补丁」，`setup-node` 用 `"26"` 取该分支最新补丁。
- **待观察**：Node 26 首次上 CI 若出现原生依赖/打包差异，按「大版本升级」流程回退 24 或加 `engines` 约束（`apps/client/package.json` 目前**未声明** `engines`，本地 Node 22 仍可构建，所以暂不锁死下限）。
- **验证**：本地 Node v22.19.0 下 `npm run build`（`tsc --noEmit` + `vite build`）通过（3057 modules / 8.36s）；Node 26 的实跑结果待 CI 首跑确认。
- **关联**：`docs/08` §4.7（CI 构建）、`apps/client/package.json`（Vite 6 / Tauri CLI 2）。

---

## 三、已完成 · 2026-10-30（§23–§30）

> 细节见 `01` P-04/P-05/P-06/C-02/C-04、`02` §5.3/§7.4、`03` 接口表、`04` §2.2/§2.4/§2.5/§7.1、`07` §3、`09` §5-8、`10` §3。

### 23. 抽班不选军用机场

- `aoc_navdata` 读可选列 `is_military`（缺列按名称关键词 `AIR FORCE`/`AFB`/`AAF`/`NAVAL`/`ARMY`/`MILITARY`/`AB`），机场对象与 `AirportOut` 透出 `military`。
- `_airport_pool()` 丢掉军用机场（出发机场不拦）；抽班表单「不含军用机场」默认开（`exclude_military`）。

### 24. top3 候选不再雷同

- `candidate_score()` 重写：新机场按绝对数、亏损扣分、单段 balance 基准 0.6、单独给段数加分 → 478 min 亏钱单段不再压过 464 min 三段链。
- 遵循航线也按航线形状跨机去重；`_select_top()` 保证同机最多 1 条、形状互不相同；虚拟航段首段起飞时刻按飞机错开 0–120 min。

### 25. 虚拟航段随机航班号

- `_virtual_flight_number()` 用 `random.SystemRandom` 随机 3 位（最多 50 次），撞号退回顺序号、顺序号用满退回 uuid 后缀；同 roster 不复用、`(号, 起飞时刻)` 不冲突；不受抽班种子影响。

### 26. 翼展 / 跑道宽度

- `aircraft_type.wingspan_m`（内置机型真实值；0/留空按最短跑道推断 36/52/60.3/65 m），`TYPE_FIELDS`/校验/机型抽屉同步。
- `aoc_navdata` 读 `airport.longest_runway_width`（缺列时一次 `max(runway.width)` 分组），`max_wingspan_m` = <45 m → 36、45–60 m → 52、≥60 m → 80，无数据不限制。
- `_airport_pool()` 与 `_can_operate()` 加翼展过滤，`_no_candidate_reason()` 提示，候选卡片标「翼展上限 xx m（按跑道宽度推断）」；抽班表单「考虑跑道宽度（翼展）」默认开（`consider_wingspan`）。

### 27. 自动开录提前到发动机启动

- `auto_start_on = engine|taxi|takeoff`（默认 engine：发动机运转 10s；taxi：滑行 10s；takeoff 保留旧行为），随 `/status` 透出并由 core 下发。
- 预录改 1 Hz / 10 min 且**含地面帧**，`block_off` 取预录首帧、`_hasTakeoff` 由状态机在真正离地时置位。
- 发动机计时不随开录归零（未录制也累计，可从预录回溯），只有退化判定才 `engine_estimated=true`；`flight_record.engine_seconds` / `engine_estimated` 落库（老库自动补列），日志详情展示。
- demo 源改为 10s 起动发动机、起飞前滑行 12/25 kt，覆盖 `TAXI` 段。

### 28. 无任务录制的机型识别

- 建档优先级「任务上下文 → `aircraft_title` 匹配（自定义 `title_keyword` 优先，内置 `specs.TITLE_KEYWORDS` + ICAO）→ 设置默认机型」。
- 收尾的 `evaluate()` / `add_flown_leg()` 统一读记录里已存的机型，事后改「默认机型」不影响旧记录；日志详情显示 `aircraft_title`、发动机时间与已飞时间。
- 设置页「默认机型」说明改为「仅用于航路规划/推荐；录制按 SimLink 机型标题自动识别」。

### 29. 落地报告改成 report.html 版式

- 新增 `apps/client/src/components/TrendChart.tsx`（`AppendChart` 的 React 版：5 条网格、TD 竖线、2%–98% 分位裁剪、样本不足空态）与 `LandingReport.tsx`（报告头 + 落地行 + 卡片网格 + ALT/VS/G 三曲线 + TDZ；暗色 token 只作用在报告容器）。
- `LogDetail.tsx` 改「报告优先」：报告 → `TrackMap` → 「详细信息」折叠区（`Descriptions` / 事件表 / 备注），功能不删。
- `aoc_core/report_html.py` + `export?format=html`（`text/html`）：同版式单文件报告，内联 CSS/SVG、零外部依赖、无脚本；`main.py` 的 `media` 表加 `html`。

### 30. 落地后到机位才收尾

- 判据改为「连续静止（GS < 5kt）达到 `auto_stop_hold_s`（默认 60s，30–300 可调）」，或「停机刹车置位 30s」，或「停机刹车 + 发动机全部关车」；滑行中瞬时低速不再触发。
- `Sample.parking_brake` 映射 `BRAKE PARKING POSITION`（SimConnect → Sample → core `_norm_sample`）。
- core 自动收尾后补发 `stop_recording`；轮询到已 COMPLETED 的 `recording_id` 只忽略、不再 `assert`；收尾后的帧照常进日志，`block_on_utc` 取最后一帧。
- demo 源补滑入（落地后 15kt 滑行、中途停车 20s、到机位停稳 + 停机刹车 + 关车），回归断言 `block_on − landing ≥ 60s`。

---

## 四、已完成 · 2026-10-24 及更早（§1–§22）

### 1. 自由飞出发机场只允许「有可用飞机」的机场

- 后端 `GET /local/ops/free-flights/airports`：按机队当前位置去重，返回 `{icao, iata, name, city, country, lat, lon, aircraft}`。
- 领域层 `OpsService.free_airports()`：机队表位置字段是 `aircraft.current_airport_icao`（不是 `location_icao`），只统计 `ACTIVE` 且未锁的飞机。
- 前端 `OpsFreeFlight.tsx` 的出发机场改为该列表；`AirportSelect` 新增 `airports` 受限候选（本地过滤，不再远程搜全库），当前选择/基地不在列表时回落到第一座可用机场。
- 测试：`tests/test_ops.py::test_free_airports_only_lists_airports_with_available_aircraft`。

### 2. SimBrief 配载改用 `manualzfw`，呼号改 `airline` + `fltnum`

- `aoc_route/simbrief.py`：去掉 `payload`/`callsign`；`manualzfw = ZFW kg ÷ 1000`（保留 3 位小数，单位**吨**——原文「× 2.2046226 ÷ 1000 = 千磅」已由 §31 / V-2 证明是错的）；呼号按末尾数字拆成 `airline` + `fltnum`（`AOC101` → `airline=AOC&fltnum=101`），无末尾数字时只传 `airline`。
- 调用链：`RouteService.simbrief(..., zfw_kg=...)`、`PersonalService.simbrief_for_leg`（传配载单 `zfw_kg`）、`GET /local/routes/simbrief` 同步改为 `zfw_kg`。
- 测试：`tests/test_route.py::test_simbrief_splits_callsign` / `test_simbrief_uses_manualzfw`、`tests/test_ops.py::test_simbrief_preview_carries_frozen_payload`、`tools/ui_smoke.py` 断言 `manualzfw=` + `airline=`/`fltnum=`，且不含 `payload=`/`callsign=`/`pax=`/`cargo=`/`fuel=`/`fl=`。

### 3. 自由飞计划起飞时间（缺省 now + 50min）

- 后端 `create_free_flight`：`dep_time_utc` 缺省改为「领取时刻 + 50min」（`FREE_DEP_OFFSET_MINUTES`）。
- 前端 `OpsFreeFlight.tsx`：新增「计划起飞时间」（`DatePicker`，本地时区显示、提交转 UTC），默认 `当前时间 + 50min`；当前任务卡片展示计划起飞。
- 数据：沿用 `free_flight.dep_time_utc`，执行页 `task.scheduled_dep_utc` 不变。
- 测试：`tests/test_ops.py::test_free_flight_dep_time_defaults_to_now_plus_50min`。

### 4. 推出前 ZFW 低于配载单时提示

> §32 已将开录快照改为推出定稿；下表的 `actual_zfw_kg` 入参只有 demo/replay 源还走旧路径。

- SimLink 采样：`SimConnectSource.cs` 增加 `TOTAL WEIGHT`、`FUEL TOTAL QUANTITY WEIGHT`（磅 → kg）、`GENERAL ENG RPM:1..4`、`TURB ENG N1:1..4`、`ENG COMBUSTION:1..4`；`Sample` 增加 `total_weight_kg`、`fuel_weight_kg`、`eng_rpm[]`、`eng_n1[]`、`eng_combustion[]`；demo 源给模拟值。`FUEL TOTAL QUANTITY` 是体积，已不再当燃油重量用（`fuel_kg` 改由重量 SimVar 换算）。
- SimLink 新增 `GET /latest`（未开始记录也能取最新帧），`SimLinkClient.latest_sample()` 优先用它、退化到 `/samples` 末尾。
- `aoc-core`：`POST /local/ops/rosters/{id}/legs/{seq}/start`、`POST /local/ops/free-flights/{id}/start`、`POST /local/recording/start` 接受 `actual_zfw_kg`；低于配载单 `zfw_kg` 时返回 `warnings[]`（不阻断），差异写进任务与 `flight_record.actual_zfw_kg`/`zfw_delta_kg`（老库自动补列），并记 `zfw_check` 事件。
- 执行页：`GET /local/ops/flight-status` 提供 `actual_zfw_kg`（总重 − 燃油重量），点「开始记录」前偏低时 `Modal.confirm` 提示「可能漏装旅客/货物」，确认后继续；日志详情展示实际 ZFW 与差异。
- 测试：`tests/test_ops.py::test_start_leg_warns_when_actual_zfw_below_load_sheet`、`::test_start_free_flight_records_actual_zfw`、`::test_recording_start_persists_actual_zfw_and_timers`。

### 5. 执行页实时飞行状态（速度/高度/位置/ETE）

- 后端 `GET /local/ops/flight-status`：取 SimLink 最新采样，返回 `{gs_kt, ias_kt, alt_ft, agl_ft, lat, lon, vs_fpm, on_ground, phase, remaining_nm, ete_min, eta_utc, total_weight_kg, fuel_weight_kg, actual_zfw_kg, available}`。
- `remaining_nm` = 到到达机场的大圆距离；`ete_min = remaining_nm ÷ gs_kt × 60`；未起飞、地速 < 50kt 或采样缺失时为 `null`（界面「—」）。
- 前端 `OpsExecute.tsx`：每 2s 轮询展示地速/表速/高度/AGL/升降率/经纬度/剩余/ETE/ETA；无采样时提示检查 SimLink。
- 测试：`tests/test_api.py::test_ops_flight_status_and_free_airports`。

### 6. 执行页记录状态改为「发动机运转时间 / 已飞行时间」

- SimLink：`RecordingInfo` 增加 `engine_seconds`、`flight_seconds`、`engine_estimated`；按 `GENERAL ENG RPM:1..4 > 200` 判定运转，四台全部 < 200 持续 5s 停止累计（再启动继续累加），RPM 恒 0 时退回 `N1 > 20%` / `ENG COMBUSTION` 并标 `estimated`；模拟时间按 `sim_rate` 折算、暂停不计；已飞行时间 takeoff 起算、landing 冻结。
- 协议/核心：`aoc_protocol.schemas.RecordingStatus` 与 `FlightService.status()` 透传三个字段（只展示，不落库、不参与结算）。
- 前端：执行页「记录中」标签、顶部 Badge、Dashboard hero 全部改为 `发动机 HH:MM:SS · 已飞 HH:MM:SS`，不再显示采样点数。
- 测试/工具：`tests/test_ops.py` 录制用例断言字段存在且非负；`tools/smoke_m1.py`、`tools/smoke_m2.py` 改打印 `engine_s=`/`flight_s=`。

### 7. 飞行日志补「跑道接地区俯视图」

- 前端新增 `components/RunwayTouchdown.tsx`（SVG）：跑道轮廓/中线/入口、接地点、接地后滑跑轨迹、距入口/中心线偏移标注，横向按米放大并标注倍数。
- 数据：`GET /local/flights/{id}` 的 `touchdown_lat/lon`、`threshold_distance_m`、`centerline_offset_m`、`runway_ident`；`/track` 取接地后的点；`GET /local/airports/{arr_icao}` 的跑道几何新增 `lat`/`lon`/`elev_ft`（入口坐标 + 真航向 + 长度）。
- 兜底：无 navdata 或 `runway_ident` 为空/未匹配时显示「无跑道数据」，不影响主地图轨迹。
- 验收：`A-31`（落地后打开日志详情即见俯视图）。

### 8. 跑道窗口 10Hz 采样（`RUNWAY` 段）

- SimLink `Engine.cs::SaveSample`：新增 `InRunwayWindow()`——`OnGround && GsKt >= 40`，或 `!OnGround && AGL < 100ft`（无导航库，用它近似「距机场 < 5NM」），窗口内间隔 **0.1s**、不受 `_hz` 限制；起飞滑跑至离地、落地至 `GsKt < 40` 自然收尾。SimConnect 用 `SIM_FRAME` 逐帧回调，10Hz 有数据来源。
- 核心 `track.py`：新增 `MODE_RUNWAY` 与 `runway_window()`（同口径），`interval_s[RUNWAY]=0.1`，`select_saved()` 对 RUNWAY 段**逐点保存、不抽稀**；`TAXI` 仍只保留非跑道滑行（10s）。`detect_mode()` 把跑道窗口放在进近/转弯判定之前。
- **BIN_V2**：`dt` 由「整秒 1 字节」改成「0.1s 2 字节」（`<HiiiHHhHh`），否则 0.1s 采样时间戳全退化成 0；`write_chunks` 默认写 `BIN_V2`，`decode_points/decode_chunks` 按 chunk 的 `encoding` 兼容解码旧 `BIN_V1`。`track_profile.encoding` 与 `/track` 的 `encoding` 同步。
- 前端 `RunwayTouchdown.tsx`：滑跑线优先取 `mode === "RUNWAY"` 的点（至少 2 点），退化才用接地后全部点。
- 测试：`tests/test_track.py::test_runway_window_covers_roll_and_low_altitude` / `test_runway_segment_is_10hz_and_not_thinned`（10Hz、点间距 ≤8m、不抽稀）/ `test_bin_v2_keeps_sub_second_timestamps`；`tools/smoke_m1.py` 断言落地后存在 `RUNWAY` 段。
- 文档：`01` P-05/P-06/A-21、`02` §7.2/§7.4/§10.1、`03` §2。

### 9. 跑道内移入口（displaced threshold）

- `aoc_navdata/navdata.py::_load_runways`：按可选列读取 `runway_end.offset_threshold`，用「跑道两端坐标反推长度」的比例判断该库长度类字段是英尺还是米（`_raw_length_is_feet`），英尺 → 米；缺列/0/异常一律按 0。跑道对象新增 `displaced_threshold_m`，`length_m` 仍是物理长度。
- `aoc_core/landing.py`：`threshold_distance_m = along_m − displaced_threshold_m`（着陆入口 = 物理入口 + 内移），并回写 `displaced_threshold_m`。
- 数据/接口：`flight_record.displaced_threshold_m`（老库自动补列）、`/local/airports/{icao}` 的每条跑道带 `displaced_threshold_m`、`GET /local/flights/{id}` 透出同名字段；`nav.find_runway()` 返回值也带该字段。
- 前端 `RunwayTouchdown.tsx`：画物理跑道端、着陆入口、内移段（斜纹着色），刻度/「距入口」从着陆入口起算；内移为 0 时布局与之前一致。
- 测试：`tests/test_landing.py::test_displaced_threshold_read_from_navdata`（KJFK 31L ≈ 1000 m，物理长度不变）、`::test_missing_offset_column_falls_back_to_zero`、`::test_threshold_distance_measured_from_displaced_threshold`（接地在 1200 m → 距着陆入口 200 m）。

### 10. 无控制台启动 + 系统托盘图标

- Tauri 外壳 `apps/client/src-tauri/src/main.rs`：release 构建给 `aoc-core` / `aoc-simlink` 子进程加 `CREATE_NO_WINDOW`（`CommandExt::creation_flags`），stdout/stderr 重定向到 `%LOCALAPPDATA%/AOC/logs/core.log`、`simlink.log`；debug 构建保留控制台。
- 托盘：`tauri = { features = ["tray-icon"] }` + `TrayIconBuilder`（窗口图标 + tooltip），菜单「打开客户端 / 打开日志目录 / 退出」；左键点托盘聚焦窗口；退出时结束两个 sidecar。关闭主窗口改为 `prevent_close()` + `hide()`（最小化到托盘）。
- 单实例：启动时绑定固定回环端口作为实例锁，已有实例则直接退出，不重复起 sidecar。
- `apps/simlink/AocSimLink.csproj`：`<OutputType>WinExe</OutputType>`（自身不弹控制台；日志由父进程重定向）。
- 便携版：新增 `tools/portable-launcher`（`AOC-portable.exe`，纯 Win32 P/Invoke 托盘，**不依赖 WinForms/WPF**，自包含单文件约 14 MB）：无控制台拉起包内 `aoc-core.exe` + `aoc-simlink.exe`，健康检查（`/local/health`）通过后打开默认浏览器，菜单同上，命名互斥单实例，退出时结束子进程。子进程挂在 Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）上，启动器被任务管理器强杀也不会留残留进程；`Shell_NotifyIcon` 失败会写 `logs/launcher.log`（Win32 错误码）。
- 注意：`out/core/aoc-core/aoc-core.exe` 只是 API sidecar（无托盘、无界面），托盘在 `AOC-portable.exe` 与新构建的 Tauri 安装包里；Win11 默认把新托盘图标收进 `^` 溢出区。
- `tools/make_portable.py`：产物带 `AOC-portable.exe`，`start.bat`/`start.py` 保留为排障入口（会显示控制台，优先用包内 exe）。
- 顺带修掉冻结版的启动崩溃：`--noconsole` 下 `sys.stdout/stderr is None`，`uvicorn` 的 formatter 会 `AttributeError: 'NoneType' object has no attribute 'isatty'` 并以「Unable to configure formatter 'default'」退出；`main.py::_ensure_streams()` 先把它们接到 `logs/stdout.log`、`logs/stderr.log`。同时捕获 `KeyboardInterrupt` / 其它异常写日志退出，避免冻结版弹 traceback 对话框。
- 验证：`cargo check --offline`（含 tray-icon）通过；打包版 `aoc-core.exe` 实测 `/local/health` 0.5s 内 200、退出无残留。
- 人工验收：T-21 / A-32 通过（2026-10-24，安装版 + 便携版）。文档：`01` P-11/A-32、`02` §2.1/§13.1、`08` §2/T-01/T-05/T-21、`09` §1/§4/§5、`10` §5、`README` D-29。

### 11. 自包含打包（去掉 Python / .NET 依赖）

- 新增 `tools/build_core_exe.py`：PyInstaller `--noconsole --onedir`，`--paths` 带 `packages/*`，`--add-data data;data` 与 `Pre-train/src;Pre-train/src`，hidden import `numpy/scipy`、`--collect-submodules uvicorn`、`--collect-all tzdata`，并 `--exclude-module torch/pandas/PIL/matplotlib/...`（打包机上的无关大件）。产物 `out/core/aoc-core/aoc-core.exe`（onedir，**实测 134 MB**），参数不变（`--port --token --home --static-dir`）。`--verify` 跑一次 `aoc-core.exe --version/--help`（`--noconsole` 无 stdout，只看退出码与 `%TEMP%\aoc-core-probe.txt` 阶段标记；超时/非零时自动用 `--console` 版复现并打印真实报错，因为窗口化产物的未捕获异常会弹模态框把 CI 挂到超时）。
- 新增 `apps/aoc-core/entry.py`：冻结后先把 `AOC_ROOT` 指向 `_MEIPASS`，再调 `main.main()`；`main.py` / `aoc_core.service` / `aoc_route.graph` / `aoc_route.aip` 的 `ROOT` 改为「`AOC_ROOT` → 冻结 `_MEIPASS` → `__file__` 层级」三级解析。
- `apps/simlink`：发布命令改 `--self-contained true`（不要求 .NET 8）。
- `apps/client/src-tauri/tauri.conf.json`：`bundle.resources` 从 Python 源码改为 `{ "../dist": "client", "../../../out/core/aoc-core": "aoc-core", "simlink": ... }`；`main.rs` 增加 `resource_dir/aoc-core/aoc-core.exe` 启动分支（仍保留源码 python 回退给开发用）。
- `tools/make_portable.py`：打包 `aoc-core/` + 自包含 SimLink + `AOC-portable.exe`，不再复制 `packages/` 源码；`start.py` 优先起 exe。
- `tools/build.ps1`：新增 `aoc-core self-contained (PyInstaller)` 步骤（`-SkipCore` 可跳过），SimLink 改自包含，`-Clean` 清 `out/core`。
- 文档：`08` §2/§4.4/§4.4.1、`README` D-30。

### 12. GitHub Actions：云端编译与产物

- 新增 `.github/workflows/build.yml`：`windows-latest`，触发 `push`（main + tag `v*`）/`pull_request`/`workflow_dispatch`（`bundle=nsis|msi|both`、`make_release`），`concurrency` 去重，`timeout-minutes: 45`。
- 作业：`test`（ruff F,E9 + pytest + `npm ci && npm run build`（含 `tsc --noEmit`）+ `dotnet build`；PR 只跑它）→ `core`（`tools/build_core_exe.py --verify` → artifact `aoc-core-win64`）、`simlink`（自包含 publish → `aoc-simlink-win64`）→ `app`（下载两个产物到资源目录 + `dtolnay/rust-toolchain@stable` + `Swatinem/rust-cache` → `npm run tauri build -- --bundles ...` → `aoc-installers`）、`portable`（下载 core + 前端构建 → `tools/make_portable.py --no-core` → `aoc-portable-win64`）→ `release`（tag 或 `make_release` 时 `softprops/action-gh-release` 出草稿 Release）。
- 缓存：pip / npm / cargo（`apps/client/src-tauri`）/ NuGet；artifact `retention-days: 14`。
- 约束：navdata / `network.pkl` / SimBrief key 不进仓库与产物；签名等有证书再补。
- 文档：`08` §4.7「CI 构建」、`README` 构建状态徽章。

### 13. SimLink 自动重连（原「启动时模拟器未开启 → 不重试」）

- `apps/simlink/SimConnectSource.cs`：改为后台线程状态机「连接 → 收消息 → 断开 → 5s 退避重连」；`new SimConnect(...)` 失败、`OnRecvQuit`、`ReceiveMessage` 异常都只置 `sim_connected=false` 并重试，握手 10s 超时按失败处理；`Reconnect()` 可立即重试。
- `ISimSource` 增加 `Reconnect()` / `ReconnectAttempts` / `LastConnectError` / `ConnectionChanged`；`Engine` 在录制中把 `sim_connected` / `sim_disconnected` 写进事件流；`RecordingInfo` 与 `/local/simlink/status` 透出 `reconnect_attempts` / `last_connect_error`；`POST /command {action:"reconnect"}` + `POST /local/simlink/reconnect`，设置页「重新连接」。
- 验收（实机）：先开 AOC 再开 MSFS，`sim_connected` 10s 内自动 `true`；飞行中退出再进能自动恢复 → 复测项见 1.2。
- 文档：`09` §5-12、`08` §3.3、`02` §7.2。

### 14. 自定义机型模板（原「允许玩家自己添加飞机数据」）

- `aircraft_type` 新增 `source`（`BUILTIN`/`CUSTOM`）、`builtin_key`、`title_keyword`（老库自动补列）；内置模板标记 `BUILTIN`，`GET` 带 `source`。
- `POST/PATCH/DELETE /local/ops/aircraft-types`：`CUSTOM` 可增/改/删；`BUILTIN` 改删返回 `BUILTIN_TYPE_READONLY`（只能「复制为自定义」）；被机队/班期/未完成实例引用时 `AIRCRAFT_TYPE_IN_USE`。
- 校验：`0 < OEW < MZFW ≤ MTOW`、`MLW ≤ MTOW`、座位数 = 客舱构型合计、油耗 > 0、`cruise_speed_kt` 60–600、`min_runway_m` 0–5000、`range_nm` 1–20000 等，越界 `PARAM_OUT_OF_RANGE`（`details.key` 供前端就地高亮）。
- 生效面：`generate_load_sheet` / `estimate_block_minutes` / 推荐 / 异常策略 / 结算成本都读同一张表；`CUSTOM` 机型在班期无同名机型时允许「机型替换」（跑道/航程过滤）；新增飞机可留空机型按 `title_keyword` 匹配 SimLink `aircraft_title`；档案 zip 带整库（含 `CUSTOM`）。
- 前端：机队页「机型模板」抽屉（列表 + 新增 + 复制 + 编辑 + 停用 + 删除），新增飞机的机型下拉随即刷新。
- 测试：`tests/test_ops.py::test_custom_aircraft_type_feeds_loadsheet_and_settlement` / `::test_custom_type_rejects_invalid_weights` / `::test_delete_custom_type_blocked_when_in_fleet` / `::test_builtin_type_copy_to_custom`；`tools/ui_smoke.py` 断言接口里存在 `CUSTOM`、抽屉可打开。
- 文档：`01` C-02 注、`04` §7.1、`10` §1/§3。

### 15. 右上角航班信息跳「配载与执行」

- `OpsFly.tsx`：页签先读 `?tab=`（`roster|free|execute`）再回退路径，最后兜底 `roster`；切换页签跳规范路径（`/ops/roster|free|execute`），查询参数随之清掉。
- `ops.ts::opsStateMeta`：`FLIGHT`、`GROUND` 且有任务、按钮上已有呼号/起降 → `/ops/execute`；完全没有航班信息 → `/ops/roster`。
- 测试：`tools/ui_smoke.py` 点状态条后断言 URL `/ops/execute` + 页签高亮，再切「抽班」「自由飞行」校验 URL，并验证 `/ops/fly?tab=execute` 深链。
- 文档：`10` §3。

### 16. 跑道接地区俯视图补跑道标志

- `RunwayTouchdown.tsx`：跑道编号、入口条纹（8 条）、接地区（TDZ）条纹、900 ft 瞄准点、中线（着陆入口实线 + 其余虚线）、自着陆入口起每 300 m 刻度与米数、末端总长、100 m 比例尺与图例（蓝线=滑跑、红点=接地点、斜纹=内移段）；横向放大倍数照旧标注。
- 宽度：`aoc_navdata` 读取 `runway.width`（英尺/米自动校准，越界回 `None`），`/local/airports/{icao}` 带 `width_m`；缺失时视图按 45 m 兜底。
- 测试：`tools/ui_smoke.py` 断言跑道 SVG 含 `18`、`300 m`、`100 m`。
- 文档：`09` §5-8/§5-10、`01` P-06。

### 17. SimLink 未连模拟器的三态提示

- 状态链路：`recording.sim_connected` / `simlink_source` / `last_connect_error` 透传到 `/local/health`、`/local/recording/status`、`/local/simlink/status`。
- 前端 `simlink.ts::simlinkState()` 三态：「SimLink 未运行」（灰）/「SimLink 在运行 · 模拟器未连接」（橙）/「已连接模拟器（demo/replay）」（绿），tooltip 带 `source`；首页与执行页共用 `components/SimlinkNotice.tsx`（排查步骤 + 原始错误 + 打开日志目录，`POST /local/system/open-logs`）。
- 拦截：`POST /local/recording/start` 在 `sim_connected=false` 且 `source=simconnect` 时返回 `warnings[]`（不阻断）；执行页「开始记录」先 `Modal.confirm`。
- 测试：`tests/test_api.py::test_health_reports_simlink_disconnected` / `::test_recording_start_warns_without_sim_connection` / `::test_ui_pulse_and_simlink_reconnect`。
- 文档：`01` P-10、`09` §5-12、`08` §3.3、`10` §3。

### 18. 结算详情标题不再显示 `— ????→????`

- `OpsService.settlement()` 平铺 `callsign/dep_icao/arr_icao/block_off_utc/block_minutes/touchdown_vs_fpm/landing_rating`（与列表接口同名字段），嵌套 `flight` 保留。
- `settlementTitle()` 兼容平铺与嵌套、无呼号只显示 `DEP→ARR`、全缺显示「未知航班」（`OpsReview` 复用同函数）。
- 测试：`tests/test_api.py::test_settlement_detail_flattens_flight_fields`；`tools/ui_smoke.py` 点开一条结算断言标题不含 `????`。
- 文档：`10` §3。

### 19. 抽班「不遵循航线 / 排除机场 / 每程航时」

- `CONSTRAINT_LIMITS` 增加 `min/max_leg_block_minutes`（5–1440 / 10–1440）；`min > max` 返回 `PARAM_OUT_OF_RANGE`；`_build_chains` 对单段 block 做区间过滤（`max_block_minutes` 仍是合计）。
- `follow_routes: false`：`_airport_pool()` 从 navdata 机场库按机型 `range_nm × 0.9` / `min_runway_m` / 航时过滤并随机化，`_virtual_chains()` 拼链；候选标 `virtual`，token 带 `virtual_legs`，**确认时**才落一次性 `flight_instance`（`mission_type=FREE`，航班号按航班表内唯一），取消/过期作废不回池。
- `excluded_airports`：`_available_instances` 与 `_build_chains` 都过滤（中转也算）；`draw()` 返回 `follow_routes` / `excluded_airports` / 无候选 `reason`。
- 前端：抽班表单加「遵循航线」「排除机场」（多选远程搜索 + 「填入最近去过」）、每程最短/最长航时（就地校验），候选卡片标「虚拟航段」/「已排除 N 个机场」。
- 测试：`tests/test_ops.py::test_draw_ignores_routes_when_disabled` / `::test_draw_excludes_airports` / `::test_draw_respects_per_leg_block_range` / `::test_draw_min_leg_block_greater_than_max_rejected` / `::test_draw_follow_routes_keeps_legacy_behaviour`。
- 文档：`01` C-04、`04` §2.2/§2.4、`10` §1/§3。

### 20. SimLink 内存（D-26）

- `AocSimLink.csproj`：`ServerGarbageCollection=false` + 并发 GC（Web SDK 默认 Server GC）。
- `SimConnectSource`：平时 `SIMCONNECT_PERIOD.SECOND`，跑道窗口（`Engine.InRunwayWindow`）临时切 `SIM_FRAME`；切换失败不影响采样。
- `Engine`：`_samples` 只保留最近 2 万点（`Samples()` 按 `Seq` 二分）、预录帧 5Hz、逐点写盘改 `Utf8JsonWriter` + 复用缓冲写 `FileStream`（不再每点分配字符串）。
- 工具：`tools/simlink_mem_probe.py`（WS/PM + `/status` 采样点，CSV + 趋势/峰值摘要）；低配机复核见 1.3。
- 文档：`02` §7.2/§7.4/§10.1.1、`08` T-09、`09` §5-12。

### 21. aoc-core 空闲 CPU（D-27）

- `Database`：每线程常驻连接 + 可重入事务（最外层提交），不再每请求 open/close；导入档案改用 `restore_from()`（SQLite 备份 API）。
- `_poll_loop` 自适应（录制/连上 1s、未连模拟器 2s、失败 5→15s、无 SimLink 15s）；`_watch_simlink` 5s + mtime；`/local/ops/status` 在 HTTP 层 1s TTL；新增 `/local/ui/pulse` 合并前端两条轮询，`document.hidden` 暂停；uvicorn 关 access log。
- 工具：`tools/core_cpu_probe.py`（Get-Process CPU 增量 → 单核 %，CSV + 均值/峰值）。
- 文档：`02` §10.1.1、`08` T-09。

### 22. aoc-core 空闲 CPU 2s 尖峰（D-27 残留）

- 根因：`aoc_core/simlink.py` 每个请求都 `httpx.AsyncClient(...)` 上下文管理器新建客户端；Windows 上构造会重建 SSL 上下文，实测 **约 0.54s CPU/次**（`verify=False` 则 0.0007s），而 `_poll_loop` 在「SimLink 在跑但没连模拟器」档是 2s、录制/连上是 1s，`/local/ops/flight-status` 又是 2s → 周期尖峰与常驻高 CPU。不是 `_cached_ops_status()`（实测 `ops_status()` 仅 0.10ms）。
- 修法：`SimLinkClient` 复用一条客户端（同事件循环；换 loop 或已关闭时重建），`aclose()` 在 `PersonalService.close()` / `set_simlink()` 换配置时调用（旧客户端延后关闭，无循环时交给 GC）。
- 轮询：未连模拟器档 2s → `POLL_SLOW_S`（5s，仍满足「先开 AOC 再开 MSFS，10s 内 `sim_connected=true`」）。
- 前端 `App.tsx`：`/local/ui/pulse` 改为自适应——有任务/录制中 2s、空闲 5s，`document.hidden` 暂停、切回前台立即补一次（原来固定 2s）。
- 实测（Windows 11，源码运行，SimLink 在跑未连模拟器、无前端页面，`tools/core_cpu_probe.py --interval 1 --minutes 5`）：修复前 2 分钟平均 **19.9%**、峰值 48.3%；修复后 5 分钟平均 **0.130%**、峰值 1.378%（单核，已低于 D-27 的 0.3%），CSV 时间线上非零样本不再按 2s 周期出现。
- 顺带修 `tools/core_cpu_probe.py` / `tools/simlink_mem_probe.py`：PowerShell 脚本里的 `{0}` 占位与 `str.format(pid=...)` 冲突，探针一启动就 `IndexError`，改 `__PID__` 替换。
- 验证：`tests/test_api.py::test_simlink_client_reuses_connection` / `::test_poll_interval_backs_off_when_sim_not_connected`；`tools/smoke_m1.py`（demo 录制端到端）通过；`pytest` 全绿、`ruff F,E9` 通过。
- 文档：`02` §10.1.1、`03` §接口表、`08` T-09、`10` §3。

---

## 五、已完成 · 2026-11-04（§38–§40）

> 三件事都是「规则/判据在跑，但输入漏了」：§38 数据 + 覆盖范围、§39 触发输入、§40 两套算法口径。
> 测试：`pytest` 172 项、`ruff F,E9`、`tsc --noEmit` + `npm run build`、`dotnet build` 全绿。

### 38. 抽班翼展规则的三处漏洞（CYXY 放行 A359）

- **背景**：A359 抽班（`follow_routes=false`、`consider_wingspan=true`）出现 CYXY（最长跑道 2895.6 m ≥ `min_runway_m` 2400 不拦、宽 45.1 m → 上限 52 m）。规则代码在跑，根因是**老库数据没刷新** + **遵循航线分支没校验**。
- **落地**：
  1. **P0 老库翼展同步**：`specs.builtin_wingspans()` 与 `build_aircraft_types()` 同源给真值；`_seed_types()` 末尾调 `_sync_builtin_wingspans()`，只覆盖 `source='BUILTIN'` 的行（`CUSTOM` 不动），`ops_meta.wingspan_sync=v1` 只跑一次（改口径时提升版本号即可重跑）。同时把 `WINGSPAN_OVERRIDES` 补全到目录里全部机型（B763 47.6 / B772 60.9 / B78X 60.1 / A339 64.0 / B744 64.4、A20N/A21N/B737 35.8、CRJ7/E170/E75L/DH8D/SF34 与公务机…），新建库的 wide 兜底 65 m 也不再误伤 767。
  2. **P1 遵循航线也查跑道**：抽出 `_runway_operable()`（到达跑道够长 + 翼展 ≤ `max_wingspan_m`），`_can_operate()`（机型替换，另含航程）复用它；`_build_chains()` 在「班期机型 == 飞机机型」分支也调它（受 `consider_wingspan` 控制，关掉回旧行为），被挡的航段计入 `_runway_blocked`，`_no_candidate_reason()` 显示「N 个航段的目的地跑道不够长/不够宽」。放宽阶梯仍只放开航时，不放开翼展/跑道。
  3. **P2 重置入口**：`OpsService.reset_type_wingspan()` + `POST /local/ops/aircraft-types/{id}/reset-wingspan`（写审计 `TYPE_WINGSPAN_FIX`；`CUSTOM` 本来就能直接编辑，这里返回 `INVALID_STATE`），机型模板抽屉加「翼展」列与「重置翼展」按钮 —— 内置行仍只读（选方案 ②，不需要额外的 `wingspan_source` 字段）。
- **测试**：`tests/test_ops.py::test_old_builtin_wingspan_is_synced_once`（模拟老库 52/60.3 → 64.8/79.8，`CUSTOM` 不动，已同步不再覆盖）、`::test_reset_builtin_wingspan_restores_truth_and_audits`、`::test_follow_routes_checks_destination_runway`（A359 + 45 m 跑道抽不到、B738 正常、关掉开关回旧行为）；§26 的 `test_draw_respects_runway_width_for_wingspan` / `test_missing_width_column_means_no_limit` 仍绿。
- **关联**：§26（翼展/跑道宽度）、§36（场景库跑道影响 `max_wingspan_m`）、§23（同一处军用机场过滤）、§34（放宽阶梯）、`ops/specs.py::builtin_wingspans/WINGSPAN_OVERRIDES`、`ops/service.py::_sync_builtin_wingspans/_seed_types/_runway_operable/_build_chains/_no_candidate_reason`。

### 39. 发动机启动即视为「已推出」

- **落地（`apps/simlink/Engine.cs`）**：
  1. `TrackPushback()` 拆成「判据 + 定稿」：第一判据是**发动机启动上升沿**满 `AutoStartHoldS`（10s）且 `OnGround && !_hasTakeoff` → `pushback_source=engine`；地速分支（GS ≥ 5kt 连续 3s）保留为兜底 → `pushback_source=gs`（旧值 `pushback` 由 core 的 `_pushback_source()` 按别名映射到 `gs`）。
  2. 定稿语义不变（`FinalizePushback()`）：近 5 帧中位数、相邻帧跳变 >10% 重新起表、`_pushbackZfw != null` 后不再覆盖；`pushback` 事件加 `source`。
  3. 只认上升沿：`OnConnectionChanged()` 重新点亮的是「接入时就在转」（`_engineOnFromConnect`），进程第一帧就看到发动机在转同样按接入处理；瞬移重置也把该标记置成当前状态 —— 这几种都不产生 `engine` 快照，仍走 `start` / `gs`。
  4. 开录不再清 `_engineOnSince`（自动开录本身就是「发动机运转 10s」触发的，清掉的话 engine 分支永远等不到）；每段录制仍在 `StartRecording` 清 `_pushback*`，`StopLocked` / 瞬移照旧清空。
  5. 协议/展示：`pushback_source` 枚举写清 `engine|gs|start`（`aoc_protocol/schemas.py`），`/local/ops/flight-status` 的 `zfw_source` 透传，执行页「实际 ZFW（推出后定稿）」按来源打标签（发动机启动 / 地速推出 / 开录首帧 / 推出前临时值）。
- **风险（已知并保留）**：怠速等货先点火 → 定稿值偏低，靠 10% 跳变重起表缓解；快照落定后再装货不会更新。
- **测试**：`tests/test_ops.py::test_pushback_source_accepts_legacy_alias`（老值别名）；`dotnet build` 通过。实机五项验收见 1.1.2。
- **关联**：§27（自动开录同一条沿）、§32（推出定稿只换触发输入）、§33（位置闸 / 瞬移重置 / 重连点亮发动机）、V-5、`aoc_core/service.py::_pushback_source/flight_status`。

### 40. 实际 ZFW 与配载单一致时显示「-0 kg」

- **落地**：
  1. `ops/service.py::zfw_check()` 归一化：`abs(delta) < 0.5 kg` 直接归 `0.0`（`round(x, 1)` 出来的 `-0.0` 一并折成 `+0.0`），且 `delta > -1 kg` 不再发「偏低」警告（与 `zfw_state` 的 ±1 kg 同一阈值）。
  2. `/local/ops/flight-status` 新增 `zfw_delta_kg`，与 `zfw_state` 用同一个 `zfw_check()` 算；前端不再自己相减。
  3. 前端 `utils.ts::fmtSignedKg(delta, digits=0)`：按显示精度先归零，输出 `0 kg` / `+300 kg` / `-5,000 kg`，永不出现 `-0`。执行页「差异」与日志详情「实际 ZFW（…）」都走它。
- **背景**：执行页原来自己算 `num(actual - planned)`，`toLocaleString` 把 -0.4 舍成 `"-0"`；后端同一份数据判 `ok`，两边口径不一致。差异本身来自 SimLink `TotalWeight − FuelWeight` 的浮点求和（0.1–0.5 kg）。
- **测试**：`tests/test_ops.py::test_zfw_check_zeroes_float_noise`、`::test_flight_status_reports_normalized_zfw_delta`（±0.4 → `0 kg`/`ok`，-5000 → `short`）、`tests/test_api.py::test_ops_flight_status_and_free_airports` 断言新字段；`tsc --noEmit` + `npm run build` 通过。
- **关联**：§32、C-08（推出前只提示不阻断）、`apps/client/src/pages/ops/OpsExecute.tsx`、`apps/client/src/pages/LogDetail.tsx`、`aoc_core/ops/service.py::zfw_check`、`aoc_core/service.py::flight_status`。

---

## 六、已完成 · 2026-11-05（§41）

> 一类「规则都在跑，但先后顺序没人管」的链路：SimLink 自动开录早于「开始本段」，于是整段飞行落成 `mode=PERSONAL`，班表航段永远 `IN_PROGRESS`，而且**全程没有任何报错**。
> 测试：`pytest` 175 项、`ruff F,E9`、`tsc --noEmit` + `npm run build` 全绿（本次未改 C#）。

### 41. 班表航段没记上（自动开录抢先建档 → 整段变成个人/自由飞行）

- **现场（2026-11-05，A359 `B-1090`，班表 `fcf5e5cd` 第 3 段 KAMA→KEWR / OVO517）**：
  - 日志 `61dd0092`：`mode=PERSONAL`、呼号 `AOC001`、`roster_leg_id=NULL`、`created_at=block_off_utc=2026-11-05T10:16:59Z`、`block_off_source=preroll`、`late_join=0`（10:48 起飞 / 13:42 落地 / 210 min）。
  - `ops_audit` 里 `LEG_START` 只有一条，时间 **10:25:11Z** —— 比开录晚 **8 分 12 秒**；`start_leg` 写进 `roster_leg.flight_record_id` 的 `c0907318` 在 `flight_record` 表里**根本不存在**。
  - 连带卡死：`roster`/`roster_leg` 停在 `IN_PROGRESS`（`expires_at` 已过 1 天）、`flight_instance` 停在 `STARTED`、`B-1090` 停在 `KAMA`+`IN_FLIGHT`（真实在 KEWR）、`ops_active_task` 还挂着已飞完的任务。
  - 执行页的表现：记录 id ≠ 任务 id → 一直显示「开始记录」，点了也没用（`FlightService.start()` 直接返回旧状态）。
- **根因（三处叠加，任缺一处都不会发生）**：
  1. **SimLink 先自动开录**：§27/§39 的自动开录在「发动机运转 10s」就触发，此时 `ops_context()` 为空 → `FlightService.start()` 建 `mode=PERSONAL` + 默认呼号（`flights.py:470-503`）。
  2. **`FlightService.start()` 没有改绑通路**：`if self.recorder is not None: return self.status()`（`flights.py:439`），之后点「开始记录」也调不动。
  3. **`start_leg()` 不校验「已在录制」**：只查 `active_task()` / 航段状态 / 飞机位置（`ops/service.py`），航段照样置 `IN_PROGRESS`；收尾时 `on_flight_finalized()` 发现 `flight_record_id` 与任务不符就 `return None` → 不结算、不更新机队位置、不清任务。
  4. **次因**：`start_leg()` 不校验 `roster.expires_at`（11-03 抽的班表 11-05 还能开始）；`_expire_locks()` 只过期 `LOCKED` 班表。
- **落地（D-9：无主录制改绑，而不是一律拒绝）**：
  1. `OpsService._live_recording()`：以 `app_setting.active_recording`（`FlightService` 持久化指针）+ `flight_record.status='RECORDING'` 双条件判断「真的在录」，崩溃/强杀残留的 `RECORDING` 行不会被误判。
  2. `_unbound_recording()`：再判「没绑任何任务」——`roster_leg.flight_record_id`、`flight_instance_id`、`_task_for_flight()` 全空才算无主。
  3. `start_leg` / `start_free_flight`：无主 → **沿用原 `flight_id` 改绑**（`mode` → `ROSTER`/`FREE`，补 `roster_leg_id`/`flight_instance_id`/`aircraft_id`/`callsign`/`dep`/`arr`/`mission_type`/`scheduled_dep_utc`），`block_off` 保持真实推出时刻，配载单与经济快照照常固化，返回 `adopted_recording=true` + `warnings[]`，审计 `LEG_ADOPT_RECORDING` / `FREE_FLIGHT_ADOPT_RECORDING`；**已绑别的任务 → `RECORDING_IN_PROGRESS`（409）**。
  4. `PersonalService.start_recording()`：任务已开始但活跃记录 id 与任务不符 → `RECORDING_IN_PROGRESS`，不再静默返回旧状态。
  5. 班表过期：`status=LOCKED`（首段）且 `expires_at < now` → `ROSTER_EXPIRED`（409）；`IN_PROGRESS` 超窗只给 `warnings[]`，不阻断后续航段。
  6. 前端：`OpsRoster.startLeg()` 有录制时先 `Modal.confirm`（会改绑、含起飞前已录部分）并逐条展示 `warnings[]`；`OpsExecute` 在「记录 id ≠ 任务 id」时显示「有一条记录在录制，但没有绑定到本航段」。
  7. 新错误码进 `main.py::OPS_CONFLICT`（409）；接口表 `docs/03` 的 `legs/{seq}/start`、`free-flights/{id}/start` 同步。
- **数据修复（这一班，已执行）**：`void` 第 3 段 → 用新的改绑逻辑重新绑定真实记录 `61dd0092` → 走正式 `settle_flight()`。结果：航段/班表 `COMPLETED`、`B-1090` → `KEWR`+`ACTIVE`（11.4 h / 12 cycles）、任务 `finished`、`active_recording` 清空、结算 `SETTLED`（收入 63,742.92 / 成本 64,193.65 / 利润 **−450.73**，1.5 天晚到按策略扣分）。改前备份 `backups/aoc-before-s41-20261105-142449.db`。
- **测试**：`tests/test_ops.py::test_start_leg_adopts_auto_recording`（改绑后照常结算到本段）、`::test_start_leg_rejects_recording_bound_to_other_task`、`::test_start_leg_rejects_expired_roster`。
- **取舍**：不采用「一律拒绝」——先推飞机再点「开始本段」是常见顺序，拒绝只会让人白飞；也不做「在自动开录时自动绑定」（分不清玩家是在飞自由飞还是班表）。只在「无主的 PERSONAL 记录」这一确定态上改绑，其余情况明确报错。
- **残余（见 §42）**：实机复测 3 条、陈旧 `IN_PROGRESS` 班表清理、改绑时回填推出 ZFW、卡死恢复入口。
- **关联**：§27（自动开录提前到发动机启动）、§32（ZFW 定稿依赖 task 上下文）、§33（位置闸 / 记录与任务绑定）、§35（快速调机改位置）、`flights.py::start/ingest`、`ops/service.py::start_leg/start_free_flight/on_flight_finalized/_expire_locks`、`apps/client/src/pages/ops/OpsRoster.tsx`、`apps/client/src/pages/ops/OpsExecute.tsx`。

---

## 七、已完成 · 2026-11-06（§42–§45）

> 批次顺序：先把「卡死 / 丢数据」的后端遗留收口（§42、§43），再按 D-10 / D-11 已拍口径落地前端 P0 与结构性合并（§44、§45）。
> 测试：`pytest`（186 项，新增 11 项）、`ruff F,E9`、`tsc --noEmit` + `npm run build` 全绿；本次未改 C#。

### 42. §41 三项遗留（陈旧班表清理 / 改绑回填推出 ZFW / 卡死恢复入口）

- **落地**：
  1. **陈旧班表清理**：`_expire_locks()` 调 `_close_stale_rosters()` —— 条件是「`IN_PROGRESS` + `expires_at` 已过 + 一段都没 `COMPLETED` + 无活跃录制绑在它的航段上 + 无活动任务属于它」。命中后 `roster` → `EXPIRED`、待执行/执行中航段 → `CANCELLED`、实例回 `SCHEDULED`、锁 `EXPIRED`、飞机回 `ACTIVE`；**不收费、不记失约、不动机队位置**，审计 `ROSTER_STALE_EXPIRE`。
  2. **改绑回填推出 ZFW**：`OpsService.pushback_provider`（`PersonalService._pushback_snapshot` 注入：`flights.zfw_at_pushback` / `fuel_at_pushback` / `pushback_source`）；`start_leg` / `start_free_flight` 改绑时以它为 `actual_zfw` 来源，写 `actual_zfw_kg` / `zfw_delta_kg` / `fuel_start_kg`，补一条 `final=true` 的 `zfw_check`（`adopted_from_pushback`），并在 `warnings[]` 里说明；任务带 `zfw_source` / `zfw_final`。`flights._finalize()` 在内存快照缺失时回落记录里的 `fuel_start_kg`。
  3. **卡死恢复入口**：`POST /local/ops/tasks/recover`（`PersonalService.recover_stuck` → `OpsService.recover_task`）—— 先停掉「不属于当前任务」的录制（`abort=True`），再把 `IN_PROGRESS` 且未结算的航段退回 `PLANNED`、实例回 `SCHEDULED`、释放锁并把飞机状态放回 `ACTIVE`，**位置保持现状**（不像 `void` 写回出发机场）；审计 `TASK_RECOVER`（带 `keep_position` 与 `flight_record_id`）。
- **背景**：§41 现场留下的三个尾巴 —— ① 窗口已过又无录制/任务的 `IN_PROGRESS` 班表永远卡住（`test_a27` 又明确要求「有已完成航段的中途班表不过期」，所以规则收窄到「一段未完成」）；② 推出常发生在点「开始本段」之前，`set_actual_zfw()` 当时没有活动任务直接返回，定稿值丢失只能退回配载单；③ 唯一的解开手段 `void` 会把飞机位置写回出发机场，与真实位置（已落地别的机场）冲突，且对「记录没绑上」的卡死无能为力。
- **取舍**：不把「有已完成航段的中途班表」也自动收尾 —— 玩家可能在跨天分段飞，机械收尾会吞掉余下航段；这类仍由「取消班表」或新的 `recover` 人工处置。`recover` 也不冲销账本（该段本来就没结算）。
- **测试**：`tests/test_ops.py::test_stale_in_progress_roster_is_closed_without_penalty` / `::test_partial_roster_with_completed_leg_is_not_auto_closed` / `::test_start_leg_adopt_backfills_pushback_zfw_and_fuel` / `::test_recover_task_keeps_aircraft_position`。
- **前端**：执行页在「有录制但没绑到本航段」的警告里加「一键解除」（带 Popconfirm 说明位置保持现状）。
- **关联**：§41（改绑 / 过期拦截）、§32（推出定稿）、§33（位置闸与 `void`）、`ops/service.py::_close_stale_rosters/recover_task/start_leg/start_free_flight/set_actual_zfw`、`flights.py::_finalize`、`service.py::recover_stuck`。

### 43. 原 `1.4` 三项遗留（手工跑道覆盖表 / 位置字段收口 / 推出后配载变更）

- **落地**：
  1. **§36 兜底 C**：`ops/schema.py` 新增 `airport_runway_override(icao, ident, length_m, width_m, threshold_lat/lon, hdg, updated_at)`；`NavData.set_runway_overrides()` 在 `runways()` 结果上合并（命中行 `source=override`，未命中的跑道号追加），并同步机场的 `longest_runway_m` / `runway_width_m` / `max_wingspan_m`；删除覆盖时按备份还原（切换 navdata 也不留脏值）。接口 `GET /local/navdata/runway-overrides`、`PUT/DELETE .../{icao}/{ident}`（越界 `PARAM_OUT_OF_RANGE`，写审计 `RUNWAY_OVERRIDE_SET/DELETE`）；设置页新增「修正跑道数据」卡片（机场/跑道号/长度/宽度/真航向/入口经纬度 + 列表删除）。
  2. **§35 收口**：`update_aircraft` 不再接受裸 `current_airport_icao`（422，`details.key=current_airport_icao`）；带 `force=true` 才写入并补 `AIRCRAFT_FIX_POSITION` 审计（before/after）。
  3. **§32 边界**：`set_actual_zfw(final=True)` 若该任务已定稿且新值差 `> 1000 kg`（`ZFW_CHANGE_ALERT_KG`），**不覆盖** `flight_record` 的值，只写 `zfw_changed_after_pushback` 事件（`previous_kg` / `actual_kg` / `delta_kg` / `source`）。
- **背景**：三者都是「写路径没闸」的小口子：跑道几何只能靠场景库/navdata（add-on 机场无处修正）；位置字段可被免费瞬移且无审计；推出定稿后再动配载会静默改写记录值，人工事后无法还原。
- **测试**：`tests/test_ops.py::test_runway_override_takes_priority_and_can_be_removed` / `::test_update_aircraft_position_requires_force_and_audits` / `::test_zfw_change_after_pushback_is_logged_not_overwritten`。
- **关联**：§36（跑道数据源）、§35（快速调机）、§32（推出定稿）、`aoc_navdata/navdata.py::set_runway_overrides/_with_overrides`、`ops/service.py::runway_overrides/set_runway_override/update_aircraft/set_actual_zfw`、`components/RunwayOverrideCard.tsx`。

### 44. `9.1` 的 P0 前端问题（`UI-01`–`UI-06`）

- **落地**：
  1. **UI-01**：抽班与确认分工 —— `draw()` 只生成候选（不落库/不锁机，**确认前可一直重抽**）；`confirm_roster()` 已有 `LOCKED/IN_PROGRESS` 班表 → 409 `ROSTER_EXISTS`（`details.roster_id/status`，进 `OPS_CONFLICT`）。`OpsRoster` 的「抽班/重抽」按钮始终可用（`LOCKED` 时文案「重抽（替换当前班表）」），`IN_PROGRESS` 时置灰提示「先飞完或取消」，合并页同样有入口。
  2. **UI-02**：`flight_record` 新增 `data_source`（开录时写 `SimLink` 的 `source`；老库自动补列、老记录为 NULL）；日志详情改用 `flight.data_source`，不再读当前会话的 `recording.simlink_source`。
  3. **UI-03**：`LogDetail.load()` 先单独取 `flight`（失败 → 错误态 + 重试），`track` 与机场详情各自 try/catch 降级；接口出错不再显示「记录不存在」。
  4. **UI-04**：成本行改为 `money(-Math.abs(amount))`（不再 `--$…`）；抽屉里的状态/策略用与列表相同的 `settlementStatus` / `policyAction` 本地化 Tag。
  5. **UI-05**：`styles.css` 补 `.text-danger`（`#ef4444` + 600）。
  6. **UI-06**：`WorldMap` 用单个 `popupRef`（开新弹窗先关旧的、数据/筛选变化与卸载时关闭）；弹窗里的「规划航路」改成 `onPlanRoute` 按钮回调，去掉 `<a href>`；点击空白同时关弹窗与清筛选。
- **背景**：见「九、9.1」对应条目的现象记录；六条都会让用户当成「功能坏了」（重复锁机、数据源误导、把接口错误报成数据不存在、金额多一个负号、提示不生效、弹窗叠屏/跳出应用）。
- **口径修订（2026-11-06）**：初版把拦截放在 `draw()`，与「确认前可以一直重抽」冲突 —— 已按新口径改为「`draw()` 不拦、`confirm_roster()` 拦」，代码与测试同步完成，详见 §46。
- **测试**：`tests/test_ops.py::test_confirm_rejects_when_roster_exists`（并断言 `draw()` 可重复出候选）、`::test_flight_record_keeps_own_data_source`；前端 `tsc --noEmit` + `npm run build`。
- **关联**：D-10、`ops/service.py::draw`、`db.py::FLIGHT_COLUMNS/_ensure_columns`、`LogDetail.tsx`、`OpsSettlements.tsx`、`WorldMap.tsx`、`styles.css`。

### 45. `9.2` 信息架构已定口径（`IA-01/02/04/07/09`）

- **落地**：
  1. **IA-01**：`OpsFinance` 增加第三个页签「待复核」（`/ops/review` 解析为 `review`），`OpsReview` 支持 `embedded`；`/ops/review` 路由改指 `OpsFinance`（深链保留），侧栏去掉独立「复核队列」。
  2. **IA-02**：`Logs` 改成「列表 / 地图」两页签，`/map` 落到地图页签（保留 `?focus=`/`?track=`）；列表新增「来源：AOC / 导入」，导入航班用 `/local/volanta/flights`（本地搜索、点击行 → `/map?track=<id>`）；`MapPage` 支持 `embedded` 与 `focusTrackId`，并透传 `onPlanRoute`。
  3. **IA-04**：`Dashboard` 的六张累计指标卡换成一行摘要（班次 / 总时间 / 机场 / 国家）+「查看统计」，累计数据只归 `Stats`。
  4. **IA-07**：`AppContext` 新增 `onlineMode`（读 `loadOnline()`，随轮询同步）；联机时 `OpsNetwork` / `OpsFleet` / `OpsRules` 显示「该数据由公司服务端维护」并禁用新增/编辑/删除/生成/发布/回滚/调机等写操作，未联机保持现状。
  5. **IA-09**：`/recommend` 与 `/route` 同渲染新页 `RoutePlan`（① 推荐目的地 → ② 规划航路）：机场与机型/巡航高度共用，推荐卡片点选直接把 `dep/arr` 填进下方表单并同步到 URL；`Recommend` / `RoutePlanner` 增加受控 props，切机场后清掉旧航路结果。
- **收益/变化**：客户端导航 15 → 12（复核→财务、地图→日志、推荐→航路）；「待复核」入口 3 → 1；导入航班在日志列表可见；累计指标只剩一处。
- **当时未做（现况）**：`IA-03` / `IA-05` / `IA-10` 已由 §47 完成；`IA-06`（管理端经济/策略合并，待拍板）、`IA-08`（共享 money/time/enum 封装，客户端侧已集中）、`IA-11` / `IA-12`（管理端）→ 见 `1.3.2` 的 `M-07` / `M-05` / `M-08`。
- **测试**：`tsc --noEmit` + `npm run build`；页面级人工走查见 1.2 之外的待办（未新增自动化 UI 测试）。
- **关联**：D-11、`App.tsx`、`pages/RoutePlan.tsx`、`pages/Logs.tsx`、`pages/MapPage.tsx`、`pages/ops/OpsFinance.tsx`、`components/WorldMap.tsx`、`context.ts`。

---

## 八、已完成 · 2026-11-06（客户端收口：§46–§47）

> 范围：**只动客户端**（`apps/client`）与它需要的支撑（`OpsService.confirm_roster` 的 `replace` 参数、`/local/ops/rosters/confirm` 的请求体、接口文档）。
> 管理端 `apps/admin-web` 一行未改，条目整理成「1.3.2 管理端」。
> 验证：`pytest` 186 项 / `tsc --noEmit` + `npm run build` 全绿（未改 C#，`dotnet build` 未涉及）。

### 46. `UI-01` 口径修订 + 客户端 `UI-07`–`UI-19`

- **UI-01 修订（D-10 ① 落地）**：拦截点从 `draw()` 挪到 `confirm_roster()`。
  - 后端：`draw()` 不再查已有班表（只生成候选、不落库不锁机）；`confirm_roster(token, index, replace=False)` 在落库前查 `LOCKED/IN_PROGRESS`——`replace=True` 且旧班表是 `LOCKED` 时按「重抽」口径取消旧班表（`redraw=True`，不收费、不记失约），否则 409 `ROSTER_EXISTS`（`details.roster_id/status`，`IN_PROGRESS` 一律拒绝）。`/local/ops/rosters/confirm` 透传 `replace`，`docs/03` 同步。
  - 前端：`OpsRoster` 的「抽班/重抽」按钮始终可用（`IN_PROGRESS` 时置灰并提示先飞完/取消），文案区分「抽班 / 重抽（替换当前班表）」；确认遇到 409 且旧班表是 `LOCKED` → 弹「替换并确认」（`replace=true` 重试），`IN_PROGRESS` → 报错说明不能替换。合并页（`OpsFly`）里的同一个表单按钮即「重抽」入口。
  - 测试：`tests/test_ops.py::test_confirm_rejects_when_roster_exists`（抽班可反复出候选 → 确认 409 → `replace` 替换且不记失约 → 首段开始后禁止替换）、`::test_a05_*` 的断言改为「确认时拒绝」；`tests/test_api.py::test_roster_exists_and_task_recover_endpoints` 断言 draw 200 / confirm 409。
- **UI-07 图表文字拉伸**：`TrendChart` 用 `ResizeObserver` 取容器宽度作为 viewBox 宽（兜底 1040），去掉 `preserveAspectRatio="none"`；1440 以下和嵌在卡片里时左侧数值/底部时间刻度不再被横向拉伸。管理端 sider 见 `M-01`。
- **UI-08 顶栏刷新**：`AppContext` 新增 `refreshKey`，顶栏「刷新」在重取 settings/navdata/recording/opsStatus 的同时自增；各页把它放进加载依赖（`[load, refreshKey]`），与页面内同名按钮行为一致。设置页不重挂载（不丢草稿）。
- **UI-09 加载失败错误态**：新增 `components/LoadError.tsx`；`OpsHome`（不再永远骨架屏）、`OpsRules`、`OpsLedger`、`OpsSettlements`、`OpsReview`、`Logs`、`MapPage`（不再永久「加载中…」）、`Stats`（不再静默显示 0）都改成持久错误 + 重试。管理端 `Network` 见 `M-02`。
- **UI-10 设置页**：① 「导入档案（覆盖本地库）」改成 `Popconfirm`（未填路径时禁用）；② 主题/语言旁写明「保存后生效」（口径不变，D-10 ②）；③ 未保存浮条加警示图标 + 「离开将丢失」文案 + 高亮边框；④ 新增 `leaveGuard` 注册表：脏状态下拦侧栏导航（`Modal.confirm`「放弃并离开 / 留下继续编辑」）并挂 `beforeunload`。
- **UI-11 高影响操作确认**：客户端两处——`OpsNetwork` 班期「启用」由可点 Tag 改成 `Switch`（明确的控件语义，联机只读仍禁用）；`OpsFleet` 机型「停用」加 `Popconfirm`；顺带给 `OpsRules` 的「回滚」加确认（原来点了就直接生效）。
- **UI-12 关键输入**：`OpsHome` 基地机场改用 `AirportSelect`；`OpsFleet` 新增飞机的基地改用 `AirportSelect`，默认取本机档案 `base_airport_icao`（不再写死 `ZBAA`）；`OpsNetwork` 本地起飞时刻加 `HH:MM` 归一化（`8:00 → 08:00`）+ 正则校验，班期「运行日」全空时直接拦下（不再静默按每天生成 `127`）。
- **UI-13 i18n**：`OpsNetwork` 星期标签/实例状态、`OpsRules` 的 `ACCEPT/WEIGHTED/REVIEW/REJECT` 与 scope/reject 模式、`OpsExecute` 的 `task.kind` 与航段状态、`OpsFreeFlight` 任务状态与机型状态、`LogDetail` 的事件类型（新增 `ops.ts::eventLabel`）与 `anomaly_flags`（改用 `anomalyLabel`）、`Online` 的角色/班表/航段/同步事件枚举、`MapPage`/`Logs`/`LogDetail`/`LandingReport` 的 `????` 占位（统一成 `—`）。
- **UI-14 日志搜索**：输入框与请求分离（300ms 防抖），`page` 不再进 effect 依赖、翻页只在 `pagination.onChange` 取数（不再一次操作两个请求）；导入航班仍用输入框原值做本地过滤。
- **UI-15 ErrorBoundary**：新增 `components/ErrorBoundary.tsx`（错误 + 堆栈 + 「重试 / 打开日志目录」），包在 `Outlet` 外并用 `pathname + refreshKey` 作 `resetKey`（换页/刷新自动复位）。管理端见 `M-06`。
- **UI-16 首页与自由飞**：`Dashboard` 的「开始记录」与执行页同口径——`sim.level === "no-sim"` 先确认，然后把 `warnings[]` 逐条 `message.warning`；`OpsFreeFlight` 任务 `IN_FLIGHT` 时主按钮改为「去执行页（任务进行中）」，不再点了才 409。
- **UI-17 旧结果失效**：`Recommend` 在机场/机型/可用时间/两个开关变化时清空旧候选；滑块范围与输入框统一为 20–720 min；两个开关改动即写回 `settings.recommend`（`RoutePlanner` 原有的清空逻辑保留）。
- **UI-18 回放**：`TrackMap` 播放到结尾后按钮变「重播」，再点回到起点重播；事件列表默认 6 条 + 「更多（N）/收起」。
- **UI-19 合并页工具栏**：`OpsLedger` 的条数选择器与「刷新」在 `embedded` 时也渲染（右上角小工具栏）；`OpsReview` 表格加分页（12/页）。
- **顺带修掉 `api.ts` 的错误码解析（UI-01 的前置缺陷）**：`aoc-core` 的 `OpsError` 处理器返回平铺的 `{code, message, details, request_id}`，而客户端只读 `detail.*`（FastAPI 的 `HTTPException` 才有这层包裹），于是 `err.code` **永远是 undefined** —— `ROSTER_EXISTS`、`RECORDING_IN_PROGRESS`、`AIRCRAFT_NOT_AT_DEPARTURE`（§35 的「去快速调机」弹窗）这些分支其实一直没生效。现在两者都兼容（`detail.code` 优先，缺失时取顶层 `code`/`details`）。
- **关联**：D-10 ①、`ops/service.py::draw/confirm_roster`、`main.py::ops_roster_confirm`、`api.ts`（错误码解析）、`context.ts`（`refreshKey`/`openWizard`）、`components/LoadError|ErrorBoundary|SettlementSummary|NavdataPanel|SimlinkPanel`、`leaveGuard.ts`。

### 47. `IA-03` / `IA-05` / `IA-10`（客户端信息架构）

- **IA-03 自由飞的「可用飞机」表**：保留表格（信息密度高）但**行点击即选中**（与左侧下拉联动、选中行高亮），上方加摘要卡（机型 / 座位 / 航程 / 是否被锁），卡片右上角「去机队」链接；状态标签本地化。这样既解决「能看不能选」，也不用把机队页的信息再复制一遍。
- **IA-05 结算信息抽组件**：新增 `components/SettlementSummary.tsx`（`compact` = 四张数字卡，`detailed` = 状态/策略/金额 + 异常政策明细 + 收入/成本拆分 + 账本条目）。落地三处复用：
  - `OpsExecute`「结算结果」卡 → `compact`（保留「查看明细 / 回放轨迹」）；
  - `OpsSettlements` 抽屉 → `detailed`（删掉原来那套 Descriptions + 两张卡 + 账本表）；
  - `LogDetail` → 新增「结算（收入 / 成本 / 账本）」折叠区（同一航班的轨迹与结算不再分两页来回跳）。
  金额取负、状态/策略本地化、`HELD/VOID 不写账本` 的提示都收敛在组件里。
- **IA-10 向导与设置的共用面板**：新增 `components/NavdataPanel.tsx`（状态 + 路径 + 检测并保存 + 错误提示）与 `components/SimlinkPanel.tsx`（三态 + 重新连接 + 日志目录），`Onboarding` 只做步骤编排，`Settings` 直接复用两块面板；`AppContext` 新增 `openWizard()`，设置页「数据源」卡片右上角可「重新运行向导」。
- **未做（管理端，见 1.3.2）**：`IA-06`（经济/策略是否合页，待拍板）、`IA-08`（跨端共享封装；客户端侧已集中）、`IA-11`、`IA-12`。
- **关联**：`pages/ops/OpsFreeFlight.tsx`、`components/SettlementSummary.tsx`、`pages/ops/OpsExecute.tsx`、`pages/ops/OpsSettlements.tsx`、`pages/LogDetail.tsx`、`components/NavdataPanel.tsx`、`components/SimlinkPanel.tsx`、`pages/Onboarding.tsx`、`pages/Settings.tsx`。

---

## 九、已完成台账 · 走查清单（`UI-xx` / `IA-xx`）

> 2026-11-05 的前端可用性与信息架构走查，逐条明细从「一、待办」搬到这里：客户端侧**全部已处置**，
> 管理端条目已迁到「1.3.2」（`M-01`–`M-08`）。保留原文与落点，用于追溯「当时怎么发现的、改在哪」；
> 对应实现记录见 §44 / §46 / §47。标题里的 `（原 1.7 / 1.8）` 是为了让 §42–§47 与附录里的旧引用仍然对得上。

### 9.1 前端可用性 / 布局 / 交互走查（原 1.7，✅ 客户端已全部处置）

> 范围：`apps/client`（Tauri 客户端，22 个页面 + 11 个组件）与 `apps/admin-web`（管理端，11 个页面），最初为只读走查。
> **状态：客户端 `UI-01`–`UI-19` 全部落地**（`UI-01`–`UI-06` → §44；`UI-01` 口径修订 + `UI-07`–`UI-19` → §46）；管理端条目已剥到「1.3.2」，原编号保留在标题里备查。
> 排序：P0 = 用户会当成功能 bug（数据/逻辑/误导）→ P1 = 交互与布局 → P2 = 一致性与打磨。编号用 `UI-xx`，不占用功能项 `§` 号。

**P0 · 逻辑 / 数据**

- [x] **UI-01 有 `LOCKED` 班表时还能再抽一张，合并页里又没有「重抽」**
  - 现象（2026-11-06 修订前）：`OpsRoster` 表单按钮仍可点「抽班」（`runDraw(false)`，文案却是「先取消/重抽再抽新班」）。`draw()` 不拦已有班表，`confirm_roster()` 会再插一条 `roster` 并锁第二架飞机，而 `current_roster()` 只取 `created_at desc limit 1` → 前一张班表和它锁的飞机从界面上消失（飞机仍被占着）。
  - 「重抽」按钮只在非合并页的 `page-head` 里（`OpsRoster.tsx:212`），`OpsFly` 的三个页签内没有；抽到不满意的班表只能「取消班表」（首段之后取消收 $5,000）。
  - **口径（D-10 ①，2026-11-06 修订）**：「抽班」只是生成候选（不落库、不锁机），**确认前可以一直重抽**；拦截点放在「确认」（`confirm_roster`）——已有 `LOCKED`/`IN_PROGRESS` 班表时返回 409 `ROSTER_EXISTS`（带当前 `roster_id`），前端引导「重抽（替换）/ 取消旧班表」。已确认但首段未开始（`LOCKED`）仍可重抽（= 取消旧班表后再抽再确认）；`IN_PROGRESS` 首段已开始，不能重抽。合并页补齐「重抽」入口。
  - 落点：`apps/client/src/pages/ops/OpsRoster.tsx:212-214,493`、`OpsFly.tsx`、`packages/aoc_core/aoc_core/ops/service.py::draw/confirm_roster/current_roster`、`apps/aoc-core/main.py`（错误码映射）。
- [x] **UI-02 日志详情「数据源」显示的是当前会话，不是这条记录**
  - `LandingReport` 的 `dataSource` 取 `recording?.simlink_source`（当前 SimLink 状态），历史日志会显示成当前会话的 demo/replay/simconnect；未录制时退回 `flight.mode`（`ROSTER`/`PERSONAL`，不是采样源）。`flight_record` 里没有「这条记录来自哪个采样源」的字段。
  - 落点：`apps/client/src/pages/LogDetail.tsx:179`；要么给记录补一列（或复用 track profile 的 source），要么先去掉这个标签。
- [x] **UI-03 轨迹接口失败 → 整页变成「记录不存在」**
  - `load()` 用 `Promise.all([flights/:id, flights/:id/track])`，track 404/解析失败时连 `flight` 一起丢；随后 `if (!flight)` 渲染「记录不存在」，把「接口出错」误报成「数据不存在」。
  - 落点：`LogDetail.tsx:60-86,114-115`（track 单独 catch，失败只降级地图）。
- [x] **UI-04 结算详情成本行会出现 `--$1,234`**
  - `-{money(item.amount).replace("$", "$")}`：`replace` 是空操作；`amount` 为负（冲销/调整）时输出 `--$…`。抽屉里的「状态」「策略」还直接显示 `SETTLED`/`ACCEPT` 原始枚举，与列表的本地化 Tag 不一致。
  - 落点：`apps/client/src/pages/ops/OpsSettlements.tsx:163,110-115`。
- [x] **UI-05 `.text-danger` 类未定义，ZFW 偏低不标红**
  - 执行页两处 `className="text-danger"`（实际 ZFW、差异），`styles.css` 里没有这个类 → 视觉上完全没有提示。
  - 落点：`apps/client/src/pages/ops/OpsExecute.tsx:391,414`、`apps/client/src/styles.css`（补类或改用 `Text type="danger"`）。
- [x] **UI-06 世界地图弹窗累积，弹窗里的链接会跳出应用**
  - 每次点机场/航段都 `new maplibregl.Popup(...).addTo(map)`，旧弹窗不关；连点几条航段会叠一屏，筛选变化后弹窗内容也不刷新。
  - 弹窗里的「查看航路 / 生成航路」是裸 `<a href="/route?...">`，Tauri webview 里会整页跳转（不是 SPA 内导航），应改成按钮回调 `navigate()`；「点击空白处取消筛选」的提示与「弹窗仍开着」也不一致。
  - 落点：`apps/client/src/components/WorldMap.tsx:391-428`。

> **已落地**：P0（`UI-01`–`UI-06`）见「七、§44」；`UI-01` 口径修订与 P1/P2（`UI-07`–`UI-19`）见「八、§46」。下面的条目正文保留作历史台账。

**P1 · 交互与布局**

- [x] **UI-07 窄窗口布局（低优先级：D-10 已定「只保证 1440」）** —— 只做了本条目里「仍建议修」的那一项：`TrendChart` 改为按容器实测宽度出图（文字不再横向拉伸）；顶栏/侧栏/表格挤压按 D-10 明确**不投工作量**，仅记录（管理端 sider 见 `1.3.2 M-01`）
  - **口径**：不设最小窗口宽度，只保证 1440 宽下正常，下面的窄窗口问题只记录、不投工作量；但 `TrendChart`/`LandingReport` 的文字拉伸在 1440 下同样存在，仍建议修。
  - 顶栏 `height:60px` 固定 + `Space wrap`：窗口一窄，状态标签/「记录中」Badge/刷新换行后直接溢出到内容区（`App.tsx:155-184` + `styles.css:67-73`）。
  - 侧栏 216px 固定、无 `breakpoint`；`OpsFleet` 机队表 8 列没有 `scroll={{x}}`；`OpsExecute` 的 `Col span={6}`、`Descriptions column={3}`、`OpsSettlements` 收入/成本 `Col span={12}`，窄窗口全部挤压。
  - `TrendChart` 用 `preserveAspectRatio="none"`，左侧数值/底部时间刻度会随容器宽度横向拉伸（viewBox 宽 1040）；`LandingReport` 同样。
  - 管理端：`.admin-sider-foot` 绝对定位在底部，菜单在 ~768px 高度以下会被遮住且没有滚动区。
  - 落点：`apps/client/src/App.tsx`、`styles.css`、`OpsFleet.tsx:344-415`、`OpsExecute.tsx:273,436-441`、`OpsSettlements.tsx:146-169`、`components/TrendChart.tsx:94-95`、`apps/admin-web/src/styles.css:58-66`。
- [x] **UI-08 顶栏「刷新」不刷新当前页**
  - `App.refresh()` 只重取 settings/navdata/recording/opsStatus，页面自己的表格/候选不会更新，而每个页面又各有一个同名「刷新」——同一按钮两种行为。
  - 落点：`apps/client/src/App.tsx:181,263-274`（改成通过 context 触发页面级 `refreshKey`，或去掉全局刷新）。
- [x] **UI-09 加载失败后停在骨架屏 / 全 0，没有错误态** —— 客户端已改；管理端 `Network.loadFlights()` 见 `1.3.2 M-02`
  - `OpsHome`（`if (!data) return <Card loading />`）、`OpsRules`、`OpsLedger`、`MapPage`（永久「加载中…」）、`Stats`（静默显示 0）在接口失败时只有一条会消失的 toast，页面永远等下去。
  - 管理端 `Network.loadFlights()` 没有 try/catch，筛选/翻页失败是静默 unhandled rejection。
  - 落点：`OpsHome.tsx:89`、`OpsRules.tsx:133`、`OpsLedger.tsx:42`、`MapPage.tsx:30-37,162-175`、`Stats.tsx:15-17`、`apps/admin-web/src/pages/Network.tsx:46-50`。
- [x] **UI-10 设置页：覆盖本地库无确认、外观不即时生效、离开不拦截**
  - 「导入档案（覆盖本地库）」直接 POST，没有 Popconfirm；`主题/语言` 只改 `draft`，必须点「保存」才生效——切到 English 后界面仍是中文，容易被当成切换失效；有未保存改动时切换页面/关窗口没有拦截，只有右下角浮条。
  - **口径（D-10）**：保持「保存后生效」，不做即时预览；但要（a）在主题/语言控件旁写清「保存后生效」，（b）把右下角浮条改成更显眼的未保存提示，（c）路由切换/关窗口时拦截确认。
  - 落点：`apps/client/src/pages/Settings.tsx:61-67,328-347,429-430,441-454`、`apps/client/src/App.tsx`（路由级拦截）。
- [x] **UI-11 高影响操作缺少二次确认 / 反馈** —— 客户端已改；管理端部分见 `1.3.2 M-03`
  - 管理端：用户「角色」下拉即时生效、启用开关即时生效（可能把自己降权）；邀请码只在 `message.success` 里出现一次（关掉就找不回，也没有复制按钮）；航班实例「取消」无确认；策略/经济「回滚」无确认。
  - 客户端：`OpsNetwork` 班期启用 Tag 点一下就切换（不像控件）；机型「停用」无确认，且只能进编辑再打开开关才能恢复。
  - 落点：`apps/admin-web/src/pages/Users.tsx:90,121-128`、`Network.tsx:174`、`Policy.tsx:258-260`、`Economy.tsx:198-200`、`apps/client/src/pages/ops/OpsNetwork.tsx:198-205`、`OpsFleet.tsx:505-509`。
- [x] **UI-12 机场/时刻等关键输入还是自由文本，校验口径不一致** —— 客户端已改；管理端见 `1.3.2 M-04`
  - `OpsHome` 基地、`OpsFleet` 新增飞机（默认写死 `ZBAA`）、`OpsNetwork` 本地起飞时刻（`HH:MM` 文本）、管理端公司基地/航线机场都是纯 `Input`，没有 `AirportSelect`、没有大写/格式校验，错了只能等后端报错。
  - `OpsNetwork` 班期「星期」全部取消勾选时 `days.reduce(...) || 127` 静默变成「每天」，用户会以为不排班。
  - 落点：`OpsHome.tsx:324`、`OpsFleet.tsx:741-754`、`OpsNetwork.tsx:70-73,290-292`、`apps/admin-web/src/pages/Company.tsx:82-84`、`Network.tsx:184-185,201`。

**P2 · 一致性与打磨**

- [x] **UI-13 i18n 覆盖不全（英文模式下中英混排）** —— 客户端已改；管理端同 `IA-08`（`1.3.2 M-05`）
  - 示例：`OpsNetwork` 星期标签「一二三四五六日」、`OpsRules` 的 `ACCEPT（正常结算）` 等选项、`OpsExecute` 的 `task.kind`、`OpsFreeFlight` 的 `current.status` 与机型状态原始枚举、`LogDetail` 的事件类型与 `anomaly_flags`、`Online` 页状态枚举、`MapPage` 的 `????` 占位。
  - 落点：`pages/ops/OpsNetwork.tsx:12-16`、`OpsRules.tsx:14-19`、`OpsExecute.tsx:276`、`OpsFreeFlight.tsx:161,276`、`LogDetail.tsx:169,271`、`Online.tsx:187,203,212`。
- [x] **UI-14 日志页搜索每敲一个字就发一次请求**
  - `search` 直接在 effect 依赖里，无防抖；改 `pageSize` 时 `onChange` 与 effect 各触发一次 `load`（双请求）。
  - 落点：`apps/client/src/pages/Logs.tsx:23-39,150-158`。
- [x] **UI-15 没有 ErrorBoundary** —— 客户端已加；管理端见 `1.3.2 M-06`
  - 任一页面渲染抛错（例如后端字段缺失导致 `.toFixed()`）整窗白屏，Tauri 里只能重启。建议两端都在根部加 ErrorBoundary +「重新加载 / 打开日志」。
  - 落点：`apps/client/src/App.tsx`、`apps/admin-web/src/App.tsx`。
- [x] **UI-16 首页「开始记录」忽略后端 warnings；自由飞对已开始任务仍显示「开始飞行」**
  - `Dashboard` 只 `await api(...)` 然后报「已开始记录」，不看 `warnings`（执行页会先弹「没连上模拟器」确认）；`OpsFreeFlight` 在 `status=IN_FLIGHT` 时仍显示主按钮「开始飞行」，点了才 409。
  - 落点：`pages/Dashboard.tsx:57-68`、`pages/ops/OpsFreeFlight.tsx:179-189`。
- [x] **UI-17 航路 / 推荐页改了输入，旧结果还挂着**
  - `RoutePlanner` 生成后换机场/机型，下面的航路卡片不失效，卡片里也不显示这对机场，容易照着旧航路飞；`Recommend` 换基地后旧候选仍在。另外 `Recommend` 的滑块 max=360 与输入框 max=720 不一致，两个开关改了也不写回设置。
  - 落点：`apps/client/src/pages/RoutePlanner.tsx:43,69-88,210`、`Recommend.tsx:21-22,31-33,95-106`。
- [x] **UI-18 回放播放完停在结尾，再点「播放」没反应**
  - `currentT >= end` 时直接 `setPlaying(false)`，按钮不回到起点，用户必须先拖滑块；另只展示前 6 条事件、没有「更多」。
  - 落点：`apps/client/src/components/TrackMap.tsx:169-183,215-217,238-247`。
- [x] **UI-19 合并页里少了独立页的工具栏**
  - `OpsLedger` 的 `limit` 选择器与「刷新」只在非合并页渲染；`OpsReview` 没有分页（行多了只能整页滚）。
  - 落点：`pages/ops/OpsLedger.tsx:35-39`、`pages/ops/OpsReview.tsx:64-68`。

> **三条口径（D-10，2026-11-06 已按此落地）**：① `UI-01` 确认前可一直重抽、拦截在 `confirm_roster()`；② `UI-10` 主题/语言保持「保存后生效」，补文案 + 强化提示 + 离开拦截；③ `UI-07` 不设最小宽度、只保证 1440，仅顺手修图表文字拉伸。详见附录 A `D-10`。

### 9.2 页面拆分与功能重叠（信息架构走查，原 1.8，✅ 客户端已全部处置）

> 范围：客户端 15 个导航项 / 22 个页面，管理端 10 个一级菜单 / 11 个页面；**客户端已全部落地**（§45 / §47），剩余 4 条属管理端（`IA-06` / `IA-08` / `IA-11` / `IA-12`，描述已迁至 1.9）。
> 判据：① 同一件事要在两个地方做；② 同一领域出现两套拆法；③ 同一状态或数字在 3 处以上重复展示。
> 结论：**确实存在**，而且代码里已有「合并成页签」的先例（`OpsFly` = 抽班/自由飞/执行，`OpsFinance` = 结算/账本），问题是这套做法没有贯彻：
> - 3 组「一件事拆两页」：复核 vs 结算、日志 vs 地图（含导入航班）、推荐 vs 航路。
> - 4 组「两页功能高度重合」：`Dashboard` 指标卡 vs `Stats`、客户端 `OpsNetwork`/`OpsFleet` vs 管理端 `Network`/`Fleet`、客户端 `OpsRules` vs 管理端 `Economy`+`Policy`、`Onboarding` vs `Settings` 数据源。
> - **两个首页不算重合**：`/` 是个人模式入口（录制/数据源/最近日志），`/ops` 是运营模式入口（档案/余额/机队/班表/结算），面向不同模式、内容也不同 —— 保留两页（见 IA-04 修订）。
> - 2 组「同一信息四处展示」：结算数字（执行页/财务/复核/首页）、navdata+SimLink 状态（顶栏/Dashboard/设置/执行页）。
> 编号 `IA-xx`（信息架构），与 9.1 的 `UI-xx`（可用性）分开。

**A. 低风险（不动导航结构，先消重）· 已全部落地**

- [x] **IA-01 复核队列与结算/财务是同一份数据的两个页面**
  - 现状：`/ops/review`（`OpsReview`）列的就是 `HELD` 状态的结算，动作是 ACCEPT/WEIGHTED/REJECT；`/ops/finance` 的「结算」页签已经有状态列、金额与明细抽屉，顶部摘要卡还显示「N 待复核」，`OpsHome` 又有一个「待复核」指标卡链过去。同一批数据 3 个入口、2 套加载逻辑。
  - **已定（D-11）**：并成「财务 → 待复核」第三个页签（与 `UI-19` 的 `OpsLedger` 工具栏一起收口）；`/ops/review` 保留深链（`OpsFinance` 读路径切页签，和 `/ops/settlements`、`/ops/ledger` 现在的做法一致）。
  - 收益：导航项 15 → 14，「待复核」入口 3 → 1。
  - 落点：`apps/client/src/pages/ops/OpsReview.tsx`、`OpsFinance.tsx:129-144`、`App.tsx:368-369`、`OpsHome.tsx:181-183`。

- [x] **IA-02 飞行历史被拆成「日志列表」「地图网络」「地图页里的导入表」三处**
  - 现状：`/local/flights` 只返回 AOC 自己的 `flight_record`（`apps/aoc-core/main.py:368`），所以 `Logs` 里**看不到** Volanta/CSV 导入的航班；导入航班只能在 `MapPage` 最下面那张表里翻，点开只在地图上画轨迹、进不了「日志详情」。`MapPage` 另有一张 AOC 航班表（时间/航段/机型/落地），列与 `Logs` 大量重合。
  - 可先做的最小步：只在 `Logs` 顶部加「来源：AOC / 导入」筛选（`/local/volanta/flights` 已有接口），先解决「导入航班看不到」，不动导航。
  - **已定（D-11）**：地图作为「日志」页的一个页签（列表 / 地图），`MapPage` 的两张历史表并入列表页签的「来源」筛选；`/map` 保留深链路由（进入日志页并切到地图页签，保留 `?focus=`）。
  - 落点：`Logs.tsx:23-39`、`MapPage.tsx:199-317`、`apps/aoc-core/main.py:368,434`。

- [x] **IA-03 自由飞行页里的「可用飞机」表与机队页重复，而且不能操作**
  - 现状：`OpsFreeFlight` 右侧 5 列表（注册号/机型/角色/座位/状态）只是把 `/local/ops/free-flights/aircraft` 原样铺开，没有行点击、不能选、看不到锁；真正选飞机在左边下拉里。机队页已经有完整档案、状态与锁信息。
  - 建议：删掉这张表，改成「下拉选飞机 + 一张摘要卡（机型/航程/座位/是否被锁）+ “去机队”链接」；或者让行点击 = 选中该飞机。
  - 落点：`apps/client/src/pages/ops/OpsFreeFlight.tsx:260-283`、`OpsFleet.tsx`。

- [x] **IA-04 `Dashboard` 的累计指标卡与 `Stats` 完全同源（两个首页保留）**
  - 现状：`Dashboard` 的 6 张指标卡（总飞行/总时间/总距离/机场/平均接地/最大过载）与 `Stats` 顶部 8 张卡读的是同一个 `/local/stats`，数值与文案都一样，只是首页顺手放了一份。
  - **已定（D-11）**：`/`（个人首页）与 `/ops`（运营概览）**不合并** —— 面向两种模式，内容分别是录制/数据源/最近日志 vs 档案/余额/机队/班表/结算；只把 `Dashboard` 的累计指标去掉或收成一行摘要（如「1,284 班 · 2,310 h · 96 机场 → 统计」），累计数据统一归 `Stats`。
  - 落点：`Dashboard.tsx:222-229`、`Stats.tsx:37-46`。

- [x] **IA-05 结算信息在 4 个地方各画一遍，同一航班的两半还分在两页**
  - 现状：`OpsExecute` 的「结算结果」卡、`OpsFinance` 的结算表 + 抽屉、`OpsReview`、`OpsHome` 的「最近结算」表，各写了一套「收入/成本/利润/策略/状态」渲染；`OpsSettlements` 抽屉（财务）与 `LogDetail`（轨迹/落地报告）是同一航班的两半，只能互相跳转。
  - 建议：抽 `SettlementSummary` 组件（数字卡 + 明细）复用；`LogDetail` 对 `mode=ROSTER/FREE` 的记录加「结算」折叠区，去掉「回放轨迹 ↔ 看结算」的来回跳。
  - 落点：`OpsExecute.tsx:478-503`、`OpsSettlements.tsx:98-200`、`OpsReview.tsx:64-116`、`OpsHome.tsx:255-290`、`LogDetail.tsx`。

**B. 结构性合并 · `IA-07/09` 已落地；`IA-06` / `IA-08` 已迁 1.3.2**

- [x] **IA-07 客户端「航线与班期」「机队」与管理端同名页面高度同构**
  - 现状：`OpsNetwork`（客户端）与 `Network`（管理端）都是「航线 / 班期 / 实例」三层 + 生成未来 7 天；`OpsFleet` 与 `Fleet` 都是「机型模板 / 飞机 / 释放锁」，客户端还多出机型 CRUD、送修、退役、快速调机。玩家和管理员都能建航线、建班期、改机型 —— 两份入口、两套校验，同一个实体有两种编辑路径。
  - **已定（D-11）**：按模式分，不做「玩家端一律只读」——
    ① **开启联机模式**时，客户端这三页（航线与班期 / 机队 / 运营规则）**变只读**：隐藏新增/编辑/删除/发布/回滚，页头挂一条「联机模式：该数据由公司服务端维护」提示；
    ② **未开启联机**（本地单机运营）保持现状，仍可自由编辑；
    ③ 管理端始终可编辑（服务端权威），不改。
  - 实现要点：现在只有 `Online.tsx` 从 `online.ts::loadOnline()` 读 localStorage，`App` 与其它页面不知道当前是否联机；需要把 `onlineMode` 提升到 `App` context（登录/退出/刷新时同步），三页共用一个 `readOnly` 判断，避免各页各读一遍。
  - 风险：只做「界面只读」挡不住直接调接口；本地 `ops_*` 表与联机服务端是两套数据，联机模式下应同时考虑是否隐藏本地这些页（或只读+提示），否则用户会以为看到的是公司数据。
  - 落点：`apps/client/src/pages/ops/OpsNetwork.tsx:134-315`、`OpsFleet.tsx`、`OpsRules.tsx`、`apps/client/src/online.ts`、`App.tsx`（context）。

- [x] **IA-09 推荐（`/recommend`）与航路（`/route`）是同一条流的两页**
  - 现状：`Recommend` 只负责按可用时间选机场，点「生成航路」跳到 `/route?dep=&arr=`；两页共用机场/机型选择器与 SimBrief，但换页后机型/巡航高度要重新确认。
  - **已定（D-11）**：合成一页「航路规划」，按「先推荐、后规划」排：上方推荐候选（点卡片把机场填进下方表单），下方是现在的生成结果区；`/recommend` 与 `/route` 都保留深链，落在同一页并带上 `dep/arr`。
  - 落点：`Recommend.tsx:61`、`RoutePlanner.tsx:41-45`、`App.tsx:351-352`。

**C. 记录备查 · `IA-10` 已落地；`IA-11/12` 已迁 1.3.2**

- [x] **IA-10 首次向导与设置页「数据源」重复同一块面板**
  - 现状：`Onboarding` 的 3 步（navdata / SimLink / Volanta）= `Settings` 数据源区三段；`VolantaImport` 已共用，另外两段各自实现。向导只跑一次，设置里没有「重新运行向导」。
  - 建议：`navdata 选择` / `SimLink 状态` 也抽成共用块，向导只做步骤编排；设置页加「重新运行向导」。
  - 落点：`Onboarding.tsx`、`Settings.tsx:148-246`。
> **已落地**：`IA-01/02/04/07/09` 见「七、§45」，`IA-03/05/10` 见「八、§47」—— 客户端 `IA` 全部收口。
> **管理端 4 条已迁出**：`IA-06` / `IA-08` / `IA-11` / `IA-12` → 「1.3.2」的 `M-07` / `M-05` / `M-08`，本台账不再重复描述。

**页面数变化（按已定口径估算，不是承诺）**

| 范围 | 改前 | 现在（D-11 已落地） | 若 `IA-06` / `IA-11` 也做 |
|---|---|---|---|
| 客户端导航项 | 15 | **12**（复核→财务、地图→日志、推荐→航路） | 12 |
| 管理端一级菜单 | 10 | 10 | 8（经济+策略、公司+系统） |

> 两个首页保留（`/` 个人模式、`/ops` 运营模式），只去重 `Dashboard` 的累计指标卡。
> 合并后页面组件大多仍然保留（以页签/区块形式复用，如现在的 `OpsSettlements`、`OpsLedger`），所以「页面文件数」不会等量下降，这里只统计用户能看到的入口。

> 五条口径（`IA-01/02/04/07/09`）见附录 A `D-11`，均已于 §45 落地。
> **仍未拍板**：`IA-06` —— 管理端的「经济参数」与「结算策略」是否也合成一页 3 页签？（客户端已经是一页）→ 见 `1.3.2 M-07`。

---

## 附录 A. 决策记录（D-1～D-7 于 2026-11-02；D-8 于 11-03；D-9～D-11 于 11-05；D-10 ① 于 11-06 修订）

| 编号 | 议题 | 结论 |
|---|---|---|
| D-1 | §33 位置闸阈值与降级 | **10 NM**；`on_ground=false` 或距出发机场 >10 NM 才拦；navdata 缺失 / 查不到出发机场 → 只做瞬移断点，仍允许开录 |
| D-2 | §33 已在空中才开 AOC | 按 `partial=true` 记录并进复核，不自动判 `COMPLETED`、不置航段 `COMPLETED` |
| D-3 | §33「本段作废重飞」 | 本批就做，含 `settlement` / 账本 / 机队位置冲销 |
| D-4 | §34 下限口径 | 可填字段，留空按「上限 × 0.75」推导（480 → 360）；填写值优先 |
| D-5 | §32 方案 B 参数 | `GS ≥ 5kt` 连续 3s、5 帧中位数、跳变 >10% 继续等；`POST /local/recording/start` **彻底移除** `actual_zfw_kg`（单一来源） |
| D-6 | §35 快速调机参数 | 允许透支（不拦负余额）；`fast_ferry_hold` 默认关；`fast_ferry_fee_per_nm = 12.0`、`fast_ferry_fixed_fee = 1000.0`（运营规则页可改） |
| D-7 | §36 数据源路线 | **场景库优先**（按 V-3 改判）：跑道几何取 Little Navmap 的 `little_navmap_msfs24.sqlite`，缺失回落 navdata，手工覆盖表兜底（已做，§43）；SimConnect facility 降为后续可选 |
| D-8 | §37 CI 的 Node 版本 | 升到**最新 LTS 26**（Lithium）；不用 Current/alpha，不锁精确补丁（`setup-node` 用 `"26"`）；Node 20 已 EOL |
| D-9 | §41 录制早于任务的处理 | **改绑**而不是拒绝：只有「无主的 PERSONAL 记录」才自动改绑到任务（`adopted_recording=true` + 前端确认）；已绑别的任务一律 409 `RECORDING_IN_PROGRESS`；不做「开录时自动绑定」（分不清自由飞与班表） |
| D-10 | 9.1 前端走查三条口径 | ① **确认前可以一直重抽**（`draw()` 只生成候选、不拦已有班表），拦截在 `confirm_roster()`（已有 `LOCKED`/`IN_PROGRESS` → 409 `ROSTER_EXISTS`，`IN_PROGRESS` 不可重抽），前端引导「重抽（替换）/ 取消」（`UI-01`；2026-11-06 修订，原为「禁止再抽、`draw()` 也拒绝」；已按此实现，见 §46）；② 主题/语言**保持保存后生效**，补文案 + 强化未保存提示 + 离开拦截（`UI-10`）；③ **不设最小窗口宽度**，只保证 1440，`UI-07` 降级为低优先级，仅顺手修图表文字拉伸 |
| D-11 | 9.2 信息架构五条口径 | ① 复核并进「财务」第三个页签，`/ops/review` 保留深链（`IA-01`）；② 地图并进「日志」页签、导入航班并入列表「来源」筛选（`IA-02`）；③ **两个首页不合并**（个人模式 ≠ 运营模式），只把 `Dashboard` 累计指标去重归 `Stats`（`IA-04`）；④ **仅开启联机模式时**客户端「航线与班期 / 机队 / 运营规则」只读，未联机保持现状（`IA-07`）；⑤ 推荐与航路合成一页（先推荐、后规划），两个深链都保留（`IA-09`） |

---

## 附录 B. 验证记录（V-1～V-5 于 2026-11-02；V-6 为最近一次回归）

> V-1～V-5 为原型验证，工具在 `tools/`；结论已并入 §31–§36，此处保留原始数据备查。
> V-6 只记「跑了什么、结果如何」，用来判断某次文档更新有没有破坏既有行为。

- **V-1 §33 采样真相**（MSFS 2024 实机，`tools/v1_ghost_probe.py`）：
  - 幽灵状态：`lat=0.00000 / lon=90.00032`、`on_ground=false`、`alt≈233ft`、`agl≈216ft`、`gs=0`、`parking_brake=false`、发动机在转 —— 出现在菜单/切场景期间，**不是只有 KBFI**。
  - 进飞行那一刻瞬移到真实机场（本次 RJTT `35.54213 / 139.80199`），`dt=147.7s`（加载期 SimConnect 无回调）、位移 **3,501.5 NM**、推算 **85,365 kt**。历史录制 `ddc31929` 里 4 处跳变，最小 **16,609 kt**、最大 **12,717,282 kt**（WMKN→(0,90)→海口→**KBFI**→RPLL，总里程 14,185 NM）→ **900 kt 阈值足够**，但要叠加「`dt > 30s` 且位移 > 10 NM」（加载期 dt 很大）。
  - `on_ground` 恰在跳变处 `false`→`true`：假起飞 + 假落地，`evaluate()` 的 `takeoff=0` 兜底必中。
  - **预录只对自动开录生效**（旧代码）：`Engine.StartRecording` 只在 `!manual` 时写入 600s 预录；实测手动开录首帧就是当前机位、不带历史帧 → 自动开录中招于预录里的空中帧，手动开录中招于「开录瞬间镜像未稳定」。结论：闸必须挡在 core 的 **ingest 之前**，预录截断是自动路径的关键，起飞门槛是最后兜底。
  - **顺带发现**：重连/切场景后 SimLink 不重置 `_engineRunning`/`_engineOnSince`/`_hasTakeoff`/`_landed` → 「发动机在转却不自动开录」（已在 §33 修复）。
- **V-2 §31 `manualzfw` 单位**（人工比对四条对照链接，`tools/v2_simbrief_zfw_links.py`）：单位是 **ton**（t = 1000 kg），正确值 = ZFW ÷ 1000（166714 kg → `166.714`；`182.555` = 182555 kg）。按千磅传 `367.542` 会被当成 367.542 t 超 MTOW 而丢弃。
- **V-3 §36 可行性**（`tools/v3_navdata_compare.py`）：① SimConnect 设施 API 存在（SDK 12.2，MSFS 2024 应用名 `SunRise`），但按猜的字段名（`LENGTH`/`WIDTH`/`HEADING`/`PRIMARY_LATITUDE`…）全返回 `DATA_ERROR(20)`，需官方 `FacilityDataDefinitionFlightsim.csv`；② **LNM 的 `little_navmap_msfs24.sqlite` 就是「游戏库」**：WMKN 10,041 ft = **3,060.5 m**（navigraph 11,417 ft = 3,480 m），入口坐标差 ~2.2 km，与游戏内实测 3060 m 一致 → D-7 改判。
- **V-4 §34 候选数量**（真实机队 9 架 / 134 实例，`tools/v4_draw_probe.py`）：遵循航线时链只有 7–10 条；上限 480 + 下限 360 → **达标 0 条（全灭）**，上限 360 → 1/10，上限 240 → 2/7；虚拟航段 553 条链里 66% 达标。
- **V-5 §32 推出判定**（19 段历史录制，`tools/v5_pushback_probe.py`）：7/19 有真实推出可触发、2 段空中接入无推出、其余短录制/幽灵不触发；触发点 15s 内 ZFW 波动 **0 kg（0.00%）**；帧间隔 0.98–2.0s → 必须「候选帧起表，等 `t − since ≥ 3s` 再取值」。
- **V-6 §42–§47 回归**（2026-11-06，开发机）：`pytest` **186 项全过**（含新增 `test_confirm_rejects_when_roster_exists`、`test_flight_record_keeps_own_data_source` 等）；`tsc --noEmit` 无错；`npm run build` 成功（唯一告警是单 chunk >2.5 MB，历史遗留）。未运行 `tools/ui_smoke.py`（需浏览器/实机）与低配机性能探针 —— 对应项在 1.2 / 1.3。
