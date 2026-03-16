"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Design tokens matching the rest of the app
const GREEN = "#22C55E";
const COLORS = {
  baseline_no_transfer: "#64748B",
  greedy_xpts: "#F59E0B",
  bandit_ilp: "#22C55E",
};
const CARD_STYLE = {
  background: "rgba(255,255,255,0.03)",
  border: "1px solid rgba(255,255,255,0.07)",
  borderRadius: 16,
  padding: "24px",
  marginBottom: 20,
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface ModelMetricRow {
  gw_id: number;
  model_version: string;
  mae: number;
  rmse: number;
  rank_corr: number;
  top_10_hit_rate: number;
}

interface StrategyRow {
  gw_id: number;
  gw_points: number;
  cumulative_points: number;
}

// ─── Custom tooltip ───────────────────────────────────────────────────────────

function DarkTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "#0F1117",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 10,
        padding: "10px 14px",
        fontFamily: "var(--font-ui, sans-serif)",
        fontSize: 12,
      }}
    >
      <p style={{ color: "rgba(255,255,255,0.5)", marginBottom: 6 }}>GW {label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color, margin: "2px 0" }}>
          {p.name}: <strong>{typeof p.value === "number" ? p.value.toFixed(2) : p.value}</strong>
        </p>
      ))}
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

interface SimResult {
  n_simulations: number;
  remaining_gws: number;
  current_gw: number;
  points_distribution: { p10: number; p25: number; p50: number; p75: number; p90: number; mean: number; std: number };
  rank_distribution: { p10: number; p25: number; p50: number; p75: number; p90: number };
  chip_timing_recommendation: string;
  risk_profile: "low" | "medium" | "high";
  error?: string;
}

