"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import BottomDock from "@/components/BottomDock";
import { formatCost } from "@/lib/fdr";
import type { Player } from "@/types/fpl";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const POS_FILTERS = [
  { label: "All", value: undefined },
  { label: "GK",  value: 1 },
  { label: "DEF", value: 2 },
  { label: "MID", value: 3 },
  { label: "FWD", value: 4 },
];

const POS_ACCENT: Record<number, string> = {
  1: "var(--amber)",
  2: "var(--green)",
  3: "rgba(255,255,255,0.5)",
  4: "var(--red)",
};
const POS_LABEL: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };

export default function PlayersPage() {
  const [players, setPlayers] = useState<Player[]>([]);
  const [search, setSearch]   = useState("");
  const [pos, setPos]         = useState<number | undefined>();
  const [loading, setLoading] = useState(false);

  const load = async (s = search, p = pos) => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "60" });
    if (s) params.set("search", s);
    if (p) params.set("element_type", String(p));
    try {
      const res = await fetch(`${API}/api/players/?${params}`);
      if (!res.ok) return;
      const data = await res.json();
      setPlayers(Array.isArray(data) ? data : []);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [pos]);

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <main style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 20px 96px" }}>
        <div style={{ marginBottom: 22 }}>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.04em" }}>
            Player Scout
          </h1>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 20, alignItems: "center" }}>
          <form onSubmit={(e) => { e.preventDefault(); load(); }} style={{ display: "flex", gap: 6 }}>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search player…"
              style={{
                background: "var(--surface-2)", border: "1px solid var(--divider)", borderRadius: 10,
                padding: "8px 14px", color: "var(--text-1)", fontSize: 13, fontFamily: "var(--font-ui)",
                outline: "none", width: 180,
              }}
            />
            <button type="submit" style={{
              fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600,
              padding: "8px 16px", borderRadius: 8, border: "1px solid var(--divider)",
              background: "rgba(255,255,255,0.04)", color: "var(--text-2)", cursor: "pointer",
            }}>
              search
            </button>
          </form>
          <div style={{ display: "flex", gap: 5 }}>
            {POS_FILTERS.map(({ label, value }) => (
              <button
                key={label}
                onClick={() => setPos(value)}
                style={{
                  fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: pos === value ? 600 : 400,
                  padding: "5px 12px", borderRadius: 999,
                  border: `1px solid ${pos === value ? "rgba(255,255,255,0.3)" : "var(--divider)"}`,
                  background: pos === value ? "rgba(255,255,255,0.08)" : "transparent",
                  color: pos === value ? "var(--text-1)" : "var(--text-3)", cursor: "pointer",
                  transition: "all 150ms",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 }}>
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="skeleton" style={{ height: 120, borderRadius: 12 }} />
            ))}
          </div>
        ) : players.length > 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(152px, 1fr))", gap: 8 }}>
            {players.map((player, i) => (
              <PlayerCard key={player.id} player={player} index={i} />
            ))}
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "56px 0", color: "var(--text-3)", fontSize: 13, fontFamily: "var(--font-ui)" }}>
            no players found — try syncing your squad first.
          </div>
        )}
      </main>
      <BottomDock />
    </div>
  );
}

function PlayerCard({ player, index }: { player: Player; index: number }) {
  const accent   = POS_ACCENT[player.element_type] ?? "var(--text-3)";
  const posLabel = POS_LABEL[player.element_type] ?? "—";
  const injured  = player.status === "i" || player.status === "d";
  const hasNews  = Boolean(player.news && player.news.trim().length > 0);

  const trendArrow = player.form_trend === "rising" ? "↑"
    : player.form_trend === "falling" ? "↓"
    : null;
  const trendColor = player.form_trend === "rising"  ? "var(--green)"
    : player.form_trend === "falling" ? "var(--red)"
    : "var(--text-3)";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.018, type: "spring", stiffness: 280, damping: 26 }}
      whileHover={{ y: -2, transition: { duration: 0.15 } }}
      style={{
        background: "var(--surface)", border: "1px solid var(--divider)", borderRadius: 12,
        padding: "12px 12px 10px", cursor: "default", transition: "border-color 150ms",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{
          fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
          color: accent, border: `1px solid ${accent}`,
          borderRadius: 999, padding: "2px 8px", letterSpacing: "0.08em",
          background: "rgba(255,255,255,0.03)",
        }}>
          {posLabel}
        </span>
        <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
          {/* News dot — shown when player has a news/availability note */}
          {hasNews && !injured && (
            <span
              title={player.news ?? undefined}
              style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--amber)", display: "inline-block", flexShrink: 0 }}
            />
          )}
          {player.has_double_gw && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--amber)", display: "inline-block", boxShadow: "0 0 5px var(--amber)" }} />}
          {player.has_blank_gw && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--divider)", display: "inline-block" }} />}
        </div>
      </div>

      {/* Team badge + player name */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        {player.team_code && (
          <img
            src={`https://resources.premierleague.com/premierleague/badges/25/t${player.team_code}.png`}
            alt={player.team_short_name ?? ""}
            width={16} height={16}
            style={{ objectFit: "contain", flexShrink: 0, opacity: 0.85 }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        {player.team_short_name && (
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
            {player.team_short_name}
          </span>
        )}
      </div>

      {/* Player name + form trend arrow */}
      <div style={{
        fontFamily: "var(--font-display)", fontSize: 14, fontWeight: 600,
        color: injured ? "var(--text-3)" : "var(--text-1)",
        lineHeight: 1.15, marginBottom: 10, letterSpacing: "-0.01em",
        display: "flex", alignItems: "baseline", gap: 4,
      }}>
        <span>{player.web_name}</span>
        {trendArrow && (
          <span style={{
            fontSize: 11, color: trendColor, fontFamily: "var(--font-data)",
            fontWeight: 600, lineHeight: 1,
          }}>{trendArrow}</span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 }}>
        <div>
          <div style={{ fontSize: 8, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: "var(--font-ui)", marginBottom: 1 }}>cost</div>
          <div style={{ fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 600, color: "var(--text-1)", letterSpacing: "-0.02em" }}>{formatCost(player.now_cost)}</div>
        </div>
        {player.predicted_xpts_next != null && (
          <div>
            <div style={{ fontSize: 8, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: "var(--font-ui)", marginBottom: 1 }}>xPts</div>
            <div style={{ fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 600, color: "var(--green)", letterSpacing: "-0.02em" }}>{player.predicted_xpts_next.toFixed(1)}</div>
          </div>
        )}
      </div>

      <div style={{ marginTop: 8, display: "flex", gap: 4, flexWrap: "wrap" }}>
        {player.fdr_next != null && <span className="badge badge-muted" style={{ fontSize: 9 }}>FDR {player.fdr_next}</span>}
        {player.suspension_risk && <span className="badge badge-amber" style={{ fontSize: 9 }}>YC</span>}
        {injured && <span className="badge badge-neg" style={{ fontSize: 9 }}>{player.status === "i" ? "inj" : "doubt"}</span>}
      </div>
    </motion.div>
  );
}
