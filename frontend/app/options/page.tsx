"use client";

import { PageHeader, Section, StatCard } from "@/components/Cards";
import { ErrorPanel, LoadingPanel } from "@/components/States";
import { useDashboard } from "@/lib/api";
import { money } from "@/lib/format";

export default function OptionsPage() {
  const { data, error, loading, refresh } = useDashboard();
  if (loading && !data) return <LoadingPanel />;
  if (error && !data) return <ErrorPanel error={error} onRetry={() => void refresh()} />;
  if (!data) return <ErrorPanel error="No dashboard payload." />;

  const evidence = data.options.evidence as Record<string, unknown>;
  const paper = (evidence.paper as Record<string, unknown>) || {};
  const gate = data.options.live_gate as Record<string, unknown>;
  const failed = Array.isArray(gate.failed) ? gate.failed : [];
  const status = String(gate.status || "NO_GO");

  return (
    <>
      <PageHeader
        kicker="PAPER OPERATIONS"
        title="Crypto options"
        subtitle="Long-premium paper lanes, forward evidence, and the options live gate."
      />

      <div className="stats-grid">
        <StatCard
          label="Options live"
          value={status}
          detail="hard capital gate"
          tone={status === "GO" ? "good" : "bad"}
        />
        <StatCard
          label="Paper days"
          value={`${paper.paper_days ?? "—"} / ${paper.target_paper_days ?? 56}`}
          detail="forward evidence"
          tone="info"
        />
        <StatCard
          label="Fills"
          value={String(paper.fills ?? 0)}
          detail={`${paper.cycles ?? 0} paper cycles`}
        />
        <StatCard
          label="Equity"
          value={money(Number(paper.equity ?? 0))}
          detail="paper account"
        />
        <StatCard
          label="Open holdings"
          value={String(data.options_holdings.open_contracts)}
          detail={money(data.options_holdings.value_usd)}
        />
        <StatCard
          label="Evidence status"
          value={String(evidence.status || "—")}
          detail="forward + real-chain replay"
          tone="info"
        />
      </div>

      <Section title="Options lanes" subtitle="Independent accounts; no live order path" />
      <div className="lane-grid">
        {data.options.lanes.map((lane) => (
          <div className="lane-card" key={lane.lane}>
            <div className="lane-top">
              <span className="lane-dot" style={{ background: "#fbbf24" }} />
              <strong>{lane.lane}</strong>
              <span className={lane.status === "ok" ? "status-dot on" : "status-dot"} />
            </div>
            <div className="lane-equity">{money(lane.equity ?? 0)}</div>
            <div className="lane-detail">
              {Object.entries(lane.directions).length
                ? Object.entries(lane.directions)
                    .map(([key, value]) => `${key}: ${value}`)
                    .join(" · ")
                : "no directional decision"}
            </div>
            <div className="lane-detail">status: {lane.status}</div>
          </div>
        ))}
      </div>

      <Section title="Failed live checks" subtitle="The gate fails closed" />
      <div className="list-panel">
        {failed.length ? (
          <ul>{failed.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
        ) : (
          <p className="fine">No gate failures listed.</p>
        )}
      </div>

      <p className="fine">
        Live options remain disabled. The options live gate and credential
        namespace are separate from testnet.
      </p>
    </>
  );
}
