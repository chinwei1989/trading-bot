"use client";

import Link from "next/link";
import { AiGistCard } from "@/components/AiGistCard";
import { Chip, Section, StatCard, WorkspaceLinks } from "@/components/Cards";
import { PerformanceChart } from "@/components/PerformanceChart";
import { ErrorPanel, LoadingPanel } from "@/components/States";
import { regenerateGist, useDashboard } from "@/lib/api";
import { money, pct, signedMoney, signedPct, tone } from "@/lib/format";

export default function HomePage() {
  const { data, error, loading, refresh, liveApi } = useDashboard();

  if (loading && !data) return <LoadingPanel />;
  if (error && !data) return <ErrorPanel error={error} onRetry={() => void refresh()} />;
  if (!data) return <ErrorPanel error="No dashboard payload." onRetry={() => void refresh()} />;

  const readiness = data.readiness || {};
  const paperTone = readiness.paper_ready ? "good" : "bad";
  const spotGate = String(readiness.live_gate || "NO_GO");
  const optionsGate = String(readiness.options_live_gate || "NO_GO");

  async function regenerate() {
    await regenerateGist();
    await refresh();
  }

  return (
    <>
      <section className="hero">
        <div>
          <div className="kicker">NOVA · PAPER OPERATIONS</div>
          <h1>Trading Operations</h1>
          <p>
            Deterministic sleeves, AI research lanes, crypto options, and hard
            risk gates in one read-only command surface.
          </p>
        </div>
        <div className="hero-chips">
          <Chip label="Paper" value={readiness.paper_ready ? "READY" : "CHECK"} tone={paperTone} />
          <Chip label="Host" value={String(readiness.host_status || "UNKNOWN")} tone="bad" />
          <Chip label="Spot live" value={spotGate} tone={spotGate === "GO" ? "good" : "bad"} />
          <Chip
            label="Options live"
            value={optionsGate}
            tone={optionsGate === "GO" ? "good" : "bad"}
          />
          <Chip
            label="Evidence"
            value={`${readiness.paper_days ?? 0}/${readiness.target_paper_days ?? 56}`}
            tone="info"
          />
        </div>
      </section>

      <AiGistCard gist={data.ai_gist} liveApi={liveApi} onRegenerate={regenerate} />

      <Section
        title="Paper portfolio"
        subtitle={`Independent paper accounts · data as of ${data.data_as_of} · refreshed ${new Date(
          data.generated_at,
        ).toLocaleTimeString()}`}
        action={
          <button className="button ghost" onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />
      <div className="stats-grid">
        <StatCard
          label="Gross exposure"
          value={money(data.portfolio.gross_usd)}
          detail={`${data.portfolio.positions} open positions · ${data.portfolio.active_lanes} active lanes`}
        />
        <StatCard
          label="Net exposure"
          value={money(data.portfolio.net_usd)}
          detail={`${data.portfolio.paper_accounts} paper accounts`}
        />
        <StatCard
          label="Open P&L"
          value={signedMoney(data.portfolio.open_pnl_usd)}
          detail={`${signedPct(data.portfolio.open_pnl_pct)} against entry`}
          tone={tone(data.portfolio.open_pnl_usd)}
        />
        <StatCard
          label="Lane P&L"
          value={signedMoney(data.portfolio.lane_pnl_usd)}
          detail={`${signedPct(data.portfolio.lane_pnl_pct)} equity vs starting cash`}
          tone={tone(data.portfolio.lane_pnl_usd)}
        />
        <StatCard
          label="SUI holdings"
          value={`${data.sui.qty.toLocaleString(undefined, { maximumFractionDigits: 1 })} SUI`}
          detail={`${money(data.sui.value_usd)} · ${signedMoney(data.sui.pnl_usd)} open P&L`}
          tone={tone(data.sui.pnl_usd)}
        />
        <StatCard
          label="Tracked equity"
          value={money(
            data.lanes.reduce((sum, lane) => sum + (Number(lane.equity) || 0), 0),
          )}
          detail="aggregate across independent accounts"
        />
      </div>

      <Section title="Open a workspace" subtitle="Drill into the detailed views" />
      <WorkspaceLinks />

      <Section
        title="Lanes"
        subtitle="Separate books, separate risk state"
        action={
          <Link className="text-link" href="/holdings">
            Open holdings →
          </Link>
        }
      />
      <div className="lane-grid">
        {data.lanes.map((lane) => (
          <div className="lane-card" key={lane.lane}>
            <div className="lane-top">
              <span className="lane-dot" style={{ background: lane.color }} />
              <strong>{lane.lane}</strong>
              <span className={lane.positions ? "status-dot on" : "status-dot"} />
            </div>
            <div className="lane-equity">{money(lane.equity)}</div>
            <div className={`lane-pnl ${tone(lane.pnl)}`}>
              {signedMoney(lane.pnl)} · {signedPct(lane.pnl_pct)}
            </div>
            <div className="lane-detail">
              {lane.positions} position{lane.positions === 1 ? "" : "s"}
            </div>
          </div>
        ))}
      </div>

      {data.performance?.ranges?.["7D"] ? (
        <>
          <Section
            title="7D performance"
            subtitle="Aggregate paper equity · daily P&L and cumulative return"
            action={
              <Link className="text-link" href="/performance">
                Open performance →
              </Link>
            }
          />
          <PerformanceChart range={data.performance.ranges["7D"]} />
          <div className="mini-stats">
            <span>
              Period P&L:{" "}
              <strong className={tone(data.performance.ranges["7D"].period_pnl)}>
                {signedMoney(data.performance.ranges["7D"].period_pnl)}
              </strong>
            </span>
            <span>
              Return:{" "}
              <strong className={tone(data.performance.ranges["7D"].period_return)}>
                {signedPct(data.performance.ranges["7D"].period_return)}
              </strong>
            </span>
            <span>{pct(data.performance.ranges["7D"].period_return)} this range</span>
          </div>
        </>
      ) : null}

      <Section title="Readiness" subtitle="Live-capital gates remain separate from paper health" />
      <div className="readiness-strip">
        <span>Code: <strong>{String(readiness.code_status || "—")}</strong></span>
        <span>Health: <strong>{String(readiness.health_status || "—")}</strong></span>
        <span>Host: <strong>{String(readiness.host_status || "—")}</strong></span>
        <span>Spot: <strong className={spotGate === "GO" ? "good" : "bad"}>{spotGate}</strong></span>
        <span>Options: <strong className={optionsGate === "GO" ? "good" : "bad"}>{optionsGate}</strong></span>
        <Link href="/readiness">Details →</Link>
      </div>
    </>
  );
}
