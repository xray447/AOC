import {
  AimOutlined,
  CloudDownloadOutlined,
  CopyOutlined,
  ExportOutlined,
  RocketOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, Descriptions, Empty, Form, InputNumber, Row, Select, Space, Table, Tag, Tooltip, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { aircraftGroups, categoryLabel } from "../aircraft";
import { api, download } from "../api";
import { AirportSelect } from "../components/AirportSelect";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { AircraftType, RouteResult } from "../types";

const { Text } = Typography;

const statusMeta: Record<string, { zh: string; en: string; color: string }> = {
  OK: { zh: "可用航路", en: "Route available", color: "success" },
  REQUIRES_SIMBRIEF: { zh: "请使用 SimBrief", en: "Use SimBrief", color: "warning" },
  NO_ROUTE: { zh: "无航路", en: "No route", color: "error" },
  NO_AIRPORT: { zh: "机场不在 navdata", en: "Airport missing", color: "error" },
  NAVDATA_MISSING: { zh: "缺少 navdata", en: "navdata missing", color: "default" },
};

const coverageMeta: Record<string, { zh: string; en: string; color: string }> = {
  AIP: { zh: "AIP 官方", en: "AIP", color: "purple" },
  HIGH_ALT_AIRWAY: { zh: "高空航路覆盖", en: "High-alt coverage", color: "green" },
  NO_HIGH_ALT: { zh: "无高空覆盖", en: "No high-alt coverage", color: "red" },
  OCEANIC: { zh: "跨洋", en: "Oceanic", color: "blue" },
  NO_DATA: { zh: "未检查", en: "Not checked", color: "default" },
};

export function RoutePlanner() {
  const { tr } = useI18n();
  const { settings, navdata } = useApp();
  const [params] = useSearchParams();
  const [dep, setDep] = useState(params.get("dep") || "");
  const [arr, setArr] = useState(params.get("arr") || "");
  const [cruiseFl, setCruiseFl] = useState(settings.aircraft_type ? 350 : 350);
  const [aircraft, setAircraft] = useState(settings.aircraft_type);
  const [types, setTypes] = useState<AircraftType[]>([]);
  const [result, setResult] = useState<RouteResult | null>(null);
  const [simbrief, setSimbrief] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<{ items: AircraftType[] }>("/local/aircraft-types").then((d) => setTypes(d.items)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (dep.length !== 4) { setSimbrief(""); return; }
    if (arr.length !== 4) { setSimbrief(""); return; }
    const timer = window.setTimeout(async () => {
      try {
        const d = await api<{ simbrief_url: string }>(
          `/local/routes/simbrief?dep=${dep}&arr=${arr}&aircraft_type=${encodeURIComponent(aircraft)}&cruise_fl=${cruiseFl}`);
        setSimbrief(d.simbrief_url);
      } catch {
        setSimbrief("");
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [dep, arr, aircraft, cruiseFl]);

  const generate = async () => {
    if (dep.length !== 4 || arr.length !== 4) {
      message.warning(tr("请输入 4 位 ICAO 起降机场", "Enter 4-letter ICAO airports"));
      return;
    }
    setLoading(true);
    try {
      const res = await api<RouteResult>("/local/routes/generate", {
        method: "POST",
        body: JSON.stringify({ dep, arr, aircraft_type: aircraft, cruise_fl: cruiseFl }),
      });
      setResult(res);
      if (res.simbrief_url) setSimbrief(res.simbrief_url);
      if (res.status === "OK") message.success(tr("航路已生成", "Route generated"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success(tr("已复制", "Copied"));
    } catch {
      message.error(tr("复制失败", "Copy failed"));
    }
  };

  const exportPln = async () => {
    try {
      await download("/local/routes/export?format=pln", `${dep}-${arr}.pln`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dep, arr, aircraft_type: aircraft, cruise_fl: cruiseFl }),
      });
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const selectedType = types.find((t) => t.icao === aircraft);
  const meta = result ? statusMeta[result.status] : null;
  const altitudeLabel = result?.altitude_valid === true
    ? tr("高度已校验", "Altitude verified")
    : result?.altitude_valid === false
      ? tr("高度不覆盖", "Altitude not covered")
      : tr("高度未校验", "Altitude unverified");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("航路规划", "Route planning")}</h2>
          <p>{tr("AIP 官方航路 → 覆盖检查 → Pre-train 图；任一环节失败都会给出 SimBrief 链接", "AIP → coverage → graph; any failure falls back to SimBrief")}</p>
        </div>
      </div>

      <Card className="panel" variant="borderless">
        <Form layout="vertical">
          <Row gutter={[16, 0]}>
            <Col xs={24} md={5}>
              <Form.Item label={tr("起飞机场", "Departure")}>
                <AirportSelect value={dep} onChange={setDep} placeholder="ZBAA" />
              </Form.Item>
            </Col>
            <Col xs={24} md={5}>
              <Form.Item label={tr("到达机场", "Arrival")}>
                <AirportSelect value={arr} onChange={setArr} placeholder="ZSSS" />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item label={tr("巡航高度", "Cruise FL")}>
                <InputNumber min={10} max={450} step={5} value={cruiseFl} onChange={(v) => setCruiseFl(Number(v || 350))} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={5}>
              <Form.Item
                label={
                  <Space size={6}>
                    {tr("机型", "Aircraft")}
                    {selectedType ? <Tag color="blue">{categoryLabel(selectedType.category, tr)}</Tag> : null}
                  </Space>
                }
              >
                <Select
                  value={aircraft}
                  onChange={setAircraft}
                  showSearch
                  optionFilterProp="label"
                  options={aircraftGroups(types, tr)}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={5}>
              <Form.Item label=" ">
                <Space>
                  <Button type="primary" icon={<RocketOutlined />} loading={loading} onClick={() => void generate()}>
                    {tr("生成航路", "Generate")}
                  </Button>
                  <Tooltip title={tr("选定机场即可生成，不依赖航路结果", "Generated as soon as both airports are set")}>
                    <Button icon={<ExportOutlined />} disabled={!simbrief} onClick={() => window.open(simbrief, "_blank")}>
                      SimBrief
                    </Button>
                  </Tooltip>
                </Space>
              </Form.Item>
            </Col>
          </Row>
        </Form>
        {!navdata.available ? (
          <Alert
            type="warning"
            showIcon
            message={tr("navdata 未导入：航路生成会返回 NAVDATA_MISSING，但仍可使用 SimBrief", "navdata missing: route generation returns NAVDATA_MISSING, SimBrief still works")}
          />
        ) : null}
      </Card>

      {result ? (
        <>
          <Space wrap>
            <Tag color={meta?.color}>{meta ? tr(meta.zh, meta.en) : result.status}</Tag>
            <Tag color="geekblue">{tr("来源", "Source")} {result.route_source}</Tag>
            <Tag color={coverageMeta[result.coverage]?.color}>{coverageMeta[result.coverage] ? tr(coverageMeta[result.coverage].zh, coverageMeta[result.coverage].en) : result.coverage}</Tag>
            <Tag color={result.altitude_valid === true ? "green" : result.altitude_valid === false ? "red" : "default"}>{altitudeLabel}</Tag>
            {result.airac ? <Tag>AIRAC {result.airac}</Tag> : null}
            <Tag>{Math.round(result.elapsed_ms)} ms</Tag>
          </Space>

          {result.warnings.length ? (
            <Alert
              type={result.status === "OK" ? "warning" : "error"}
              showIcon
              icon={<WarningOutlined />}
              message={tr("航路提示", "Route warnings")}
              description={<ul style={{ margin: 0, paddingLeft: 18 }}>{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
            />
          ) : null}

          {result.route ? (
            <Card
              className="panel"
              variant="borderless"
              title={tr("航路", "Route")}
              extra={
                <Space>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => void copy(result.route!)}>{tr("复制", "Copy")}</Button>
                  <Button size="small" icon={<CloudDownloadOutlined />} onClick={() => void exportPln()}>{tr("导出 .pln", "Export .pln")}</Button>
                </Space>
              }
            >
              <div className="route-box">{result.tokens_full.join(" ") || result.route}</div>
              <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} style={{ marginTop: 12 }}>
                <Descriptions.Item label={tr("距离", "Distance")}>{result.distance_nm ? `${result.distance_nm} NM` : "—"}</Descriptions.Item>
                <Descriptions.Item label={tr("大圆距离", "GCD")}>{result.gcd_nm ? `${result.gcd_nm} NM` : "—"}</Descriptions.Item>
                <Descriptions.Item label={tr("巡航", "Cruise")}>FL{result.cruise_fl}</Descriptions.Item>
                <Descriptions.Item label={tr("AIP 版本", "AIP version")}>{result.aip_version || "—"}</Descriptions.Item>
              </Descriptions>
            </Card>
          ) : result.status === "REQUIRES_SIMBRIEF" || result.status === "NAVDATA_MISSING" ? (
            <Card className="panel" variant="borderless">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={tr("本地没有可用航路，请使用 SimBrief 生成并导入模拟器", "No local route available. Use SimBrief and load it into the simulator.")}
              >
                <Button type="primary" icon={<ExportOutlined />} disabled={!simbrief} onClick={() => window.open(simbrief, "_blank")}>
                  {tr("打开 SimBrief", "Open SimBrief")}
                </Button>
              </Empty>
            </Card>
          ) : null}

          <Row gutter={[12, 12]}>
            <Col xs={24} md={8}>
              <Card className="panel" variant="borderless" title={tr("SID 候选", "SID options")} size="small">
                {result.sid_options.length ? <Space wrap>{result.sid_options.map((s) => <Tag color="blue" key={s.name}>{s.name}{s.runway ? ` · ${s.runway}` : ""}</Tag>)}</Space> : <Text className="muted">{tr("无（或来自 SimBrief）", "None (or from SimBrief)")}</Text>}
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card className="panel" variant="borderless" title={tr("STAR 候选", "STAR options")} size="small">
                {result.star_options.length ? <Space wrap>{result.star_options.map((s) => <Tag color="purple" key={s.name}>{s.name}{s.runway ? ` · ${s.runway}` : ""}</Tag>)}</Space> : <Text className="muted">{tr("无（或来自 SimBrief）", "None (or from SimBrief)")}</Text>}
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card className="panel" variant="borderless" title={tr("跑道候选", "Runways")} size="small">
                {result.runway_options.length ? (
                  <Space wrap>
                    {result.runway_options.map((r) => (
                      <Tag key={`${r.airport}-${r.ident}`}>{r.airport}/{r.ident}{r.length_m ? ` · ${Math.round(r.length_m)}m` : ""}{r.ils ? " · ILS" : ""}</Tag>
                    ))}
                  </Space>
                ) : <Text className="muted">{tr("navdata 无跑道数据", "No runway data in navdata")}</Text>}
              </Card>
            </Col>
          </Row>

          {result.coverage_gaps.length ? (
            <Card className="panel" variant="borderless" title={tr("覆盖缺口", "Coverage gaps")} size="small">
              <Table
                size="small"
                rowKey={(r) => `${r.start_nm}-${r.end_nm}`}
                pagination={false}
                dataSource={result.coverage_gaps}
                columns={[
                  { title: tr("起点", "From"), dataIndex: "start_nm", render: (v) => `${v} NM` },
                  { title: tr("终点", "To"), dataIndex: "end_nm", render: (v) => `${v} NM` },
                  { title: tr("缺口", "Length"), dataIndex: "length_nm", render: (v) => v ? `${v} NM` : "—" },
                  { title: tr("中心", "Center"), key: "center", render: (_, r) => r.center_lat != null ? `${r.center_lat?.toFixed(1)}, ${r.center_lon?.toFixed(1)}` : "—" },
                ]}
              />
            </Card>
          ) : null}

          <Card className="panel" variant="borderless" title={tr("尝试链路", "Attempts")} size="small">
            <Table
              size="small"
              rowKey={(r, i) => `${r.provider}-${i}`}
              pagination={false}
              dataSource={result.attempts}
              columns={[
                { title: "Provider", dataIndex: "provider" },
                { title: tr("结果", "Status"), dataIndex: "status", render: (v) => <Tag color={v === "ok" ? "green" : v === "deferred" ? "orange" : "default"}>{v}</Tag> },
                { title: tr("原因", "Reason"), dataIndex: "reason", render: (v) => v || "—" },
                { title: "ms", dataIndex: "ms" },
              ]}
            />
          </Card>

          {simbrief ? (
            <Card className="panel" variant="borderless" size="small" title="SimBrief">
              <Space direction="vertical" style={{ width: "100%" }}>
                <Text className="muted" style={{ fontSize: 12 }}>
                  {tr("链接始终生成，与航路结果无关；有航路时 SimBrief 会预填 route。", "The link is always generated. When a route exists it is pre-filled.")}
                </Text>
                <Space>
                  <Button icon={<CopyOutlined />} onClick={() => void copy(simbrief)}>{tr("复制链接", "Copy link")}</Button>
                  <Button type="primary" icon={<AimOutlined />} onClick={() => window.open(simbrief, "_blank")}>{tr("打开 SimBrief", "Open SimBrief")}</Button>
                </Space>
              </Space>
            </Card>
          ) : null}
        </>
      ) : (
        <div className="panel empty-hint">
          {tr("选择起降机场后点击「生成航路」。没有 navdata 时会直接给出 SimBrief 链接。", "Pick airports and generate. Without navdata you get a SimBrief link.")}
        </div>
      )}
    </div>
  );
}
