import { useMemo, useState } from "react";

const W = 780, H = 360, M = { l: 64, r: 22, t: 16, b: 50 };
const SURFACE = "#0f1523";

export function Marker({ shape, x, y, r = 5, color, hollow = false, ring = true }) {
  const fill = hollow ? SURFACE : color;
  const stroke = hollow ? color : ring ? SURFACE : color;
  const sw = hollow ? 2 : ring ? 2 : 1;
  const c = { fill, stroke, strokeWidth: sw, paintOrder: "stroke" };
  switch (shape) {
    case "square": return <rect x={x - r} y={y - r} width={2 * r} height={2 * r} rx="1.5" {...c} />;
    case "triangle": return <polygon points={`${x},${y - r - 1.5} ${x + r + 1.5},${y + r} ${x - r - 1.5},${y + r}`} {...c} />;
    case "down": return <polygon points={`${x},${y + r + 1.5} ${x + r + 1.5},${y - r} ${x - r - 1.5},${y - r}`} {...c} />;
    case "diamond": return <polygon points={`${x},${y - r - 1.5} ${x + r + 1.5},${y} ${x},${y + r + 1.5} ${x - r - 1.5},${y}`} {...c} />;
    case "plus": return <g><path d={`M${x - r - 1},${y}H${x + r + 1}M${x},${y - r - 1}V${y + r + 1}`} stroke={SURFACE} strokeWidth="5.5" /><path d={`M${x - r},${y}H${x + r}M${x},${y - r}V${y + r}`} stroke={color} strokeWidth="2.6" /></g>;
    case "cross": return <g><path d={`M${x - r},${y - r}L${x + r},${y + r}M${x - r},${y + r}L${x + r},${y - r}`} stroke={SURFACE} strokeWidth="5.5" /><path d={`M${x - r},${y - r}L${x + r},${y + r}M${x - r},${y + r}L${x + r},${y - r}`} stroke={color} strokeWidth="2.4" /></g>;
    default: return <circle cx={x} cy={y} r={r} {...c} />;
  }
}

