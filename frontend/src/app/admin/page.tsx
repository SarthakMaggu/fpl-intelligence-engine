"use client";
import React, { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/* ─── Types ────────────────────────────────────────────────────────── */
interface RunEntry { ts: string; status: string; duration_s: number; error: string | null; }
interface Job {
  id: string; name: string;
  next_run: string | null; next_run_mins: number | null;
  last_run: string | null; last_status: string | null;
  last_error: string | null; last_duration_s: number | null;
  run_history: RunEntry[];
}
interface ChainStep {
  id: string; name: string; offset_min: number;
  status: string; last_run: string | null; last_error: string | null; next_run: string | null;
  run_history: RunEntry[];
}
interface HealthSvc { status: string; error?: string; last_heartbeat_s_ago?: number | null; last_gw?: number | null; running?: boolean; last_finished_gw?: number | null; }
interface MaeRow { gw: number; season: string; mae: number | null; hit_rate: number | null; }
interface CalRow { position: string; price_band: string; mean_residual: number; sample_size: number; }
interface OracleRow { gw: number; oracle_pts: number | null; top_pts: number | null; beat_top: boolean | null; }
interface FiRow { feature: string; importance: number; }

/* ─── Helpers ──────────────────────────────────────────────────────── */
const TOKEN_KEY = "fpl_admin_token";
const stored  = () => typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
const saveToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function apiFetch(path: string, token: string, opts: RequestInit = {}) {
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(opts.headers || {}) },
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/* ─── Status dot ───────────────────────────────────────────────────── */
function Dot({ status }: { status: string }) {
  const col = status === "up" || status === "success" ? "#22C55E"
    : status === "failed" || status === "down" ? "#EF4444"
    : status === "stale" || status === "scheduled" ? "#F59E0B"
    : "rgba(255,255,255,0.25)";
  return <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: col, flexShrink: 0 }} />;
}

