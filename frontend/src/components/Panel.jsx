import { useState } from "react";
import { cacheMeta, ORIGINS } from "../lib/style.js";
import Strata from "./Strata.jsx";

export const reads = (st) => (st?.io?.point_read || 0) + (st?.io?.scan_read || 0);

function Reaction({ cache }) {
  const chips = [];
  if (cache.flush_seeded) chips.push(<span key="s" className="react" title="KV groups built in the new L0 run from the flushed data (no disk read)">seeded {cache.flush_seeded} group{cache.flush_seeded > 1 ? "s" : ""} ({cache.kv_copied_flush_seed ?? 0} KVs copied)</span>);
  if (cache.case2_completed) chips.push(<span key="c" className="react" title="Incomplete groups completed from the merged stream (no disk read)">completed {cache.case2_completed} range{cache.case2_completed > 1 ? "s" : ""}</span>);
  if (cache.case1_kept) chips.push(<span key="k" className="react" style={{ background: "#241f3d", color: "#c9b8ff" }} title="Every key in the range was cached, so the group was rebuilt (Group Cache Case 1)">rebuilt {cache.case1_kept} (Case 1)</span>);
  if (cache.case2_discarded) chips.push(<span key="d" className="react bad" title="The merged output had keys the group did not hold, so Group Cache throws the group away (Case 2)">discarded {cache.case2_discarded} range{cache.case2_discarded > 1 ? "s" : ""} (Case 2)</span>);
  return chips.length ? <>{chips}</> : <span className="faint">no cache effect</span>;
}

