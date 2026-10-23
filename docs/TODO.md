# TODO

> 更新：2026-10-22 文档变更（运营模式 · 飞行执行 / SimBrief）已全部落地——代码 + 测试 + 文档同步，
> 下面只剩需要真人/干净机才能完成的验收项。

## 待人工验收

- **T-21 / A-32**（安装版 + 便携版）：双击无控制台窗口、托盘出现、安装版直开窗口 / 便携版默认浏览器、关闭窗口最小化到托盘、托盘「退出」后无残留 `aoc-core` / `aoc-simlink`。
- **T-01 / T-06a**（干净 Windows，无 Python / .NET / Node）：用 `out/AOC-0.1.0-x64-setup.exe` / `*.msi` / `AOC-portable-*-win64.zip` 各跑一次。
- **体积实测**：自包含改造后 `out/AOC-portable-*-win64.zip`、NSIS/MSI 重新生成，把实测值回填 `08` §2 / §4.4（`aoc-core` onedir 已实测 134 MB）。
- **Authenticode 签名**：等证书。

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
- 待人工：T-21 / A-32。文档：`01` P-11/A-32、`02` §2.1/§13.1、`08` §2/T-01/T-05/T-21、`09` §1/§4/§5、`10` §5、`README` D-29。

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
