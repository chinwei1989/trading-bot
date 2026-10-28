"use client";

import { useState } from "react";
import type { AIGist } from "@/lib/types";
import { dateTime } from "@/lib/format";

export function AiGistCard({
  gist,
  liveApi,
  onRegenerate,
}: {
  gist: AIGist | null;
  liveApi: boolean;
  onRegenerate: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function regenerate() {
    setBusy(true);
    setError(null);
    try {
      await onRegenerate();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  if (!gist) {
    return (
      <div className="gist-card empty">
        <div className="kicker">AI PAPER GIST</div>
        <h2>No gist generated yet</h2>
        <p>
          Generate a concise Jev-classified summary from the latest paper state.
        </p>
        <button className="button" onClick={regenerate} disabled={busy || !liveApi}>
          {busy ? "Asking Jev…" : "Generate gist"}
        </button>
        {!liveApi ? <p className="fine">Live API is not configured; snapshot mode.</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className="gist-card">
      <div className="gist-top">
        <span className="kicker">AI PAPER GIST · JEV</span>
      </div>
      <h2>{gist.headline || "Paper state"}</h2>
      <p className="gist-summary">{gist.summary}</p>
      <ul className="gist-bullets">
        {(gist.bullets || []).map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
      <div className="gist-meta">
        Created {dateTime(gist.created_at)} · data {gist.data_as_of || "—"} ·{" "}
        {gist.model || "Jev"} ·{" "}
        {typeof gist.confidence === "number"
          ? `${(gist.confidence * 100).toFixed(0)}% confidence · `
          : ""}
        typed classification, paper only
      </div>
      <div className="gist-actions">
        <button className="button ghost" onClick={regenerate} disabled={busy || !liveApi}>
          {busy ? "Regenerating…" : "Regenerate with latest data"}
        </button>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
    </div>
  );
}
