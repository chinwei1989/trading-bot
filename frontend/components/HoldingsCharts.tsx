"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Lane, Position } from "@/lib/types";

export function ExposureChart({ positions }: { positions: Position[] }) {
  const byAsset = new Map<string, { asset: string; net: number; gross: number }>();
  for (const position of positions) {
    const row = byAsset.get(position.asset) || {
      asset: position.asset,
      net: 0,
      gross: 0,
    };
    row.net += position.value;
    row.gross += Math.abs(position.value);
    byAsset.set(position.asset, row);
  }
  const data = [...byAsset.values()].sort((a, b) => b.gross - a.gross);

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 5, right: 8, bottom: 10, left: 0 }}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis
            dataKey="asset"
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            interval={0}
            angle={-28}
            textAnchor="end"
            height={54}
            axisLine={{ stroke: "rgba(148,163,184,0.2)" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickFormatter={(value) => `$${Number(value).toFixed(0)}`}
            axisLine={false}
            tickLine={false}
            width={48}
          />
          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid rgba(148,163,184,.25)",
              borderRadius: "10px",
              color: "#e2e8f0",
            }}
            formatter={(value) => `$${Number(value ?? 0).toFixed(0)}`}
          />
          <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
          <Bar dataKey="gross" name="Gross" fill="rgba(148,163,184,0.45)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="net" name="Net" fill="#4ade80" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LanePnlChart({ lanes }: { lanes: Lane[] }) {
  const data = [...lanes].sort((a, b) => a.pnl - b.pnl);
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 5, right: 18, bottom: 5, left: 10 }}
        >
          <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            tickFormatter={(value) => `$${Number(value).toFixed(0)}`}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="lane"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            width={78}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid rgba(148,163,184,.25)",
              borderRadius: "10px",
              color: "#e2e8f0",
            }}
            formatter={(value) => `$${Number(value ?? 0).toFixed(2)}`}
          />
          <Bar dataKey="pnl" name="P&L" fill="#fb7185" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
