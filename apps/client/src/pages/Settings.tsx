import {
  CloudDownloadOutlined,
  ExclamationCircleOutlined,
  ExportOutlined,
  FolderOpenOutlined,
  ImportOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import {
  Button, Card, Col, Divider, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Switch, Tag,
  Typography, message,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { aircraftGroups } from "../aircraft";
import { api, download } from "../api";
import { BASEMAPS } from "../basemap";
import { AirportSelect } from "../components/AirportSelect";
import { NavdataPanel } from "../components/NavdataPanel";
import { RunwayOverrideCard } from "../components/RunwayOverrideCard";
import { SimlinkPanel } from "../components/SimlinkPanel";
import { StandNoticeCard } from "../components/StandNoticeCard";
import { TerminalRulesCard } from "../components/TerminalRulesCard";
import { VolantaImport } from "../components/VolantaImport";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import { setLeaveGuard } from "../leaveGuard";
import type { AircraftType, Settings } from "../types";
import { deepEqual } from "../utils";

const { Text, Paragraph } = Typography;

export function SettingsPage() {
  const { tr } = useI18n();
  const { settings, navdata, bootstrap, saveSettings, refresh, openWizard } = useApp();
  const [draft, setDraft] = useState<Settings>(settings);
  const [types, setTypes] = useState<AircraftType[]>([]);
  const [saving, setSaving] = useState(false);
  const [archivePath, setArchivePath] = useState("");
  const [importPath, setImportPath] = useState("");
  const [archiveBusy, setArchiveBusy] = useState(false);

  useEffect(() => { setDraft(settings); }, [settings]);
  useEffect(() => {
    api<{ items: AircraftType[] }>("/local/aircraft-types").then((d) => setTypes(d.items)).catch(() => undefined);
  }, []);

  const patch = (p: Partial<Settings>) => setDraft((d) => ({ ...d, ...p }));
  const dirty = useMemo(() => !deepEqual(draft, settings), [draft, settings]);

  /** UI-10：有未保存改动时，切页/关窗口先确认（不再是「只有右下角一条浮条」）。 */
  useEffect(() => {
    if (!dirty) {
      setLeaveGuard(null);
      return undefined;
    }
    setLeaveGuard(() => new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: tr("设置有未保存的更改", "Unsaved settings"),
        content: tr("离开这一页会丢掉刚才的修改（主题/语言等保存后才生效）。确认离开？",
          "Leaving this page discards your edits (theme/language apply after saving). Leave anyway?"),
        okText: tr("放弃并离开", "Discard & leave"),
        okButtonProps: { danger: true },
        cancelText: tr("留下继续编辑", "Stay"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    }));
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // 老式浏览器/WebView 需要设置 returnValue 才会弹确认
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      setLeaveGuard(null);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [dirty, tr]);

  const discard = () => {
    setDraft(settings);
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
          <Card
            className="panel"
            variant="borderless"
            title={<Space><FolderOpenOutlined />{tr("数据源", "Data sources")}</Space>}
            extra={<Button size="small" onClick={openWizard}>{tr("重新运行向导", "Re-run wizard")}</Button>}
          >
            <Space direction="vertical" style={{ width: "100%" }} size={10}>
              {/* IA-10：navdata 选择块与首次向导共用（同一份状态/错误处理） */}
              <NavdataPanel
                onLoaded={(status) => patch({ navdata_path: status.available ? status.path : null })}
              />
              <Divider style={{ margin: "8px 0" }} />
              <div className="setting-row">
                <div>
                  <div className="label">
                    {tr("场景库数据（游戏内跑道 + 停机位）", "Scenery data (runways & stands)")}
                  </div>
                  <div className="hint">
                    {navdata.scenery_available
                      ? tr(`游戏内数据已启用：${navdata.scenery_path || ""}`,
                        `In-game data enabled: ${navdata.scenery_path || ""}`)
                      : tr("未找到 little_navmap_msfs24.sqlite：跑道与机位回落现实 navdata（机位只有编号）",
                        "little_navmap_msfs24.sqlite not found — runways and stands fall back to navdata (ident only)")}
                  </div>
                </div>
                <Tag color={navdata.scenery_available ? "green" : "default"}>
                  {navdata.runway_data_source || "auto"}
                </Tag>
              </div>
              <Input
                value={draft.scenery_navdata_path || ""}
                onChange={(e) => patch({ scenery_navdata_path: e.target.value || null })}
                placeholder="%APPDATA%\\ABarthel\\little_navmap_db\\little_navmap_msfs24.sqlite"
                prefix={<FolderOpenOutlined />}
              />
              <Select
                value={draft.runway_data_source || "auto"}
                onChange={(v) => patch({ runway_data_source: v })}
                options={[
                  { value: "auto", label: tr("自动（场景库命中优先）", "Auto (scenery first)") },
                  { value: "scenery", label: tr("只用场景库（游戏内）", "Scenery only (in-game)") },
                  { value: "navdata", label: tr("只用现实 navdata", "navdata only") },
                ]}
              />
              <Divider style={{ margin: "8px 0" }} />
              {/* IA-10：SimLink 状态块与首次向导共用 */}
              <SimlinkPanel />
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

        {/* §36 兜底 C（1.4）：场景库扫不到 / add-on 机场的手工跑道覆盖 */}
        <Col xs={24} lg={12}>
          <RunwayOverrideCard />
        </Col>

        {/* docs/12：到达前预计停机位提醒（阈值 / 通道 / Hoppie）与航站楼规则 */}
        <Col xs={24} lg={12}>
          <StandNoticeCard draft={draft} patch={patch} />
        </Col>
        <Col xs={24} lg={12}>
          <TerminalRulesCard />
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
              {/* UI-10 / D-10：主题与语言保持「保存后生效」，但在控件旁写清楚，避免被当成切换失效 */}
              <div className="setting-row">
                <div>
                  <div className="label">{tr("主题", "Theme")}</div>
                  <div className="hint">{tr("保存后生效", "Applies after saving")}</div>
                </div>
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
                <div>
                  <div className="label">{tr("语言", "Language")}</div>
                  <div className="hint">{tr("保存后生效", "Applies after saving")}</div>
                </div>
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
              {/* UI-10：覆盖本地库是不可逆操作（旧库会被自动备份），先确认再提交 */}
              <Popconfirm
                title={tr("导入档案会覆盖本地数据库", "Importing replaces the local database")}
                description={tr("当前的 aoc.db、轨迹与设置会被替换（旧库会自动备份）。确认导入？",
                  "The current aoc.db, tracks and settings are replaced (the old DB is backed up first). Continue?")}
                okText={tr("导入并覆盖", "Import & overwrite")}
                okButtonProps={{ danger: true }}
                cancelText={tr("返回", "Back")}
                disabled={!importPath.trim()}
                onConfirm={() => void importArchive()}
              >
                <Button loading={archiveBusy} disabled={!importPath.trim()} danger>
                  {tr("导入档案（覆盖本地库）", "Import archive (replaces local DB)")}
                </Button>
              </Popconfirm>
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
        <div className="save-float save-float-dirty" role="status" aria-live="polite">
          <div>
            <div className="label">
              <ExclamationCircleOutlined style={{ color: "#f59e0b", marginRight: 6 }} />
              {tr("有未保存的更改（离开将丢失）", "Unsaved changes (lost if you leave)")}
            </div>
            <div className="hint">{tr("主题/语言/单位等保存后才生效", "Theme, language and units apply after saving")}</div>
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