/* ─── Mini bar chart for MAE trend ─────────────────────────────────── */
function MaeChart({ rows }: { rows: MaeRow[] }) {
  if (!rows.length) return <p style={{ color: "rgba(255,255,255,0.3)", fontSize: 12, fontFamily: "var(--font-ui)" }}>No backtest data yet</p>;
  const maxMae = Math.max(...rows.map(r => r.mae ?? 0));
  const seasons = [...new Set(rows.map(r => r.season))];
  const colors = ["#22C55E", "#3B82F6", "#F59E0B", "#A78BFA"];
  return (
    <div style={{ width: "100%", overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 80, minWidth: Math.max(rows.length * 6, 300) }}>
        {rows.map((r, i) => {
          const h = r.mae ? (r.mae / maxMae) * 72 : 0;
          const si = seasons.indexOf(r.season);
          return (
            <div key={i} title={`GW${r.gw} · ${r.season} · MAE ${r.mae?.toFixed(2) ?? "—"}`}
              style={{ flex: 1, minWidth: 4, height: h, background: colors[si % colors.length], opacity: 0.8, borderRadius: "2px 2px 0 0", transition: "opacity 0.2s" }} />
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
        {seasons.map((s, i) => (
          <span key={s} style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: colors[i % colors.length], display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: colors[i % colors.length], display: "inline-block", flexShrink: 0 }} />
            {" "}{s}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ─── Calibration heatmap ──────────────────────────────────────────── */
function CalHeatmap({ rows }: { rows: CalRow[] }) {
  if (!rows.length) return <p style={{ color: "rgba(255,255,255,0.3)", fontSize: 12, fontFamily: "var(--font-ui)" }}>No calibration data</p>;
  const positions = [...new Set(rows.map(r => r.position))];
  const bands = [...new Set(rows.map(r => r.price_band))];
  const max = Math.max(...rows.map(r => Math.abs(r.mean_residual)));
  const cell = (pos: string, band: string) => rows.find(r => r.position === pos && r.price_band === band);
  const col = (v: number) => {
    const t = Math.min(Math.abs(v) / (max || 1), 1);
    if (v > 0) return `rgba(34,197,94,${0.15 + t * 0.65})`;
    if (v < 0) return `rgba(239,68,68,${0.15 + t * 0.65})`;
    return "rgba(255,255,255,0.05)";
  };
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 11, fontFamily: "var(--font-ui)" }}>
        <thead>
          <tr>
            <th style={{ padding: "4px 8px", color: "rgba(255,255,255,0.4)", textAlign: "left", fontWeight: 500 }}>Position</th>
            {bands.map(b => <th key={b} style={{ padding: "4px 8px", color: "rgba(255,255,255,0.4)", fontWeight: 500 }}>{b}</th>)}
          </tr>
        </thead>
        <tbody>
          {positions.map(pos => (
            <tr key={pos}>
              <td style={{ padding: "4px 8px", color: "var(--text-1)", fontWeight: 600 }}>{pos}</td>
              {bands.map(band => {
                const c = cell(pos, band);
                const v = c?.mean_residual ?? 0;
                return (
                  <td key={band} title={`${pos} · ${band} · residual ${v > 0 ? "+" : ""}${v.toFixed(2)} (n=${c?.sample_size ?? 0})`}
                    style={{ padding: "4px 8px", background: col(v), borderRadius: 4, textAlign: "center", color: "var(--text-1)" }}>
                    {v > 0 ? "+" : ""}{v.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 6, fontFamily: "var(--font-ui)" }}>
        Green = model under-predicts (actual &gt; predicted) · Red = over-predicts
      </p>
    </div>
  );
}

/* ─── Oracle history chart ─────────────────────────────────────────── */
function OracleChart({ rows }: { rows: OracleRow[] }) {
  if (!rows.length) return <p style={{ color: "rgba(255,255,255,0.3)", fontSize: 12, fontFamily: "var(--font-ui)" }}>No resolved Oracle entries yet</p>;
  const max = Math.max(...rows.flatMap(r => [r.oracle_pts ?? 0, r.top_pts ?? 0]));
  return (
    <div style={{ width: "100%", overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 80, minWidth: Math.max(rows.length * 20, 200) }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: "flex", alignItems: "flex-end", gap: 1, flex: 1 }}>
            <div title={`GW${r.gw} Oracle: ${r.oracle_pts}`}
              style={{ flex: 1, height: ((r.oracle_pts ?? 0) / max) * 72, background: r.beat_top ? "#22C55E" : "#3B82F6", borderRadius: "2px 2px 0 0", opacity: 0.85 }} />
            <div title={`GW${r.gw} Top FPL: ${r.top_pts}`}
              style={{ flex: 1, height: ((r.top_pts ?? 0) / max) * 72, background: "rgba(255,255,255,0.2)", borderRadius: "2px 2px 0 0" }} />
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "#22C55E", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "#22C55E", display: "inline-block" }} />Oracle (beat top)
        </span>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "#3B82F6", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "#3B82F6", display: "inline-block" }} />Oracle (lost)
        </span>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.4)", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(255,255,255,0.3)", display: "inline-block" }} />Top FPL
        </span>
      </div>
    </div>
  );
}

/* ─── Feature importance ───────────────────────────────────────────── */
function FeatureChart({ rows }: { rows: FiRow[] }) {
  if (!rows.length) return <p style={{ color: "rgba(255,255,255,0.3)", fontSize: 12, fontFamily: "var(--font-ui)" }}>No feature importance data yet — run a retrain first.</p>;
  const top = rows.slice(0, 15);
  const max = top[0]?.importance ?? 1;
  const total = top.reduce((s, f) => s + f.importance, 0) || 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {top.map((f, i) => {
        const pct = Math.round((f.importance / total) * 100);
        const barPct = (f.importance / max) * 100;
        // Friendly label: replace underscores with spaces, title-case
        const label = f.feature.replace(/_/g, " ");
        return (
          <div key={f.feature} style={{ display: "grid", gridTemplateColumns: "18px 150px 1fr 38px", alignItems: "center", gap: 8 }}>
            {/* Rank */}
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.35)", textAlign: "right" }}>{i + 1}</span>
            {/* Feature name — outside bar so it's always readable */}
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.75)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={f.feature}>{label}</span>
            {/* Bar — pure visual, no text inside */}
            <div style={{ height: 10, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${barPct}%`, background: i === 0 ? "rgba(34,197,94,0.7)" : i < 3 ? "rgba(34,197,94,0.5)" : "rgba(34,197,94,0.3)", borderRadius: 3, transition: "width 400ms ease" }} />
            </div>
            {/* Percentage */}
            <span style={{ fontFamily: "var(--font-data)", fontSize: 10, color: "rgba(255,255,255,0.45)", textAlign: "right" }}>{pct}%</span>
          </div>
        );
      })}
    </div>
  );
}

/* ─── Feature importance card (gain vs SHAP tab toggle) ────────────── */
function FeatureImportanceCard({
  gainRows,
  shapRows,
  isotonicSummary,
}: {
  gainRows: FiRow[];
  shapRows: FiRow[];
  isotonicSummary: Record<string, { n: number; residual_before: number; residual_after: number }>;
}) {
  const [mode, setMode] = React.useState<"shap" | "gain">("shap");
  const rows = mode === "shap" ? shapRows : gainRows;
  const hasShap = shapRows.length > 0;
  const hasGain = gainRows.length > 0;

  const tabStyle = (active: boolean) => ({
    fontFamily: "var(--font-ui)",
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: "0.1em",
    textTransform: "uppercase" as const,
    padding: "3px 10px",
    borderRadius: 4,
    border: "none",
    cursor: "pointer",
    background: active ? "rgba(34,197,94,0.18)" : "transparent",
    color: active ? "#22C55E" : "rgba(255,255,255,0.35)",
  });

  return (
    <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 10, padding: "16px 18px", marginBottom: 16 }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "rgba(255,255,255,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", margin: 0 }}>
          Feature importance (top 15)
        </p>
        <div style={{ display: "flex", gap: 4 }}>
          <button style={tabStyle(mode === "shap")} onClick={() => setMode("shap")}>
            SHAP
          </button>
          <button style={tabStyle(mode === "gain")} onClick={() => setMode("gain")}>
            Gain
          </button>
        </div>
      </div>

      {/* Explanation */}
      <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.35)", margin: "0 0 12px", lineHeight: 1.5 }}>
        {mode === "shap"
          ? "SHAP (mean |Shapley value|) distributes credit fairly among correlated features — xa_last_5_gws and xg_last_5_gws each get their share instead of one stealing the other's gain."
          : "Gain importance (total info gain per feature). Correlated features steal each other's score — use SHAP for the true picture."}
      </p>

      {/* Chart */}
      {rows.length > 0 ? (
        <FeatureChart rows={rows} />
      ) : (
        <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "rgba(255,255,255,0.25)", margin: 0 }}>
          {mode === "shap"
            ? "No SHAP data yet — will populate after next retrain (shap package required)."
            : "No gain importance data yet — run a retrain first."}
        </p>
      )}

      {/* Isotonic calibration summary */}
      {Object.keys(isotonicSummary).length > 0 && (
        <div style={{ marginTop: 18, borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 14 }}>
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "rgba(255,255,255,0.3)", letterSpacing: "0.12em", textTransform: "uppercase", margin: "0 0 10px" }}>
            Isotonic calibration — residual reduction by group
          </p>
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.3)", margin: "0 0 10px", lineHeight: 1.5 }}>
            Per-group mean error before → after applying the fitted IsotonicRegression. Closer to 0 = better calibrated.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 6 }}>
            {Object.entries(isotonicSummary)
              .sort(([, a], [, b]) => Math.abs(b.residual_before) - Math.abs(a.residual_before))
              .slice(0, 12)
              .map(([key, v]) => {
                const improved = Math.abs(v.residual_after) < Math.abs(v.residual_before);
                const posMap: Record<string, string> = { pos1: "GK", pos2: "DEF", pos3: "MID", pos4: "FWD" };
                const [posKey, bandPart] = key.split("_band");
                const posLabel = posMap[posKey] ?? posKey;
                return (
                  <div key={key} style={{ background: "rgba(255,255,255,0.03)", borderRadius: 6, padding: "7px 10px", border: `1px solid ${improved ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.15)"}` }}>
                    <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 700, color: "rgba(255,255,255,0.6)", marginBottom: 4 }}>
                      {posLabel} £{bandPart}m <span style={{ color: "rgba(255,255,255,0.3)", fontWeight: 400 }}>n={v.n}</span>
                    </div>
                    <div style={{ fontFamily: "var(--font-data)", fontSize: 11, display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={{ color: v.residual_before > 0 ? "#22C55E" : "#EF4444" }}>
                        {v.residual_before > 0 ? "+" : ""}{v.residual_before.toFixed(2)}
                      </span>
                      <span style={{ color: "rgba(255,255,255,0.25)" }}>→</span>
                      <span style={{ color: improved ? "#22C55E" : "#F59E0B" }}>
                        {v.residual_after > 0 ? "+" : ""}{v.residual_after.toFixed(2)}
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Section card ─────────────────────────────────────────────────── */
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 10, padding: "16px 18px", marginBottom: 16 }}>
      <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "rgba(255,255,255,0.35)", letterSpacing: "0.12em", textTransform: "uppercase", margin: "0 0 14px" }}>{title}</p>
      {children}
    </div>
  );
}

/* ─── Main component ───────────────────────────────────────────────── */
export default function AdminPage() {
  const [token, setToken]     = useState<string | null>(null);
  const [tab, setTab]         = useState<"health" | "jobs" | "chain" | "ml" | "users">("health");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  // Login form
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginErr, setLoginErr] = useState("");

  // Data
  const [health, setHealth]   = useState<Record<string, HealthSvc> | null>(null);
  const [jobs, setJobs]       = useState<Job[]>([]);
  const [chain, setChain]     = useState<{ steps: ChainStep[]; current_gw: number | null; chain_complete: boolean } | null>(null);
  const [ml, setMl]           = useState<{ mae_by_gw: MaeRow[]; calibration: CalRow[]; oracle_history: OracleRow[]; feature_importance: FiRow[]; shap_importance: FiRow[]; isotonic_calibration_summary: Record<string, { n: number; residual_before: number; residual_after: number }>; current: Record<string, unknown> } | null>(null);
  const [users, setUsers]     = useState<unknown[]>([]);
  // Backfill state
  const [backfillTeamId, setBackfillTeamId]   = useState("");
  const [backfillFromGw, setBackfillFromGw]   = useState("");
  const [backfillToGw, setBackfillToGw]       = useState("");
  const [backfillResult, setBackfillResult]   = useState<string | null>(null);
  const [backfilling, setBackfilling]         = useState(false);
  // Trigger feedback: map jobId → { ok: bool, msg: string }
  const [triggerMsgs, setTriggerMsgs]         = useState<Record<string, { ok: boolean; msg: string }>>({});
  // Expanded run history: set of job IDs whose history is expanded
  const [expandedJobs, setExpandedJobs]        = useState<Set<string>>(new Set());
  const toggleExpand = (id: string) => setExpandedJobs(prev => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });

  // Restore token
  useEffect(() => { const t = stored(); if (t) setToken(t); }, []);

  const login = async () => {
    setLoginErr("");
    try {
      const r = await fetch(`${API}/api/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) { setLoginErr("Invalid credentials"); return; }
      const d = await r.json();
      saveToken(d.access_token);
      setToken(d.access_token);
    } catch { setLoginErr("Cannot reach backend"); }
  };

  const logout = () => { clearToken(); setToken(null); };

  const load = useCallback(async (t: string) => {
    setLoading(true); setError(null);
    try {
      if (tab === "health") {
        const d = await apiFetch("/api/admin/health", t);
        setHealth(d);
      } else if (tab === "jobs") {
        const d = await apiFetch("/api/admin/jobs", t);
        setJobs(d.jobs);
      } else if (tab === "chain") {
        const d = await apiFetch("/api/admin/gw-chain", t);
        setChain(d);
      } else if (tab === "ml") {
        const d = await apiFetch("/api/admin/ml", t);
        setMl(d);
      } else if (tab === "users") {
        const d = await apiFetch("/api/admin/users", t);
        setUsers(d.users);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.startsWith("401")) { logout(); return; }
      setError(msg);
    } finally { setLoading(false); }
  }, [tab]);

  useEffect(() => { if (token) load(token); }, [token, tab, load]);

  const runBackfill = async () => {
    if (!token || !backfillTeamId || !backfillFromGw || !backfillToGw) return;
    setBackfilling(true); setBackfillResult(null);
    try {
      const r = await fetch(
        `${API}/api/oracle/backfill?team_id=${backfillTeamId}&from_gw=${backfillFromGw}&to_gw=${backfillToGw}`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } }
      );
      const d = await r.json();
      const ok = d.results?.filter((x: { status: string }) => x.status === "ok").length ?? 0;
      const skip = d.results?.filter((x: { status: string }) => x.status === "skipped").length ?? 0;
      const err = d.results?.filter((x: { status: string }) => x.status === "error").length ?? 0;
      setBackfillResult(`Done — ${ok} computed, ${skip} skipped (already exist), ${err} failed`);
    } catch (e: unknown) { setBackfillResult(`Error: ${e}`); }
    finally { setBackfilling(false); }
  };

  const trigger = async (jobId: string) => {
    if (!token) return;
    setTriggerMsgs(prev => ({ ...prev, [jobId]: { ok: true, msg: "Starting…" } }));
    try {
      const res = await apiFetch(`/api/admin/jobs/${jobId}/trigger`, token, { method: "POST" });
      const mode = (res as Record<string, unknown>).mode ?? "queued";
      setTriggerMsgs(prev => ({ ...prev, [jobId]: { ok: true, msg: `✓ Triggered (${mode})` } }));
      setTimeout(() => {
        setTriggerMsgs(prev => { const n = { ...prev }; delete n[jobId]; return n; });
        load(token);
      }, 3000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setTriggerMsgs(prev => ({ ...prev, [jobId]: { ok: false, msg: `✗ ${msg}` } }));
      setTimeout(() => setTriggerMsgs(prev => { const n = { ...prev }; delete n[jobId]; return n; }), 6000);
    }
  };

  const clearLock = async (key: string) => {
    if (!token) return;
    try {
      await apiFetch("/api/admin/locks/clear", token, { method: "POST", body: JSON.stringify({ key }) });
      setTimeout(() => load(token), 800);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`Clear lock failed: ${msg}`);
    }
  };

  /* ── Login screen ──────────────────────────────────────────────────── */
  if (!token) {
    return (
      <div style={{ minHeight: "100vh", background: "#0B0B0D", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
        <div style={{ width: "100%", maxWidth: 360, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 14, padding: "32px 28px" }}>
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "rgba(34,197,94,0.7)", letterSpacing: "0.16em", textTransform: "uppercase", margin: "0 0 8px" }}>Admin</p>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, color: "#fff", margin: "0 0 24px", letterSpacing: "-0.02em" }}>Intelligence Engine</h1>
          <input placeholder="Username" value={username} onChange={e => setUsername(e.target.value)}
            style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, padding: "10px 12px", color: "#fff", fontFamily: "var(--font-ui)", fontSize: 13, marginBottom: 10, boxSizing: "border-box", outline: "none" }} />
          <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") login(); }}
            style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, padding: "10px 12px", color: "#fff", fontFamily: "var(--font-ui)", fontSize: 13, marginBottom: 16, boxSizing: "border-box", outline: "none" }} />
          {loginErr && <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "#EF4444", marginBottom: 12 }}>{loginErr}</p>}
          <button onClick={login} style={{ width: "100%", background: "#22C55E", border: "none", borderRadius: 8, padding: "11px 0", color: "#0B0B0D", fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
            Sign in
          </button>
        </div>
      </div>
    );
  }

  /* ── Dashboard ─────────────────────────────────────────────────────── */
  const TABS = [
    { id: "health", label: "System" },
    { id: "jobs",   label: "Jobs" },
    { id: "chain",  label: "GW Chain" },
    { id: "ml",     label: "ML Model" },
    { id: "users",  label: "Users" },
  ] as const;

  return (
    <div style={{ minHeight: "100vh", background: "#0B0B0D", color: "var(--text-1)" }}>
      {/* Top bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(0,0,0,0.4)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "rgba(34,197,94,0.7)", letterSpacing: "0.16em", textTransform: "uppercase" }}>Admin</span>
          <span style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em" }}>Intelligence Engine</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => load(token)} style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, padding: "6px 12px", color: "rgba(255,255,255,0.7)", fontFamily: "var(--font-ui)", fontSize: 11, cursor: "pointer" }}>
            Refresh
          </button>
          <button onClick={logout} style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 6, padding: "6px 12px", color: "#EF4444", fontFamily: "var(--font-ui)", fontSize: 11, cursor: "pointer" }}>
            Sign out
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 0, padding: "0 20px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            style={{ background: "none", border: "none", borderBottom: tab === t.id ? "2px solid #22C55E" : "2px solid transparent", padding: "12px 16px", color: tab === t.id ? "#22C55E" : "rgba(255,255,255,0.4)", fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: tab === t.id ? 700 : 400, cursor: "pointer", transition: "color 0.2s" }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "20px", maxWidth: 900, margin: "0 auto" }}>
        {loading && <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "rgba(255,255,255,0.3)" }}>Loading…</p>}
        {error && (
          <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: 8, padding: "10px 14px", marginBottom: 12 }}>
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "#EF4444", margin: 0 }}>
              {error.toLowerCase().includes("load failed") || error.toLowerCase().includes("failed to fetch")
                ? "Cannot reach backend — check that Docker is running and the backend container is healthy."
                : `Error: ${error}`}
            </p>
            <button onClick={() => token && load(token)} style={{ marginTop: 8, background: "none", border: "1px solid rgba(239,68,68,0.4)", borderRadius: 5, padding: "4px 10px", color: "#EF4444", fontFamily: "var(--font-ui)", fontSize: 10, cursor: "pointer" }}>
              Retry
            </button>
          </div>
        )}

        {/* ── SYSTEM HEALTH ─────────────────────────────────────────────── */}
        {tab === "health" && health && (
          <>
            <Card title="Services">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 }}>
                {Object.entries(health).map(([svc, info]) => (
                  <div key={svc} style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, padding: "12px 14px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                      <Dot status={info.status} />
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "var(--text-1)", textTransform: "capitalize" }}>{svc.replace(/_/g, " ")}</span>
                    </div>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
                      {info.status}
                      {info.last_gw ? ` · last GW${info.last_gw}` : ""}
                      {info.last_heartbeat_s_ago != null ? ` · ${info.last_heartbeat_s_ago}s ago` : ""}
                      {info.running ? " · running" : ""}
                    </span>
                    {info.error && <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "#EF4444", marginTop: 4 }}>{info.error}</div>}
                  </div>
                ))}
              </div>
            </Card>
            <Card title="Quick actions">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {[
                  { label: "Clear GW watcher lock", key: "gw_watcher:last_finished_gw" },
                  { label: "Clear pipeline lock", key: "pipeline:lock" },
                  { label: "Clear refresh lock", key: "refresh:lock" },
                ].map(({ label, key }) => (
                  <button key={key} onClick={() => clearLock(key)}
                    style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 6, padding: "7px 12px", color: "#EF4444", fontFamily: "var(--font-ui)", fontSize: 11, cursor: "pointer" }}>
                    {label}
                  </button>
                ))}
              </div>
            </Card>
          </>
        )}

        {/* ── JOBS ──────────────────────────────────────────────────────── */}
        {tab === "jobs" && (
          <Card title={`Scheduled jobs (${jobs.length})`}>
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.35)", marginBottom: 10 }}>
              All jobs run automatically on schedule. Click ▸ to see run history. Use Run only to force-trigger manually.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {jobs.map(j => (
                <div key={j.id} style={{ background: "rgba(255,255,255,0.02)", borderRadius: 7, border: "1px solid rgba(255,255,255,0.05)", overflow: "hidden" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto auto auto", gap: 8, alignItems: "center", padding: "8px 10px" }}>
                    <Dot status={j.last_status || "unknown"} />
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: "var(--text-1)" }}>{j.name}</span>
                        {(j.run_history?.length ?? 0) > 0 && (
                          <button onClick={() => toggleExpand(j.id)}
                            style={{ background: "none", border: "none", color: "rgba(255,255,255,0.3)", cursor: "pointer", fontFamily: "var(--font-ui)", fontSize: 10, padding: "0 4px" }}>
                            {expandedJobs.has(j.id) ? "▾ hide" : `▸ ${j.run_history.length} runs`}
                          </button>
                        )}
                      </div>
                      <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
                        {j.last_run ? `Last: ${new Date(j.last_run).toLocaleString()}` : "Never run"}
                        {j.last_duration_s ? ` · ${j.last_duration_s.toFixed(0)}s` : ""}
                      </div>
                      {j.last_error && <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "#EF4444", marginTop: 2 }}>{j.last_error}</div>}
                    </div>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.3)" }}>
                      {j.next_run_mins != null ? (j.next_run_mins < 0 ? "overdue" : `in ${j.next_run_mins}m`) : "—"}
                    </span>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: j.last_status === "success" ? "#22C55E" : j.last_status === "failed" ? "#EF4444" : "rgba(255,255,255,0.3)", textTransform: "capitalize" }}>
                      {j.last_status || "—"}
                    </span>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
                      <button onClick={() => trigger(j.id)}
                        style={{ background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: 5, padding: "4px 10px", color: "#22C55E", fontFamily: "var(--font-ui)", fontSize: 10, cursor: "pointer" }}>
                        Run
                      </button>
                      {triggerMsgs[j.id] && (
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: triggerMsgs[j.id].ok ? "#22C55E" : "#EF4444", whiteSpace: "nowrap" }}>
                          {triggerMsgs[j.id].msg}
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Run history drawer */}
                  {expandedJobs.has(j.id) && j.run_history?.length > 0 && (
                    <div style={{ borderTop: "1px solid rgba(255,255,255,0.05)", padding: "6px 10px 8px", display: "flex", flexDirection: "column", gap: 3 }}>
                      <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.25)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.1em" }}>Run History (newest first)</div>
                      {j.run_history.map((r, i) => (
                        <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: r.status === "success" ? "#22C55E" : "#EF4444", flexShrink: 0, display: "inline-block" }} />
                          <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.5)", flex: 1 }}>
                            {new Date(r.ts).toLocaleString()} · {r.duration_s}s
                          </span>
                          {r.error && <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "#EF4444", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.error}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* ── GW CHAIN ──────────────────────────────────────────────────── */}
        {tab === "chain" && (
          <Card title="Oracle Backfill — compute missing past GW snapshots">
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "rgba(255,255,255,0.4)", marginBottom: 12 }}>
              If a user has GW30 oracle data but is now in GW32, fill in GW31 retroactively.
              The snapshot endpoint computes the optimal team using player xPts available at that time.
            </p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
              {[
                { label: "Team ID", val: backfillTeamId, set: setBackfillTeamId, placeholder: "843351" },
                { label: "From GW", val: backfillFromGw, set: setBackfillFromGw, placeholder: "31" },
                { label: "To GW",   val: backfillToGw,   set: setBackfillToGw,   placeholder: "31" },
              ].map(({ label, val, set, placeholder }) => (
                <div key={label}>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.35)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>{label}</div>
                  <input
                    value={val}
                    onChange={e => set(e.target.value)}
                    placeholder={placeholder}
                    style={{ width: 80, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 6, padding: "7px 10px", color: "#fff", fontFamily: "var(--font-ui)", fontSize: 12, outline: "none" }}
                  />
                </div>
              ))}
              <button
                onClick={runBackfill}
                disabled={backfilling}
                style={{ background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: 6, padding: "8px 14px", color: "#22C55E", fontFamily: "var(--font-ui)", fontSize: 11, cursor: backfilling ? "wait" : "pointer", fontWeight: 600 }}>
                {backfilling ? "Running…" : "Run Backfill"}
              </button>
            </div>
            {backfillResult && (
              <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "#22C55E", marginTop: 10 }}>{backfillResult}</p>
            )}
          </Card>
        )}
        {tab === "chain" && chain && (
          <Card title={`Post-GW chain — GW${chain.current_gw ?? "?"} ${chain.chain_complete ? "✓ complete" : "pending"}`}>
            <div style={{ display: "flex", flexDirection: "column", gap: 0, position: "relative" }}>
              {chain.steps.map((step, i) => (
                <div key={step.id} style={{ display: "flex", gap: 14, alignItems: "flex-start", paddingBottom: 16, position: "relative" }}>
                  {/* timeline line */}
                  {i < chain.steps.length - 1 && <div style={{ position: "absolute", left: 9, top: 20, bottom: 0, width: 1, background: "rgba(255,255,255,0.08)" }} />}
                  <Dot status={step.status} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: "var(--text-1)" }}>{step.name}</span>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.3)", background: "rgba(255,255,255,0.05)", borderRadius: 4, padding: "1px 6px" }}>
                        +{step.offset_min}min
                      </span>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: step.status === "success" ? "#22C55E" : step.status === "failed" ? "#EF4444" : step.status === "scheduled" ? "#F59E0B" : "rgba(255,255,255,0.3)", textTransform: "capitalize" }}>
                        {step.status}
                      </span>
                    </div>
                    {step.last_run && <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 3 }}>Last: {new Date(step.last_run).toLocaleString()}</div>}
                    {step.last_error && <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "#EF4444", marginTop: 2 }}>{step.last_error}</div>}
                    {step.next_run && <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "#F59E0B", marginTop: 3 }}>Scheduled: {new Date(step.next_run).toLocaleString()}</div>}
                    {/* Run history mini-log */}
                    {(step.run_history?.length ?? 0) > 0 && (
                      <div style={{ marginTop: 5, display: "flex", flexDirection: "column", gap: 2 }}>
                        {step.run_history.slice(0, 5).map((r, i) => (
                          <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <span style={{ width: 5, height: 5, borderRadius: "50%", background: r.status === "success" ? "#22C55E" : "#EF4444", flexShrink: 0, display: "inline-block" }} />
                            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.4)" }}>
                              {new Date(r.ts).toLocaleString()} · {r.duration_s}s
                              {r.error && <span style={{ color: "#EF4444", marginLeft: 4 }}>{r.error.slice(0, 60)}</span>}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 0 }}>
                    <button onClick={() => trigger(step.id)}
                      style={{ background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: 5, padding: "4px 10px", color: "#22C55E", fontFamily: "var(--font-ui)", fontSize: 10, cursor: "pointer" }}>
                      Run now
                    </button>
                    {triggerMsgs[step.id] && (
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: triggerMsgs[step.id].ok ? "#22C55E" : "#EF4444", whiteSpace: "nowrap" }}>
                        {triggerMsgs[step.id].msg}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* ── ML MODEL ──────────────────────────────────────────────────── */}
        {tab === "ml" && ml && (
          <>
            <Card title="MAE by GW (lower = better)">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 14 }}>
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: ml.current.mae ? "#22C55E" : "rgba(255,255,255,0.25)" }}>
                    {ml.current.mae ? Number(ml.current.mae).toFixed(2) : "—"}
                  </div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: 2 }}>
                    {(ml.current as any).mae_source === "backtest_avg"
                      ? <span title="Redis key unavailable — showing average of last 10 backtest GW rows">Backtest Avg MAE</span>
                      : "Live MAE (recent GWs)"}
                  </div>
                </div>
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 700, color: (ml.current as any).pipeline_gw ? "#60A5FA" : "rgba(255,255,255,0.25)" }}>
                    {(ml.current as any).pipeline_gw ? `GW${(ml.current as any).pipeline_gw}` : "—"}
                  </div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: 2 }}>Pipeline ran</div>
                  {(ml.current as any).pipeline_ran && (
                    <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "rgba(255,255,255,0.25)", marginTop: 2 }}>
                      {new Date((ml.current as any).pipeline_ran).toLocaleString()}
                    </div>
                  )}
                </div>
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: "rgba(255,255,255,0.5)" }}>{ml.mae_by_gw.length}</div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: 2 }}>GWs tracked</div>
                </div>
              </div>
              <MaeChart rows={ml.mae_by_gw} />
            </Card>
            <Card title="Calibration heatmap — mean residual by position × price band">
              <CalHeatmap rows={ml.calibration} />
            </Card>
            <FeatureImportanceCard
              gainRows={ml.feature_importance}
              shapRows={ml.shap_importance}
              isotonicSummary={ml.isotonic_calibration_summary}
            />
            <Card title="Oracle vs Top FPL manager — GW by GW">
              <OracleChart rows={ml.oracle_history} />
              {ml.oracle_history.length > 0 && (() => {
                const wins = ml.oracle_history.filter(r => r.beat_top).length;
                const total = ml.oracle_history.length;
                const winRate = Math.round((wins / total) * 100);
                return (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
                      <div>
                        <div style={{ fontFamily: "var(--font-data)", fontSize: 18, fontWeight: 700, color: wins > total / 2 ? "#22C55E" : "#3B82F6" }}>
                          {wins}/{total}
                        </div>
                        <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em" }}>GWs oracle beat top</div>
                      </div>
                      <div>
                        <div style={{ fontFamily: "var(--font-data)", fontSize: 18, fontWeight: 700, color: "rgba(255,255,255,0.6)" }}>
                          {winRate}%
                        </div>
                        <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em" }}>win rate</div>
                      </div>
                    </div>
                    <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "rgba(255,255,255,0.35)", lineHeight: 1.5, margin: 0 }}>
                      The &quot;top FPL manager&quot; is the #1 ranked manager globally that GW. Beating them consistently is the hardest possible benchmark — they frequently use chips (Triple Captain, Bench Boost) that inflate their score. A 30–50% win rate against the top 100K average is strong. 0/{total} GWs is expected early in the season while the model is still calibrating.
                    </p>
                  </div>
                );
              })()}
            </Card>
          </>
        )}

        {/* ── USERS ─────────────────────────────────────────────────────── */}
        {tab === "users" && (
          <Card title={`Registered users (${users.length})`}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(users as Array<{ team_id: number; name: string; email: string; created_at: string; free_transfers: number | null; budget: number | null }>).map(u => (
                <div key={u.team_id} style={{ display: "grid", gridTemplateColumns: "80px 1fr 1fr 60px 60px", gap: 8, alignItems: "center", padding: "8px 10px", background: "rgba(255,255,255,0.02)", borderRadius: 7, border: "1px solid rgba(255,255,255,0.05)" }}>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: "rgba(255,255,255,0.5)" }}>#{u.team_id}</span>
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--text-1)", fontWeight: 600 }}>{u.name || "—"}</span>
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.4)" }}>{u.email}</span>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 11, color: "#22C55E", textAlign: "center" }}>{u.free_transfers ?? "—"} FT</span>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 11, color: "rgba(255,255,255,0.5)", textAlign: "center" }}>£{u.budget?.toFixed(1) ?? "—"}m</span>
                </div>
              ))}
              {users.length === 0 && <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "rgba(255,255,255,0.3)" }}>No registered users yet</p>}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
