import { useEffect, useState } from "react";

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

export default function Settings() {
  const [settings, setSettings] = useState(loadSettings);
  const [status, setStatus] = useState<VoiceStatus | null>(null);

  useEffect(() => {
    fetch("/api/voice/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ human_voice: false, provider: null }));
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
