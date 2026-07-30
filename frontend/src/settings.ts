import type { AppSettings, ThemePref, VoiceMode } from "./types";

const KEY = "coach.settings";

const DEFAULTS: AppSettings = {
  // "human" routes through the backend TTS provider; "browser" uses the phone's free
  // built-in voice. Falls back to browser automatically if no provider is configured.
  voiceMode: "human",
  // Off by default: the first thing a new install does shouldn't be talk at you.
  speakReplies: false,
  theme: "system",
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

export function setSpeakReplies(on: boolean): AppSettings {
  const next = { ...loadSettings(), speakReplies: on };
  saveSettings(next);
  return next;
}

export function setTheme(theme: ThemePref): AppSettings {
  const next = { ...loadSettings(), theme };
  saveSettings(next);
  return next;
}
