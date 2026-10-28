"use client";

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PerformanceRange } from "@/lib/types";
import { shortDate } from "@/lib/format";

export function PerformanceChart({ range }: { range: PerformanceRange }) {
  const points = range.points.map((point) => ({
    ...point,
    label:
      range.granularity === "intraday"
        ? new Date(point.timestamp).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })
        : shortDate(point.timestamp),
  }));

  if (!points.length) {
    return <div className="empty-panel">No performance history for this range.</div>;
  }

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={points} margin={{ top: 10, right: 8, bottom: 10, left: 0 }}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            minTickGap={20}
            axisLine={{ stroke: "rgba(148,163,184,0.2)" }}
            tickLine={false}
          />
          <YAxis
            yAxisId="pnl"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickFormatter={(value) => `$${Number(value).toFixed(0)}`}
            axisLine={false}
            tickLine={false}
            width={48}
          />
          <YAxis
            yAxisId="return"
            orientation="right"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickFormatter={(value) => `${(Number(value) * 100).toFixed(2)}%`}
            axisLine={false}
            tickLine={false}
            width={58}
          />
          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid rgba(148,163,184,.25)",
              borderRadius: "10px",
              color: "#e2e8f0",
            }}
            formatter={(value, name) => {
              const number = Number(value ?? 0);
              return name === "Cumulative return"
                ? [`${(number * 100).toFixed(2)}%`, name]
                : [`$${number.toFixed(2)}`, name];
            }}
          />
          <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
          <Bar
            yAxisId="pnl"
            dataKey="pnl"
            name="P&L"
            fill="#fb7185"
            radius={[3, 3, 0, 0]}
            isAnimationActive={false}
          />
          <Line
            yAxisId="return"
            type="monotone"
            dataKey="cum_pct"
            name="Cumulative return"
            stroke="#38bdf8"
            strokeWidth={2}
            dot={{ r: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
