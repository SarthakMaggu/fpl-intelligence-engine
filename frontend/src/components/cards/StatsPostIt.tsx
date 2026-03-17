"use client";
import { motion } from "framer-motion";
import type { GwIntelligence } from "@/types/fpl";

interface Props { intel: GwIntelligence }

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        fontFamily: "var(--font-ui)",
        fontSize: 9,
        fontWeight: 600,
        color: "var(--text-3)",
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        marginBottom: 8,
      }}
    >
      {children}
    </p>
  );
}

function Divider() {
  return <div style={{ height: 1, background: "var(--divider)", margin: "14px 0" }} />;
}

export default function StatsPostIt({ intel }: Props) {
  const cap            = intel.captain_recommendation;
  const injuries       = intel.injury_alerts;
  const suspensions    = intel.suspension_risk.filter((s) => s.yellow_cards >= 7);
  const dgwPlayers     = intel.double_gw_players.slice(0, 4);
  const hasAlerts      = injuries.length > 0 || suspensions.length > 0;
  const isClearCaptain = cap != null && (cap.predicted_xpts_next ?? 0) >= 6.0;

  return (
    <motion.div
      initial={{ opacity: 0, x: -24 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 240, damping: 26, delay: 0.1 }}
      className="glass"
      style={{ borderRadius: 16, padding: "18px 18px 16px", position: "relative", overflow: "hidden" }}
    >
      {/* Ambient glow — top right */}
      <div
        style={{
          position: "absolute",
          top: -60,
          right: -60,
          width: 160,
          height: 160,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(34,197,94,0.12) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      {/* ── Header ─────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 20,
            fontWeight: 600,
            color: "var(--text-1)",
            letterSpacing: "-0.03em",
          }}
        >
          GW{intel.gameweek}
        </span>
        <span
          style={{
            fontFamily: "var(--font-ui)",
            fontSize: 9,
            fontWeight: 600,
            color: "var(--text-3)",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            padding: "3px 8px",
            border: "1px solid var(--divider)",
            borderRadius: 999,
          }}
        >
          intel
        </span>
      </div>

      {/* ── Captain ─────────────────────────────────────────────── */}
      {cap && (
        <>
          <SectionLabel>captain pick</SectionLabel>
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, type: "spring", stiffness: 280 }}
            style={{
              background: "rgba(34,197,94,0.06)",
              border: "1px solid rgba(34,197,94,0.18)",
              borderRadius: 12,
              padding: "12px 14px",
              marginBottom: 2,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              position: "relative",
              overflow: "hidden",
            }}
          >
            {/* Background editorial watermark */}
            {isClearCaptain && (
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  paddingLeft: 12,
                  pointerEvents: "none",
                  opacity: 0.05,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 56,
                    fontWeight: 700,
                    color: "var(--green)",
                    letterSpacing: "-0.04em",
                    whiteSpace: "nowrap",
                  }}
                >
                  CAPTAIN
                </span>
              </div>
            )}

            <div style={{ position: "relative", zIndex: 1, minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
                {cap.team_code && (
                  <img
                    src={`https://resources.premierleague.com/premierleague/badges/25/t${cap.team_code}.png`}
                    alt={cap.team_short_name ?? ""}
                    width={16} height={16}
                    style={{ objectFit: "contain", opacity: 0.85, flexShrink: 0 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                )}
                {cap.team_short_name && (
                  <span style={{
                    fontFamily: "var(--font-ui)",
                    fontSize: 9,
                    fontWeight: 700,
                    color: "var(--text-3)",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    flexShrink: 0,
                  }}>
                    {cap.team_short_name}
                  </span>
                )}
                <div
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 20,
                    fontWeight: 600,
                    color: "var(--text-1)",
                    letterSpacing: "-0.03em",
                    lineHeight: 1.1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {cap.web_name}
                </div>
              </div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {cap.fdr_next != null && (
                  <span className="badge badge-muted" style={{ fontSize: 9, fontFamily: "var(--font-ui)" }}>
                    FDR {cap.fdr_next}
                  </span>
                )}
                <span className="badge badge-muted" style={{ fontSize: 9 }}>
                  {cap.is_home_next ? "home" : "away"}
                </span>
                {cap.confidence_score != null && (
                  <span className="badge badge-muted" style={{ fontSize: 9 }}>
                    {cap.confidence_score}% conf
                  </span>
                )}
                {cap.risk_profile && (
                  <span className="badge badge-muted" style={{ fontSize: 9 }}>
                    {cap.risk_profile.replace(/_/g, " ")}
                  </span>
                )}
                {cap.has_double_gw && (
                  <span className="badge badge-amber" style={{ fontSize: 9 }}>DGW</span>
                )}
              </div>
            </div>

            <div style={{ textAlign: "right", position: "relative", zIndex: 1, flexShrink: 0, paddingLeft: 8 }}>
              <span
                style={{
                  display: "block",
                  fontFamily: "var(--font-data)",
                  fontSize: 40,
                  fontWeight: 600,
                  color: "var(--green)",
                  lineHeight: 0.9,
                  letterSpacing: "-0.04em",
                }}
              >
                {(cap.predicted_xpts_next ?? 0).toFixed(1)}
              </span>
              <span
                style={{
                  fontSize: 9,
                  color: "var(--text-3)",
                  letterSpacing: "0.08em",
                  fontFamily: "var(--font-ui)",
                  textTransform: "uppercase",
                }}
              >
                xPts
              </span>
            </div>
          </motion.div>
        </>
      )}

      {cap?.explanation_summary && (
        <div style={{ marginTop: 10, fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.5 }}>
          {cap.explanation_summary}
        </div>
      )}

      {/* ── Alerts ─────────────────────────────────────────────── */}
      {hasAlerts && (
        <>
          <Divider />
          <SectionLabel>alerts</SectionLabel>

          {injuries.map((a) => (
            <div
              key={a.player_id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                marginBottom: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 7, flex: 1, minWidth: 0 }}>
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    background: a.chance_of_playing === 0 ? "var(--red)" : "var(--amber)",
                    display: "inline-block",
                    flexShrink: 0,
                    marginTop: 5,
                  }}
                />
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    {a.team_code && (
                      <img
                        src={`https://resources.premierleague.com/premierleague/badges/25/t${a.team_code}.png`}
                        alt=""
                        width={13} height={13}
                        style={{ objectFit: "contain", opacity: 0.65, flexShrink: 0 }}
                        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                      />
                    )}
                    <span
                      style={{
                        fontFamily: "var(--font-ui)",
                        fontSize: 13,
                        fontWeight: 500,
                        color: "var(--text-1)",
                      }}
                    >
                      {a.web_name}
                    </span>
                  </div>
                  {a.news && (
                    <span
                      style={{
                        fontFamily: "var(--font-ui)",
                        fontSize: 10,
                        color: "var(--text-3)",
                        lineHeight: 1.35,
                        display: "block",
                        marginTop: 2,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={a.news}
                    >
                      {a.news.length > 58 ? a.news.slice(0, 58) + "…" : a.news}
                    </span>
                  )}
                </div>
              </div>
              <span
                className={a.chance_of_playing === 0 ? "badge badge-neg" : "badge badge-amber"}
                style={{ fontSize: 10, flexShrink: 0, marginLeft: 6 }}
              >
                {a.chance_of_playing === 0 ? "OUT" : a.chance_of_playing != null ? `${a.chance_of_playing}%` : "?"}
              </span>
            </div>
          ))}

          {suspensions.map((s) => (
            <div
              key={s.player_id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    background: "var(--amber)",
                    display: "inline-block",
                    flexShrink: 0,
                  }}
                />
                {s.team_code && (
                  <img
                    src={`https://resources.premierleague.com/premierleague/badges/25/t${s.team_code}.png`}
                    alt=""
                    width={13} height={13}
                    style={{ objectFit: "contain", opacity: 0.65, flexShrink: 0 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                )}
                <span
                  style={{
                    fontFamily: "var(--font-ui)",
                    fontSize: 13,
                    fontWeight: 500,
                    color: "var(--text-1)",
                  }}
                >
                  {s.web_name}
                </span>
              </div>
              <span className="badge badge-amber" style={{ fontSize: 10 }}>
                {s.yellow_cards} YC
              </span>
            </div>
          ))}
        </>
      )}

      {/* ── Double GW ──────────────────────────────────────────── */}
      {dgwPlayers.length > 0 && (
        <>
          <Divider />
          <SectionLabel>double gameweek</SectionLabel>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {dgwPlayers.map((p) => (
              <div
                key={p.player_id}
                style={{
                  background: "rgba(245,158,11,0.06)",
                  border: "1px solid rgba(245,158,11,0.18)",
                  borderRadius: 10,
                  padding: "8px 10px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
                  {p.team_code && (
                    <img
                      src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                      alt=""
                      width={12} height={12}
                      style={{ objectFit: "contain", opacity: 0.7, flexShrink: 0 }}
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                  )}
                  <div
                    style={{
                      fontFamily: "var(--font-ui)",
                      fontSize: 11,
                      fontWeight: 600,
                      color: "var(--text-1)",
                      overflow: "hidden",
                      whiteSpace: "nowrap",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {p.web_name}
                  </div>
                </div>
                {p.predicted_xpts_next != null && (
                  <div
                    style={{
                      fontFamily: "var(--font-data)",
                      fontSize: 15,
                      fontWeight: 600,
                      color: "var(--amber)",
                      letterSpacing: "-0.03em",
                    }}
                  >
                    {p.predicted_xpts_next.toFixed(1)} xP
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Blank GW ────────────────────────────────────────────── */}
      {intel.blank_gw_starters && intel.blank_gw_starters.length > 0 && (
        <>
          <Divider />
          <SectionLabel>blank gameweek — no fixture</SectionLabel>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {intel.blank_gw_starters.map((p) => (
              <span
                key={p.player_id}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  fontFamily: "var(--font-ui)",
                  fontSize: 11,
                  fontWeight: 500,
                  color: "var(--text-3)",
                  background: "rgba(255,255,255,0.02)",
                  border: "1px solid var(--divider)",
                  borderRadius: 8,
                  padding: "4px 10px",
                  letterSpacing: "-0.01em",
                }}
              >
                {p.team_code && (
                  <img
                    src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                    alt=""
                    width={12} height={12}
                    style={{ objectFit: "contain", opacity: 0.7 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                )}
                {p.web_name}
              </span>
            ))}
          </div>
        </>
      )}

      {/* Empty state */}
      {!cap && !hasAlerts && dgwPlayers.length === 0 && !(intel.blank_gw_starters?.length) && (
        <div
          style={{
            padding: "20px 0",
            textAlign: "center",
            color: "var(--text-3)",
            fontSize: 13,
            fontFamily: "var(--font-ui)",
          }}
        >
          sync squad to load intel
        </div>
      )}
    </motion.div>
  );
}
