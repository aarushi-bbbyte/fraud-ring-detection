// All requests go through /api, which Vite (dev) or nginx (container) proxies to the backend.
const BASE = "/api";

async function request(path, options) {
  const res = await fetch(BASE + path, options);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export const api = {
  alerts: (params) => request(`/alerts?${new URLSearchParams(params)}`),
  ring: (id) => request(`/rings/${encodeURIComponent(id)}`),
  account: (id) => request(`/accounts/${encodeURIComponent(id)}`),
  metrics: () => request("/metrics"),
  simulate: (pattern) =>
    request("/simulate/ring", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pattern }),
    }),
  clearSimulated: () => request("/simulate", { method: "DELETE" }),
  streamUrl: (start, rate) => `${BASE}/stream/transactions?${new URLSearchParams({ start, rate })}`,
  resultImage: (name) => `${BASE}/results/${name}`,
};

/**
 * Sum of total_usd over all alerts, for the "money flagged" counter.
 * The API has no aggregate for this, so it pages through /alerts once and
 * caches the result for the browser session.
 */
export async function flaggedVolume(totalAlerts) {
  const key = `flagged-usd:${totalAlerts}`;
  try {
    const cached = sessionStorage.getItem(key);
    if (cached) return Number(cached);
  } catch {
    /* storage unavailable: just recompute */
  }
  let sum = 0;
  for (let offset = 0; offset < totalAlerts; offset += 500) {
    const page = await api.alerts({ limit: 500, offset });
    sum += page.items.reduce((s, a) => s + (a.total_usd ?? 0), 0);
  }
  try {
    sessionStorage.setItem(key, String(sum));
  } catch {
    /* ignore */
  }
  return sum;
}
