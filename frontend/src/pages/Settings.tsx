import { useEffect, useState } from "react";

import { getAuthStatus, getUsage, logout, type UsageSummary, type UsageWindow } from "../api";
import { loadSettings, setSpeakReplies, setTheme, setVoiceMode } from "../settings";
import { applyTheme } from "../theme";
import type { ThemePref, VoiceMode } from "../types";
import { dictationSupported, speak, stopSpeaking } from "../voice";

const THEMES: { value: ThemePref; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const OPTIONS: { value: VoiceMode; label: string; hint: string }[] = [
  { value: "human", label: "Human voice", hint: "Natural-sounding TTS. Costs money per word." },
  { value: "browser", label: "Built-in voice", hint: "Your phone's free robotic voice." },
];

const SAMPLE =
  "You said you owe it to yourself to be in the best shape of your life. So go do the workout.";

interface VoiceStatus {
  human_voice: boolean;
  provider: string | null;
}

function money(dollars: number | null): string {
  if (dollars === null) return "—";
  // Sub-cent totals are normal early on, and rounding them to $0.00 reads as "free".
  return dollars < 0.01 && dollars > 0 ? "<$0.01" : `$${dollars.toFixed(2)}`;
}

function UsageRow({ label, window }: { label: string; window: UsageWindow }) {
  const tokens = window.input_tokens + window.output_tokens + window.cache_read_tokens;
  return (
    <div className="usage__row">
      <span className="usage__label">{label}</span>
      <span className="usage__value">{money(window.estimated_cost_usd)}</span>
      <span className="usage__detail">
        {window.calls} {window.calls === 1 ? "call" : "calls"} · {(tokens / 1000).toFixed(1)}k
        tokens
      </span>
    </div>
  );
}

export default function Settings() {
  const [settings, setSettings] = useState(loadSettings);
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [locking, setLocking] = useState(false);
  const [usage, setUsage] = useState<UsageSummary | null>(null);

  useEffect(() => {
    fetch("/api/voice/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ human_voice: false, provider: null }));
    getAuthStatus()
      .then((s) => setLocking(s.required))
      .catch(() => setLocking(false));
    getUsage().then(setUsage).catch(() => setUsage(null));
  }, []);

  return (
    <div className="settings">
      <header className="home__header">
        <h1 className="home__title">Settings</h1>
      </header>

      <section className="panel">
        <h2 className="panel__title">Voice</h2>

        <label className="choice">
          <input
            type="checkbox"
            checked={settings.speakReplies}
            onChange={(e) => {
              if (!e.target.checked) stopSpeaking();
              setSettings(setSpeakReplies(e.target.checked));
            }}
          />
          <span>
            <span className="choice__label">Read replies aloud</span>
            <span className="choice__hint">The coach speaks every answer as it arrives.</span>
          </span>
        </label>

        {OPTIONS.map((opt) => (
          <label key={opt.value} className="choice">
            <input
              type="radio"
              name="voice"
              checked={settings.voiceMode === opt.value}
              onChange={() => setSettings(setVoiceMode(opt.value))}
            />
            <span>
              <span className="choice__label">{opt.label}</span>
              <span className="choice__hint">{opt.hint}</span>
            </span>
          </label>
        ))}

        <button
          className="button"
          type="button"
          onClick={() => void speak(SAMPLE, settings.voiceMode)}
        >
          Hear it
        </button>

        {status && !status.human_voice && (
          <p className="muted">
            No human voice provider is configured, so "human" falls back to the built-in
            voice. Set <code>ELEVENLABS_API_KEY</code> or <code>OPENAI_API_KEY</code> in{" "}
            <code>backend/.env</code>.
          </p>
        )}
        {status?.human_voice && <p className="muted">Human voice via {status.provider}.</p>}
      </section>

      {usage && (
        <section className="panel">
          <h2 className="panel__title">What it costs</h2>
          <div className="usage">
            <UsageRow label="Today" window={usage.today} />
            <UsageRow label="7 days" window={usage.week} />
            <UsageRow label="30 days" window={usage.month} />
          </div>
          <p className="muted">
            Estimated from list prices, not a bill.
            {usage.month.calls > 0 && (
              <> {Math.round(usage.month.cached_share * 100)}% of input came from cache.</>
            )}
          </p>
        </section>
      )}

      <section className="panel">
        <h2 className="panel__title">Appearance</h2>
        {THEMES.map((t) => (
          <label key={t.value} className="choice">
            <input
              type="radio"
              name="theme"
              checked={settings.theme === t.value}
              onChange={() => {
                setSettings(setTheme(t.value));
                applyTheme(t.value);
              }}
            />
            <span className="choice__label">{t.label}</span>
          </label>
        ))}
      </section>

      {locking && (
        <section className="panel">
          <h2 className="panel__title">Access</h2>
          <button
            className="button"
            type="button"
            onClick={() => {
              // The 401 from the next request is what raises the lock screen.
              void logout().then(() => window.location.reload());
            }}
          >
            Lock this device
          </button>
        </section>
      )}

      <section className="panel">
        <h2 className="panel__title">Talking to it</h2>
        <p className="muted">
          {dictationSupported()
            ? "Tap the microphone next to the message box and just talk. It sends when you stop."
            : "This browser can't do speech recognition — Safari on iOS or Chrome work. You can still type."}
        </p>
      </section>
    </div>
  );
}
