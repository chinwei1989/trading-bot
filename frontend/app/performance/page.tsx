"use client";

import { useState } from "react";
import { PageHeader, Section, StatCard } from "@/components/Cards";
import { PerformanceChart } from "@/components/PerformanceChart";
import { ErrorPanel, LoadingPanel } from "@/components/States";
import { useDashboard } from "@/lib/api";
import type { RangeKey } from "@/lib/types";
import { money, signedMoney, signedPct, tone } from "@/lib/format";

const RANGES: RangeKey[] = ["Today", "7D", "30D", "3M", "1Y", "All"];

export default function PerformancePage() {
  const { data, error, loading, refresh } = useDashboard();
  const [range, setRange] = useState<RangeKey>("7D");

  if (loading && !data) return <LoadingPanel />;
  if (error && !data) return <ErrorPanel error={error} onRetry={() => void refresh()} />;
  if (!data) return <ErrorPanel error="No dashboard payload." />;

  const selected = data.performance.ranges[range];
  if (!selected) {
    return <ErrorPanel error={`No ${range} performance data.`} />;
  }

  return (
    <>
      <PageHeader
        kicker="PAPER OPERATIONS"
        title="Paper performance"
        subtitle="Daily P&L and cumulative return across the independent paper accounts."
      />

      <div className="range-row" role="group" aria-label="Performance range">
        {RANGES.map((item) => (
          <button
            key={item}
            className={item === range ? "range-button active" : "range-button"}
            onClick={() => setRange(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <p className="note">
        {selected.granularity === "intraday" ? "Today · intraday" : `${range} · daily`} ·{" "}
        {selected.observations} observations · aggregate of{" "}
        {data.portfolio.paper_accounts} independent spot accounts · starting cash{" "}
        {money(selected.initial_total)}.
        {selected.observations < 7 ? " Only the available history is shown." : ""}
      </p>

      <div className="stats-grid">
        <StatCard
          label="Period P&L"
          value={signedMoney(selected.period_pnl)}
          detail="selected range"
          tone={tone(selected.period_pnl)}
        />
        <StatCard
          label="Period return"
          value={signedPct(selected.period_return)}
          detail="selected range"
          tone={tone(selected.period_return)}
        />
        <StatCard
          label="Best interval"
          value={signedMoney(selected.best)}
          detail={selected.best > 0 ? "largest gain" : "least negative"}
          tone={tone(selected.best)}
        />
        <StatCard
          label="Worst interval"
          value={signedMoney(selected.worst)}
          detail={selected.worst < 0 ? "largest drawdown" : "smallest gain"}
          tone={tone(selected.worst)}
        />
        <StatCard label="Latest equity" value={money(selected.latest_equity)} detail="aggregate paper" />
        <StatCard label="Observations" value={String(selected.observations)} detail="buckets" />
      </div>

      <Section
        title="Daily performance"
        subtitle="Bars: daily P&L · line: cumulative return"
        action={
          <button className="button ghost" onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />
      <PerformanceChart range={selected} />

      <p className="fine">
        Aggregate sums independent paper accounts; it is illustrative, not one
        brokerage balance. Main campaign lanes were reset when SUI was added to
        the 9-asset universe, so the forward history is short.
      </p>
    </>
  );
}
