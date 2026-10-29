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

export const usd = (v) =>
  v == null ? "–" : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const time = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "–");

export const RULE_LABEL = { cycle: "Cycle", fan_in: "Fan-in", fan_out: "Fan-out" };
