export function createApi(getToken, onUnauthorized) {
  async function req(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {}
    );
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(path, { ...options, headers });
    let body = null;
    const text = await res.text();
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { detail: text };
    }
    if (res.status === 401) {
      onUnauthorized && onUnauthorized();
    }
    if (!res.ok) {
      const detail = body && (body.detail || body.message);
      const err = new Error(typeof detail === "string" ? detail : res.statusText);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  return {
    get: (path) => req(path),
    post: (path, data) =>
      req(path, { method: "POST", body: JSON.stringify(data || {}) }),
    bonds: () => req("/api/bonds"),
    bond: (key) => req(`/api/bonds/${encodeURIComponent(key)}`),
    openBond: (data) => req("/api/bonds", { method: "POST", body: JSON.stringify(data) }),
    deposit: (data) =>
      req("/api/bonds/deposit", { method: "POST", body: JSON.stringify(data) }),
    cages: (status) =>
      req(status ? `/api/cages?status=${encodeURIComponent(status)}` : "/api/cages"),
    cage: (id) => req(`/api/cages/${id}`),
    freeze: (data) =>
      req("/api/cages/freeze", { method: "POST", body: JSON.stringify(data) }),
    attestations: () => req("/api/attestations"),
    attest: (data) =>
      req("/api/attestations", { method: "POST", body: JSON.stringify(data) }),
    releases: () => req("/api/releases"),
    release: (data) =>
      req("/api/releases", { method: "POST", body: JSON.stringify(data) }),
    forfeits: () => req("/api/forfeits"),
    forfeit: (data) =>
      req("/api/forfeits", { method: "POST", body: JSON.stringify(data) }),
    reconcile: () => req("/api/reconcile"),
    reconcileOne: (code) => req(`/api/reconcile/${encodeURIComponent(code)}`),
    proof: (party) => req(`/api/proof/${encodeURIComponent(party)}`),
    audit: () => req("/api/audit?limit=120"),
    contention: () => req("/api/contention"),
    locks: () => req("/api/locks"),
    dashboard: () => req("/api/dashboard"),
    topupJobs: () => req("/api/topup/jobs"),
    topupStub: (data) =>
      req("/api/topup-stub", { method: "POST", body: JSON.stringify(data) }),
    splitJobs: () => req("/api/split/jobs"),
    splitStub: (data) =>
      req("/api/split-stub", { method: "POST", body: JSON.stringify(data) }),
  };
}
