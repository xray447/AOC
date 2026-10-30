import { Select, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Airport } from "../types";

interface Props {
  value?: string[];
  onChange?: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  style?: React.CSSProperties;
}

/** 多选机场（远程搜 navdata）：机场排除列表用，已选值不在结果里时按 ICAO 原样显示。 */
export function AirportMultiSelect({ value, onChange, placeholder, disabled, style }: Props) {
  const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const timer = useRef<number | null>(null);

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
        const data = await api<{ items: Airport[] }>(
          `/local/airports?q=${encodeURIComponent(q)}&limit=30`);
        setOptions(data.items.map((a) => ({
          value: a.icao,
          label: `${a.icao}${a.iata ? ` / ${a.iata}` : ""} · ${a.name || a.city || ""}`,
        })));
      } catch {
        setOptions([]);
      } finally {
        setLoading(false);
      }
    }, 180);
  };

  return (
    <Select
      mode="multiple"
      showSearch
      allowClear
      value={value || []}
      placeholder={placeholder}
      filterOption={false}
      defaultActiveFirstOption={false}
      onSearch={search}
      onChange={(v: string[]) => onChange?.(v.map((item) => item.toUpperCase()))}
      notFoundContent={loading ? <Spin size="small" /> : null}
      options={options}
      disabled={disabled}
      style={{ width: "100%", ...style }}
    />
  );
}
