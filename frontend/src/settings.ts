import type { AppSettings, VoiceMode } from "./types";

const KEY = "coach.settings";

const DEFAULTS: AppSettings = {
  // "human" will route through the backend TTS endpoint once voice lands (build step 5).
  // "browser" uses the free built-in speechSynthesis voice for comparison.
  voiceMode: "human",
};

export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

export function saveSettings(settings: AppSettings): void {
  localStorage.setItem(KEY, JSON.stringify(settings));
}

export function setVoiceMode(mode: VoiceMode): AppSettings {
  const next = { ...loadSettings(), voiceMode: mode };
  saveSettings(next);
  return next;
}