export default function LabPage() {
  const [modelMetrics, setModelMetrics] = useState<ModelMetricRow[]>([]);
  const [strategyMetrics, setStrategyMetrics] = useState<Record<string, StrategyRow[]>>({});
  const [modelVersions, setModelVersions] = useState<string[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<string>("all");
  const [loadingMetrics, setLoadingMetrics] = useState(true);
  const [loadingStrategy, setLoadingStrategy] = useState(true);
  const [backtestJobId, setBacktestJobId] = useState<string | null>(null);
  const [backtestStatus, setBacktestStatus] = useState<string | null>(null);
  const [adminToken, setAdminToken] = useState("");
  // Season simulation state
  const [simResult, setSimResult] = useState<SimResult | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simNSims, setSimNSims] = useState(1000);

  // ── Fetch model metrics ────────────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/api/lab/model-metrics?model_version=${selectedVersion}`)
      .then((r) => r.ok ? r.json() : { metrics: [], versions: [] })
      .then((d) => {
        setModelMetrics(d.metrics || []);
        setModelVersions(d.versions || []);
      })
      .catch(() => {})
      .finally(() => setLoadingMetrics(false));
  }, [selectedVersion]);

  // ── Fetch strategy metrics ─────────────────────────────────────────────────
  useEffect(() => {
    fetch(
      `${API}/api/lab/strategy-metrics?strategies=baseline_no_transfer,greedy_xpts,bandit_ilp`
    )
      .then((r) => r.ok ? r.json() : { strategies: {} })
      .then((d) => setStrategyMetrics(d.strategies || {}))
      .catch(() => {})
      .finally(() => setLoadingStrategy(false));
  }, []);

  // ── Poll job status ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!backtestJobId || backtestStatus === "done" || backtestStatus === "error") return;
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/jobs/${backtestJobId}`);
        if (r.ok) {
          const d = await r.json();
          setBacktestStatus(d.status);
          if (d.status === "done") {
            // Refresh metrics
            setLoadingMetrics(true);
            setLoadingStrategy(true);
            fetch(`${API}/api/lab/model-metrics?model_version=all`)
              .then((r) => r.ok ? r.json() : null)
              .then((d) => d && (setModelMetrics(d.metrics), setModelVersions(d.versions)))
              .finally(() => setLoadingMetrics(false));
            fetch(`${API}/api/lab/strategy-metrics?strategies=baseline_no_transfer,greedy_xpts,bandit_ilp`)
              .then((r) => r.ok ? r.json() : null)
              .then((d) => d && setStrategyMetrics(d.strategies))
              .finally(() => setLoadingStrategy(false));
          }
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [backtestJobId, backtestStatus]);

  const handleRunSimulation = async () => {
    setSimLoading(true);
    setSimResult(null);
    try {
      const r = await fetch(`${API}/api/lab/season-simulation?n_simulations=${simNSims}`);
      if (r.ok) setSimResult(await r.json());
    } catch {}
    setSimLoading(false);
  };

  const handleRunBacktest = async () => {
    if (!adminToken) {
      alert("Enter admin token first");
      return;
    }
    setBacktestStatus("pending");
    try {
      const r = await fetch(`${API}/api/lab/run-backtest?model_version=current`, {
        method: "POST",
        headers: { "X-Admin-Token": adminToken },
      });
      if (r.ok) {
        const d = await r.json();
        setBacktestJobId(d.job_id);
      } else if (r.status === 403) {
        alert("Invalid admin token");
        setBacktestStatus(null);
      }
    } catch {
      setBacktestStatus("error");
    }
  };

  // ── Build chart data ───────────────────────────────────────────────────────
  const maChartData = modelMetrics.reduce<Record<number, any>>((acc, row) => {
    if (!acc[row.gw_id]) acc[row.gw_id] = { gw_id: row.gw_id };
    acc[row.gw_id][row.model_version] = row.mae;
    return acc;
  }, {});
  const maData = Object.values(maChartData).sort((a: any, b: any) => a.gw_id - b.gw_id);

  const strategyGws = new Set<number>();
  Object.values(strategyMetrics).forEach((rows) => rows.forEach((r) => strategyGws.add(r.gw_id)));
  const strategyData = Array.from(strategyGws).sort((a, b) => a - b).map((gw) => {
    const row: Record<string, any> = { gw_id: gw };
    for (const [name, rows] of Object.entries(strategyMetrics)) {
      const match = rows.find((r) => r.gw_id === gw);
      if (match) row[name] = match.cumulative_points;
    }
    return row;
  });

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0B0B0D",
        color: "#FFFFFF",
        padding: "clamp(24px, 4vw, 48px)",
        fontFamily: "var(--font-ui, sans-serif)",
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1
          style={{
            fontFamily: "var(--font-display, sans-serif)",
            fontSize: "clamp(24px, 3vw, 36px)",
            fontWeight: 700,
            letterSpacing: "-0.04em",
            color: "#FFFFFF",
            marginBottom: 6,
          }}
        >
          Lab
        </h1>
        <p style={{ fontSize: 13, color: "rgba(255,255,255,0.38)", letterSpacing: "0.01em" }}>
          Model accuracy &amp; strategy evaluation over historical gameweeks
        </p>
        <a
          href="/"
          style={{ fontSize: 12, color: GREEN, opacity: 0.7, textDecoration: "none", display: "inline-block", marginTop: 8 }}
        >
          ← Back to dashboard
        </a>
      </div>

      {/* ── Card 1: Model MAE over time ───────────────────────────────────── */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <h2 style={{ fontFamily: "var(--font-display, sans-serif)", fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em" }}>
            Model MAE over Gameweeks
          </h2>
          <select
            value={selectedVersion}
            onChange={(e) => setSelectedVersion(e.target.value)}
            style={{
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8,
              color: "#FFFFFF",
              fontSize: 12,
              padding: "4px 10px",
              cursor: "pointer",
            }}
          >
            <option value="all">All versions</option>
            {modelVersions.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </div>

        {loadingMetrics ? (
          <p style={{ textAlign: "center", color: "rgba(255,255,255,0.3)", fontSize: 13, padding: "40px 0" }}>
            Loading…
          </p>
        ) : maData.length === 0 ? (
          <p style={{ textAlign: "center", color: "rgba(255,255,255,0.25)", fontSize: 13, padding: "40px 0" }}>
            No model metrics yet. Run a backtest or let the pipeline run first.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={maData} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
              <XAxis dataKey="gw_id" tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 11 }} label={{ value: "GW", position: "insideBottom", offset: -2, fill: "rgba(255,255,255,0.3)", fontSize: 10 }} />
              <YAxis tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 11 }} />
              <Tooltip content={<DarkTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11, color: "rgba(255,255,255,0.5)" }} />
              {modelVersions.length > 0
                ? modelVersions.map((v, i) => (
                    <Line key={v} type="monotone" dataKey={v} name={`MAE (${v})`} stroke={i === 0 ? GREEN : "#F59E0B"} strokeWidth={2} dot={false} />
                  ))
                : <Line type="monotone" dataKey="mae" stroke={GREEN} strokeWidth={2} dot={false} />
              }
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Card 2: Strategy cumulative points ───────────────────────────── */}
      <div style={CARD_STYLE}>
        <h2 style={{ fontFamily: "var(--font-display, sans-serif)", fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em", marginBottom: 6 }}>
          Strategy Cumulative Points
        </h2>
        <p style={{ fontSize: 11, color: "rgba(255,255,255,0.28)", marginBottom: 16, letterSpacing: "0.01em" }}>
          baseline_no_transfer vs greedy_xpts vs bandit_ilp
        </p>

        {loadingStrategy ? (
          <p style={{ textAlign: "center", color: "rgba(255,255,255,0.3)", fontSize: 13, padding: "40px 0" }}>
            Loading…
          </p>
        ) : strategyData.length === 0 ? (
          <p style={{ textAlign: "center", color: "rgba(255,255,255,0.25)", fontSize: 13, padding: "40px 0" }}>
            No strategy data yet. Run a backtest first.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={strategyData} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
              <XAxis dataKey="gw_id" tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 11 }} />
              <YAxis tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 11 }} />
              <Tooltip content={<DarkTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11, color: "rgba(255,255,255,0.5)" }} />
              <Line type="monotone" dataKey="baseline_no_transfer" name="Baseline" stroke={COLORS.baseline_no_transfer} strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
              <Line type="monotone" dataKey="greedy_xpts" name="Greedy xPts" stroke={COLORS.greedy_xpts} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="bandit_ilp" name="Bandit ILP" stroke={COLORS.bandit_ilp} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Card 3: Run Backtest (admin) ───────────────────────────────────── */}
      <div style={CARD_STYLE}>
        <h2 style={{ fontFamily: "var(--font-display, sans-serif)", fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em", marginBottom: 6 }}>
          Run Backtest
        </h2>
        <p style={{ fontSize: 11, color: "rgba(255,255,255,0.28)", marginBottom: 16 }}>
          Admin only. Runs offline simulation over feature history and writes results to DB.
        </p>

        <input
          type="password"
          placeholder="Admin token"
          value={adminToken}
          onChange={(e) => setAdminToken(e.target.value)}
          style={{
            width: "100%",
            padding: "10px 14px",
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8,
            color: "#FFFFFF",
            fontFamily: "var(--font-ui, sans-serif)",
            fontSize: 13,
            outline: "none",
            boxSizing: "border-box",
            marginBottom: 12,
          }}
        />

        <button
          onClick={handleRunBacktest}
          disabled={backtestStatus === "pending" || backtestStatus === "running"}
          style={{
            padding: "12px 24px",
            borderRadius: 10,
            border: "1px solid rgba(34,197,94,0.3)",
            background: "rgba(34,197,94,0.1)",
            color: GREEN,
            fontSize: 14,
            fontWeight: 600,
            fontFamily: "var(--font-display, sans-serif)",
            cursor: backtestStatus === "running" ? "not-allowed" : "pointer",
            opacity: backtestStatus === "running" ? 0.6 : 1,
            transition: "all 200ms",
          }}
        >
          {backtestStatus === "pending" ? "Queuing…"
            : backtestStatus === "running" ? "Running…"
            : backtestStatus === "done" ? "✓ Done — charts updated"
            : backtestStatus === "error" ? "Error — try again"
            : "Run Backtest"}
        </button>

        {backtestJobId && backtestStatus !== "done" && backtestStatus !== "error" && (
          <p style={{ fontSize: 11, color: "rgba(255,255,255,0.3)", marginTop: 10 }}>
            Job ID: {backtestJobId} · Polling every 3s…
          </p>
        )}
      </div>

      {/* ── Card 4: Season Monte Carlo Simulation ──────────────────────────── */}
      <div style={CARD_STYLE}>
        <h2 style={{ fontFamily: "var(--font-display, sans-serif)", fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em", marginBottom: 6 }}>
          Season Projection
        </h2>
        <p style={{ fontSize: 11, color: "rgba(255,255,255,0.28)", marginBottom: 16 }}>
          Monte Carlo simulation of remaining GWs. Uses current player xPts and historical model noise.
        </p>

        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16 }}>
          <label style={{ fontSize: 12, color: "rgba(255,255,255,0.5)" }}>Simulations:</label>
          <select
            value={simNSims}
            onChange={(e) => setSimNSims(Number(e.target.value))}
            style={{
              background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, color: "#FFF", fontSize: 12, padding: "4px 10px", cursor: "pointer",
            }}
          >
            {[500, 1000, 2000, 5000].map((n) => <option key={n} value={n}>{n.toLocaleString()}</option>)}
          </select>
          <button
            onClick={handleRunSimulation}
            disabled={simLoading}
            style={{
              padding: "8px 18px", borderRadius: 8, border: "1px solid rgba(34,197,94,0.3)",
              background: "rgba(34,197,94,0.1)", color: GREEN, fontSize: 13, fontWeight: 600,
              cursor: simLoading ? "not-allowed" : "pointer", opacity: simLoading ? 0.6 : 1,
            }}
          >
            {simLoading ? "Simulating…" : "Run Simulation"}
          </button>
        </div>

        {simResult && !simResult.error && (
          <div>
            {/* Points percentile bar */}
            <div style={{ marginBottom: 20 }}>
              <p style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Projected Season Points — GW{simResult.current_gw} + {simResult.remaining_gws} remaining
              </p>
              {[
                { label: "p10 (worst 10%)", value: simResult.points_distribution.p10, color: "#ef4444" },
                { label: "p25", value: simResult.points_distribution.p25, color: "#f59e0b" },
                { label: "p50 (median)", value: simResult.points_distribution.p50, color: GREEN },
                { label: "p75", value: simResult.points_distribution.p75, color: "#22d3ee" },
                { label: "p90 (top 10%)", value: simResult.points_distribution.p90, color: "#a78bfa" },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
                  <span style={{ width: 130, fontSize: 11, color: "rgba(255,255,255,0.45)", flexShrink: 0 }}>{label}</span>
                  <div style={{ flex: 1, height: 8, background: "rgba(255,255,255,0.06)", borderRadius: 4, overflow: "hidden" }}>
                    <div style={{ width: `${Math.min(100, (value / simResult.points_distribution.p90) * 100)}%`, height: "100%", background: color, borderRadius: 4 }} />
                  </div>
                  <span style={{ width: 50, textAlign: "right", fontSize: 13, fontWeight: 600, color, fontVariantNumeric: "tabular-nums" }}>{value}</span>
                </div>
              ))}
            </div>

            {/* Rank + Risk + Chip */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, padding: "14px 16px" }}>
                <p style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Estimated Rank (median)</p>
                <p style={{ fontSize: 22, fontWeight: 700, color: GREEN, fontVariantNumeric: "tabular-nums" }}>
                  #{simResult.rank_distribution.p50.toLocaleString()}
                </p>
                <p style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 4 }}>
                  Range: #{simResult.rank_distribution.p10.toLocaleString()} – #{simResult.rank_distribution.p90.toLocaleString()}
                </p>
              </div>
              <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, padding: "14px 16px" }}>
                <p style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Risk Profile</p>
                <p style={{ fontSize: 22, fontWeight: 700, color: simResult.risk_profile === "low" ? GREEN : simResult.risk_profile === "medium" ? "#f59e0b" : "#ef4444" }}>
                  {simResult.risk_profile.toUpperCase()}
                </p>
                <p style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 4 }}>
                  σ = {simResult.points_distribution.std} pts
                </p>
              </div>
            </div>

            <div style={{ marginTop: 14, padding: "12px 14px", background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: 10 }}>
              <p style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Chip Timing</p>
              <p style={{ fontSize: 13, color: "rgba(255,255,255,0.8)", lineHeight: 1.5 }}>{simResult.chip_timing_recommendation}</p>
            </div>
          </div>
        )}

        {simResult && simResult.error && (
          <p style={{ fontSize: 13, color: "#ef4444" }}>{simResult.error}</p>
        )}
      </div>

      {/* Strategy definitions legend */}
      <div style={{ ...CARD_STYLE, marginTop: 0 }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.6)", marginBottom: 12, letterSpacing: "0.04em", textTransform: "uppercase" }}>
          Strategy Definitions
        </h3>
        {[
          { name: "baseline_no_transfer", color: COLORS.baseline_no_transfer, desc: "No transfers each GW. Captain = highest xPts. No hits, no chips." },
          { name: "greedy_xpts", color: COLORS.greedy_xpts, desc: "Captain = highest xPts. Single best-xPts transfer if 3-GW predicted gain > 4 pts. No hits." },
          { name: "bandit_ilp", color: COLORS.bandit_ilp, desc: "Captain per bandit arm. ILP-optimised transfers. Hit decisions per hit arm. Chip per chip timing arm." },
        ].map(({ name, color, desc }) => (
          <div key={name} style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 10 }}>
            <div style={{ width: 12, height: 12, borderRadius: 2, background: color, flexShrink: 0, marginTop: 2 }} />
            <div>
              <p style={{ fontSize: 12, fontWeight: 600, color: "rgba(255,255,255,0.7)", marginBottom: 2, fontFamily: "var(--font-data, monospace)" }}>{name}</p>
              <p style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", lineHeight: 1.4 }}>{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
