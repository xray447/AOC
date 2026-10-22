# TODO

> 来源：2026-10-22 文档变更（运营模式 · 飞行执行 / SimBrief）。文档先改，代码已按下述条目跟进并补测试。

## 待实现

### 1. 跑道窗口 10Hz 采样（`RUNWAY` 段）

- 问题：现在 `Engine.SaveSample()` 在地面按 1Hz 保存，`track.py` 又把 on-ground 判成 `TAXI`（10s 一点）；起飞滑跑/落地滑跑的点间距 300–800m，接地区画不出连续线。
- SimLink `apps/simlink/Engine.cs::SaveSample`：跑道窗口内改为 **0.1s**——`OnGround && 距机场 < 5NM`，或 `AGL < 100ft && 距到达机场 < 5NM`；窗口内不受 `_hz` 限制；起飞滑跑至离地、落地至 `GsKt < 40` 或离开跑道。
- 核心 `packages/aoc_core/aoc_core/track.py`：新增 `MODE_RUNWAY`（与上面同窗口），保存间隔 **0.1s**，不抽稀；`TAXI` 只保留非跑道滑行（10s）；超预算时 `RUNWAY` 不参与 Douglas–Peucker，只压 `STRAIGHT/TAXI`。
- 前端 `components/RunwayTouchdown.tsx`：滑跑线优先取 `RUNWAY` 段点（退化才用接地后全部点），保证线条连续。
- 测试：`tests/test_track.py` 补「跑道段 10Hz、点间距 ≤8m、不抽稀、不计入超预算削减」；`tools/smoke_m1.py` 检查落地后 `RUNWAY` 段存在。
- 文档已同步：`01` P-05/P-06/A-21、`02` §7.2/§7.4/§10.1、`03` §2。

### 2. 跑道内移入口（displaced threshold）

- 数据源：Little Navmap `runway_end.offset_threshold`（英尺）已有入口内移值，例如 KJFK 31L ≈ 1000m；当前 `aoc_navdata/navdata.py::_load_runways` 没有 SELECT 这列。
- `aoc_navdata`：按可选列读取 `offset_threshold`，单位校准（英尺→米，取不到列/为 0 时按 0）；跑道对象增加 `displaced_threshold_m`，`length_m` 仍为物理长度。
- `aoc_core/landing.py`：`threshold_distance_m` 以「着陆入口 = 物理入口 + 内移」为基准；`/local/airports/{icao}` 与 `/local/flights/{id}` 透出 `displaced_threshold_m`，旧库/旧数据缺失时按 0。
- 前端 `components/RunwayTouchdown.tsx`：画物理跑道端、着陆入口、内移段（着色/斜纹），刻度从着陆入口起算；内移为 0 时布局与现在一致。
- 测试：构造 KJFK 31L 跑道数据断言 `displaced_threshold_m ≈ 1000`；无 `offset_threshold` 列时回退 0 且不报错；`threshold_distance_m` 以着陆入口计算。
- 文档已同步：`01` P-06/P-09、`03` §2/§6、`09` §5。

### 3. 无控制台启动 + 系统托盘图标

- **去掉两个命令行窗口**：
  - Tauri `apps/client/src-tauri/src`：拉起 `aoc-core.exe`（自包含，见第 4 项）与 `aoc-simlink.exe` 时用 `CommandExt::creation_flags(CREATE_NO_WINDOW)`；stdout/stderr 重定向到 `%LOCALAPPDATA%/AOC/logs/core.log`、`simlink.log`。
  - `apps/simlink`：csproj `<OutputType>WinExe</OutputType>`（或保留 Console 但由父进程隐藏），自身日志写文件，不依赖控制台输出。
  - 开发脚本 `tools/dev.ps1` 保留可见控制台（调试用）；生产启动路径不得弹窗。
- **托盘图标**：
  - 安装版：Tauri `TrayIconBuilder`（图标 + tooltip 状态），菜单「打开客户端 / 打开日志目录 / 退出」；关闭主窗口最小化到托盘（设置可改「关闭即退出」），退出时结束两个 sidecar。
  - 便携版：新增 `AOC-portable.exe` 启动器（.NET WinForms `NotifyIcon` 或等价实现）：无控制台拉起包内 `aoc-core.exe` 与 `aoc-simlink.exe`，健康检查通过后 `Process.Start` 默认浏览器；菜单同上。
  - 单实例：安装版命名互斥聚焦窗口；便携版检测已有实例时只打开页面，不重复起进程。
