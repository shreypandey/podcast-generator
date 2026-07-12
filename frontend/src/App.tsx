import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { USE_MOCK } from "./api";
import { HomePage } from "./pages/HomePage";
import { RunPage } from "./pages/RunPage";

type Theme = "light" | "dark" | "system";

function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) || "system"
  );
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  return { theme, setTheme };
}

function Topbar() {
  const { theme, setTheme } = useTheme();
  const cycle = () => setTheme(theme === "light" ? "dark" : theme === "dark" ? "system" : "light");
  const icon = theme === "light" ? "☀️" : theme === "dark" ? "🌙" : "🖥️";
  return (
    <div className="topbar">
      <Link to="/" className="brand">
        <span className="logo">◐</span>
        <span>
          Deepcast
          <small>grounded debate podcasts</small>
        </span>
      </Link>
      <div className="topbar-spacer" />
      {USE_MOCK && (
        <span className="badge mock" title="Running against the in-browser mock backend">
          demo · mock backend
        </span>
      )}
      <button className="btn ghost sm" onClick={cycle} title={`Theme: ${theme}`}>
        {icon}
      </button>
    </div>
  );
}

export default function App() {
  return (
    <div className="app-shell">
      <Topbar />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/runs/:runId" element={<RunPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </div>
  );
}
