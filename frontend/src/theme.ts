import type { ThemePref } from "./types";

// Must stay in step with --ground in styles.css and the pre-paint script in
// index.html. Three copies exist because each runs at a moment the others cannot:
// the inline script before first paint, this on every theme change, and the CSS
// itself. A mismatch shows up as a status bar that doesn't match the page.
const THEME_COLORS = { light: "#f4f6fa", dark: "#07090d" };

/** Resolve a preference to the theme actually being shown. */
export function resolveTheme(pref: ThemePref): "light" | "dark" {
  if (pref !== "system") return pref;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Stamp the theme on <html>.
 *
 * The same attribute is set by an inline script in index.html before first paint, so
 * this only ever changes an already-correct value — no flash of the wrong theme.
 */
export function applyTheme(pref: ThemePref): void {
  const theme = resolveTheme(pref);
  document.documentElement.dataset.theme = theme;
  // Keeps the phone's status bar and PWA chrome in step with the page.
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", THEME_COLORS[theme]);
}

/** Follow the OS while the preference is "system". Returns an unsubscribe. */
export function watchSystemTheme(getPref: () => ThemePref): () => void {
  const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
  if (!mq) return () => {};
  const onChange = () => {
    if (getPref() === "system") applyTheme("system");
  };
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}
