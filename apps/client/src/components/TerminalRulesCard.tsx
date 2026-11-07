import { DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag,
  Typography, message,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import type { AirportDetail, AirportTerminal, StandMatcher, TerminalRule } from "../types";
import { AirportSelect } from "./AirportSelect";

const { Text } = Typography;

type MatcherType = "number_range" | "area_prefix" | "radius" | "explicit";

/** 把 "100-199,300-399" 解析成 [[100,199],[300,399]]；非法项返回 null。 */
function parseRanges(text: string): [number, number][] | null {
  const out: [number, number][] = [];
  for (const raw of text.split(/[,;\s]+/)) {
    if (!raw) continue;
    const match = raw.match(/^(\d+)\s*[-~]\s*(\d+)$/);
    if (match) {
      const low = Number(match[1]);
      const high = Number(match[2]);
      out.push([Math.min(low, high), Math.max(low, high)]);
      continue;
    }
    if (/^\d+$/.test(raw)) {
      out.push([Number(raw), Number(raw)]);
      continue;
    }
    return null;
  }
  return out.length ? out : null;
}

function matcherSummary(matcher: StandMatcher, tr: (zh: string, en: string) => string): string {
  if (matcher.type === "number_range") {
    return `# ${matcher.ranges.map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(", ")}`;
  }
  if (matcher.type === "area_prefix") {
    return `${tr("区域", "area")} ${matcher.prefixes.join("/")}`;
  }
  if (matcher.type === "radius") {
    return `${tr("圆形", "circle")} ${matcher.r_m} m`;
  }
  return matcher.idents.join(", ");
}

/** docs/12 §4.5：航站楼是哪片机位（机场事实）+ 给谁用（承运人规则）。 */
export function TerminalRulesCard({ compact = false }: { compact?: boolean }) {
  const { tr } = useI18n();
  const [icao, setIcao] = useState("ZSSS");
  const [detail, setDetail] = useState<AirportDetail | null>(null);
  const [terminals, setTerminals] = useState<AirportTerminal[]>([]);
  const [rules, setRules] = useState<TerminalRule[]>([]);
  const [busy, setBusy] = useState(false);

  const [termOpen, setTermOpen] = useState(false);
  const [termName, setTermName] = useState("T1");
  const [matcherType, setMatcherType] = useState<MatcherType>("number_range");
  const [rangeText, setRangeText] = useState("100-199,300-399,500-599");
  const [prefixText, setPrefixText] = useState("G");
  const [identsText, setIdentsText] = useState("");
  const [circle, setCircle] = useState<{ lat: number | null; lon: number | null; r_m: number }>({
    lat: null, lon: null, r_m: 900,
  });

  const [ruleOpen, setRuleOpen] = useState(false);
  const [ruleTerminal, setRuleTerminal] = useState("");
  const [ruleScope, setRuleScope] = useState<"DOMESTIC" | "INTERNATIONAL" | "BOTH">("DOMESTIC");
  const [ruleAirlines, setRuleAirlines] = useState("9C,HBH,CXA");

  const load = useCallback(async () => {
    if (!icao) return;
    try {
      const [termRes, detailRes] = await Promise.all([
        api<{ terminals: AirportTerminal[]; rules: TerminalRule[] }>(
          `/local/airports/${icao}/terminals`),
        api<AirportDetail>(`/local/airports/${icao}`),
      ]);
      setTerminals(termRes.terminals);
      setRules(termRes.rules);
      setDetail(detailRes);
    } catch {
      setTerminals([]);
      setRules([]);
      setDetail(null);
    }
  }, [icao]);

  useEffect(() => { void load(); }, [load]);

  const standCount = detail?.stand_count ?? 0;
  const standSource = useMemo(() => {
    const map: Record<string, string> = {
      scenery: tr("游戏内场景库", "in-game scenery"),
      navdata: tr("现实 navdata（只有编号）", "real navdata (ident only)"),
      override: tr("手工覆盖", "manual override"),
      none: tr("无停机位数据", "no stand data"),
    };
    return map[detail?.stand_source || "none"] || detail?.stand_source;
  }, [detail?.stand_source, tr]);

  const buildMatcher = (): StandMatcher | null => {
    if (matcherType === "number_range") {
      const ranges = parseRanges(rangeText);
      if (!ranges) {
        message.warning(tr("编号区间格式：100-199,300-399", "Use ranges like 100-199,300-399"));
        return null;
      }
      return { type: "number_range", ranges };
    }
    if (matcherType === "area_prefix") {
      const prefixes = prefixText.split(/[,;\s]+/).filter(Boolean).map((p) => p.toUpperCase());
      if (!prefixes.length) {
        message.warning(tr("请填写区域字母（如 G）", "Enter area prefixes, e.g. G"));
        return null;
      }
      return { type: "area_prefix", prefixes };
    }
    if (matcherType === "radius") {
      if (circle.lat == null || circle.lon == null) {
        message.warning(tr("圆形圈选需要圆心经纬度", "A circle needs center lat/lon"));
        return null;
      }
      return { type: "radius", lat: circle.lat, lon: circle.lon, r_m: circle.r_m };
    }
    const idents = identsText.split(/[,;\s]+/).filter(Boolean).map((i) => i.toUpperCase());
    if (!idents.length) {
      message.warning(tr("请填写机位编号", "Enter stand idents"));
      return null;
    }
    return { type: "explicit", idents };
  };

  const saveTerminal = async () => {
    const matcher = buildMatcher();
    if (!matcher) return;
    setBusy(true);
    try {
      const res = await api<{ matched: number }>(
        `/local/airports/${icao}/terminals/${termName.trim().toUpperCase()}`,
        { method: "PUT", body: JSON.stringify({ matchers: [matcher] }) });
      message.success(tr(`已保存，命中 ${res.matched} 个机位`, `Saved, ${res.matched} stands matched`));
      setTermOpen(false);
      await load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeTerminal = async (terminal: string) => {
    try {
      await api(`/local/airports/${icao}/terminals/${terminal}`, { method: "DELETE" });
      message.success(tr("已删除（相关承运人规则一并移除）",
        "Deleted (related carrier rules removed too)"));
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const saveRule = async () => {
    if (!ruleTerminal) {
      message.warning(tr("先选择航站楼", "Pick a terminal first"));
      return;
    }
    const airlines = ruleAirlines.split(/[,;\s]+/).filter(Boolean).map((a) => a.toUpperCase());
    setBusy(true);
    try {
      await api("/local/terminal-rules", {
        method: "POST",
        body: JSON.stringify({ icao, terminal: ruleTerminal, scope: ruleScope, airlines }),
      });
      message.success(tr("规则已保存", "Rule saved"));
      setRuleOpen(false);
      await load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeRule = async (id: string) => {
    try {
      await api(`/local/terminal-rules/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <Card
      className="panel"
      variant="borderless"
      title={tr("航站楼与承运人", "Terminals & carriers")}
      extra={(
        <Space size={8}>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
            {tr("刷新", "Refresh")}
          </Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        <Space wrap size={8}>
          <div style={{ width: 180 }}>
            <AirportSelect value={icao} onChange={(v) => setIcao(v || "")} />
          </div>
          <Tag>{tr(`${standCount} 个机位`, `${standCount} stands`)}</Tag>
          <Tag color={standCount ? "blue" : "default"}>{standSource}</Tag>
        </Space>

        <Alert
          type="info"
          showIcon
          message={tr("航站楼是「一片机位」的命名，不是数据里的字段",
            "A terminal is a named set of stands, not a database field")}
          description={tr(
            "数据里没有航站楼（LNM 的 airline_codes 全空）：用编号区间/区域字母/圆形圈选/指定机位圈出一批点，再按承运人分配。未命中任何规则时只用「没被别的航司声明」的机位。",
            "The navdata has no terminal field (LNM airline_codes is empty): carve out a set of stands (ranges / area letters / circle / explicit) and assign carriers. When nothing matches, only stands not claimed by other carriers are used.")}
          style={{ marginBottom: 4 }}
        />

        <Table<AirportTerminal>
          size="small"
          rowKey="terminal"
          pagination={false}
          dataSource={terminals}
          locale={{ emptyText: tr("还没有定义航站楼", "No terminals yet") }}
          columns={[
            { title: tr("航站楼", "Terminal"), dataIndex: "terminal", width: 90 },
            {
              title: tr("机位条件", "Stand matcher"),
              render: (_, row) => (row.matchers || []).map((m) => matcherSummary(m, tr)).join(" / "),
            },
            {
              title: tr("命中", "Matched"),
              dataIndex: "matched",
              width: 90,
              render: (n: number) => <Tag color={n ? "green" : "red"}>{n}</Tag>,
            },
            {
              title: "",
              width: 56,
              render: (_, row) => (
                <Popconfirm
                  title={tr("删除该航站楼？", "Delete this terminal?")}
                  description={tr("指向它的承运人规则会一起删除。",
                    "Carrier rules pointing at it are removed too.")}
                  okText={tr("删除", "Delete")}
                  cancelText={tr("取消", "Cancel")}
                  onConfirm={() => void removeTerminal(row.terminal)}
                >
                  <Button size="small" danger type="text" icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
        <Button size="small" icon={<PlusOutlined />} onClick={() => {
          setTermName(`T${terminals.length + 1}`);
          setTermOpen(true);
        }}>
          {tr("新增航站楼", "Add terminal")}
        </Button>

        <Table<TerminalRule>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={rules}
          locale={{ emptyText: tr("还没有承运人规则（任意承运人可用）", "No carrier rules (open to all)") }}
          columns={[
            { title: tr("航站楼", "Terminal"), dataIndex: "terminal", width: 90 },
            {
              title: tr("适用范围", "Scope"),
              dataIndex: "scope",
              width: 130,
              render: (scope: string) => (
                scope === "INTERNATIONAL" ? tr("国际", "International")
                  : scope === "DOMESTIC" ? tr("国内", "Domestic") : tr("不限", "Both")
              ),
            },
            {
              title: tr("承运人", "Carriers"),
              dataIndex: "airlines",
              render: (airlines: string[]) => (airlines?.length
                ? airlines.map((a) => <Tag key={a}>{a}</Tag>)
                : <Text type="secondary">{tr("任意承运人", "any carrier")}</Text>),
            },
            {
              title: "",
              width: 56,
              render: (_, row) => (
                <Button size="small" danger type="text" icon={<DeleteOutlined />}
                  onClick={() => void removeRule(row.id)} />
              ),
            },
          ]}
        />
        <Space>
          <Button size="small" icon={<PlusOutlined />} disabled={!terminals.length} onClick={() => {
            setRuleTerminal(terminals[0]?.terminal || "");
            setRuleOpen(true);
          }}>
            {tr("新增承运人规则", "Add carrier rule")}
          </Button>
        </Space>
        {!compact ? (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {tr("公司承运人代码在「运营规则 → 公司档案」里维护；界面只显示机位编号，不写航站楼。",
              "Company carrier codes live in Operations → Company. The UI shows stand idents only, never terminals.")}
          </Text>
        ) : null}
      </Space>

      <Modal
        title={tr("新增/更新航站楼", "Add or update terminal")}
        open={termOpen}
        onCancel={() => setTermOpen(false)}
        onOk={() => void saveTerminal()}
        confirmLoading={busy}
        okText={tr("保存", "Save")}
        cancelText={tr("取消", "Cancel")}
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Input value={termName} onChange={(e) => setTermName(e.target.value)}
            addonBefore={tr("航站楼", "Terminal")} placeholder="T1" />
          <Select
            value={matcherType}
            onChange={(v) => setMatcherType(v)}
            options={[
              { value: "number_range", label: tr("编号区间（最常见）", "Number ranges (most common)") },
              { value: "area_prefix", label: tr("区域字母（parking.name）", "Area prefix (parking.name)") },
              { value: "radius", label: tr("圆形圈选（圆心 + 半径）", "Circle (center + radius)") },
              { value: "explicit", label: tr("指定机位编号", "Explicit stands") },
            ]}
          />
          {matcherType === "number_range" ? (
            <Input value={rangeText} onChange={(e) => setRangeText(e.target.value)}
              addonBefore={tr("区间", "Ranges")} placeholder="100-199,300-399" />
          ) : null}
          {matcherType === "area_prefix" ? (
            <Input value={prefixText} onChange={(e) => setPrefixText(e.target.value)}
              addonBefore={tr("区域", "Prefixes")} placeholder="G,GV" />
          ) : null}
          {matcherType === "radius" ? (
            <Space>
              <InputNumber placeholder={tr("纬度", "Lat")} value={circle.lat}
                onChange={(v) => setCircle((c) => ({ ...c, lat: typeof v === "number" ? v : null }))} />
              <InputNumber placeholder={tr("经度", "Lon")} value={circle.lon}
                onChange={(v) => setCircle((c) => ({ ...c, lon: typeof v === "number" ? v : null }))} />
              <InputNumber placeholder={tr("半径 m", "Radius m")} value={circle.r_m}
                onChange={(v) => setCircle((c) => ({ ...c, r_m: Number(v) || 900 }))} />
            </Space>
          ) : null}
          {matcherType === "explicit" ? (
            <Input value={identsText} onChange={(e) => setIdentsText(e.target.value)}
              addonBefore={tr("机位", "Stands")} placeholder="601,602,603" />
          ) : null}
          <Text type="secondary" style={{ fontSize: 12 }}>
            {tr("保存时会校验命中数量：一个都圈不到会直接拒绝。",
              "Saving validates the match: a matcher that hits nothing is rejected.")}
          </Text>
        </Space>
      </Modal>

      <Modal
        title={tr("新增承运人规则", "Add carrier rule")}
        open={ruleOpen}
        onCancel={() => setRuleOpen(false)}
        onOk={() => void saveRule()}
        confirmLoading={busy}
        okText={tr("保存", "Save")}
        cancelText={tr("取消", "Cancel")}
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Select
            value={ruleTerminal}
            onChange={(v) => setRuleTerminal(v)}
            options={terminals.map((t) => ({ value: t.terminal, label: t.terminal }))}
          />
          <Select
            value={ruleScope}
            onChange={(v) => setRuleScope(v)}
            options={[
              { value: "DOMESTIC", label: tr("国内航班", "Domestic") },
              { value: "INTERNATIONAL", label: tr("国际航班", "International") },
              { value: "BOTH", label: tr("不限", "Both") },
            ]}
          />
          <Input value={ruleAirlines} onChange={(e) => setRuleAirlines(e.target.value)}
            addonBefore={tr("承运人", "Carriers")} placeholder="9C,HBH,CXA" />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {tr("留空 = 任意承运人（如「国际航班用 T1」）；多个代码用逗号分隔。",
              "Empty = any carrier (e.g. all international flights); separate codes with commas.")}
          </Text>
        </Space>
      </Modal>
    </Card>
  );
}
