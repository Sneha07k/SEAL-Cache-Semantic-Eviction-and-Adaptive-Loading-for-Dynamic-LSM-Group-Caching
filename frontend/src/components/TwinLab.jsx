import { useCallback, useEffect, useState } from "react";
import { api, friendly } from "../api.js";
import { CANON, cacheMeta, tint } from "../lib/style.js";
import Panel, { reads } from "./Panel.jsx";

const CACHES = CANON.filter((c) => c !== "none").concat("none");
const TREES = {
  small: { label: "Small tree (readable)", cfg: { block_size: 8, memtable_size: 64, size_ratio: 4, l0_run_limit: 3, l1_capacity: 256, policy: "leveling", granularity: "file" } },
  tiny: { label: "Tiny MemTable (more flushes)", cfg: { block_size: 8, memtable_size: 32, size_ratio: 4, l0_run_limit: 2, l1_capacity: 128, policy: "leveling", granularity: "file" } },
  tiering: { label: "Tiering", cfg: { block_size: 8, memtable_size: 64, size_ratio: 4, l0_run_limit: 3, l1_capacity: 256, policy: "tiering", granularity: "file" } },
  levelwise: { label: "Whole-level merges", cfg: { block_size: 8, memtable_size: 64, size_ratio: 4, l0_run_limit: 3, l1_capacity: 256, policy: "leveling", granularity: "level" } },
};

// Deterministic "hot" scans so both engines receive the identical operations.
function hotOps(lo, hi, n, width = 3, seed = 7) {
  let x = seed; const out = [];
  for (let i = 0; i < n; i++) {
    x = (Math.imul(x, 1103515245) + 12345) & 0x7fffffff;
    const a = lo + ((x >> 8) % Math.max(hi - lo - width + 2, 1));
    out.push(["scan", a, a + width - 1]);
  }
  return out;
}
const delta = (a, b, k) => (b?.cache?.stats?.[k] || 0) - (a?.cache?.stats?.[k] || 0);
const L = (c) => cacheMeta(c).label;

function Num({ label, value, set, min = 0, max, step = 1 }) {
  return (
    <label className="field"><span>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(e) => set(e.target.value === "" ? "" : Number(e.target.value))} /></label>
  );
}

function Race({ A, B }) {
  if (!A || !B) return null;
  const rows = [
    ["Query disk reads (since reset)", reads(A), reads(B)],
    ["Last query: blocks read", A.last_query?.blocks_read.length ?? null, B.last_query?.blocks_read.length ?? null],
    ["Cached items", A.cache?.groups.length ?? 0, B.cache?.groups.length ?? 0, true],
  ];
  const ca = cacheMeta(A.config.cache), cb = cacheMeta(B.config.cache);
  return (
    <section className="card race" aria-label="Engine A versus engine B">
      {rows.map(([label, a, b, neutral]) => {
        const mx = Math.max(a ?? 0, b ?? 0, 1);
        const d = a && b !== null ? ((b - a) / a) * 100 : null;
        return (
          <div className="race-row" key={label}>
            <div className="race-label">{label}</div>
            <div className="race-bars">
              {[["A", a, ca], ["B", b, cb]].map(([sid, v, m]) => (
                <div className="race-bar" key={sid}>
                  <span className="race-sid">{sid}</span>
                  <div className="race-track"><div className="race-fill" style={{ width: `${v === null ? 0 : Math.max((v / mx) * 100, v ? 2 : 0)}%`, "--c": m.color, "--c2": tint(m.color, 0.15) }} /></div>
                  <span className="race-v num">{v === null ? "–" : v.toLocaleString()}</span>
                </div>
              ))}
            </div>
            <div className={`race-d ${d === null || neutral ? "" : d < 0 ? "good" : d > 0 ? "bad" : ""}`}>{d === null || !isFinite(d) ? "" : `B ${d > 0 ? "+" : ""}${d.toFixed(0)}%`}</div>
          </div>
        );
      })}
    </section>
  );
}

