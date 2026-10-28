"use client";

import { ExposureChart, LanePnlChart } from "@/components/HoldingsCharts";
import { PageHeader, Section, StatCard } from "@/components/Cards";
import { ErrorPanel, LoadingPanel } from "@/components/States";
import { useDashboard } from "@/lib/api";
import { money, signedMoney, signedPct, tone } from "@/lib/format";

export default function HoldingsPage() {
  const { data, error, loading, refresh } = useDashboard();
  if (loading && !data) return <LoadingPanel />;
  if (error && !data) return <ErrorPanel error={error} onRetry={() => void refresh()} />;
  if (!data) return <ErrorPanel error="No dashboard payload." />;

  const lanes = data.lanes || [];
  const positions = data.positions || [];
  const sui = data.sui;
  const openPnl = positions.reduce((sum, position) => sum + (position.pnl || 0), 0);
  const gross = positions.reduce((sum, position) => sum + Math.abs(position.value), 0);
  const costBasis = positions.reduce((sum, position) => sum + (position.cost || 0), 0);
  const net = positions.reduce((sum, position) => sum + position.value, 0);
  const laneInitial = lanes.reduce((sum, lane) => sum + lane.starting_cash, 0);
  const lanePnl = lanes.reduce((sum, lane) => sum + lane.pnl, 0);
  const long = positions.filter((position) => position.value > 0).reduce((s, p) => s + p.value, 0);
  const short = Math.abs(
    positions.filter((position) => position.value < 0).reduce((s, p) => s + p.value, 0),
  );

  return (
    <>
      <PageHeader
        kicker="PAPER OPERATIONS"
        title="Paper holdings"
        subtitle={`Aggregate across independent paper accounts · marked at ${data.data_as_of}`}
      />
      <p className="note">
        Illustrative aggregate, not one brokerage balance. Short positions are
        negative.
      </p>

      <div className="stats-grid">
        <StatCard label="Gross exposure" value={money(gross)} detail={`${positions.length} positions`} />
        <StatCard label="Net exposure" value={money(net)} detail="long minus short" />
        <StatCard label="Long exposure" value={money(long)} detail="signed long value" />
        <StatCard label="Short exposure" value={money(short)} detail="absolute short value" />
        <StatCard
          label="Open P&L"
          value={signedMoney(openPnl)}
          detail={`${signedPct(openPnl / costBasis)} against entry cost`}
          tone={tone(openPnl)}
        />
        <StatCard
          label="Lane P&L"
          value={signedMoney(lanePnl)}
          detail={`${signedPct(lanePnl / laneInitial)} equity vs starting cash`}
          tone={tone(lanePnl)}
        />
      </div>

      <div className="two-col">
        <div>
          <Section title="Exposure by asset" subtitle="Gross and signed net USD" />
          <ExposureChart positions={positions} />
        </div>
        <div>
          <Section title="P&L by lane" subtitle="Equity versus starting cash" />
          <LanePnlChart lanes={lanes} />
        </div>
      </div>

      <Section
        title="Lane P&L"
        subtitle="Account-level paper performance"
      />
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Lane</th>
              <th>Starting cash</th>
              <th>Equity</th>
              <th>P&L</th>
              <th>P&L %</th>
              <th>Positions</th>
            </tr>
          </thead>
          <tbody>
            {[...lanes]
              .sort((a, b) => b.pnl - a.pnl)
              .map((lane) => (
                <tr key={lane.lane}>
                  <td><span className="table-dot" style={{ background: lane.color }} />{lane.lane}</td>
                  <td>{money(lane.starting_cash)}</td>
                  <td>{money(lane.equity)}</td>
                  <td className={tone(lane.pnl)}>{signedMoney(lane.pnl)}</td>
                  <td className={tone(lane.pnl)}>{signedPct(lane.pnl_pct)}</td>
                  <td>{lane.positions}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <Section title="SUI focus" subtitle="Main campaign and isolated SUI lab" />
      <div className="sui-card">
        <div>
          <span className="stat-label">SUI holdings</span>
          <div className="sui-qty">{sui.qty.toLocaleString(undefined, { maximumFractionDigits: 1 })} SUI</div>
        </div>
        <div>
          <span className="stat-label">Marked value</span>
          <strong>{money(sui.value_usd)}</strong>
        </div>
        <div>
          <span className="stat-label">Open P&L</span>
          <strong className={tone(sui.pnl_usd)}>{signedMoney(sui.pnl_usd)}</strong>
        </div>
      </div>

      <Section title="Position detail" subtitle="Every open spot position" />
      <div className="table-wrap desktop-table">
        <table className="data-table">
          <thead>
            <tr>
              <th>Lane</th>
              <th>Asset</th>
              <th>Side</th>
              <th>Open P&L</th>
              <th>Open P&L %</th>
              <th>Qty</th>
              <th>Last</th>
              <th>Value</th>
              <th>Weight</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position, index) => (
              <tr key={`${position.lane}-${position.asset}-${index}`}>
                <td>{position.lane}</td>
                <td>{position.asset}</td>
                <td className={position.side === "long" ? "good" : "bad"}>{position.side}</td>
                <td className={tone(position.pnl)}>{signedMoney(position.pnl)}</td>
                <td className={tone(position.pnl)}>{signedPct(position.pnl_pct)}</td>
                <td>{position.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
                <td>{position.last_price ? money(position.last_price, 4) : "—"}</td>
                <td>{money(position.value)}</td>
                <td>{signedPct(position.weight)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="position-cards">
        {positions.map((position, index) => (
          <div className="position-card" key={`${position.lane}-${position.asset}-${index}`}>
            <div className="position-card-top">
              <strong>{position.asset}</strong>
              <span className={position.side === "long" ? "good" : "bad"}>{position.side}</span>
            </div>
            <div className="position-card-lane">{position.lane}</div>
            <div className="position-card-values">
              <span>Value <strong>{money(position.value)}</strong></span>
              <span className={tone(position.pnl)}>
                P&L <strong>{signedMoney(position.pnl)}</strong>
              </span>
            </div>
            <div className="position-card-meta">
              {position.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })} units ·{" "}
              {signedPct(position.pnl_pct)}
            </div>
          </div>
        ))}
      </div>

      <Section
        title="Option holdings"
        subtitle="Long-premium contracts held by the options accounts"
      />
      {data.options_holdings.open_contracts ? (
        <p className="note">
          {data.options_holdings.open_contracts} contracts ·{" "}
          {money(data.options_holdings.value_usd)} marked value
        </p>
      ) : (
        <div className="empty-panel">No open option holdings.</div>
      )}

      <p className="fine">
        Paper marks only. Live trading remains disabled. Data source:{" "}
        {data.source}.
      </p>
    </>
  );
}
