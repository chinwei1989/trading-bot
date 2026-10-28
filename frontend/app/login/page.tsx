"use client";

import { useState } from "react";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const body = (await response.json()) as { ok?: boolean; error?: string };
      if (!response.ok || !body.ok) {
        setError(body.error || "Invalid password.");
        return;
      }
      window.location.assign("/");
    } catch {
      setError("Could not reach the login endpoint.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand-mark">N</div>
        <div className="kicker">NOVA · RESTRICTED</div>
        <h1>Dashboard password</h1>
        <p>Read-only paper operations. Enter the dashboard password to continue.</p>
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Password"
          autoFocus
        />
        <button className="button" type="submit" disabled={busy || !password}>
          {busy ? "Unlocking…" : "Unlock"}
        </button>
        {error ? <p className="error-text">{error}</p> : null}
      </form>
    </div>
  );
}