function niceTicks(lo, hi, n = 5) {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

// Line chart: CI bands, emphasis, crosshair tooltip, arrow-key navigation.
export default function LineChart({ series, xs, xLabel, yLabel, yFmt = (v) => v.toFixed(3),
  xFmt = (v) => String(v), zeroLine = false, includeZero = false, logX = false, ariaLabel,
  focus = null, activeX = null, onPickX }) {
  const [hover, setHover] = useState(null);
  const pts = series.flatMap((s) => s.points);
  const view = useMemo(() => {
    const ys = pts.flatMap((p) => [p.y - (p.ci || 0), p.y + (p.ci || 0)]);
    const z = zeroLine || includeZero ? [0] : [];
    let lo = Math.min(...ys, ...z), hi = Math.max(...ys, ...z);
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = (hi - lo || 1) * 0.08;
    const tf = logX ? Math.log10 : (v) => v;
    const xLo = tf(Math.min(...xs)), xHi = tf(Math.max(...xs)), span = xHi - xLo || 1;
    return { yLo: lo - pad, yHi: hi + pad, xLo: xLo - span * 0.05 - (xs.length > 1 ? 0 : 0.5), xHi: xHi + span * 0.05 + (xs.length > 1 ? 0 : 0.5), tf };
  }, [series, xs, zeroLine, includeZero, logX]); // eslint-disable-line react-hooks/exhaustive-deps
  const sx = (x) => M.l + ((view.tf(x) - view.xLo) / (view.xHi - view.xLo)) * (W - M.l - M.r);
  const sy = (y) => H - M.b - ((y - view.yLo) / (view.yHi - view.yLo)) * (H - M.t - M.b);
  const yTicks = niceTicks(view.yLo, view.yHi, 5);
  const isOn = (k) => !focus || focus.has(k);
  const ordered = [...series].sort((a, b) => Number(isOn(a.key)) - Number(isOn(b.key)));   // focused on top

  const move = (e) => {
    const r = e.currentTarget.ownerSVGElement.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    xs.forEach((x, i) => { if (Math.abs(sx(x) - px) < Math.abs(sx(xs[best]) - px)) best = i; });
    setHover(best);
  };
  const key = (e) => {
    if (e.key === "ArrowRight") { setHover((h) => Math.min((h ?? -1) + 1, xs.length - 1)); e.preventDefault(); }
    if (e.key === "ArrowLeft") { setHover((h) => Math.max((h ?? xs.length) - 1, 0)); e.preventDefault(); }
    if (e.key === "Enter" && hover !== null) onPickX?.(xs[hover]);
    if (e.key === "Escape") setHover(null);
  };
  const hx = hover === null ? null : xs[hover];
  const rows = hx === null ? [] : series.map((s) => ({ s, p: s.points.find((p) => p.x === hx) })).filter((r) => r.p)
    .sort((a, b) => b.p.y - a.p.y);
  const leftPct = hx === null ? 0 : (sx(hx) / W) * 100;

  if (!pts.length) return <p className="hint">Nothing to plot for this selection.</p>;
  return (
    <div className="chart-wrap" tabIndex={0} onKeyDown={key} onBlur={() => setHover(null)}
         role="group" aria-label={`${ariaLabel || "Chart"}. Left/right arrows read values; Enter selects that ${xLabel}.`}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        <defs>
          <linearGradient id="plotbg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#141d33" /><stop offset="1" stopColor="#0f1523" /></linearGradient>
        </defs>
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="url(#plotbg)" rx="8" />
        {activeX !== null && xs.includes(activeX) && (
          <rect x={sx(activeX) - 16} y={M.t} width="32" height={H - M.t - M.b} fill="#e6eaf2" opacity=".06" rx="6" />
        )}
        <g className="axis">
          {yTicks.map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} />
              <text x={M.l - 10} y={sy(t) + 4} textAnchor="end">{yFmt(t)}</text>
            </g>
          ))}
          {xs.map((x) => (
            <text key={x} x={sx(x)} y={H - M.b + 20} textAnchor="middle" className={x === activeX ? "x-active" : ""}>{xFmt(x)}</text>
          ))}
          <text x={(M.l + W - M.r) / 2} y={H - 8} textAnchor="middle">{xLabel}</text>
          <text transform={`translate(16 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle">{yLabel}</text>
        </g>
        {zeroLine && <line x1={M.l} x2={W - M.r} y1={sy(0)} y2={sy(0)} stroke="#8d99b0" strokeWidth="1.2" />}
        {ordered.map((s) => {
          const on = isOn(s.key);
          const col = on ? s.color : "#3b465f";
          const band = s.points.length > 1 && s.points.some((p) => p.ci > 0)
            ? `M${s.points.map((p) => `${sx(p.x)},${sy(p.y + (p.ci || 0))}`).join("L")}L${[...s.points].reverse().map((p) => `${sx(p.x)},${sy(p.y - (p.ci || 0))}`).join("L")}Z` : null;
          return (
            <g key={s.key} className="series" style={{ opacity: on ? 1 : 0.55 }}>
              {band && on && <path d={band} fill={s.color} fillOpacity=".12" />}
              <polyline className={s.dash ? "" : "draw"} pathLength="1" fill="none" stroke={col} strokeWidth={on ? 2.4 : 1.6}
                        strokeDasharray={s.dash ? s.dash.split(" ").map((v) => v / 400).join(" ") : undefined}
                        strokeLinejoin="round" strokeLinecap="round" points={s.points.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")} />
              {s.points.map((p) => (
                <g key={p.x}>
                  {p.ci > 0 && s.points.length === 1 && (
                    <path d={`M${sx(p.x)},${sy(p.y - p.ci)}V${sy(p.y + p.ci)}`} stroke={col} strokeWidth="1.4" />
                  )}
                  <Marker shape={s.marker} x={sx(p.x)} y={sy(p.y)} color={col} hollow={p.hollow} r={on ? 5.5 : 4} />
                </g>
              ))}
            </g>
          );
        })}
        {hx !== null && <line x1={sx(hx)} x2={sx(hx)} y1={M.t} y2={H - M.b} stroke="#e6eaf2" strokeOpacity=".5" />}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="transparent" style={{ cursor: onPickX ? "pointer" : "crosshair" }}
              onPointerMove={move} onPointerLeave={() => setHover(null)} onClick={() => hx !== null && onPickX?.(hx)} />
      </svg>
      {hx !== null && (
        <div className="tooltip" role="status" style={{ left: `${leftPct}%`, top: 10, transform: leftPct > 58 ? "translateX(calc(-100% - 14px))" : "translateX(14px)" }}>
          <div className="tt-head">{xLabel}: <b>{xFmt(hx)}</b>{onPickX && <span className="faint"> · click to select</span>}</div>
          {rows.map(({ s, p }) => (
            <div className={`t-row ${isOn(s.key) ? "" : "faint"}`} key={s.key}>
              <span><span className="swatch" style={{ background: s.color, marginRight: 7 }} />{s.label}</span>
              <span className="num">{yFmt(p.y)}{p.ci ? ` ±${yFmt(p.ci)}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
