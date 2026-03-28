"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import BottomDock from "@/components/BottomDock";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface GWBlock {
  id: number;
  name: string;
  deadline?: string | null;
  gw_start_time?: string | null;
  gw_end_time?: string | null;
  finished: boolean;
  data_checked: boolean;
  is_blank: boolean;
  is_double: boolean;
  mins_to_kickoff?: number | null;
  mins_to_end?: number | null;
  mins_to_deadline?: number | null;
}

interface UpcomingEvent {
  event: string;
  label: string;
  at: string;
  mins_from_now: number | null;
  done?: boolean;   // true only if the action actually completed (not just time passed)
}

interface StatusData {
  state: string;
  state_label: string;
  state_detail: string;
  server_time: string;
  current_gw: GWBlock | null;
  next_gw: GWBlock | null;
  previous_gw: GWBlock | null;
  model: {
    trained: boolean;
    mode: string;
    current_mae?: number | null;
    last_retrain_at?: string | null;
    calibration_groups?: number;
  };
  pipeline_last_run: string | null;
  pipeline_running: boolean;
  upcoming_events: UpcomingEvent[];
  system_actions: string[];
}

const STATE_COLORS: Record<string, string> = {
  live:        "var(--green)",
  planning:    "var(--blue)",
  settling:    "var(--amber)",
  pre_kickoff: "var(--amber)",
};

const STATE_DOT_PULSE: Record<string, boolean> = {
  live:     true,
  settling: true,
};

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", timeZone: "Europe/London",
  }) + " GMT";
}

function minsLabel(mins: number | null | undefined): string {
  if (mins == null) return "";
  const abs = Math.abs(mins);
  if (abs < 1) return "now";
  const h = Math.floor(abs / 60);
  const m = Math.round(abs % 60);
  const dur = h > 0 ? `${h}h${m > 0 ? ` ${m}m` : ""}` : `${Math.round(abs)}m`;
  return mins < 0 ? `${dur} ago` : `in ${dur}`;
}

