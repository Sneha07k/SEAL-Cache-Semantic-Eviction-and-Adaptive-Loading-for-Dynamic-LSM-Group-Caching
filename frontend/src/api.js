// Thin client for the FastAPI backend (proxied at /api by Vite).
async function call(path, body, signal) {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch { /* keep status text */ }
    throw new Error(detail);
  }
  return res.json();
}

const s = (sid) => `?sid=${sid || "A"}`;
const enc = (name) => name.split("/").map(encodeURIComponent).join("/");

export const api = {
  meta: () => call("/meta"),
  state: (sid) => call(`/state${s(sid)}`),
  reset: (cfg, sid) => call(`/reset${s(sid)}`, cfg),
  workload: (w, sid) => call(`/workload${s(sid)}`, w),
  ops: (ops, sid) => call(`/ops${s(sid)}`, { ops }),
  put: (key, value, sid) => call(`/put${s(sid)}`, { key, value }),
  putRange: (p, sid) => call(`/put_range${s(sid)}`, p),
  del: (key, sid) => call(`/delete${s(sid)}`, { key }),
  get: (key, sid) => call(`/get${s(sid)}`, { key }),
  scan: (lo, hi, sid) => call(`/scan${s(sid)}`, { lo, hi }),
  flush: (sid) => call(`/flush${s(sid)}`, {}),
  benchmark: (body, signal) => call("/benchmark", body, signal),
  results: () => call("/results"),
  result: (name) => call(`/results/${enc(name)}`),
};

export function friendly(e) {
  if (e?.name === "AbortError") return "Cancelled.";
  const m = String(e?.message ?? e);
  return m.includes("Failed to fetch") || m.includes("NetworkError")
    ? "Can't reach the backend. Start it with: cd backend && python run.py" : m;
}
