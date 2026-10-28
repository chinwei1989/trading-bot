import Link from "next/link";

export function StatCard({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "good" | "bad" | "neutral" | "info";
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone}`}>{value}</div>
      {detail ? <div className="stat-detail">{detail}</div> : null}
    </div>
  );
}

export function Section({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Chip({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "neutral" | "info";
}) {
  return (
    <span className={`chip ${tone}`}>
      <span className="chip-dot" />
      {label} · {value}
    </span>
  );
}

export function PageHeader({
  kicker,
  title,
  subtitle,
}: {
  kicker: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="page-head">
      <div className="kicker">{kicker}</div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  );
}

export function WorkspaceLinks() {
  const links = [
    { href: "/holdings", title: "Holdings", detail: "Positions, P&L and SUI" },
    { href: "/performance", title: "Performance", detail: "Daily range graph" },
    { href: "/readiness", title: "Readiness", detail: "Live gates and host" },
    { href: "/options", title: "Options", detail: "Premium lanes and evidence" },
  ];
  return (
    <div className="workspace-grid">
      {links.map((link) => (
        <Link key={link.href} href={link.href} className="workspace-card">
          <span className="workspace-arrow">→</span>
          <strong>{link.title}</strong>
          <small>{link.detail}</small>
        </Link>
      ))}
    </div>
  );
}
