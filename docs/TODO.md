# TODO

> 更新：2026-10-30 §23–§30（军用机场、候选多样性、随机航班号、翼展、自动开录/收尾、机型识别、落地报告）已全部落地，
> 代码 + 测试 + 文档同步（证据见 `10` §3）。仍需真人/干净机（低配机内存、安装包、签名）的验收项在下方。

## 已完成（2026-10-30，功能改进 §23–§30）

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

## 待人工验收

- **T-01 / T-06a**（干净 Windows，无 Python / .NET / Node）：用 `out/AOC-0.1.0-x64-setup.exe` / `*.msi` / `AOC-portable-*-win64.zip` 各跑一次。
- **体积实测**：自包含改造后 `out/AOC-portable-*-win64.zip`、NSIS/MSI 重新生成，把实测值回填 `08` §2 / §4.4（`aoc-core` onedir 已实测 134 MB）。
- **Authenticode 签名**：等证书。

## 已通过（人工验收）

- **T-21 / A-32**（安装版 + 便携版，2026-10-24）：双击无控制台窗口、托盘出现、安装版直开窗口 / 便携版默认浏览器、关闭窗口最小化到托盘、托盘「退出」后无残留 `aoc-core` / `aoc-simlink` → **通过**。

## 待人工实测（性能与实机）

- **SimLink 内存（D-26）**：`python tools/simlink_mem_probe.py --minutes 30 --interval 60`；判据：未连接 < 60 MB、连上未录制 < 80 MB、录制稳态 < 100 MB 且趋势 |≤5 MB/h|。
- **aoc-core 空闲 CPU（D-27）**：代码侧已修（见下方 §22）；`python tools/core_cpu_probe.py --minutes 5` 在开发机上实测空闲平均 **0.130%**、峰值 1.378%（单核，SimLink 在跑未连模拟器）。待低配机复核：空闲 5 分钟平均 < 0.3%（单核），录制中平均 < 1.5%。
- **SimLink 自动重连（实机）**：先开 AOC 再开 MSFS，10s 内 `sim_connected=true`；飞行中退出模拟器再进，`/events` 有 `sim_disconnected` / `sim_connected`，记录不重复、缺口标记正确。

## 已修复（性能，2026-10-24）

- **aoc-core 空闲 CPU 每 2 秒一次尖峰（D-27 残留）**：根因是 `SimLinkClient` 每次请求都新建 `httpx.AsyncClient`（Windows 上构造要重建 SSL 上下文，实测 **约 0.54s CPU/次**），轮询按 1–2s 打一次 → 常驻高 CPU + 2s 周期尖峰。同一场景实测：修复前 2 分钟空闲平均 **19.9%**、峰值 48%；修复后 5 分钟平均 **0.130%**、峰值 1.378%（只剩取整级别的单 tick），CSV 时间线上不再有 2s 周期。详见 §22。

## 已完成（代码 + 文档）

### 1. 自由飞出发机场只允许「有可用飞机」的机场

- 后端 `GET /local/ops/free-flights/airports`：按机队当前位置去重，返回 `{icao, iata, name, city, country, lat, lon, aircraft}`。
- 领域层 `OpsService.free_airports()`：机队表位置字段是 `aircraft.current_airport_icao`（不是 `location_icao`），只统计 `ACTIVE` 且未锁的飞机。
- 前端 `OpsFreeFlight.tsx` 的出发机场改为该列表；`AirportSelect` 新增 `airports` 受限候选（本地过滤，不再远程搜全库），当前选择/基地不在列表时回落到第一座可用机场。
- 测试：`tests/test_ops.py::test_free_airports_only_lists_airports_with_available_aircraft`。

### 2. SimBrief 配载改用 `manualzfw`，呼号改 `airline` + `fltnum`

- `aoc_route/simbrief.py`：去掉 `payload`/`callsign`；`manualzfw = ZFW kg × 2.2046226 ÷ 1000`（保留 3 位小数）；呼号按末尾数字拆成 `airline` + `fltnum`（`AOC101` → `airline=AOC&fltnum=101`），无末尾数字时只传 `airline`。
- 调用链：`RouteService.simbrief(..., zfw_kg=...)`、`PersonalService.simbrief_for_leg`（传配载单 `zfw_kg`）、`GET /local/routes/simbrief` 同步改为 `zfw_kg`。
- 测试：`tests/test_route.py::test_simbrief_splits_callsign` / `test_simbrief_uses_manualzfw`、`tests/test_ops.py::test_simbrief_preview_carries_frozen_payload`、`tools/ui_smoke.py` 断言 `manualzfw=` + `airline=`/`fltnum=`，且不含 `payload=`/`callsign=`/`pax=`/`cargo=`/`fuel=`/`fl=`。

### 3. 自由飞计划起飞时间（缺省 now + 50min）

- 后端 `create_free_flight`：`dep_time_utc` 缺省改为「领取时刻 + 50min」（`FREE_DEP_OFFSET_MINUTES`）。
- 前端 `OpsFreeFlight.tsx`：新增「计划起飞时间」（`DatePicker`，本地时区显示、提交转 UTC），默认 `当前时间 + 50min`；当前任务卡片展示计划起飞。
- 数据：沿用 `free_flight.dep_time_utc`，执行页 `task.scheduled_dep_utc` 不变。
- 测试：`tests/test_ops.py::test_free_flight_dep_time_defaults_to_now_plus_50min`。

### 4. 推出前 ZFW 低于配载单时提示

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
- 验收（实机）：先开 AOC 再开 MSFS，`sim_connected` 10s 内自动 `true`；飞行中退出再进能自动恢复。
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
- 工具：`tools/simlink_mem_probe.py`（WS/PM + `/status` 采样点，CSV + 趋势/峰值摘要）。
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
