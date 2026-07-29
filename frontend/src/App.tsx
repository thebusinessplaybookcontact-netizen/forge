import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { ChatProvider } from "./ChatContext";
import Chat from "./pages/Chat";
import Goals from "./pages/Goals";
import Home from "./pages/Home";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/chat", label: "Chat", end: false },
  { to: "/goals", label: "Goals", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export default function App() {
  return (
    // One chat session shared by every screen: the conversation survives navigation,
    // and Home can react to changes the coach makes.
    <ChatProvider>
      <div className="app">
        <main className="app__main">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav__link${isActive ? " nav__link--active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </ChatProvider>
  );
}
