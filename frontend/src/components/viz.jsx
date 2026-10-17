// Columns, meter, gain bars, stat tiles.
import { useId } from "react";
import { cacheMeta, fmt, pct, tint } from "../lib/style.js";

/* ---------------------------------------------------------------- columns */
/** Scale for the columns. zoom=false: zero baseline. zoom=true: the smallest bar sits at ~32% and
 *  the tallest at ~88% of the track, so close values separate visibly while every bar stays tall
 *  enough to hold its label (the Benchmark view states that the scale is zoomed). */
export function columnScale(items, zoom) {
  const vlo = Math.min(...items.map((i) => i.value)), vhi = Math.max(...items.map((i) => i.value));
  if (!zoom || vhi - vlo < 1e-9) return { floor: 0, top: vhi * 1.14, zoom: false };
  const k = (vhi - vlo) / 0.56;                    // value units per 100% of track height
  return { floor: Math.max(0, vlo - 0.32 * k), top: vhi + 0.12 * k, zoom: true };
}

export function Columns({ items, scale, base, best, onPick, dim }) {
  // items: [{key, value, ci, n}] ; value = reads per query (lower is better)
  const { floor, top } = scale;
  const y = (v) => Math.max(0, Math.min(100, ((v - floor) / (top - floor)) * 100));
  return (
    <div className={`cols ${dim ? "dim" : ""}`} role="list" aria-label="Reads per query by cache">
      {items.map((it) => {
        const m = cacheMeta(it.key);
        const h = Math.max(y(it.value), 3);
        return (
          <button key={it.key} role="listitem" className={`col ${it.key === base ? "is-base" : ""}`} onClick={() => onPick?.(it.key)}
                  title={`${m.label}: ${fmt(it.value)} reads per query${it.n > 1 ? ` ±${fmt(it.ci)} (95% CI, ${it.n} seeds)` : ""}. Click to use as baseline.`}>
            <div className="col-track">
              {it.key === best && <span className="col-badge">lowest</span>}
              <div className="col-fill" style={{ height: `${h}%`, "--c": m.color }}>
                <div className="col-in">
                  <b>{fmt(it.value)}</b>
                  <span>reads / query{it.n > 1 ? ` ±${fmt(it.ci, 3)}` : ""}</span>
                </div>
              </div>
            </div>
            <div className="col-label"><span className="dotc" style={{ background: m.color }} /><span className="col-name">{m.label}</span></div>
            <div className="col-role">{it.key === base ? "baseline" : "click to compare"}</div>
          </button>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- meter */
export function Meter({ value, max, label, sub, color, ticks = [] }) {
  // Semicircle meter for a bounded share (0..max %). Track = darker step of the same hue.
  const gid = `mg${useId().replace(/:/g, "")}`;
  const R = 92, C = Math.PI * R, cx = 120, cy = 112;
  const f = Math.max(0, Math.min(value / max, 1));
  const pt = (t) => [cx - R * Math.cos(Math.PI * t), cy - R * Math.sin(Math.PI * t)];
  return (
    <div className="meter-wrap">
      <svg viewBox="0 0 240 136" role="img" aria-label={`${label}: ${value.toFixed(1)}%`}>
        <defs>
          <linearGradient id={gid} x1="0" x2="1"><stop offset="0" stopColor={tint(color, -0.25)} /><stop offset="1" stopColor={tint(color, 0.3)} /></linearGradient>
        </defs>
        <path d={`M${cx - R},${cy} A${R},${R} 0 0 1 ${cx + R},${cy}`} fill="none" stroke="#1c2740" strokeWidth="16" strokeLinecap="round" />
        <path className="meter-arc" d={`M${cx - R},${cy} A${R},${R} 0 0 1 ${cx + R},${cy}`} fill="none" stroke={color} strokeWidth="16"
              strokeLinecap="round" strokeDasharray={`${C * f} ${C}`} />
        {ticks.map((t) => {
          const tt = Math.max(0, Math.min(t.value / max, 1));
          const [x1, y1] = pt(tt), [x2, y2] = [cx - (R + 14) * Math.cos(Math.PI * tt), cy - (R + 14) * Math.sin(Math.PI * tt)];
          return <g key={t.label}><line x1={x1} y1={y1} x2={x2} y2={y2} stroke={t.color} strokeWidth="3" strokeLinecap="round" /><title>{`${t.label}: ${t.value.toFixed(1)}%`}</title></g>;
        })}
        <circle cx={pt(f)[0]} cy={pt(f)[1]} r="7" fill="#fff" stroke="#0f1523" strokeWidth="2" />
        <text x={cx - R} y={cy + 18} textAnchor="middle" fill="#94a0b8" fontSize="11">0%</text>
        <text x={cx + R} y={cy + 18} textAnchor="middle" fill="#94a0b8" fontSize="11">{max}%</text>
      </svg>
      <div className="meter-num"><b>{value.toFixed(1)}%</b><span>{sub}</span></div>
    </div>
  );
}

/* ---------------------------------------------------------------- diverging */
export function GainBars({ rows, baseLabel }) {
  // rows: [{key, value, ci, significant, worse, n}] ; value = % fewer reads than the baseline
  if (!rows.length) return <p className="hint">No comparison available.</p>;
  const lim = Math.max(...rows.map((r) => Math.abs(r.value) + (r.ci || 0)), 1) * 1.45;   // headroom so tip labels never overlap the names
  const pos = (v) => 50 + (v / lim) * 50;
  return (
    <div className="gain-bars" role="list" aria-label={`Paired % fewer reads than ${baseLabel}`}>
      <div className="gb-axis"><span>more reads than {baseLabel}</span><span>0</span><span>fewer reads</span></div>
      {rows.map((r) => {
        const m = cacheMeta(r.key);
        const l = Math.min(pos(0), pos(r.value)), w = Math.abs(pos(r.value) - pos(0));
        return (
          <div key={r.key} className="gb-row" role="listitem"
               title={`${m.label}: ${pct(r.value, 2)}${r.n > 1 ? ` ±${r.ci.toFixed(2)}` : ""} vs ${baseLabel}; worse in ${r.worse}/${r.n} seeds${r.n > 1 && !r.significant ? "; CI includes 0" : ""}`}>
            <div className="gb-name"><span className="dotc" style={{ background: m.color }} />{m.label}</div>
            <div className="gb-plot">
              <span className="gb-zero" />
              <span className={`gb-bar ${r.value < 0 ? "neg" : "pos"} ${r.n > 1 && !r.significant ? "ns" : ""}`}
                    style={{ left: `${l}%`, width: `${Math.max(w, 0.4)}%`, "--c": m.color, "--c2": tint(m.color, 0.15) }} />
              {r.n > 1 && r.ci > 0 && <span className="gb-ci" style={{ left: `${pos(r.value - r.ci)}%`, width: `${pos(r.value + r.ci) - pos(r.value - r.ci)}%` }} />}
              <span className="gb-val" style={r.value >= 0 ? { left: `calc(${pos(r.value + (r.ci || 0))}% + 8px)` } : { right: `calc(${100 - pos(r.value - (r.ci || 0))}% + 8px)` }}>
                {pct(r.value, 2)}{r.n > 1 && !r.significant ? " n.s." : ""}
              </span>
            </div>
            <div className="gb-worse">{r.worse}/{r.n} seeds worse</div>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- stat tile */
export function Sparkline({ points, color, w = 120, h = 34 }) {
  if (!points || points.length < 2) return null;
  const ys = points.map((p) => p.y), lo = Math.min(...ys, 0), hi = Math.max(...ys, 0);
  const sx = (i) => 3 + (i / (points.length - 1)) * (w - 6);
  const sy = (y) => h - 4 - ((y - lo) / (hi - lo || 1)) * (h - 8);
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(i)},${sy(p.y)}`).join("");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <line x1="0" x2={w} y1={sy(0)} y2={sy(0)} stroke="#2a3856" strokeWidth="1" />
      <path d={`${d}L${sx(points.length - 1)},${sy(0)}L${sx(0)},${sy(0)}Z`} fill={color} fillOpacity=".14" />
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {points.map((p, i) => <circle key={i} cx={sx(i)} cy={sy(p.y)} r={p.active ? 4 : 2.2} fill={p.active ? "#fff" : color} stroke={p.active ? color : "none"} strokeWidth="2" />)}
    </svg>
  );
}

export function StatTile({ label, value, sub, color, badge, spark, big }) {
  return (
    <div className={`stat ${big ? "big" : ""}`} style={{ "--c": color || "#3a4d7a" }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-foot">
        <span className="stat-sub">{sub}</span>
        {badge && <span className={`sig ${badge.kind}`}>{badge.text}</span>}
      </div>
      {spark}
    </div>
  );
}

export function sigBadge(p) {
  if (!p) return null;
  if (p.n < 2) return { kind: "na", text: "1 seed" };
  if (!p.significant) return { kind: "ns", text: "not significant" };
  return p.reduction > 0 ? { kind: "up", text: "significant" } : { kind: "down", text: "significant loss" };
}
