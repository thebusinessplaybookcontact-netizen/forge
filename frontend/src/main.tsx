import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { loadSettings } from "./settings";
import { applyTheme, watchSystemTheme } from "./theme";
import "./styles.css";

// index.html already stamped the theme before paint; this keeps it in step when the OS
// preference changes while the app is open.
applyTheme(loadSettings().theme);
watchSystemTheme(() => loadSettings().theme);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);

// Register the service worker so the app is installable on the phone.
// Dev is skipped: a cached shell during development is only ever confusing.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* installability is a nice-to-have; never block the app on it */
    });
  });
}
