"use client";

import { useMemo, useState } from "react";
import { PageHeader, Section } from "@/components/Cards";
import { ErrorPanel, LoadingPanel } from "@/components/States";
import { useDashboard } from "@/lib/api";
import { dateTime } from "@/lib/format";

function lineTone(line: string): string {
  const lower = line.toLowerCase();
  if (/\b(error|failed|failure|traceback|exception|critical)\b/.test(lower)) return "error";
  if (/\b(warn|warning|degraded|stale|retry)\b/.test(lower)) return "warn";
  if (/\b(ok|ready|complete|starting|start)\b/.test(lower)) return "info";
  return "";
}

export default function LogsPage() {
  const { data, error, loading, refresh } = useDashboard();
  const [selectedName, setSelectedName] = useState("");
  const [query, setQuery] = useState("");

  const files = data?.logs?.files ?? [];
  const current = files.find((file) => file.name === selectedName) ?? files[0];
  const filtered = useMemo(() => {
    const lines = current?.lines ?? [];
    const needle = query.trim().toLowerCase();
    return needle ? lines.filter((line) => line.toLowerCase().includes(needle)) : lines;
  }, [current, query]);

  if (loading && !data) return <LoadingPanel />;
  if (error && !data) return <ErrorPanel error={error} onRetry={() => void refresh()} />;
  if (!data) return <ErrorPanel error="No dashboard payload." />;

  return (
    <>
      <PageHeader
        kicker="OPERATIONS"
        title="Logs"
        subtitle="Bounded, read-only tails from the paper campaign and sleeve processes"
      />
      <p className="note">
        Last {data.logs?.max_lines ?? 200} lines per file. Secrets are redacted
        before this page receives the data. This view never exposes raw log
        files or changes trading state. It refreshes every 60 seconds.
      </p>

      {files.length ? (
        <>
          <Section
            title="Log files"
            subtitle={`${files.length} allowlisted files · refreshed from the same payload as the dashboard`}
            action={
              <button className="button ghost" onClick={() => void refresh()} disabled={loading}>
                {loading ? "Refreshing…" : "Refresh"}
              </button>
            }
          />
          <div className="log-toolbar">
            <label className="log-field">
              File
              <select
                value={current?.name ?? ""}
                onChange={(event) => setSelectedName(event.target.value)}
              >
                {files.map((file) => (
                  <option key={file.name} value={file.name}>
                    {file.label} ({file.name})
                  </option>
                ))}
              </select>
            </label>
            <label className="log-field">
              Filter lines
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="error, sleeve name, date…"
                spellCheck={false}
              />
            </label>
          </div>

          {current ? (
            <>
              <div className="log-meta">
                <span>Updated {dateTime(current.updated_at)}</span>
                <span>
                  {filtered.length}
                  {query.trim() ? ` of ${current.lines.length}` : ""} lines
                </span>
                {current.truncated ? <span>Older lines truncated</span> : null}
                {data.logs?.redacted ? <span>Redaction enabled</span> : null}
              </div>
              <div className="log-view" aria-label={`${current.label} log tail`}>
                {filtered.length ? (
                  filtered.map((line, index) => (
                    <div className={`log-line ${lineTone(line)}`} key={`${index}-${line}`}>
                      {line}
                    </div>
                  ))
                ) : (
                  <div className="log-line dim">No lines match this filter.</div>
                )}
              </div>
            </>
          ) : null}
        </>
      ) : (
        <div className="empty-panel">No allowlisted log files are available.</div>
      )}

      <p className="fine">
        Paper only. Log lines are operational evidence, not a statement of
        profitability or live readiness.
      </p>
    </>
  );
}