- **便携包调整**：`tools/make_portable.py` 产物增加 `AOC-portable.exe`；`start.bat`/`start.py` 保留排障（会显示控制台）。
- **测试/验收**：新增 T-21 与 A-32——双击无控制台窗口、托盘出现、安装版直开窗口 / 便携版默认浏览器、退出后无残留 `aoc-core`/`aoc-simlink`。
- 文档已同步：`01` P-11/A-32、`02` §2.1/§13.1、`08` §2/T-01/T-05/T-21、`09` §1/§4/§5、`10` §5、`README` D-29。

### 4. 自包含打包（去掉 Python / .NET 依赖）

- `tools/build_core_exe.py`（新增）或 `aoc-core.spec`：PyInstaller `--noconsole --onedir`，包含 `fastapi/uvicorn/pydantic/httpx/numpy/scipy/tzdata` 与 `packages/*`、`data/`、`Pre-train/src`；产物 `out/core/aoc-core.exe`，启动参数不变（`--port --token --home --static-dir`）。
- `apps/simlink`：发布命令改 `dotnet publish -c Release -r win-x64 --self-contained true`（不要求 .NET 8）；体积增加约 60–80 MB。
- `apps/client/src-tauri`：`bundle.resources` 从 Python 源码改为 `aoc-core.exe` 目录；`tauri.conf.json` 同步。
- `tools/make_portable.py`：打包 `aoc-core.exe` + 自包含 SimLink，不再复制 `packages/` 源码；`smoke_portable.py` 改为直接起 exe。
- 体积预算：PyInstaller（numpy/scipy）约 80–150 MB；NSIS/MSI 与便携 ZIP 相应变大，更新 08 的体积记录。
- 验证：干净 Windows（无 Python/.NET/Node）跑 T-01、T-06a；`/local/health`、航路建图、SimLink 连接均正常。
- 文档已同步：`01` P-11、`02` §7.2/§13.1、`08` §2/§4.4.1/T-01/T-06a、`09` §1/§4/§5、`10` §5、`README` D-30。

### 5. GitHub Actions：云端编译与产物

- 新增 `.github/workflows/build.yml`，`runs-on: windows-latest`，触发：`push`（main + tag `v*`）、`pull_request`、`workflow_dispatch`。
- 作业拆分（可并行）：
  - **test**：Python 3.12 + `pip install -r requirements.txt` → `pytest` + `ruff check packages apps tests tools --select F,E9`；前端 `npm ci && npm run build`（`tsc --noEmit`）；`dotnet build apps/simlink -c Release`。
  - **core**：按 TODO §4 跑 PyInstaller 生成 `aoc-core.exe`（onedir），上传 artifact `aoc-core-win64`。
  - **simlink**：`dotnet publish -c Release -r win-x64 --self-contained true`，上传 artifact `aoc-simlink-win64`。
  - **app**：`npm ci` + `cargo` 缓存 + `npm run tauri build -- --bundles nsis,msi`；Windows runner 已带 MSVC/WebView2，需 `dtolnay/rust-toolchain@stable`；上传 `AOC-*-setup.exe`、`*.msi`。
  - **portable**：下载 core/app 产物 → `tools/make_portable.py` 打包 ZIP（含 `AOC-portable.exe`）并上传。
- Tag 构建额外用 `softprops/action-gh-release`（或 `tauri-apps/tauri-action`）把 NSIS/MSI/便携 ZIP 挂到 Release；PR 只跑 test，不产包。
- 缓存：`actions/setup-python` 的 pip、`actions/setup-node` 的 npm、`actions/cache` 的 `~/.cargo` 与 `apps/client/src-tauri/target`、`~/.nuget/packages`。
- 约束：不把 navdata / `network.pkl` / SimBrief key 放进仓库与产物；Windows 路径与中文编码回归；单次构建超时 45 min；artifact 保留 14 天。
- 可选：`workflow_dispatch` 输入 `bundle=nsis|msi|both`、`make_release=true`；签名（Authenticode）留到有证书后。
- 文档：在 `08` §4 增加「CI 构建」小节与徽章；`README` 补构建状态。

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