export default function TwinLab() {
  const [st, setSt] = useState({ A: null, B: null });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [deck, setDeck] = useState("scenarios");
  const [cacheA, setCacheA] = useState("group");
  const [cacheB, setCacheB] = useState("zio-naive");
  const [kb, setKb] = useState(32);
  const [tree, setTree] = useState("small");
  const [lo, setLo] = useState(300), [hi, setHi] = useState(360);
  const [hotN, setHotN] = useState(300);
  const [key, setKey] = useState(300);
  const [burst, setBurst] = useState({ lo: 301, hi: 359, step: 2 });
  const [mix, setMix] = useState({ n: 2000, write_ratio: 0.5, scan_ratio: 0.2, zipf_theta: 0.8, seed: 11 });
  const [stacked, setStacked] = useState(false);
  const [scn, setScn] = useState({ id: "cold", step: 0, results: [] });

  const refresh = useCallback(async () => {
    try { const [A, B] = await Promise.all([api.state("A"), api.state("B")]); setSt({ A, B }); setCacheA(A.config.cache); setCacheB(B.config.cache); setKb(A.config.cache_kb); }
    catch (e) { setErr(friendly(e)); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const both = useCallback(async (fn) => {
    setBusy(true); setErr(null);
    try { const [A, B] = await Promise.all([fn("A"), fn("B")]); setSt({ A, B }); return { A, B }; }
    catch (e) { setErr(friendly(e)); return null; }
    finally { setBusy(false); }
  }, []);
  const cfgFor = (cache) => ({ ...TREES[tree].cfg, cache, cache_kb: kb });
  const reset = () => both((sid) => api.reset(cfgFor(sid === "A" ? cacheA : cacheB), sid));
  const preload = () => both(async (sid) => { await api.reset(cfgFor(sid === "A" ? cacheA : cacheB), sid); await api.putRange({ lo: 0, hi: 1198, step: 2, tag: "v" }, sid); return api.flush(sid); });

  const SCENARIOS = {
    cold: {
      title: "Fresh data is cold", icon: "1",
      blurb: "Group Cache only caches data after a query touches it. What happens to a hot range when new keys are written into it?",
      steps: [
        ["Load 600 keys", async () => preload(), (b, a) => `Identical data in both engines (${a.A.stats.flushes} flushes).`],
        [`Make 300–360 hot (${hotN} short scans)`, async () => both((sid) => api.ops(hotOps(300, 360, hotN), sid)),
          (b, a) => `Disk reads this step: A ${reads(a.A) - reads(b.A)}, B ${reads(a.B) - reads(b.B)}. Cached items: A ${a.A.cache?.groups.length ?? 0}, B ${a.B.cache?.groups.length ?? 0}.`],
        ["Insert 30 new keys into the hot range + flush", async () => both(async (sid) => { await api.putRange({ lo: 301, hi: 359, step: 2, tag: "new" }, sid); return api.flush(sid); }),
          (b, a) => `Groups seeded at flush: A ${delta(b.A, a.A, "flush_seeded")}, B ${delta(b.B, a.B, "flush_seeded")}. Look for coloured groups over the new L0 run.`],
        ["Scan 300–360 again", async () => both((sid) => api.scan(300, 360, sid)),
          (b, a) => `Blocks read from disk: A ${a.A.last_query.blocks_read.length}, B ${a.B.last_query.blocks_read.length}.`],
      ],
    },
    case2: {
      title: "Compaction and Case 2", icon: "2",
      blurb: "When compaction merges a cached run with new keys the group did not hold, Group Cache discards the group (Case 2).",
      steps: [
        ["Load 600 keys", async () => preload(), (b, a) => `Identical data in both engines (${a.A.stats.flushes} flushes).`],
        [`Make 300–360 hot (${hotN} short scans)`, async () => both((sid) => api.ops(hotOps(300, 360, hotN), sid)),
          (b, a) => `Cached items: A ${a.A.cache?.groups.length ?? 0}, B ${a.B.cache?.groups.length ?? 0}.`],
        ["Insert 500 new keys everywhere + flush", async () => both(async (sid) => { await api.putRange({ lo: 101, hi: 1099, step: 2, tag: "ins" }, sid); return api.flush(sid); }),
          (b, a) => `${a.A.stats.compactions - b.A.stats.compactions} compactions. Case-2 discards: A ${delta(b.A, a.A, "case2_discarded")}, B ${delta(b.B, a.B, "case2_discarded")} · completed: A ${delta(b.A, a.A, "case2_completed")}, B ${delta(b.B, a.B, "case2_completed")} · rebuilt (Case 1): A ${delta(b.A, a.A, "case1_kept")}, B ${delta(b.B, a.B, "case1_kept")}.`],
        ["Scan 300–360 again", async () => both((sid) => api.scan(300, 360, sid)),
          (b, a) => `Blocks read from disk: A ${a.A.last_query.blocks_read.length}, B ${a.B.last_query.blocks_read.length}.`],
      ],
    },
    churn: {
      title: "Write-heavy churn", icon: "3",
      blurb: "A write-heavy Zipf workload through both engines. One small run: exploratory only.",
      steps: [
        ["Load 600 keys", async () => preload(), () => "Identical data in both engines."],
        ["3000 ops: 80% writes (half inserts), skewed reads", async () => both((sid) => api.workload({ n: 3000, key_space: 600, seed: 11, write_ratio: 0.8, delete_ratio: 0, scan_ratio: 0.1, zipf_theta: 0.8, perm_seed: 3 }, sid)),
          (b, a) => `Query disk reads: A ${reads(a.A)}, B ${reads(a.B)} (${reads(a.A) ? (((reads(a.B) - reads(a.A)) / reads(a.A)) * 100).toFixed(1) : "–"}% for B). Groups seeded so far: B ${a.B.cache?.maintenance?.groups_created_flush_seed ?? 0}.`],
      ],
    },
  };
  const sc = SCENARIOS[scn.id];
  const runStep = async () => {
    if (scn.step >= sc.steps.length) return;
    const before = st;
    const out = await sc.steps[scn.step][1]();
    if (!out) return;
    const text = sc.steps[scn.step][2](before.A ? before : out, out);
    setScn((s) => ({ ...s, step: s.step + 1, results: [...s.results, text] }));
  };

  return (
    <div className="stack">
      {err && <p className="error" role="alert">{err}</p>}
      <section className="card deck">
        <div className="card-head">
          <div><h2>Engine lab</h2>
            <p className="sub">A: {L(st.A?.config.cache ?? cacheA)} · B: {L(st.B?.config.cache ?? cacheB)} · same operations on both</p></div>
          <div className="toolbar">
            <div className="seg" role="tablist" aria-label="Control deck">
              {[["scenarios", "Scenarios"], ["ops", "Operations"], ["setup", "Setup"]].map(([k, l]) => (
                <button key={k} role="tab" aria-selected={deck === k} aria-pressed={deck === k} onClick={() => setDeck(k)}>{l}</button>))}
            </div>
            <div className="seg" role="group" aria-label="Panel layout">
              <button aria-pressed={!stacked} onClick={() => setStacked(false)}>Side by side</button>
              <button aria-pressed={stacked} onClick={() => setStacked(true)}>Stacked</button>
            </div>
          </div>
        </div>

        {deck === "scenarios" && (
          <div className="deck-scn">
            <div className="scn-cards">
              {Object.entries(SCENARIOS).map(([id, s]) => (
                <button key={id} className={`scn-card ${scn.id === id ? "on" : ""}`} onClick={() => setScn({ id, step: 0, results: [] })}>
                  <span className="scn-ico">{s.icon}</span><b>{s.title}</b><span>{s.blurb}</span>
                </button>
              ))}
            </div>
            <div className="stepper" style={{ gridTemplateColumns: `repeat(${sc.steps.length}, minmax(0, 1fr))` }}>
              {sc.steps.map(([title], i) => (
                <div key={i} className={`stp ${i < scn.step ? "done" : i === scn.step ? "now" : ""}`}>
                  <div className="stp-n">{i < scn.step ? "✓" : i + 1}</div>
                  <div className="stp-t">{title}</div>
                  {scn.results[i] && <div className="stp-r">{scn.results[i]}</div>}
                </div>
              ))}
              <div className="stp-actions">
                <button className="btn primary" disabled={busy || scn.step >= sc.steps.length} onClick={runStep}>{scn.step >= sc.steps.length ? "Finished" : busy ? "Running…" : `Run step ${scn.step + 1}`}</button>
                <button className="btn" disabled={busy} onClick={() => setScn({ ...scn, step: 0, results: [] })}>Restart</button>
                {scn.step === 0 && <span className="faint" style={{ fontSize: 12 }}>Step 1 resets both engines using Setup.</span>}
              </div>
            </div>
          </div>
        )}

        {deck === "ops" && (
          <div className="deck-ops">
            <div className="opgroup"><h3>Query</h3>
              <div className="row"><Num label="From" value={lo} set={setLo} /><Num label="To" value={hi} set={setHi} /></div>
              <div className="row"><button className="btn" disabled={busy} onClick={() => both((sid) => api.scan(lo, hi, sid))}>Scan range</button>
                <Num label="× short scans" value={hotN} set={setHotN} min={1} max={5000} />
                <button className="btn" disabled={busy} onClick={() => both((sid) => api.ops(hotOps(lo, hi, hotN, 3, 7), sid))} title="Many short scans inside the range: makes it hot">Make hot</button></div>
            </div>
            <div className="opgroup"><h3>Single key</h3>
              <Num label="Key" value={key} set={setKey} />
              <div className="row"><button className="btn" disabled={busy} onClick={() => both((sid) => api.get(key, sid))}>Look up</button>
                <button className="btn" disabled={busy} onClick={() => both((sid) => api.put(key, "x", sid))}>Write</button>
                <button className="btn" disabled={busy} onClick={() => both((sid) => api.del(key, sid))}>Delete</button></div>
            </div>
            <div className="opgroup"><h3>Insert burst</h3>
              <div className="row"><Num label="From" value={burst.lo} set={(v) => setBurst({ ...burst, lo: v })} /><Num label="To" value={burst.hi} set={(v) => setBurst({ ...burst, hi: v })} /><Num label="Step" value={burst.step} set={(v) => setBurst({ ...burst, step: v })} min={1} /></div>
              <div className="row"><button className="btn" disabled={busy} onClick={() => both((sid) => api.putRange({ ...burst, tag: "b" }, sid))}>Write burst</button>
                <button className="btn" disabled={busy} onClick={() => both((sid) => api.flush(sid))}>Flush MemTable</button></div>
            </div>
            <div className="opgroup"><h3>Random traffic</h3>
              <div className="row"><Num label="Ops" value={mix.n} set={(v) => setMix({ ...mix, n: v })} min={1} max={50000} /><Num label="Writes" value={mix.write_ratio} set={(v) => setMix({ ...mix, write_ratio: v })} step={0.1} max={1} />
                <Num label="Scans" value={mix.scan_ratio} set={(v) => setMix({ ...mix, scan_ratio: v })} step={0.1} max={1} /><Num label="Zipf" value={mix.zipf_theta} set={(v) => setMix({ ...mix, zipf_theta: v })} step={0.1} max={1.5} /></div>
              <button className="btn" disabled={busy} onClick={() => both((sid) => api.workload({ ...mix, key_space: 600, delete_ratio: 0, perm_seed: mix.seed }, sid))}>Run traffic</button>
            </div>
          </div>
        )}

        {deck === "setup" && (
          <div className="deck-setup">
            <label className="field"><span>Engine A cache</span><select value={cacheA} onChange={(e) => setCacheA(e.target.value)}>{CACHES.map((c) => <option key={c} value={c}>{L(c)}</option>)}</select></label>
            <label className="field"><span>Engine B cache</span><select value={cacheB} onChange={(e) => setCacheB(e.target.value)}>{CACHES.map((c) => <option key={c} value={c}>{L(c)}</option>)}</select></label>
            <label className="field"><span className="field-head"><span>Cache budget (both)</span><span className="val">{kb} KB</span></span>
              <input type="range" min={8} max={128} step={4} value={kb} onChange={(e) => setKb(Number(e.target.value))} /></label>
            <label className="field"><span>Tree shape</span><select value={tree} onChange={(e) => setTree(e.target.value)}>{Object.entries(TREES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
            <div className="row"><button className="btn primary" disabled={busy} onClick={reset}>Apply &amp; reset</button>
              <button className="btn" disabled={busy} onClick={preload} title="Reset and load 600 even keys (0, 2, … 1198)">Reset + load data</button></div>
          </div>
        )}
      </section>

      <Race A={st.A} B={st.B} />

      <div className={`twin ${stacked ? "stacked" : ""}`}>
        <Panel sid="A" state={st.A} other={st.B} label="B" />
        <Panel sid="B" state={st.B} other={st.A} label="A" />
      </div>
      <details className="help">
        <summary>Legend</summary>
        <p>Blue bars: blocks (lighter = newer level). White: read by the last query. Lane under the blocks: cached groups.
          Log tags: seeded/completed = our maintenance; rebuilt (Case 1)/discarded (Case 2) = Group Cache. Small demo, not a benchmark.</p>
      </details>
    </div>
  );
}
