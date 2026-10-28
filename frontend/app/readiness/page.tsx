"use client";

import { PageHeader, Section, StatCard } from "@/components/Cards";
import { ErrorPanel, LoadingPanel } from "@/components/States";
import { useDashboard } from "@/lib/api";

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export default function ReadinessPage() {
  const { data, error, loading, refresh } = useDashboard();
  if (loading && !data) return <LoadingPanel />;
  if (error && !data) return <ErrorPanel error={error} onRetry={() => void refresh()} />;
  if (!data) return <ErrorPanel error="No dashboard payload." />;
  const readiness = data.readiness;
  const blockers = asArray(readiness.blockers);
  const hostBlockers = asArray(readiness.host_blockers);
  const spotFailed = asArray(readiness.live_gate_failed);
  const optionsFailed = asArray(readiness.options_live_gate_failed);
  const validation = data.validation;
  const validationRows = validation?.strategies ?? [];
  const stressRows = validation?.sensitivity ?? [];
  const dataStart = validation?.data?.start?.slice(0, 10) ?? "unknown";
  const dataEnd = validation?.data?.end?.slice(0, 10) ?? "unknown";

  return (
    <>
      <PageHeader
        kicker="PAPER OPERATIONS"
        title="Readiness & live gates"
        subtitle="Paper infrastructure, host health, and separate capital gates."
      />
      <div className="stats-grid">
        <StatCard
          label="Paper infrastructure"
          value={readiness.paper_ready ? "READY" : "CHECK"}
          detail={String(readiness.health_status || "unknown")}
          tone={readiness.paper_ready ? "good" : "bad"}
        />
        <StatCard
          label="Paper evidence"
          value={`${readiness.paper_days ?? 0}/${readiness.target_paper_days ?? 56}`}
          detail="days toward options gate"
          tone="info"
        />
        <StatCard
          label="Host"
          value={String(readiness.host_status || "UNKNOWN")}
          detail="scheduler and network"
          tone="bad"
        />
        <StatCard
          label="Spot live"
          value={String(readiness.live_gate || "NO_GO")}
          detail="capital gate"
          tone={readiness.live_gate === "GO" ? "good" : "bad"}
        />
        <StatCard
          label="Options live"
          value={String(readiness.options_live_gate || "NO_GO")}
          detail="capital gate"
          tone={readiness.options_live_gate === "GO" ? "good" : "bad"}
        />
        <StatCard
          label="Options evidence"
          value={String(readiness.options_status || "—")}
          detail="forward + replay"
          tone="info"
        />
      </div>

      {validationRows.length ? (
        <>
          <Section
            title="9-asset walk-forward"
            subtitle="DSR/PBO evidence; a failed row cannot be promoted by another sleeve passing"
          />
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Folds</th>
                  <th>Trials</th>
                  <th>DSR</th>
                  <th>PBO</th>
                  <th>OOS Sharpe</th>
                  <th>OOS CAGR</th>
                  <th>OOS Max DD</th>
                  <th>Gate</th>
                </tr>
              </thead>
              <tbody>
                {validationRows.map((row) => (
                  <tr key={row.strategy}>
                    <td>{row.strategy}</td>
                    <td>{row.folds}</td>
                    <td>{row.trials}</td>
                    <td>{row.dsr.toFixed(3)}</td>
                    <td>{row.pbo.toFixed(3)}</td>
                    <td>{row.oos_sharpe.toFixed(2)}</td>
                    <td>{(row.oos_cagr * 100).toFixed(1)}%</td>
                    <td>{(row.oos_max_dd * 100).toFixed(1)}%</td>
                    <td className={row.passed ? "good" : "bad"}>
                      {row.passed ? "PASS" : "FAIL"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="fine">
            {validation?.data?.n_assets ?? 0} assets,{" "}
            {(validation?.data?.rows ?? 0).toLocaleString()} bars, {dataStart} to{" "}
            {dataEnd}. {validation?.verdict}
          </p>
          {stressRows.length ? (
            <>
              <Section
                title="180-day stress check"
                subtitle="Seven shorter OOS folds; same 900-day training window"
              />
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th>Folds</th>
                      <th>Trials</th>
                      <th>DSR</th>
                      <th>PBO</th>
                      <th>OOS Sharpe</th>
                      <th>Gate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stressRows.map((row) => (
                      <tr key={`stress-${row.strategy}`}>
                        <td>{row.strategy}</td>
                        <td>{row.folds}</td>
                        <td>{row.trials}</td>
                        <td>{row.dsr.toFixed(3)}</td>
                        <td>{row.pbo.toFixed(3)}</td>
                        <td>{row.oos_sharpe.toFixed(2)}</td>
                        <td className={row.passed ? "good" : "bad"}>
                          {row.passed ? "PASS" : "FAIL"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      <Section title="Blockers" subtitle="Conditions preventing live capital" />
      <div className="list-panel">
        {blockers.length ? (
          <ul>
            {blockers.map((item, index) => (
              <li key={index}>{String(item)}</li>
            ))}
          </ul>
        ) : (
          <p className="fine">No readiness blockers reported.</p>
        )}
        {hostBlockers.map((item, index) => (
          <p key={`host-${index}`} className="error-text">{String(item)}</p>
        ))}
      </div>

      <div className="two-col">
        <div>
          <Section title="Failed spot checks" subtitle="Live gate" />
          <div className="list-panel">
            {spotFailed.length ? (
              <ul>{spotFailed.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
            ) : (
              <p className="fine">No spot failures listed.</p>
            )}
          </div>
        </div>
        <div>
          <Section title="Failed options checks" subtitle="Live gate" />
          <div className="list-panel">
            {optionsFailed.length ? (
              <ul>{optionsFailed.map((item, index) => <li key={index}>{String(item)}</li>)}</ul>
            ) : (
              <p className="fine">No options failures listed.</p>
            )}
          </div>
        </div>
      </div>

      <p className="fine">
        This page is read-only. It cannot enable live trading, alter risk, or
        place an order.
      </p>
    </>
  );
}
