import { DEPTH, ORIGINS } from "../lib/style.js";



// Levels on one key axis (newest on top); cached groups drawn under their run's blocks.
const W = 1000, ROW = 44, GAP = 16, LABEL = 64, LANE = 12;



function keyDomain(levels, q) {

  let lo = Infinity, hi = -Infinity;

  for (const lvl of levels) for (const r of lvl.runs) { lo = Math.min(lo, r.min_key); hi = Math.max(hi, r.max_key); }

  if (q?.kind === "scan") { lo = Math.min(lo, q.args.lo); hi = Math.max(hi, q.args.hi); }

  if (!isFinite(lo)) return [0, 1];

  return lo === hi ? [lo - 1, hi + 1] : [lo, hi];

}



export default function Strata({ state, selected, onSelect }) {

  const { levels, last_query: q, config } = state;

  const groups = state.cache?.groups ?? [];

  const oneRow = config.policy === "leveling" && config.granularity === "file";

  const deepest = levels.reduce((d, l, i) => (l.runs.length ? i : d), 0);

  const visible = levels.slice(0, deepest + 1);

  const [kLo, kHi] = keyDomain(visible, q);

  const x = (k) => LABEL + ((Math.min(Math.max(k, kLo), kHi) - kLo) / (kHi - kLo)) * (W - LABEL - 8);

  const read = new Set(q?.blocks_read ?? []);

  const rangeLane = groups.some((g) => g.run === null);



  let y = rangeLane ? ROW + GAP : 6;

  const rowOfRun = new Map();

  const rows = visible.map((lvl) => {

    const top = y;

    const lanes = !lvl.runs.length ? [null] : lvl.level > 0 && oneRow ? [lvl.runs] : lvl.runs.map((r) => [r]);

    lanes.forEach((lane, li) => lane && lane.forEach((r) => rowOfRun.set(r.run_id, top + li * ROW)));

    y += lanes.length * ROW + GAP;

    return { lvl, top, lanes };

  });

  const height = Math.max(y, 60);

  const band = q?.kind === "scan" ? { x: x(q.args.lo), w: Math.max(x(q.args.hi) - x(q.args.lo), 2) }

    : q?.kind === "get" ? { x: x(q.args.key) - 1, w: 2 } : null;



  const gRect = (g) => {

    const ry = g.run === null ? 4 : rowOfRun.get(g.run);

    if (ry === undefined) return null;

    const gx = x(g.lb), gw = Math.max(x(g.ub) - gx, 2.5);

    return { gx, gw, gy: g.run === null ? ry : ry + ROW - LANE - 2, gh: g.run === null ? ROW - 8 : LANE };

  };

  const used = [...new Set(groups.map((g) => g.origin))];



  return (

    <figure className="strata">

      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Sorted runs per level by key range, with cached groups">

        {band && <rect className="band" x={band.x} y={0} width={band.w} height={height} />}

        {rangeLane && <text className="level-name" x={4} y={ROW / 2 + 6}>cache</text>}

        {rows.map(({ lvl, top, lanes }) => (

          <g key={lvl.level}>

            <text className="level-name" x={4} y={top + ROW / 2 + 4}>L{lvl.level}</text>

            {lanes.map((lane, li) => {

              const ry = top + li * ROW;

              if (!lane) return <text key="e" className="empty" x={LABEL} y={ry + ROW / 2 + 4}>empty</text>;

              return lane.flatMap((run) => run.blocks.map((b) => {

                const bx = x(b.min), bw = Math.max(x(b.max) - bx, 1.5);

                const cls = ["block", read.has(b.id) && "read", b.tombstones && "has-tomb"].filter(Boolean).join(" ");

                return (

                  <rect key={b.id} className={cls} x={bx + 0.6} y={ry + 3} width={Math.max(bw - 1.2, 1)} height={ROW - LANE - 8} rx="2"

                        fill={DEPTH[Math.min(lvl.level, DEPTH.length - 1)]}>

                    <title>{`Run ${run.run_id}, block ${b.id}: keys ${b.min}–${b.max}, ${b.n} entries${b.tombstones ? `, ${b.tombstones} deleted` : ""}${read.has(b.id) ? " (read from disk by the last query)" : ""}`}</title>

                  </rect>

                );

              }));

            })}

          </g>

        ))}

        {groups.map((g) => {

          const r = gRect(g);

          if (!r) return null;

          const o = ORIGINS[g.origin] ?? { color: "#8d99b0", label: g.origin };

          const cls = ["group-rect", g.hit && "hit", selected === g.id && "sel"].filter(Boolean).join(" ");

          return (

            <rect key={g.id} className={cls} x={r.gx} y={r.gy} width={r.gw} height={r.gh} rx="2" fill={o.color} fillOpacity=".78"

                  stroke={g.hit ? undefined : o.color} tabIndex={0} role="button"

                  aria-label={`Cached ${o.label}: keys ${g.lb} to ${g.ub}, ${g.n} entries${g.hit ? ", has been hit" : ", never hit"}`}

                  onClick={() => onSelect?.(selected === g.id ? null : g)}

                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(selected === g.id ? null : g); } }}>

              <title>{`${o.label}\nkeys ${g.lb}–${g.ub} · ${g.n} entries · ${g.hit ? "has served a probe" : "never hit yet"}`}</title>

            </rect>

          );

        })}

      </svg>

      <figcaption>

        <span>key {kLo}</span>

        <span>Blue = blocks (lighter = newer level) · white = read by the last query · lane = cached groups</span>

        <span>key {kHi}</span>

      </figcaption>

      {used.length > 0 && (

        <div className="origin-legend" aria-label="Group origins">

          {used.map((k) => <span key={k}><span className="swatch" style={{ background: ORIGINS[k]?.color, marginRight: 5 }} />{ORIGINS[k]?.label ?? k}</span>)}

          <span><span className="swatch" style={{ background: "transparent", border: "1.5px solid #fff", marginRight: 5 }} />white outline = has been hit</span>

        </div>

      )}

    </figure>

  );

}

