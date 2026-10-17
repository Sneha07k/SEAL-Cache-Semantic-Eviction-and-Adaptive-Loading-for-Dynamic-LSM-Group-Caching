import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import Benchmark from "./components/Benchmark.jsx";
import Results from "./components/Results.jsx";
import TwinLab from "./components/TwinLab.jsx";

const TABS = [
  ["bench", "Benchmark"],
  ["results", "Results"],
  ["lab", "Engine lab"],
];

function loadTab() {
  try { const t = localStorage.getItem("tab"); return TABS.some(([k]) => k === t) ? t : "bench"; } catch { return "bench"; }
}

export default function App() {
  const [tab, setTab] = useState(loadTab);
  const [online, setOnline] = useState(null);
  const [nonce, setNonce] = useState(0);
  const ping = useCallback(() => api.meta().then(() => setOnline(true)).catch(() => setOnline(false)), []);
  useEffect(() => { ping(); const t = setInterval(ping, 15000); return () => clearInterval(t); }, [ping]);
  const pick = (k) => { setTab(k); try { localStorage.setItem("tab", k); } catch { /* private mode */ } };
  const onKey = (e) => {
    const i = TABS.findIndex(([k]) => k === tab);
    if (e.key === "ArrowRight") pick(TABS[(i + 1) % TABS.length][0]);
    if (e.key === "ArrowLeft") pick(TABS[(i + TABS.length - 1) % TABS.length][0]);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <div>
            <h1>LSM cache testbed</h1>
            <p>KV-group cache maintenance in LSM-trees</p>
          </div>
        </div>
        <div className="top-actions">
          <span className={`chip ${online ? "ok" : online === false ? "bad" : ""}`} role="status">
            <span className="dot" />{online ? "backend ok" : online === false ? "backend offline" : "connecting"}
          </span>
          <button className="btn small" onClick={() => { ping(); setNonce((n) => n + 1); }}>Refresh</button>
        </div>
      </header>

      {online === false && (
        <p className="error" role="alert">Can't reach the backend. Start it with <span className="mono">cd backend &amp;&amp; python run.py</span>, then press Refresh.</p>
      )}

      <nav className="tabs" role="tablist" aria-label="Views" onKeyDown={onKey}>
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" className="tab" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} onClick={() => pick(k)}>{label}</button>
        ))}
      </nav>

      <main role="tabpanel" key={`${tab}-${nonce}`}>
        {tab === "bench" && <Benchmark />}
        {tab === "results" && <Results />}
        {tab === "lab" && <TwinLab />}
      </main>
    </div>
  );
}
