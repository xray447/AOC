import { CompassOutlined, RocketOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, InputNumber, Row, Select, Slider, Space, Switch, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { aircraftGroups, categoryLabel } from "../aircraft";
import { api } from "../api";
import { AirportSelect } from "../components/AirportSelect";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { AircraftType, Candidate, RecommendResult } from "../types";

const { Text, Paragraph } = Typography;

export function Recommend() {
  const { tr } = useI18n();
  const { settings, navdata } = useApp();
  const navigate = useNavigate();
  const [minutes, setMinutes] = useState(90);
  const [base, setBase] = useState<string>(settings.home_airport || "");
  const [aircraft, setAircraft] = useState(settings.aircraft_type);
  const [never, setNever] = useState(settings.recommend.only_never_visited);
  const [newCountry, setNewCountry] = useState(settings.recommend.prefer_new_country);
  const [types, setTypes] = useState<AircraftType[]>([]);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<{ items: AircraftType[] }>("/local/aircraft-types").then((d) => setTypes(d.items)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!base && settings.home_airport) setBase(settings.home_airport);
  }, [settings.home_airport, base]);

  const submit = async () => {
    if (!base) {
      message.warning(tr("请选择出发机场", "Choose a departure airport"));
      return;
    }
    setLoading(true);
    try {
      const res = await api<RecommendResult>("/local/recommend", {
        method: "POST",
        body: JSON.stringify({
          available_minutes: minutes,
          base_icao: base,
          aircraft_type: aircraft,
          only_never_visited: never,
          prefer_new_country: newCountry,
          limit: 8,
        }),
      });
      setResult(res);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const goRoute = (c: Candidate) => navigate(`/route?dep=${encodeURIComponent(base)}&arr=${encodeURIComponent(c.icao)}`);
  const selectedType = types.find((t) => t.icao === aircraft);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("去一个没去过的地方", "Fly somewhere new")}</h2>
          <p>{tr("按可用时间筛选机场，优先从未到达、且是新的国家/地区", "Filter by available time, preferring never-visited airports and new countries")}</p>
        </div>
      </div>

      {!navdata.available ? (
        <Alert
          type="warning"
          showIcon
          message={tr("需要 navdata 才能推荐机场", "navdata is required for discovery")}
          description={tr("机场距离、跑道与程序来自 navdata。导入后即可使用；没有 navdata 时仍可手动选机场并走 SimBrief。", "Distances and runways come from navdata. Import it to use discovery; manual SimBrief still works without it.")}
          action={<Button size="small" onClick={() => navigate("/settings")}>{tr("去导入", "Import")}</Button>}
        />
      ) : null}

      <Card className="panel" variant="borderless">
        <Form layout="vertical">
          <Row gutter={[16, 10]}>
            <Col xs={24} md={12}>
              <Form.Item label={tr("可用时间", "Available time")} style={{ marginBottom: 8 }}>
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Space wrap>
                    {[45, 60, 90, 120, 180, 240].map((v) => (
                      <Tag.CheckableTag key={v} checked={minutes === v} onChange={() => setMinutes(v)}>
                        {v >= 60 ? `${v / 60}h` : `${v}m`}
                      </Tag.CheckableTag>
                    ))}
                    <InputNumber
                      size="small"
                      min={20}
                      max={720}
                      step={15}
                      value={minutes}
                      onChange={(v) => setMinutes(Number(v || 90))}
                      addonAfter={tr("分钟", "min")}
                      style={{ width: 130 }}
                    />
                  </Space>
                  <Slider min={30} max={360} step={15} value={minutes} onChange={setMinutes} tooltip={{ formatter: (v) => `${v} min` }} />
                </Space>
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item label={tr("出发机场", "Departure")}>
                <AirportSelect value={base} onChange={setBase} placeholder="ZBAA" />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
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
                  options={aircraftGroups(types, tr, { withName: true })}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={[16, 0]} align="middle">
            <Col xs={24} md={9}>
              <Space size={20}>
                <span>
                  <Switch checked={never} onChange={setNever} /> <Text>{tr("只去没到达过的", "Never arrived")}</Text>
                </span>
                <span>
                  <Switch checked={newCountry} onChange={setNewCountry} /> <Text>{tr("优先新国家", "Prefer new country")}</Text>
                </span>
              </Space>
            </Col>
            <Col xs={24} md={15} style={{ textAlign: "right" }}>
              <Button type="primary" size="large" icon={<CompassOutlined />} loading={loading} onClick={() => void submit()}>
                {tr("推荐机场", "Discover")}
              </Button>
            </Col>
          </Row>
        </Form>
      </Card>

      {result ? (
        <>
          <Space wrap>
            <Tag icon={<ThunderboltOutlined />}>{tr("候选池", "Pool")} {result.candidates_considered}</Tag>
            <Tag>{tr("出发", "Base")} {result.base_icao}</Tag>
            <span className="muted">{result.generated_at.replace("T", " ").replace("Z", " UTC")}</span>
          </Space>
          {result.warnings.map((w, i) => <Alert key={i} type="warning" showIcon message={w} />)}
          {result.candidates.length ? (
            <div className="card-grid">
              {result.candidates.map((c) => (
                <Card key={c.icao} className="panel airport-card" variant="borderless">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span className="icao">{c.icao}</span>
                    <Tag color={c.country ? "geekblue" : "default"}>{c.country || tr("未知国家", "Unknown")}</Tag>
                  </div>
                  <div className="name">{c.name || c.city || "—"}</div>
                  <Space size={6} wrap>
                    <Tag>{Math.round(c.distance_nm)} NM</Tag>
                    <Tag color="blue">{c.block_minutes >= 60 ? `${Math.floor(c.block_minutes / 60)}h${String(c.block_minutes % 60).padStart(2, "0")}m` : `${c.block_minutes}m`}</Tag>
                    {c.longest_runway_m ? <Tag>{Math.round(c.longest_runway_m)} m</Tag> : null}
                  </Space>
                  <div className="reason-tags">
                    {c.reasons.map((r, i) => <Tag key={i} color={i === 0 ? "cyan" : undefined}>{r}</Tag>)}
                  </div>
                  <div className="card-actions">
                    <Button type="primary" size="small" icon={<RocketOutlined />} onClick={() => goRoute(c)}>
                      {tr("生成航路", "Plan route")}
                    </Button>
                    <Button size="small" onClick={() => navigate(`/map?focus=${c.icao}`)}>{tr("看地图", "Map")}</Button>
                  </div>
                </Card>
              ))}
            </div>
          ) : (
            <Empty description={tr("没有满足条件的机场，试试放宽时间或关闭筛选", "No airports matched. Try relaxing the filters.")} />
          )}
        </>
      ) : (
        <div className="panel empty-hint">
          <Paragraph className="muted" style={{ marginBottom: 6 }}>
            {tr("输入可用时间和出发机场后点击「推荐机场」。", "Set your available time and departure, then hit Discover.")}
          </Paragraph>
          <Text className="muted" style={{ fontSize: 12 }}>
            {tr("算法：0.6–1.4 倍目标航程内筛选 → 未飞判定 → 航时估算（含 15 分钟滑行/爬降）→ 评分。", "0.6–1.4× target range → never-visited filter → block-time estimate (15 min taxi/climb/descent) → scoring.")}
          </Text>
        </div>
      )}
    </div>
  );
}
