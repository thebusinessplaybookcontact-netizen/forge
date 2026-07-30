import { useCallback, useEffect, useState, type ReactNode } from "react";

import { getAuthStatus, login, setUnauthorizedHandler } from "./api";

type Phase = "checking" | "locked" | "open";

/**
 * Shows the lock screen until there's a session.
 *
 * Nothing inside mounts while locked, so the chat session and dashboard never start
 * fetching against a locked API. Any 401 later — an expired session, a changed
 * passcode — puts this back up wherever it happens.
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => setPhase("locked"));
    getAuthStatus()
      .then((s) => setPhase(s.authenticated ? "open" : "locked"))
      // If status itself can't be reached the app is unusable anyway; show the lock
      // screen rather than a half-working dashboard.
      .catch(() => setPhase("locked"));
    return () => setUnauthorizedHandler(null);
  }, []);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!passcode.trim() || busy) return;
      setBusy(true);
      const message = await login(passcode);
      setBusy(false);
      if (message) {
        setError(message);
        setPasscode("");
        return;
      }
      setError(null);
      setPasscode("");
      setPhase("open");
    },
    [passcode, busy],
  );

  if (phase === "checking") return <div className="lock" aria-busy="true" />;

  if (phase === "locked") {
    return (
      <div className="lock">
        <form className="lock__form" onSubmit={submit}>
          <h1 className="lock__title">Coach</h1>
          <p className="lock__hint">Enter your passcode.</p>
          <input
            className="input"
            type="password"
            inputMode="text"
            autoComplete="current-password"
            aria-label="Passcode"
            value={passcode}
            autoFocus
            onChange={(e) => setPasscode(e.target.value)}
          />
          {error && (
            <p className="chat__error" role="alert">
              {error}
            </p>
          )}
          <button className="button lock__submit" type="submit" disabled={busy || !passcode.trim()}>
            {busy ? "Checking…" : "Unlock"}
          </button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
