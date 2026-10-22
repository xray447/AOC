import { Select, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Airport } from "../types";

/** 受限候选：只允许传入的机场（例如「有可用飞机的机场」），不再远程搜全库。 */
export interface AirportOption {
  icao: string;
  iata?: string | null;
  name?: string | null;
  city?: string | null;
}

interface Props {
  value?: string | null;
  onChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
  style?: React.CSSProperties;
  /** 传入后只列这些机场（无机队的机场不再出现）；不传则远程搜索 navdata。 */
  airports?: AirportOption[] | null;
  loading?: boolean;
}

function label(a: AirportOption): string {
  return `${a.icao}${a.iata ? ` / ${a.iata}` : ""} · ${a.name || a.city || ""}`;
}

export function AirportSelect({
  value, onChange, placeholder, disabled, allowClear, style, airports, loading: restrictedLoading,
}: Props) {
  const [options, setOptions] = useState<{ value: string; label: string; airport: Airport | AirportOption }[]>([]);
  const [loading, setLoading] = useState(false);
  const timer = useRef<number | null>(null);
  const restricted = Array.isArray(airports);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  const search = (q: string) => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      if (!q.trim()) {
        setOptions([]);
        return;
      }
      setLoading(true);
      try {
        const data = await api<{ items: Airport[] }>(`/local/airports?q=${encodeURIComponent(q)}&limit=30`);
        setOptions(data.items.map((a) => ({
          value: a.icao,
          airport: a,
          label: `${a.icao}${a.iata ? ` / ${a.iata}` : ""} · ${a.name || a.city || ""}`,
        })));
      } catch {
        setOptions([]);
      } finally {
        setLoading(false);
      }
    }, 180);
  };

  const restrictedOptions = (airports || []).map((a) => ({
    value: a.icao,
    airport: a,
    label: label(a),
  }));

  return (
    <Select
      showSearch
      value={value || undefined}
      placeholder={placeholder}
      defaultActiveFirstOption={false}
      filterOption={restricted ? true : false}
      optionFilterProp={restricted ? "label" : undefined}
      onSearch={restricted ? undefined : search}
      onChange={(v) => onChange?.(v)}
      onClear={() => onChange?.("")}
      notFoundContent={(restricted ? restrictedLoading : loading) ? <Spin size="small" /> : null}
      options={restricted ? restrictedOptions : options}
      loading={restricted ? restrictedLoading : false}
      disabled={disabled}
      allowClear={allowClear}
      style={{ width: "100%", ...style }}
    />
  );
}
