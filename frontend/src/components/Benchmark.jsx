import { useEffect, useRef, useState } from "react";
import { api, friendly } from "../api.js";
import { CANON, cacheMeta, fmt, pct } from "../lib/style.js";
import { Columns, GainBars, Meter, StatTile, columnScale, sigBadge } from "./viz.jsx";

const PRESETS = [
  ["read", "Read-only", 0], ["light", "Light writes (20%)", 0.2],
  ["mixed", "Mixed (50% writes)", 0.5], ["heavy", "Write-heavy (80%)", 0.8],
];
const SIZES = [[5000, "5K keys · fast"], [10000, "10K keys"], [20000, "20K keys · slower"]];

function Slider({ label, value, set, min, max, step, unit = "", disabled, hint }) {
  return (
    <label className="field">
      <span className="field-head"><span>{label}</span><span className="val">{value}{unit}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => set(Number(e.target.value))} />
      {hint && <span className="faint" style={{ fontSize: 11 }}>{hint}</span>}
    </label>
  );
}

export default function Benchmark() {
  const [write, setWrite] = useState(0.5);
  const [scan, setScan] = useState(0.2);
  const [zipf, setZipf] = useState(0.8);
  const [cachePct, setCachePct] = useState(5);
  const [seeds, setSeeds] = useState(2);
  const [keys, setKeys] = useState(10000);
  const [policy, setPolicy] = useState("leveling");
  const [caches, setCaches] = useState(new Set(["none", "block", "range", "group", "zio-naive"]));
  const [open, setOpen] = useState(false);
  const [res, setRes] = useState(null);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState(null);
  const [base, setBase] = useState("group");
  const [sortBest, setSortBest] = useState(false);
  const [table, setTable] = useState(false);
  const [zoom, setZoom] = useState(true);
  const abort = useRef(null), timer = useRef(null);
  useEffect(() => () => { clearInterval(timer.current); abort.current?.abort(); }, []);

  const chosen = CANON.filter((c) => caches.has(c));
  const toggle = (c) => setCaches((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n; });
  const preset = PRESETS.find((p) => p[2] === write)?.[0] ?? "custom";

  const execute = async () => {
    if (!chosen.length) { setErr("Pick at least one cache."); return; }
    abort.current = new AbortController();
    setRunning(true); setErr(null); setElapsed(0);
    const t0 = Date.now();
    timer.current = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 500);
    try {
      const r = await api.benchmark({ caches: chosen, seeds, keys, warmup: Math.round(keys / 2), ops: keys, write_ratio: write,
        scan_share: scan, zipf, cache_frac: cachePct / 100, block_size: 48, policy, insert_share: 0.5 }, abort.current.signal);
      setRes(r);
      if (!r.summary[base]) setBase(r.summary.group ? "group" : chosen[0]);
    } catch (e) { setErr(friendly(e)); }
    finally { clearInterval(timer.current); setRunning(false); }
  };

  const shown = res ? CANON.filter((c) => res.summary[c]) : [];
  const list = res && sortBest ? [...shown].sort((a, b) => res.summary[a].mean - res.summary[b].mean) : shown;
  const colItems = res ? list.map((c) => ({ key: c, value: res.summary[c].mean, ci: res.summary[c].ci, n: res.summary[c].n })) : [];
  const scale = res ? columnScale(colItems, zoom) : null;
  const bestC = res ? shown.reduce((a, b) => (res.summary[a].mean <= res.summary[b].mean ? a : b)) : null;
  const P = (cand, b) => res?.paired.find((p) => p.cand === cand && p.base === b);
  const ours = res?.summary["zio-naive"] ? "zio-naive" : bestC;
  const meterVs = res?.summary.none ? P(ours, "none") : null;
  const gainRows = res ? list.filter((c) => c !== base).map((c) => { const p = P(c, base); return { key: c, value: p.reduction, ci: p.ci, significant: p.significant, worse: p.worse_seeds, n: p.n }; }) : [];

  const insights = [];
  if (res) {
    const verdict = (p) => (p.n < 2 ? "1 seed" : !p.significant ? "n.s." : p.reduction > 0 ? "significant" : "significant loss");
    insights.push(<>Lowest: <b>{cacheMeta(bestC).label}</b>, {fmt(res.summary[bestC].mean)} reads/query.</>);
    const og = P("zio-naive", "group");
    if (og) insights.push(<>Ours vs Group Cache: <b>{pct(og.reduction, 2)}</b>{og.n > 1 ? ` ±${og.ci.toFixed(2)}` : ""} ({verdict(og)}).</>);
    const gb = P("group", "block");
    if (gb) insights.push(<>Group Cache vs block cache: <b>{pct(gb.reduction, 2)}</b>{gb.n > 1 ? ` ±${gb.ci.toFixed(2)}` : ""} ({verdict(gb)}).</>);
    insights.push(<>{res.params.seeds.length} seed(s), {res.params.keys.toLocaleString()} keys. Demo scale; see Results for the full runs.</>);
  }

  return (
    <div className="stack">
      {err && <p className="error" role="alert">{err}</p>}
      <section className="card">
        <div className="card-head">
          <div>
            <h2>Query block reads per query</h2>
            <p className="sub">Same trace for every cache. Lower is better.</p>
          </div>
          <div className="toolbar">
            <label className="select-pill">
              <span>Workload</span>
              <select value={preset} disabled={running} onChange={(e) => { const p = PRESETS.find((x) => x[0] === e.target.value); if (p) setWrite(p[2]); }}>
                {PRESETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                {preset === "custom" && <option value="custom">Custom ({Math.round(write * 100)}% writes)</option>}
              </select>
            </label>
            <button className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>Settings</button>
            <button className="btn" aria-pressed={zoom} disabled={!res} onClick={() => setZoom(!zoom)} title="Start the axis near the smallest value so close results separate; turn off for the true zero-based scale">Zoom</button>
            <button className="btn" aria-pressed={sortBest} disabled={!res} onClick={() => setSortBest(!sortBest)}>Sort best first</button>
            <button className="btn" aria-pressed={table} disabled={!res} onClick={() => setTable(!table)}>Table</button>
            <button className="btn primary" disabled={running} onClick={execute}>{running ? `Running ${elapsed}s` : "Run"}</button>
            {running && <button className="btn" onClick={() => abort.current?.abort()}>Cancel</button>}
          </div>
        </div>

        <div className="cache-chips" role="group" aria-label="Caches to run">
          {CANON.map((c) => (
            <button key={c} className="cchip" aria-pressed={caches.has(c)} disabled={running} onClick={() => toggle(c)} style={{ "--c": cacheMeta(c).color }}>
              <span className="dotc" />{cacheMeta(c).label}
            </button>
          ))}
          <span className="faint" style={{ fontSize: 12 }}>{chosen.length} caches × {seeds} seed{seeds > 1 ? "s" : ""} = {chosen.length * seeds} runs</span>
        </div>

        {open && (
          <div className="drawer">
            <Slider label="Write ratio" hint="half of the writes insert new keys (paper mix)" value={write} set={setWrite} min={0} max={0.9} step={0.05} disabled={running} />
            <Slider label="Scan share of reads" value={scan} set={setScan} min={0} max={1} step={0.05} disabled={running} />
            <Slider label="Zipf skew" hint="0.8 = paper default" value={zipf} set={setZipf} min={0.4} max={1.2} step={0.05} disabled={running} />
            <Slider label="Cache size" unit="% of data" value={cachePct} set={setCachePct} min={1} max={25} step={1} disabled={running} />
            <Slider label="Seeds" hint="2+ seeds give confidence intervals" value={seeds} set={setSeeds} min={1} max={5} step={1} disabled={running} />
            <label className="field"><span>Dataset</span>
              <select value={keys} disabled={running} onChange={(e) => setKeys(Number(e.target.value))}>{SIZES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <label className="field"><span>Compaction policy</span>
              <select value={policy} disabled={running} onChange={(e) => setPolicy(e.target.value)}><option value="leveling">Leveling</option><option value="tiering">Tiering</option></select></label>
          </div>
        )}

        {!res && (
          <div className={`cols ghost ${running ? "busy" : ""}`} aria-busy={running}>
            {chosen.map((c, i) => (
              <div className="col" key={c}><div className="col-track">
                <div className="col-fill" style={{ height: `${running ? 30 + ((i * 23) % 50) : 8}%`, "--c": "#1d2840", "--c2": "#26324f", "--glow": "transparent" }} />
              </div><div className="col-label"><span className="dotc" style={{ background: cacheMeta(c).color }} />{cacheMeta(c).label}</div><div className="col-role">{running ? "simulating…" : "waiting"}</div></div>
            ))}
            {!running && <div className="ghost-msg">Press <b>Run</b> to start {chosen.length * seeds} simulations</div>}
          </div>
        )}
        {res && !table && (
          <>
            <Columns items={colItems} scale={scale} base={base} best={bestC} onPick={setBase} dim={running} />
            {scale.zoom && <p className="hint" style={{ marginTop: 8 }}>Zoomed: bars start at {fmt(scale.floor, 2)}, not 0.</p>}
          </>
        )}
        {res && table && <RawTable res={res} shown={shown} />}
        {res && <p className="hint" style={{ marginTop: 10 }}>{res.note} Seeds {res.params.seeds.join(", ")} · {res.params.keys.toLocaleString()} keys · {res.params.warmup.toLocaleString()} warm-up + {res.params.ops.toLocaleString()} measured ops · {Math.round(res.params.write_ratio * 100)}% writes · cache {Math.round(res.params.cache_frac * 100)}%.</p>}
      </section>

      {res && (
        <div className="grid-3">
          <section className="card">
            <div className="card-head"><div><h2>Saved vs no cache</h2><p className="sub">{cacheMeta(ours).label}</p></div></div>
            {meterVs ? (
              <>
                <Meter value={Math.max(meterVs.reduction, 0)} max={Math.max(10, Math.ceil((Math.max(meterVs.reduction, ...["group", "block", "range"].filter((c) => res.summary[c] && c !== ours).map((c) => P(c, "none").reduction)) * 1.4) / 5) * 5)} color={cacheMeta(ours).color}
                       label="Reads saved vs no cache" sub={meterVs.n > 1 ? `±${meterVs.ci.toFixed(1)} pts, ${meterVs.n} seeds` : "1 seed"}
                       ticks={["group", "block", "range"].filter((c) => c !== ours && res.summary[c]).map((c) => ({ value: Math.max(P(c, "none").reduction, 0), label: cacheMeta(c).label, color: cacheMeta(c).color }))} />
                <div className="legend-mini">
                  {["group", "block", "range"].filter((c) => c !== ours && res.summary[c]).map((c) => (
                    <span key={c}><span className="tick" style={{ background: cacheMeta(c).color }} />{cacheMeta(c).label} {pct(P(c, "none").reduction, 1)}</span>))}
                </div>
              </>
            ) : <p className="hint" style={{ padding: "40px 0" }}>Add No cache to the run to see this.</p>}
          </section>

          <section className="card">
            <div className="card-head"><div><h2>Summary</h2></div></div>
            <div className="tiles">
              <StatTile label="Lowest reads / query" value={fmt(res.summary[bestC].mean)} sub={cacheMeta(bestC).label} color={cacheMeta(bestC).color} />
              {P("zio-naive", "group") && <StatTile label="Ours vs Group Cache" value={pct(P("zio-naive", "group").reduction, 2)} sub="fewer reads, paired" color={cacheMeta("zio-naive").color} badge={sigBadge(P("zio-naive", "group"))} />}
              {P("group", "block") && <StatTile label="Group vs Block cache" value={pct(P("group", "block").reduction, 2)} sub="fewer reads, paired" color={cacheMeta("group").color} badge={sigBadge(P("group", "block"))} />}
              <StatTile label="Simulations" value={res.rows.length} sub={`${res.params.seeds.length} seeds × ${shown.length} caches`} />
            </div>
          </section>

          <section className="card insight">
            <div className="card-head"><div><h2>Notes</h2></div></div>
            <ul className="insights">{insights.map((t, i) => <li key={i}>{t}</li>)}</ul>
          </section>
        </div>
      )}

      {res && (
        <section className="card">
          <div className="card-head">
            <div><h2>Compared with {cacheMeta(base).label}</h2><p className="sub">Paired per seed, 95% CI. Faded = not significant. Click a column to change the baseline.</p></div>
          </div>
          <GainBars rows={gainRows} baseLabel={cacheMeta(base).label} />
        </section>
      )}

      <details className="help">
        <summary>Method</summary>
        <p>Identical trace and byte budget (incl. metadata) per cache. Metric: disk blocks read per query. Paired = same seed for
          both caches. Demo scale only; block reads are an I/O proxy, not latency.</p>
      </details>
    </div>
  );
}

function RawTable({ res, shown }) {
  const seeds = res.params.seeds;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead><tr><th>Cache</th>{seeds.map((s) => <th key={s} className="r">seed {s}</th>)}<th className="r">mean</th><th className="r">95% CI</th></tr></thead>
        <tbody>
          {shown.map((c) => (
            <tr key={c}><td><span className="dotc" style={{ background: cacheMeta(c).color, marginRight: 8 }} />{cacheMeta(c).label}</td>
              {seeds.map((s) => <td key={s} className="r num">{fmt(res.rows.find((r) => r.cache === c && r.seed === s)?.reads_per_query)}</td>)}
              <td className="r num">{fmt(res.summary[c].mean)}</td><td className="r num">{res.summary[c].n > 1 ? `±${fmt(res.summary[c].ci)}` : "–"}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