function EventList({ events }) {
  const [filter, setFilter] = useState("all");
  const list = events.recent.filter((e) => filter === "all" || e.kind === filter).slice().reverse();
  return (
    <div>
      <div className="panel-head" style={{ marginBottom: 4 }}>
        <div className="section-title" style={{ margin: 0 }}>Flush &amp; compaction log ({events.total} total)</div>
        <div className="chips" role="group" aria-label="Filter events">
          {["all", "flush", "compaction"].map((f) => <button key={f} className="pill" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f}</button>)}
        </div>
      </div>
      <div className="events" role="log" aria-live="polite">
        {!list.length && <p className="hint">Nothing yet. Write enough data to flush the MemTable.</p>}
        {list.map((e) => (
          <div className="event" key={e.n}>
            <span className="faint num">#{e.n}</span>
            <span className={`tag ${e.kind}`}>{e.kind === "flush" ? "flush" : `L${e.from_levels.join("+")}→L${e.to_level ?? "·"}`}</span>
            <span>
              <span className="muted">{e.kind === "flush" ? `${e.entries} entries → new L0 run ${e.run}` : `${e.inputs.length} runs → ${e.outputs.length}, ${e.merged} entries`}</span>{" "}
              <Reaction cache={e.cache} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Panel({ sid, state, other, label }) {
  const [sel, setSel] = useState(null);
  const [showGroups, setShowGroups] = useState(true);
  if (!state) return <div className="card"><p className="hint">Loading…</p></div>;
  const c = state.cache;
  const m = cacheMeta(state.config.cache);
  const r = reads(state), ro = other ? reads(other) : null;
  const diff = ro === null || ro === 0 ? null : ((r - ro) / ro) * 100;
  const byOrigin = {};
  (c?.groups ?? []).forEach((g) => { byOrigin[g.origin] = (byOrigin[g.origin] || 0) + 1; });
  const mt = c?.maintenance;
  const never = mt ? mt.resident_unused_flush_seed + mt.resident_unused_completed + (mt.retired_unused_flush_seed || 0) + (mt.retired_unused_completed || 0) + (mt.evicted_unused_flush_seed || 0) + (mt.evicted_unused_completed || 0) : 0;
  const created = mt ? mt.groups_created_flush_seed + mt.groups_created_completed : 0;
  const lq = state.last_query;
  const selGroup = sel && c?.groups.find((g) => g.id === sel);

  return (
    <section className="card engine" aria-label={`Engine ${sid}`} style={{ "--c": m.color }}>
      <div className="panel-head">
        <h2><span className="sid-badge">{sid}</span>{m.label}</h2>
        <span className="hint num">{state.stats.ops_applied.toLocaleString()} ops · {state.stats.flushes} flushes · {state.stats.compactions} compactions</span>
      </div>

      <div className="kpis">
        <div className="kpi" title="Disk blocks read by gets and scans since the last reset">
          <div className="k">Query disk reads</div><div className="v">{r.toLocaleString()}</div>
          <div className="d" style={{ color: diff === null ? "var(--faint)" : diff < 0 ? "var(--green)" : diff > 0 ? "var(--red)" : "var(--muted)" }}>
            {diff === null ? "—" : `${diff > 0 ? "+" : ""}${diff.toFixed(1)}% vs ${label}`}</div>
        </div>
        <div className="kpi" title="Blocks the most recent get/scan had to read from disk">
          <div className="k">Last query</div>
          <div className="v">{lq ? lq.blocks_read.length : "–"}</div>
          <div className="d muted">{lq ? `${lq.kind === "scan" ? `scan ${lq.args.lo}–${lq.args.hi}` : `get ${lq.args.key}`} · ${lq.kind === "scan" ? lq.result.length + " keys" : lq.result === null ? "not found" : "found"}` : "run a query"}</div>
        </div>
        <div className="kpi" title="Memory used by the cache, including metadata, out of its byte budget">
          <div className="k">Cache memory</div>
          <div className="v">{c ? `${Math.round((c.bytes / c.capacity) * 100)}%` : "–"}</div>
          <div className="d muted">{c ? `${(c.bytes / 1024).toFixed(1)} / ${(c.capacity / 1024).toFixed(0)} KB` : "no cache"}</div>
        </div>
        <div className="kpi"><div className="k">Cached items</div><div className="v">{c ? c.groups.length : "–"}</div>
          <div className="d muted">{c?.groups.length ? Object.entries(byOrigin).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ") : " "}</div></div>
      </div>

      {lq && (
        <p className="hint" style={{ marginBottom: 6 }}>
          Last query cache activity:{" "}
          {Object.keys(lq.cache_delta).length ? Object.entries(lq.cache_delta).map(([k, v]) => `${k.replace("_", " ")} ${v > 0 ? "+" : ""}${v}`).join(", ") : "none (no cache, or nothing to report)"}
        </p>
      )}

      {c && (
        <div className="meter" title="Cache bytes by origin" aria-label="Cache bytes by origin">
          {Object.entries(byOrigin).map(([k, v]) => <span key={k} style={{ width: `${(v / Math.max(c.groups.length, 1)) * (c.bytes / c.capacity) * 100}%`, background: ORIGINS[k]?.color }} />)}
        </div>
      )}

      <div className="row" style={{ margin: "10px 0 0", justifyContent: "space-between" }}>
        <span className="section-title" style={{ margin: 0 }}>Storage tree</span>
        <label className="check" style={{ padding: 0 }}><input type="checkbox" checked={showGroups} onChange={(e) => setShowGroups(e.target.checked)} />show cached groups</label>
      </div>
      <Strata state={showGroups ? state : { ...state, cache: null }} selected={sel} onSelect={(g) => setSel(g ? g.id : null)} />
      {selGroup && (
        <div className="note" style={{ marginTop: 8 }}>
          <b>{ORIGINS[selGroup.origin]?.label ?? selGroup.origin}</b>: keys {selGroup.lb}–{selGroup.ub}, {selGroup.n} entries in run {selGroup.run ?? "(range cache)"} ·{" "}
          {selGroup.hit ? "has served at least one probe" : "never hit so far"}.
          {selGroup.origin === "case1" && " (It was rebuilt at compaction; its first origin is not kept.)"}
        </div>
      )}

      {!(mt && created > 0) && c && (
        <div className="note" style={{ marginTop: 10, opacity: 0.75 }} aria-label="Maintenance accounting">
          <b>Maintenance accounting</b>: none. {state.config.cache === "zio-naive" || state.config.cache.startsWith("group+") ? "No maintained groups created yet." : `${m.label} does no flush- or compaction-time maintenance.`}
        </div>
      )}
      {mt && created > 0 && (
        <div className="note" style={{ marginTop: 10 }} aria-label="Maintenance accounting">
          <b>Maintenance accounting (our mechanism)</b>: {created} groups created, {mt.kv_copied_flush_seed + mt.kv_copied_completed} KVs copied
          in memory (zero extra disk reads); {created - never} ever hit, {never} never hit before being rebuilt, evicted or still resident unused.
        </div>
      )}
      <div style={{ marginTop: 12 }}><EventList events={state.events} /></div>
    </section>
  );
}
