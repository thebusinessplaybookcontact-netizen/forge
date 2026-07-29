import { useState } from "react";

import { loadSettings, setVoiceMode } from "../settings";
import type { VoiceMode } from "../types";

const OPTIONS: { value: VoiceMode; label: string; hint: string }[] = [
  { value: "human", label: "Human voice", hint: "Natural-sounding TTS. Costs money per word." },
  { value: "browser", label: "Built-in voice", hint: "Your phone's free robotic voice." },
];

export default function Settings() {
  const [settings, setSettings] = useState(loadSettings);

  return (
    <div className="settings">
      <header className="home__header">
        <h1 className="home__title">Settings</h1>
      </header>

      <section className="panel">
        <h2 className="panel__title">Voice</h2>
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
        <p className="muted">
          The preference is saved, but speech isn't wired up yet — that's build step 5.
        </p>
      </section>
    </div>
  );
}
