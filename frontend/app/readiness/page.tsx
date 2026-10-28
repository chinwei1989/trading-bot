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
