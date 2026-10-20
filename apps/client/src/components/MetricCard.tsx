import { Card, Statistic } from "antd";
import type { ReactNode } from "react";

export function MetricCard({ title, value, suffix, prefix, color, extra }: {
  title: string;
  value: string | number;
  suffix?: string;
  prefix?: ReactNode;
  color?: string;
  extra?: ReactNode;
}) {
  return (
    <Card size="small" variant="borderless" className="metric-card">
      <Statistic
        title={title}
        value={value}
        suffix={suffix}
        prefix={prefix}
        valueStyle={{ color, fontWeight: 650, fontSize: 24 }}
      />
      {extra ? <div className="metric-extra">{extra}</div> : null}
    </Card>
  );
}
