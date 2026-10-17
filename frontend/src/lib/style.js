// Fixed colour + marker per cache. Rainbow order, checked with the dataviz palette validator
// (colour-blind and normal-vision separation, contrast). "none" is a gray reference.
export const CACHE_META = {
  none: { label: "No cache", short: "NONE", color: "#8a96ad", marker: "cross", dash: "6 5" },
  block: { label: "Block cache", short: "BLK", color: "#ff3b30", marker: "triangle" },
  range: { label: "Range Cache", short: "RNG", color: "#ff9500", marker: "diamond" },
  group: { label: "Group Cache", short: "GRP", color: "#ffd60a", marker: "square" },
  "group+seed": { label: "Group + flush seeding", short: "SEED", color: "#34c759", marker: "down" },
  "group+complete": { label: "Group + completion", short: "CMPL", color: "#0a6cff", marker: "plus" },
  "zio-naive": { label: "Zero-I/O maintenance (ours)", short: "OURS", color: "#e08cff", marker: "circle" },
};
// Only for result files with extra variants (decision-rule sweep); markers keep them apart.
const EXTRA = ["#e66767", "#5fa8f0", "#c3a33c", "#3fb68b", "#b88ae8", "#e08a5a", "#8fa3c4", "#d9739c"];
const MARKERS = ["circle", "square", "triangle", "diamond", "down", "plus", "cross"];

export function cacheMeta(name) {
  if (CACHE_META[name]) return CACHE_META[name];
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return { label: name, short: name.slice(0, 4).toUpperCase(), color: EXTRA[h % EXTRA.length],
    marker: MARKERS[h % MARKERS.length], dash: name.endsWith("-tail") ? "3 3" : undefined };
}
export const CANON = Object.keys(CACHE_META);
export const canon = (cs) => [...CANON.filter((c) => cs.includes(c)), ...cs.filter((c) => !CACHE_META[c]).sort()];

/** Lighten (amt>0) or darken (amt<0) a hex colour, for gradients and glows only. */
export function tint(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [n >> 16, (n >> 8) & 255, n & 255].map((c) =>
    Math.round(amt >= 0 ? c + (255 - c) * amt : c * (1 + amt)));
  return `#${ch.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

// Where a cached KV group came from (Twin Lab inspector).
export const ORIGINS = {
  query: { label: "admitted by a query", color: "#ffd60a" },
  case1: { label: "rebuilt at compaction (Case 1)", color: "#ff9500" },
  flush_seed: { label: "seeded at flush (ours)", color: "#e08cff" },
  completed: { label: "completed at compaction (ours)", color: "#34c759" },
  block: { label: "cached block", color: "#ff3b30" },
  range: { label: "cached range", color: "#ff9500" },
};
// Storage-tree depth: one hue, newer = lighter (ordinal).
export const DEPTH = ["#4aa8ff", "#1e90ff", "#1677e0", "#1262bd", "#0f509c", "#0c417f"];

export const fmt = (v, d = 3) => (v === null || v === undefined || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d));
export const pct = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`);
export const xLabel = {
  write_ratio: "write ratio", scan_share: "scan share of reads", cache_frac: "cache size (fraction of data)",
  zipf: "Zipf skew (theta)",
};
export const xFormatter = (param) => (param === "cache_frac" ? (v) => `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%` : (v) => String(v));
