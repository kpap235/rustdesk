// ExelixisHub - Remote Support page.
// Lists the customer PCs from the Exelixisnet IT Support panel (through the Hub
// backend, see backend/remote_support.py) with online status and one-click Connect.
// ADAPT: swap `api` for the Hub's own fetch helper and the markup for its UI kit.
import { useEffect, useMemo, useState } from "react";

const api = async (path, opts = {}) => {
  const res = await fetch(`/api/remote-support${path}`, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "include",
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
};

const ago = (ts) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
};

export default function RemoteSupport({ canConnect = true }) {
  const [devices, setDevices] = useState([]);
  const [q, setQ] = useState("");
  const [onlyOnline, setOnlyOnline] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      setDevices(await api("/devices"));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return devices
      .filter((d) => (!onlyOnline || d.online) &&
        (!s || [d.name, d.id, d.hostname, d.phone, d.notes].join(" ").toLowerCase().includes(s)))
      .sort((a, b) => (b.online - a.online) || a.name.localeCompare(b.name));
  }, [devices, q, onlyOnline]);

  const connect = async (id) => {
    try {
      const { link } = await api(`/devices/${encodeURIComponent(id)}/connect`, { method: "POST" });
      window.location.href = link; // opens the Exelixisnet IT Support app on this PC
    } catch (e) {
      alert(e.message);
    }
  };

  const save = async () => {
    try {
      await api(`/devices/${encodeURIComponent(editing.id)}`, {
        method: "PATCH",
        body: { name: editing.name, phone: editing.phone, notes: editing.notes },
      });
      setEditing(null);
      load();
    } catch (e) {
      alert(e.message);
    }
  };

  const online = devices.filter((d) => d.online).length;

  return (
    <div className="remote-support">
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Remote Support</h2>
        <input placeholder="Search name, PC, ID, phone…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label><input type="checkbox" checked={onlyOnline} onChange={(e) => setOnlyOnline(e.target.checked)} /> Online only</label>
        <span style={{ marginLeft: "auto", opacity: 0.7 }}>{online} online · {devices.length} total</span>
      </div>
      {error && <div style={{ color: "#c21f3a", marginBottom: 8 }}>{error}</div>}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr><th align="left">Customer</th><th align="left">ID</th><th align="left">PC</th><th align="left">Last seen</th><th /></tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.id} style={{ borderTop: "1px solid #e1e5ee" }}>
              <td>
                <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", marginRight: 6,
                  background: d.online ? "#1e8e3e" : "#9aa3b5" }} />
                <b>{d.name}</b>{d.phone && <div style={{ fontSize: 13, opacity: 0.7 }}>{d.phone}</div>}
              </td>
              <td style={{ fontFamily: "monospace" }}>{d.id}</td>
              <td>{d.hostname}<div style={{ fontSize: 13, opacity: 0.7 }}>{d.os}</div></td>
              <td>{d.online ? "Online" : ago(d.last_seen)}</td>
              <td align="right" style={{ whiteSpace: "nowrap" }}>
                {canConnect && <button onClick={() => connect(d.id)}>Connect</button>}{" "}
                {canConnect && <button onClick={() => setEditing({ ...d })}>Details</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {devices.length === 0 && !error && (
        <p style={{ opacity: 0.7 }}>No PCs yet. They appear when a customer installs Exelixisnet IT Support.</p>
      )}

      {editing && (
        <div role="dialog" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", display: "grid", placeItems: "center" }}>
          <div style={{ background: "var(--card, #fff)", padding: 18, borderRadius: 10, width: "min(440px, 92vw)" }}>
            <h3 style={{ marginTop: 0 }}>{editing.id}</h3>
            <label>Name / company<input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></label>
            <label>Phone<input value={editing.phone} onChange={(e) => setEditing({ ...editing, phone: e.target.value })} /></label>
            <label>Notes<textarea rows={3} value={editing.notes} onChange={(e) => setEditing({ ...editing, notes: e.target.value })} /></label>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
              <button onClick={() => setEditing(null)}>Cancel</button>
              <button onClick={save}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
