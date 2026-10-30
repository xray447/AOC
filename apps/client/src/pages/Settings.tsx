import {
  ApiOutlined,
  CloudDownloadOutlined,
  DatabaseOutlined,
  ExportOutlined,
  FolderOpenOutlined,
  ImportOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { Button, Card, Col, Divider, Input, InputNumber, Row, Select, Space, Switch, Tag, Typography, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import { aircraftGroups } from "../aircraft";
import { api, download } from "../api";
import { BASEMAPS } from "../basemap";
import { AirportSelect } from "../components/AirportSelect";
import { VolantaImport } from "../components/VolantaImport";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import { openLogFolder, simlinkState } from "../simlink";
import type { AircraftType, Settings } from "../types";
import { deepEqual } from "../utils";

const { Text, Paragraph } = Typography;

export function SettingsPage() {
  const { tr } = useI18n();
  const { settings, navdata, recording, bootstrap, saveSettings, refresh } = useApp();
  const [draft, setDraft] = useState<Settings>(settings);
  const [types, setTypes] = useState<AircraftType[]>([]);
  const [saving, setSaving] = useState(false);
  const [navPath, setNavPath] = useState(settings.navdata_path || "");
  const [navBusy, setNavBusy] = useState(false);
  const [archivePath, setArchivePath] = useState("");
  const [importPath, setImportPath] = useState("");
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [reconnectBusy, setReconnectBusy] = useState(false);
  const sim = simlinkState(recording);

  /** 让 SimLink 立刻重建 SimConnect（否则后台每 5s 自动重试一次）。 */
  const reconnect = async () => {
    setReconnectBusy(true);
    try {
      await api("/local/simlink/reconnect", { method: "POST" });
      await refresh();
      message.success(tr("已请求重新连接，几秒后看状态", "Reconnect requested — check the status in a few seconds"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setReconnectBusy(false);
    }
  };

  const openLogs = async () => {
    const ok = await openLogFolder();
    if (!ok) {
      message.info(`${tr("日志目录", "Log folder")}: ${bootstrap.logs || `${bootstrap.home}/logs`}`);
    }
  };

  useEffect(() => { setDraft(settings); }, [settings]);
  useEffect(() => {
    api<{ items: AircraftType[] }>("/local/aircraft-types").then((d) => setTypes(d.items)).catch(() => undefined);
  }, []);

  const patch = (p: Partial<Settings>) => setDraft((d) => ({ ...d, ...p }));
  const dirty = useMemo(() => !deepEqual(draft, settings), [draft, settings]);

  const discard = () => {
    setDraft(settings);
    setNavPath(settings.navdata_path || "");
    message.info(tr("已放弃未保存的更改", "Unsaved changes discarded"));
  };

  const save = async () => {
    setSaving(true);
    try {
      await saveSettings({ ...draft, navdata_path: draft.navdata_path || null, home_airport: draft.home_airport || null });
      message.success(tr("设置已保存", "Settings saved"));
      await refresh();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const selectNavdata = async () => {
    setNavBusy(true);
    try {
      const status = await api<{ available: boolean; airac?: string; airports?: number; error?: string }>("/local/navdata/select", {
        method: "POST",
        body: JSON.stringify({ path: navPath.trim() || null }),
      });
      await refresh();
      if (status.available) {
        patch({ navdata_path: navPath.trim() });
        message.success(tr("navdata 已加载", "navdata loaded"));
      } else {
        message.warning(status.error || tr("未加载", "not loaded"));
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setNavBusy(false);
    }
  };

  const exportArchive = async () => {
    setArchiveBusy(true);
    try {
      const res = await api<{ path: string; bytes: number }>("/local/export", { method: "POST" });
      setArchivePath(res.path);
      message.success(`${tr("档案已生成", "Archive created")}: ${res.path}`);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setArchiveBusy(false);
    }
  };

  const importArchive = async () => {
    if (!importPath.trim()) return;
    setArchiveBusy(true);
    try {
      await api("/local/import-archive", { method: "POST", body: JSON.stringify({ path: importPath.trim() }) });
      await refresh();
      message.success(tr("档案已导入（原库已自动备份）", "Archive imported (previous DB backed up)"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setArchiveBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("设置", "Settings")}</h2>
          <p>{tr("数据源、记录策略、单位与档案；个人模式默认不上传任何数据", "Data sources, recording, units and archive. Personal mode uploads nothing by default.")}</p>
        </div>
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>{tr("保存设置", "Save")}</Button>
      </div>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <Card className="panel" variant="borderless" title={<Space><DatabaseOutlined />{tr("数据源", "Data sources")}</Space>}>
            <Space direction="vertical" style={{ width: "100%" }} size={10}>
              <div className="setting-row">
                <div>
                  <div className="label">{tr("navdata（Little Navmap / Navigraph SQLite）", "navdata (Little Navmap / Navigraph SQLite)")}</div>
                  <div className="hint">{navdata.available ? `AIRAC ${navdata.airac} · ${navdata.airports} ${tr("机场", "airports")}` : navdata.error}</div>
                </div>
                <Tag color={navdata.available ? "blue" : "default"}>{navdata.available ? tr("已加载", "loaded") : tr("未加载", "missing")}</Tag>
              </div>
              <Input
                value={navPath}
                onChange={(e) => setNavPath(e.target.value)}
                placeholder="%APPDATA%\\ABarthel\\little_navmap_db\\little_navmap_navigraph.sqlite"
                prefix={<FolderOpenOutlined />}
              />
              <Space>
                <Button icon={<DatabaseOutlined />} loading={navBusy} onClick={() => void selectNavdata()}>{tr("检测并保存", "Check & save")}</Button>
                <Button onClick={() => { setNavPath(""); patch({ navdata_path: null }); }}>{tr("清除", "Clear")}</Button>
              </Space>
              <Divider style={{ margin: "8px 0" }} />
              <div className="setting-row">
                <div>
                  <div className="label">SimLink</div>
                  <div className="hint">
                    {tr(sim.zh, sim.en)}
                    {sim.level === "online" ? ` · ${recording.simlink_version || ""}` : ""}
                    {sim.source ? ` · source=${sim.source}` : ""}
                  </div>
                  {sim.level === "no-sim" && sim.error ? (
                    <div className="hint" style={{ opacity: 0.75 }}>{sim.error}</div>
                  ) : null}
                  {sim.level === "offline" ? (
                    <div className="hint">
                      {tr("启动 aoc-simlink.exe（或 Tauri 客户端）后会自动发现。",
                        "Start aoc-simlink.exe (or the Tauri client) and it is picked up automatically.")}
                    </div>
                  ) : null}
                </div>
                <Space size={6} wrap>
                  <Button size="small" icon={<ReloadOutlined />} onClick={() => void refresh()}>
                    {tr("刷新", "Refresh")}
                  </Button>
                  <Button size="small" icon={<ApiOutlined />} loading={reconnectBusy}
                    disabled={!recording.simlink_connected} onClick={() => void reconnect()}>
                    {tr("重新连接", "Reconnect")}
                  </Button>
                  <Button size="small" icon={<FolderOpenOutlined />} onClick={() => void openLogs()}>
                    {tr("日志目录", "Logs")}
                  </Button>
                </Space>
              </div>
              <div className="setting-row">
                <div>
                  <div className="label">{tr("Volanta 同步", "Volanta sync")}</div>
                  <div className="hint">{tr("非官方接口，可能失效；AOC 本地日志始终是权威", "Unofficial API, may break; AOC local logbook stays authoritative")}</div>
                </div>
                <Switch checked={draft.volanta_enabled} onChange={(v) => patch({ volanta_enabled: v })} />
              </div>
              <div className="setting-row">
                <div><div className="label">{tr("启动时自动尝试同步（预留）", "Auto sync on launch (reserved)")}</div><div className="hint">{tr("M1 不保存 token，自动同步需先接入系统凭据库", "M1 never stores the token; auto sync waits for OS credential storage")}</div></div>
                <Switch checked={false} disabled />
              </div>
              <Divider style={{ margin: "4px 0" }} />
              <VolantaImport csvRows={4} onImported={() => refresh()} />
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card className="panel" variant="borderless" title={tr("记录策略", "Recording")}>
            <Space direction="vertical" style={{ width: "100%" }} size={4}>
              <div className="setting-row">
                <div>
                  <div className="label">{tr("自动开始记录", "Auto start")}</div>
                  <div className="hint">
                    {draft.auto_start_on === "takeoff"
                      ? tr("离地 5s 后开始（旧行为，会丢掉起飞前滑行）", "Starts 5s after liftoff (legacy: loses taxi-out)")
                      : tr("发动机/滑行满足条件 10s 后开始，含起飞前滑行", "Starts 10s after engine start/taxi, includes taxi-out")}
                  </div>
                </div>
                <Space size={8}>
                  <Select
                    value={draft.auto_start_on}
                    onChange={(v) => patch({ auto_start_on: v })}
                    style={{ width: 150 }}
                    options={[
                      { value: "engine", label: tr("发动机启动", "Engine start") },
                      { value: "taxi", label: tr("开始滑行", "Taxi") },
                      { value: "takeoff", label: tr("离地后", "Takeoff") },
                    ]}
                  />
                  <Switch checked={draft.auto_start} onChange={(v) => patch({ auto_start: v })} />
                </Space>
              </div>
              <div className="setting-row">
                <div>
                  <div className="label">{tr("自动结束记录", "Auto stop")}</div>
                  <div className="hint">
                    {tr("连续静止或停机刹车保持；到机位才收尾", "Continuous stop or parking brake; stops at the gate")}
                  </div>
                </div>
                <Space size={8}>
                  <InputNumber
                    value={draft.auto_stop_hold_s}
                    min={30}
                    max={300}
                    step={10}
                    style={{ width: 100 }}
                    addonAfter={tr("秒", "s")}
                    onChange={(v) => patch({ auto_stop_hold_s: Number(v) || 60 })}
                  />
                  <Switch checked={draft.auto_stop} onChange={(v) => patch({ auto_stop: v })} />
                </Space>
              </div>
              <div className="setting-row">
                <div><div className="label">{tr("记录滑行段", "Record taxi")}</div><div className="hint">{tr("M1 固定记录滑行（用于滑跑距离），M2 可裁剪", "M1 always records taxi for landing roll; trim in M2")}</div></div>
                <Switch checked disabled />
              </div>
              <div className="setting-row">
                <div><div className="label">{tr("采样密度", "Sampling density")}</div><div className="hint">{tr("自适应：直行 20s、转弯 2s、进近 1s", "Adaptive: straight 20s, turn 2s, approach 1s")}</div></div>
                <Select
                  value={draft.density}
                  onChange={(v) => patch({ density: v })}
                  style={{ width: 140 }}
                  options={[
                    { value: "adaptive", label: tr("自适应", "Adaptive") },
                    { value: "fixed_1hz", label: "1 Hz" },
                    { value: "fixed_2hz", label: "2 Hz" },
                  ]}
                />
              </div>
              <div className="setting-row">
                <div><div className="label">{tr("最大间隔", "Max gap")}</div></div>
                <InputNumber min={5} max={120} value={draft.max_gap_s} onChange={(v) => patch({ max_gap_s: Number(v || 45) })} addonAfter="s" />
              </div>
              <div className="setting-row">
                <div><div className="label">{tr("转弯阈值", "Turn threshold")}</div></div>
                <InputNumber min={1} max={12} step={0.5} value={draft.turn_threshold_dps} onChange={(v) => patch({ turn_threshold_dps: Number(v || 4) })} addonAfter="°/s" />
              </div>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card className="panel" variant="borderless" title={tr("单位与外观", "Units & appearance")}>
            <Space direction="vertical" style={{ width: "100%" }} size={4}>
              <div className="setting-row">
                <div className="label">{tr("主题", "Theme")}</div>
                <Select
                  value={draft.theme}
                  onChange={(v) => patch({ theme: v })}
                  style={{ width: 150 }}
                  options={[
                    { value: "system", label: tr("跟随系统", "System") },
                    { value: "dark", label: tr("深色", "Dark") },
                    { value: "light", label: tr("浅色", "Light") },
                  ]}
                />
              </div>
              <div className="setting-row">
                <div className="label">{tr("语言", "Language")}</div>
                <Select
                  value={draft.language}
                  onChange={(v) => patch({ language: v })}
                  style={{ width: 150 }}
                  options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]}
                />
              </div>
              <div className="setting-row">
                <div className="label">{tr("高度单位", "Altitude")}</div>
                <Select value={draft.units.altitude} onChange={(v) => patch({ units: { ...draft.units, altitude: v } })} style={{ width: 150 }} options={[{ value: "ft", label: "ft" }, { value: "m", label: "m" }]} />
              </div>
              <div className="setting-row">
                <div className="label">{tr("速度单位", "Speed")}</div>
                <Select value={draft.units.speed} onChange={(v) => patch({ units: { ...draft.units, speed: v } })} style={{ width: 150 }} options={[{ value: "kt", label: "kt" }, { value: "kmh", label: "km/h" }]} />
              </div>
              <div className="setting-row">
                <div className="label">{tr("重量单位", "Weight")}</div>
                <Select value={draft.units.weight} onChange={(v) => patch({ units: { ...draft.units, weight: v } })} style={{ width: 150 }} options={[{ value: "kg", label: "kg" }, { value: "lb", label: "lb" }]} />
              </div>
              <Divider style={{ margin: "8px 0" }} />
              <div className="setting-row">
                <div><div className="label">{tr("默认呼号", "Default callsign")}</div></div>
                <Input value={draft.callsign} onChange={(e) => patch({ callsign: e.target.value })} style={{ width: 150 }} />
              </div>
              <div className="setting-row">
                <div>
                  <div className="label">{tr("默认机型", "Default aircraft")}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {tr("仅用于航路规划/推荐；录制按 SimLink 的机型标题自动识别，识别不到才用它",
                      "Used for route planning/recommendations only; recordings detect the type from SimLink's aircraft title and fall back to this")}
                  </div>
                </div>
                <Select
                  value={draft.aircraft_type}
                  onChange={(v) => patch({ aircraft_type: v })}
                  style={{ width: 180 }}
                  showSearch
                  optionFilterProp="label"
                  options={aircraftGroups(types, tr)}
                />
              </div>
              <div className="setting-row">
                <div><div className="label">{tr("常用基地", "Home base")}</div></div>
                <div style={{ width: 200 }}><AirportSelect value={draft.home_airport} onChange={(v) => patch({ home_airport: v })} allowClear /></div>
              </div>
              <div className="setting-row">
                <div>
                  <div className="label">{tr("地图底图", "Basemap")}</div>
                  <div className="hint">{tr("离线底图为内置经纬网，不联网；卫星底图需外网", "Offline uses a built-in graticule (no network); satellite needs internet")}</div>
                </div>
                <Select
                  value={draft.map_style}
                  onChange={(v) => patch({ map_style: v })}
                  style={{ width: 190 }}
                  options={BASEMAPS.map((b) => ({ value: b.id, label: tr(b.zh, b.en) }))}
                />
              </div>
              {draft.map_style === "custom" ? (
                <div className="setting-row">
                  <div><div className="label">{tr("自定义瓦片 URL", "Custom tile URL")}</div><div className="hint">{tr("支持 {z}/{x}/{y}；留空回退 OSM", "Supports {z}/{x}/{y}; empty falls back to OSM")}</div></div>
                  <Input value={draft.tiles_url || ""} onChange={(e) => patch({ tiles_url: e.target.value || null })} style={{ width: 220 }} placeholder="https://…/{z}/{x}/{y}.png" />
                </div>
              ) : null}
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card className="panel" variant="borderless" title={tr("档案与隐私", "Archive & privacy")}>
            <Space direction="vertical" style={{ width: "100%" }} size={10}>
              <Paragraph className="muted" style={{ margin: 0, fontSize: 12 }}>
                {tr(
                  "个人模式默认零上传。档案 zip 包含 aoc.db、轨迹与设置，可用于换机/备份；导入前会自动备份当前库。",
                  "Personal mode uploads nothing. The archive zip contains aoc.db, tracks and settings; import backs up the current DB first.",
                )}
              </Paragraph>
              <div className="source-card">
                <div className="source-title">{tr("数据目录", "Data home")}<Tag>{bootstrap.version}</Tag></div>
                <div className="source-value">{bootstrap.home}</div>
              </div>
              <Space wrap>
                <Button icon={<ExportOutlined />} loading={archiveBusy} onClick={() => void exportArchive()}>{tr("生成档案 zip", "Create archive")}</Button>
                <Button icon={<CloudDownloadOutlined />} onClick={() => void download("/local/export/archive", "AOC-archive.zip").catch((e: Error) => message.error(e.message))}>
                  {tr("下载档案", "Download archive")}
                </Button>
              </Space>
              {archivePath ? <Text className="muted" style={{ fontSize: 12 }}>{archivePath}</Text> : null}
              <Input value={importPath} onChange={(e) => setImportPath(e.target.value)} placeholder={tr("档案 zip 的绝对路径", "Absolute path to archive zip")} prefix={<ImportOutlined />} />
              <Button loading={archiveBusy} onClick={() => void importArchive()}>{tr("导入档案（覆盖本地库）", "Import archive (replaces local DB)")}</Button>
              <Divider style={{ margin: "6px 0" }} />
              <div className="setting-row">
                <div><div className="label">{tr("公司模式", "Company mode")}</div><div className="hint">{tr("M2 功能，入口在发布后开放", "M2 feature, enabled after release")}</div></div>
                <Tag>{tr("未开放", "coming soon")}</Tag>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {dirty ? (
        <div className="save-float" role="status" aria-live="polite">
          <div>
            <div className="label">{tr("设置有未保存的更改", "Unsaved changes")}</div>
            <div className="hint">{tr("点击保存后才会生效", "Changes take effect after saving")}</div>
          </div>
          <Space size={8}>
            <Button size="small" onClick={discard}>{tr("放弃", "Discard")}</Button>
            <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>
              {tr("保存", "Save")}
            </Button>
          </Space>
        </div>
      ) : null}
    </div>
  );
}
