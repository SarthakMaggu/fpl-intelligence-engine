"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import BottomDock from "@/components/BottomDock";
import { useFPLStore } from "@/store/fpl.store";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function RivalsPage() {
  const { rivals, leagues, fetchRivals, fetchLeagues, teamId } = useFPLStore();
  const [newRivalId, setNewRivalId] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [captainPicks, setCaptainPicks] = useState<any[]>([]);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    fetchRivals();
    fetchLeagues();
    loadCaptainPicks();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadCaptainPicks = async () => {
    try {
      const params = teamId ? `?team_id=${teamId}` : "";
      const res = await fetch(`${API}/api/rivals/captain-picks${params}`);
      if (!res.ok) return;
      const data = await res.json();
      setCaptainPicks(data.rivals ?? []);
    } catch {}
  };

  const addRival = async () => {
    const id = Number(newRivalId.trim());
    if (!id) return;
    setAdding(true);
    try {
      const params = teamId ? `?team_id=${teamId}` : "";
      await fetch(`${API}/api/rivals/add${params}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rival_team_id: id }),
      });
      setNewRivalId("");
      fetchRivals();
      loadCaptainPicks();
    } finally { setAdding(false); }
  };

  const removeRival = async (rivalId: number) => {
    const params = teamId ? `?team_id=${teamId}` : "";
    await fetch(`${API}/api/rivals/${rivalId}${params}`, { method: "DELETE" });
    fetchRivals();
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <main style={{ maxWidth: 760, margin: "0 auto", padding: "32px 20px 96px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.04em" }}>
            Rivals &amp; Leagues
          </h1>
        </div>

        {leagues.length > 0 && (
          <Section title="My Leagues">
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {leagues.slice(0, 12).map((lg, i) => {
                const delta = lg.rank && lg.last_rank ? lg.last_rank - lg.rank : null;
                return (
                  <motion.div key={lg.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)", borderRadius: 10 }}>
                    <div>
                      <div style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>{lg.name}</div>
                      {lg.total_entries && (
                        <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
                          {lg.total_entries.toLocaleString()} mgrs{lg.type === "h2h" ? " · H2H" : ""}
                        </div>
                      )}
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontFamily: "var(--font-display)", fontSize: 17, fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.03em" }}>
                        #{lg.rank?.toLocaleString() ?? "—"}
                      </div>
                      {delta !== null && delta !== 0 && (
                        <div style={{ fontFamily: "var(--font-data)", fontSize: 11, color: delta > 0 ? "var(--green)" : "var(--red)", letterSpacing: "-0.02em" }}>
                          {delta > 0 ? `↑${delta}` : `↓${Math.abs(delta)}`}
                        </div>
                      )}
                      {lg.entry_percentile_rank && (
                        <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)" }}>top {lg.entry_percentile_rank}%</div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </Section>
        )}

        <Section title="Track a Rival">
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="number"
              value={newRivalId}
              onChange={(e) => setNewRivalId(e.target.value)}
              placeholder="Rival Team ID"
              onKeyDown={(e) => e.key === "Enter" && addRival()}
              style={{
                flex: 1, background: "var(--surface-2)", border: "1px solid var(--divider)", borderRadius: 10,
                padding: "10px 14px", color: "var(--text-1)", fontSize: 16, fontFamily: "var(--font-data)",
                outline: "none", fontVariantNumeric: "tabular-nums",
              }}
            />
            <motion.button
              whileTap={{ scale: 0.96 }}
              onClick={addRival}
              disabled={adding}
              style={{
                padding: "10px 20px", borderRadius: 10,
                border: "1px solid rgba(34,197,94,0.3)", background: "rgba(34,197,94,0.07)",
                color: "var(--green)", fontSize: 13, fontWeight: 600, fontFamily: "var(--font-display)",
                cursor: adding ? "not-allowed" : "pointer",
              }}
            >
              {adding ? "Adding…" : "Add"}
            </motion.button>
          </div>
        </Section>

        {captainPicks.length > 0 && (
          <Section title="This GW — Rival Captains">
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {captainPicks.map((r, i) => (
                <motion.div key={r.rival_team_id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)", borderRadius: 10 }}>
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>{r.rival_name ?? `Team ${r.rival_team_id}`}</span>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontFamily: "var(--font-display)", fontSize: 13, fontWeight: 600, color: "var(--amber)", letterSpacing: "-0.01em" }}>{r.captain_name}</div>
                    {r.captain_xpts != null && (
                      <div style={{ fontFamily: "var(--font-data)", fontSize: 11, color: "var(--text-3)", letterSpacing: "-0.02em" }}>{r.captain_xpts.toFixed(1)} xP</div>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          </Section>
        )}

        {rivals.length > 0 && (
          <Section title="Tracked Rivals">
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {rivals.map((r) => (
                <div key={r.rival_team_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)", borderRadius: 10 }}>
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--text-1)" }}>{r.rival_name ?? `Team #${r.rival_team_id}`}</span>
                  <button onClick={() => removeRival(r.rival_team_id)} style={{ fontSize: 11, color: "var(--red)", background: "none", border: "none", cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                    remove
                  </button>
                </div>
              ))}
            </div>
          </Section>
        )}

        {rivals.length === 0 && leagues.length === 0 && (
          <div style={{ textAlign: "center", padding: "56px 0", color: "var(--text-3)", fontSize: 13, fontFamily: "var(--font-ui)" }}>
            sync your squad to see leagues and add rivals.
          </div>
        )}
      </main>
      <BottomDock />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: "spring", stiffness: 220, damping: 26 }}
      className="glass" style={{ borderRadius: 14, padding: "18px 18px 16px" }}>
      <h2 style={{ fontFamily: "var(--font-display)", fontSize: 17, fontWeight: 600, color: "var(--text-1)", letterSpacing: "-0.02em", marginBottom: 14 }}>{title}</h2>
      {children}
    </motion.div>
  );
}
