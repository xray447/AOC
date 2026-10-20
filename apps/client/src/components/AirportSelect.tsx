import { Select, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Airport } from "../types";

interface Props {
  value?: string | null;
  onChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
  style?: React.CSSProperties;
}

export function AirportSelect({ value, onChange, placeholder, disabled, allowClear, style }: Props) {
  const [options, setOptions] = useState<{ value: string; label: string; airport: Airport }[]>([]);
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

  return (
    <Select
      showSearch
      value={value || undefined}
      placeholder={placeholder}
      defaultActiveFirstOption={false}
      filterOption={false}
      onSearch={search}
      onChange={(v) => onChange?.(v)}
      onClear={() => onChange?.("")}
      notFoundContent={loading ? <Spin size="small" /> : null}
      options={options}
      disabled={disabled}
      allowClear={allowClear}
      style={{ width: "100%", ...style }}
    />
  );
}
