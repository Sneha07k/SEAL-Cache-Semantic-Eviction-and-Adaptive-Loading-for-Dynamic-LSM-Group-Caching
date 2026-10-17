import { useEffect, useMemo, useState } from "react";
import { api, friendly } from "../api.js";
import { canon, cacheMeta, fmt, pct, xFormatter, xLabel } from "../lib/style.js";
import LineChart from "./LineChart.jsx";
import { GainBars, Sparkline, StatTile, sigBadge } from "./viz.jsx";

const EXTRA = {
  qreads_L0_share: ["share of query reads from L0 runs", "share of reads from L0"],
  maint_byte_frac: ["share of cache bytes held by maintained groups", "share of cache bytes, maintained"],
  maint_hit_frac: ["share of maintained groups hit at least once", "share of maintained groups hit"],
};
const VIEWS = [["reads", "Reads per query"], ["gain", "Paired gain"], ["extra", "Other measurements"]];
const TILE_PAIRS = [["zio-naive", "group"], ["zio-naive", "block"], ["zio-naive", "range"], ["group", "block"], ["group+seed", "group"], ["zio-naive", "group+seed"]];

export default function Results() {
  const [files, setFiles] = useState(null);
  const [sel, setSel] = useState("");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState("reads");
  const [off, setOff] = useState(() => new Set());
  const [base, setBase] = useState("group");
  const [extraKey, setExtraKey] = useState("qreads_L0_share");
  const [table, setTable] = useState(false);
  const [withNone, setWithNone] = useState(false);
  const [focusOurs, setFocusOurs] = useState(false);
  const [hoverKey, setHoverKey] = useState(null);
  const [atX, setAtX] = useState(null);

  useEffect(() => {
    api.results().then((f) => {
      setFiles(f);
      const pick = f.find((x) => !x.archived && x.param && x.name.includes("write_sweep")) || f.find((x) => !x.archived && x.param) || f[0];
      if (pick) setSel(pick.name);
    }).catch((e) => setErr(friendly(e)));
  }, []);
  useEffect(() => {
    if (!sel) return;
    setLoading(true); setErr(null);
    api.result(sel).then((d) => {
      setData(d); setOff(new Set());
      setBase(d.caches.includes("group") ? "group" : d.caches[0]);
      setExtraKey(Object.keys(d.extras)[0] || "qreads_L0_share");
      setAtX(d.param ? (d.xs.includes(0.5) ? 0.5 : d.xs[d.xs.length - 1]) : null);
    }).catch((e) => { setErr(friendly(e)); setData(null); }).finally(() => setLoading(false));
  }, [sel]);

  const groups = useMemo(() => {
    const g = {};
    [...(files || [])].sort((a, b) => Number(a.archived) - Number(b.archived) || Number(!!b.param) - Number(!!a.param) || a.name.localeCompare(b.name))
      .forEach((f) => { const dir = f.name.includes("/") ? f.name.slice(0, f.name.lastIndexOf("/")) : "(root)"; (g[dir] = g[dir] || []).push(f); });
    return g;
  }, [files]);

  const ordered = data ? canon(data.caches) : [];
  const active = ordered.filter((c) => !off.has(c) && !(view === "gain" && c === "none" && !withNone));
  const xf = data ? xFormatter(data.param) : String;
  const focus = hoverKey ? new Set([hoverKey]) : focusOurs ? new Set(["zio-naive", "group", "none"]) : null;

  const built = useMemo(() => {
    if (!data || !data.param) return { series: [] };
    const mk = (c, points) => ({ key: c, label: cacheMeta(c).label, color: cacheMeta(c).color, marker: cacheMeta(c).marker, dash: cacheMeta(c).dash, points });
    if (view === "reads") return { yLabel: "block reads / query (lower = better)", yFmt: (v) => v.toFixed(3),
      series: active.filter((c) => data.series[c]).map((c) => mk(c, data.series[c].map((p) => ({ x: p.x, y: p.mean, ci: p.ci })))) };
    if (view === "gain") return { yLabel: `% fewer reads vs ${cacheMeta(base).label}`, zero: true, yFmt: (v) => `${v.toFixed(1)}%`,
      series: active.filter((c) => c !== base && data.paired[`${c}|${base}`]).map((c) =>
        mk(c, data.paired[`${c}|${base}`].map((p) => ({ x: p.x, y: p.reduction, ci: p.ci, hollow: !p.significant })))) };
    return { yLabel: EXTRA[extraKey]?.[1], yFmt: (v) => v.toFixed(2), includeZero: true,
      series: active.filter((c) => data.extras[extraKey]?.[c]).map((c) => mk(c, data.extras[extraKey][c].map((p) => ({ x: p.x, y: p.mean })))) };
  }, [data, view, active.join("|"), base, extraKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const pAt = (a, b, x) => data?.paired[`${a}|${b}`]?.find((p) => p.x === x);
  const tiles = data && data.param ? TILE_PAIRS.filter(([a, b]) => data.paired[`${a}|${b}`]).slice(0, 4) : [];
  const gainRows = data && data.param && atX !== null ? ordered.filter((c) => c !== base && c !== "none" && !off.has(c) && pAt(c, base, atX))
    .map((c) => { const p = pAt(c, base, atX); return { key: c, value: p.reduction, ci: p.ci, significant: p.significant, worse: p.worse_seeds, n: p.n }; }) : [];
  const toggle = (c) => setOff((o) => { const n = new Set(o); n.has(c) ? n.delete(c) : n.add(c); return n; });

  return (
    <div className="stack">
      {err && <p className="error" role="alert">{err}</p>}
      <section className="card filterbar">
        <label className="select-pill wide">
          <span>Result file</span>
          <select value={sel} onChange={(e) => setSel(e.target.value)} disabled={!files?.length}>
            {!files?.length && <option value="">{files ? "No result CSVs found" : "Loading…"}</option>}
            {Object.entries(groups).map(([dir, fs]) => (
              <optgroup key={dir} label={dir}>
                {fs.map((f) => <option key={f.name} value={f.name}>{f.name.split("/").pop()} · {f.param ? (xLabel[f.param] || f.param) : "no sweep"} · {f.seeds} seeds{f.archived ? " · sensitivity" : ""}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
        <div className="seg" role="group" aria-label="View">
          {VIEWS.map(([k, l]) => <button key={k} aria-pressed={view === k} onClick={() => setView(k)} disabled={!data || (k === "extra" && !Object.keys(data.extras).length)}>{l}</button>)}
        </div>
        {view === "gain" && data && (
          <label className="select-pill"><span>Baseline</span>
            <select value={base} onChange={(e) => setBase(e.target.value)}>{ordered.map((c) => <option key={c} value={c}>{cacheMeta(c).label}</option>)}</select></label>
        )}
        {view === "extra" && data && (
          <label className="select-pill"><span>Measure</span>
            <select value={extraKey} onChange={(e) => setExtraKey(e.target.value)}>{Object.keys(data.extras).map((k) => <option key={k} value={k}>{EXTRA[k]?.[0] ?? k}</option>)}</select></label>
        )}
        <button className="btn" aria-pressed={focusOurs} onClick={() => setFocusOurs(!focusOurs)} disabled={!data}>Ours vs Group Cache</button>
        {view === "gain" && data?.caches.includes("none") && <button className="btn" aria-pressed={withNone} onClick={() => setWithNone(!withNone)}>Include No cache</button>}
        <button className="btn" aria-pressed={table} onClick={() => setTable(!table)} disabled={!data}>Table</button>
      </section>

      {data && (
        <div className="meta-line">
          <b>{data.name}</b>
          <span>{data.seeds.length} seeds ({data.seeds[0]}–{data.seeds[data.seeds.length - 1]})</span>
          {Object.entries(data.meta).filter(([k, v]) => v.length === 1 && k !== data.param).map(([k, v]) => <span key={k}>{(xLabel[k] || k.replace("_", " "))} {v[0]}</span>)}
        </div>
      )}
      {data?.archived && (
        <p className="note warn">Sensitivity run (old warm-up protocol, different hot set). Not a headline result; see DECISIONS.md §11.</p>
      )}
      {loading && <p className="hint">Loading result…</p>}

      {data && !data.param && <section className="card"><p className="note">This file has no varying sweep column, so only the table applies.</p><ResultTable data={data} view={view} base={base} extraKey={extraKey} xf={xf} /></section>}

      {data && data.param && (
        <div className="grid-main">
          <section className="card" style={{ opacity: loading ? 0.5 : 1 }}>
            <div className="card-head">
              <div>
                <h2>{view === "reads" ? "Query block reads per query" : view === "gain" ? `Paired gain vs ${cacheMeta(base).label}` : EXTRA[extraKey]?.[0]}</h2>
                <p className="sub">{view === "gain" ? "Above 0 = fewer reads than the baseline; hollow = CI includes 0." : "Mean over seeds, band = 95% CI."}</p>
              </div>
            </div>
            {!table ? (
              <>
                <LineChart series={built.series} xs={data.xs} xLabel={xLabel[data.param] || data.param} yLabel={built.yLabel} yFmt={built.yFmt}
                           xFmt={xf} zeroLine={!!built.zero} includeZero={!!built.includeZero} logX={data.param === "cache_frac"}
                           ariaLabel={`${built.yLabel} versus ${xLabel[data.param]}`} focus={focus} activeX={atX} onPickX={setAtX} />
                <div className="legend" role="group" aria-label="Show or hide caches (hover to highlight)">
                  {ordered.filter((c) => !(view === "gain" && (c === base || (c === "none" && !withNone)))).map((c) => (
                    <button key={c} aria-pressed={!off.has(c)} onClick={() => toggle(c)} onMouseEnter={() => setHoverKey(c)} onMouseLeave={() => setHoverKey(null)}
                            onFocus={() => setHoverKey(c)} onBlur={() => setHoverKey(null)} title="Click to show/hide · hover to highlight">
                      <span className="lkey" style={{ "--c": cacheMeta(c).color }} />{cacheMeta(c).label}
                    </button>
                  ))}
                </div>
              </>
            ) : <ResultTable data={data} view={view} base={base} extraKey={extraKey} xf={xf} />}
          </section>

          <aside className="card side-tiles">
            <div className="card-head">
              <div><h2>At {xLabel[data.param]} = {atX !== null ? xf(atX) : "–"}</h2><p className="sub">{data.seeds.length} seeds, paired</p></div>
            </div>
            <div className="xpick" role="group" aria-label={`Pick ${xLabel[data.param]}`}>
              {data.xs.map((x) => <button key={x} aria-pressed={x === atX} onClick={() => setAtX(x)}>{xf(x)}</button>)}
            </div>
            <div className="tiles col1">
              {tiles.length ? tiles.map(([a, b]) => {
                const p = pAt(a, b, atX);
                return (
                  <StatTile key={`${a}|${b}`} label={`${cacheMeta(a).label} vs ${cacheMeta(b).label}`} color={cacheMeta(a).color}
                            value={p ? pct(p.reduction, 2) : "–"} sub={p ? `±${p.ci.toFixed(2)} · worse in ${p.worse_seeds}/${p.n} seeds` : "no data"}
                            badge={sigBadge(p)}
                            spark={<Sparkline color={cacheMeta(a).color} points={data.paired[`${a}|${b}`].map((q) => ({ y: q.reduction, active: q.x === atX }))} />} />
                );
              }) : <p className="hint">This file has no pairs to summarise.</p>}
            </div>
          </aside>
        </div>
      )}

      {data && data.param && gainRows.length > 0 && (
        <section className="card">
          <div className="card-head">
            <div><h2>Everything vs {cacheMeta(base).label} at {xLabel[data.param]} = {xf(atX)}</h2>
              <p className="sub">Paired, 95% CI. Faded = not significant.</p></div>
          </div>
          <GainBars rows={gainRows} baseLabel={cacheMeta(base).label} />
        </section>
      )}

      <details className="help">
        <summary>Method</summary>
        <p>Mean over seeds with 95% t-intervals. Paired gain = per-seed % reduction, averaged. Data: CSVs from backend/app/experiments.
          Block reads are an I/O proxy, not latency.</p>
      </details>
    </div>
  );
}

function ResultTable({ data, view, base, extraKey, xf }) {
  const cols = canon(data.caches);
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead><tr><th>{xLabel[data.param] || "all"}</th>{cols.map((c) => <th key={c} className="r"><span className="dotc" style={{ background: cacheMeta(c).color, marginRight: 6 }} />{cacheMeta(c).label}</th>)}</tr></thead>
        <tbody>
          {data.xs.map((x) => (
            <tr key={String(x)}>
              <td className="mono">{x === null ? "all" : xf(x)}</td>
              {cols.map((c) => {
                if (view === "gain") {
                  const p = c === base ? null : data.paired[`${c}|${base}`]?.find((q) => q.x === x);
                  return <td key={c} className={`r num gain ${p ? (!p.significant ? "ns" : p.reduction > 0 ? "pos" : "neg") : ""}`}>{p ? `${pct(p.reduction, 2)} ±${p.ci.toFixed(2)} (${p.worse_seeds}/${p.n})` : "–"}</td>;
                }
                if (view === "extra") { const p = data.extras[extraKey]?.[c]?.find((q) => q.x === x); return <td key={c} className="r num">{p ? fmt(p.mean) : "–"}</td>; }
                const p = data.series[c]?.find((q) => q.x === x);
                return <td key={c} className="r num">{p ? `${fmt(p.mean)} ±${fmt(p.ci)}` : "–"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