function GWCard({ gw, label, isLive }: { gw: GWBlock; label: string; isLive?: boolean }) {
  return (
    <div style={{
      padding: "14px 16px",
      borderRadius: 12,
      background: "var(--surface)",
      border: isLive ? "1px solid rgba(34,197,94,0.3)" : "1px solid var(--divider)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
          {label}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          {isLive && (
            <span style={{ display: "flex", alignItems: "center", gap: 4, fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "var(--green)", background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: 4, padding: "2px 6px" }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--green)", display: "inline-block", boxShadow: "0 0 6px var(--green)" }} />
              LIVE
            </span>
          )}
          {gw.is_double && <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--green)",  background: "rgba(34,197,94,0.08)",  border: "1px solid rgba(34,197,94,0.2)",  borderRadius: 4, padding: "2px 6px" }}>DGW</span>}
          {gw.finished && gw.data_checked && <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", background: "rgba(255,255,255,0.04)", border: "1px solid var(--divider)", borderRadius: 4, padding: "2px 6px" }}>DONE</span>}
        </div>
      </div>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.02em", marginBottom: 10 }}>
        {gw.name}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {[
          { label: "Deadline", value: fmt(gw.deadline), sub: minsLabel(gw.mins_to_deadline) },
          { label: "First kick-off", value: fmt(gw.gw_start_time), sub: minsLabel(gw.mins_to_kickoff) },
          { label: "Est. last game ends", value: gw.gw_end_time ? fmt(gw.gw_end_time) : "—", sub: minsLabel(gw.mins_to_end) },
        ].map(({ label, value, sub }) => (
          <div key={label} style={{ padding: "8px 10px", background: "var(--bg)", borderRadius: 8, border: "1px solid var(--divider)" }}>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 2 }}>{label}</div>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-1)", fontWeight: 600 }}>{value}</div>
            {sub && <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", marginTop: 1 }}>{sub}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function StatusPage() {
  const [data, setData] = useState<StatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = async () => {
    try {
      const res = await fetch(`${API}/api/status`);
      if (res.ok) {
        setData(await res.json());
        setLastRefresh(new Date());
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000); // refresh every 60s
    return () => clearInterval(t);
  }, []);

  const stateColor = data ? (STATE_COLORS[data.state] || "var(--text-3)") : "var(--text-3)";
  const dotPulse   = data ? (STATE_DOT_PULSE[data.state] ?? false) : false;

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", paddingBottom: 80 }}>
      {/* Header */}
      <div style={{ padding: "18px 20px 0", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.02em" }}>
            System Status
          </div>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
            {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : "Loading…"}
          </div>
        </div>
      </div>

      <div style={{ padding: "14px 20px", maxWidth: 720, margin: "0 auto" }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>Loading…</div>
        ) : !data ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>Could not reach backend.</div>
        ) : (
          <>
            {/* ── State banner ──────────────────────────────────────────────── */}
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              style={{
                padding: "16px 18px",
                borderRadius: 14,
                background: "var(--surface)",
                border: `1px solid ${stateColor}44`,
                marginBottom: 16,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                {/* Pulse dot */}
                <span style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 10, height: 10, flexShrink: 0 }}>
                  {dotPulse && (
                    <span style={{
                      position: "absolute", width: 18, height: 18, borderRadius: "50%",
                      background: stateColor, opacity: 0.2,
                      animation: "ping 1.4s cubic-bezier(0,0,0.2,1) infinite",
                    }} />
                  )}
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: stateColor, flexShrink: 0 }} />
                </span>
                <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 700, color: stateColor, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                  {data.state_label}
                </span>
              </div>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 14, color: "var(--text-1)", fontWeight: 500, lineHeight: 1.4 }}>
                {data.state_detail}
              </div>
            </motion.div>

            {/* ── Pipeline preparing banner ─────────────────────────────────── */}
            {data.pipeline_running && (
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 10, background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.2)", marginBottom: 12 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--blue)", flexShrink: 0, animation: "pulse 1.2s ease-in-out infinite" }} />
                <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--blue)", fontWeight: 600 }}>
                  Preparing recommendations — pipeline running, ready in ~10 min
                </span>
              </div>
            )}

            {/* ── GW cards ──────────────────────────────────────────────────── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
              {data.current_gw  && <GWCard gw={data.current_gw}  label="Current GW" isLive={data.state === "live"} />}
              {data.next_gw     && <GWCard gw={data.next_gw}     label="Next GW" />}
              {data.previous_gw && <GWCard gw={data.previous_gw} label="Previous GW" />}
            </div>

            {/* ── What the system is doing ───────────────────────────────────── */}
            {data.system_actions.length > 0 && (
              <div style={{ padding: "14px 16px", borderRadius: 12, background: "var(--surface)", border: "1px solid var(--divider)", marginBottom: 16 }}>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 10 }}>
                  System
                </div>
                {data.system_actions.map((a, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: i < data.system_actions.length - 1 ? 6 : 0 }}>
                    <span style={{ marginTop: 4, width: 4, height: 4, borderRadius: "50%", background: stateColor, flexShrink: 0 }} />
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--text-2)", lineHeight: 1.5 }}>{a}</span>
                  </div>
                ))}
              </div>
            )}

            {/* ── Timeline (past + upcoming events) ────────────────────────── */}
            {data.upcoming_events.length > 0 && (
              <div style={{ padding: "14px 16px", borderRadius: 12, background: "var(--surface)", border: "1px solid var(--divider)", marginBottom: 16 }}>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 10 }}>
                  Timeline
                </div>
                {data.upcoming_events.map((e, i) => {
                  // Use explicit done flag if provided; fall back to time-based for non-sync events
                  const isPast = e.done !== undefined
                    ? e.done
                    : (e.mins_from_now != null && e.mins_from_now < 0);
                  return (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: i < data.upcoming_events.length - 1 ? 10 : 0, opacity: isPast ? 0.55 : 1 }}>
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                        {/* Timeline dot */}
                        <span style={{ marginTop: 4, width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: isPast ? "var(--green)" : stateColor, border: isPast ? "none" : `1px solid ${stateColor}` }} />
                        <div>
                          <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: isPast ? "var(--text-2)" : "var(--text-1)" }}>
                            {isPast && "✓ "}{e.label}
                          </div>
                          <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginTop: 1 }}>{fmt(e.at)}</div>
                        </div>
                      </div>
                      {e.mins_from_now != null && (
                        <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: isPast ? "var(--green)" : "var(--blue)", fontWeight: 600, whiteSpace: "nowrap", marginLeft: 8, marginTop: 2 }}>
                          {minsLabel(e.mins_from_now)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* ── Model health ──────────────────────────────────────────────── */}
            <div style={{ padding: "14px 16px", borderRadius: 12, background: "var(--surface)", border: "1px solid var(--divider)" }}>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 10 }}>
                Model
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {[
                  { label: "mode",       value: data.model.mode },
                  { label: "current MAE", value: data.model.current_mae != null ? data.model.current_mae.toFixed(2) + " pts" : "—" },
                  { label: "calibration", value: data.model.calibration_groups ? `${data.model.calibration_groups} groups` : "—" },
                  { label: "pipeline ran", value: data.pipeline_last_run ?? "—" },
                ].map(({ label, value }) => (
                  <div key={label} style={{ padding: "8px 10px", background: "var(--bg)", borderRadius: 8, border: "1px solid var(--divider)" }}>
                    <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 2 }}>{label}</div>
                    <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-1)", fontWeight: 600 }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      <BottomDock />

      <style>{`
        @keyframes ping {
          75%, 100% { transform: scale(2.2); opacity: 0; }
        }
      `}</style>
    </div>
  );
}
