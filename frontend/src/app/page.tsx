"use client";
import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LogOut } from "lucide-react";
import { useFPLStore } from "@/store/fpl.store";
import NapkinPitch from "@/components/napkin/NapkinPitch";
import TransferScratchpad from "@/components/cards/TransferScratchpad";
import StatsPostIt from "@/components/cards/StatsPostIt";
import ActionBrief from "@/components/cards/ActionBrief";
import BottomDock from "@/components/BottomDock";
import Onboarding from "@/components/Onboarding";
import DeadlineTimer from "@/components/DeadlineTimer";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function HomePage() {
  const {
    squad,
    gwIntel,
    priorityActions,
    transferSuggestions,
    optimalSquad,
    benchStrategies,
    freeTransfers,
    bankMillions,
    teamId,
    anonymousSessionToken,
    onboardingComplete,
    isSyncing,
    syncPhase,
    transfersRateLimited,
    fetchSquad,
    fetchGwIntel,
    fetchPriorityActions,
    fetchTransfers,
    syncSquad,
    setTeamId,
    setOnboardingComplete,
    logout,
    deadline,
    gwState,
    fetchGwState,
  } = useFPLStore();


  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem("fpl_team_id") : null;
    const storedSession = typeof window !== "undefined" ? localStorage.getItem("fpl_anonymous_session_token") : null;
    if (stored) {
      setTeamId(Number(stored));
      setOnboardingComplete(true);
      return;
    }
    if (storedSession) {
      useFPLStore.getState().setAnonymousSessionToken(storedSession);
      setOnboardingComplete(true);
      return;
    }
    setOnboardingComplete(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!onboardingComplete || (!teamId && !anonymousSessionToken)) return;
    fetchSquad();
    fetchGwIntel();
    fetchPriorityActions();
    fetchTransfers();
    fetchGwState(); // shared global — no re-fetch on return to this page
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onboardingComplete, teamId, anonymousSessionToken]);

  // Auto-sync: if the team loaded but has no squad or intel data,
  // trigger a silent background sync once. This handles new users and
  // team switches where the squad hasn't been fetched from FPL yet.
  useEffect(() => {
    if (!onboardingComplete || !teamId || isSyncing) return;
    // Only auto-sync once per team session: wait for fetchSquad to settle (1s)
    const t = setTimeout(() => {
      if (!squad && !gwIntel && !isSyncing) {
        syncSquad();
      }
    }, 1500);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onboardingComplete, teamId]);

  if (!onboardingComplete || (!teamId && !anonymousSessionToken)) return <Onboarding />;

  // ── Full-screen sync loading bar ───────────────────────────────────────────
  // Show whenever a sync is running OR on first load (no squad/intel yet).
  // Never shows the "sync squad" empty-state prompt — user has no manual sync option.
  const needsInitialLoad = onboardingComplete && teamId && !squad && !gwIntel && !isSyncing;
  if (isSyncing || needsInitialLoad) {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "var(--bg)", gap: 18,
      }}>
        {/* Indeterminate progress bar */}
        <div style={{ width: 260, height: 2, background: "rgba(255,255,255,0.07)", borderRadius: 2, overflow: "hidden", position: "relative" }}>
          <motion.div
            animate={{ x: ["-100%", "160%"] }}
            transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
            style={{ position: "absolute", width: "60%", height: "100%", background: "var(--green)", borderRadius: 2, opacity: 0.85 }}
          />
        </div>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.04em" }}>
          {syncPhase || "Loading squad…"}
        </span>
      </div>
    );
  }

  const ftCount = freeTransfers ?? squad?.free_transfers ?? 1;
  const bankM   = bankMillions ?? (squad ? squad.bank / 10 : 0);

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--bg)" }}>


      {/* ── Minimal top bar ─────────────────────────────────────── */}
      <div className="top-bar">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {squad?.team_name && (
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text-1)",
                letterSpacing: "-0.01em",
              }}
            >
              {squad.team_name}
            </span>
          )}
          {squad?.total_points != null && (
            <span style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
              <span
                style={{
                  fontFamily: "var(--font-data)",
                  fontSize: 15,
                  fontWeight: 600,
                  color: "var(--text-1)",
                  letterSpacing: "-0.03em",
                }}
              >
                {squad.total_points}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-ui)",
                  fontSize: 9,
                  color: "var(--text-3)",
                  letterSpacing: "0.08em",
                }}
              >
                PTS
              </span>
            </span>
          )}
          {squad?.overall_rank && (
            <span
              style={{
                fontFamily: "var(--font-ui)",
                fontSize: 11,
                color: "var(--text-3)",
              }}
            >
              #{squad.overall_rank.toLocaleString()}
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {deadline && <DeadlineTimer deadline={deadline} />}

        {/* Logout / switch team */}
        <motion.button
          whileHover={{ translateY: -1 }}
          whileTap={{ scale: 0.97 }}
          onClick={logout}
          title="Switch team"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            fontFamily: "var(--font-ui)",
            fontSize: 11,
            fontWeight: 500,
            padding: "6px 10px",
            borderRadius: 8,
            border: "1px solid var(--divider)",
            background: "transparent",
            color: "var(--text-3)",
            cursor: "pointer",
            transition: "all 180ms",
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--red)"; (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(239,68,68,0.3)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--text-3)"; (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--divider)"; }}
        >
          <LogOut size={11} />
          switch
        </motion.button>
        </div>
      </div>

      {/* ── Main — three-panel layout ────────────────────────────── */}
      <main
        style={{
          flex: 1,
          maxWidth: 1300,
          margin: "0 auto",
          width: "100%",
          padding: "20px 20px 88px",
        }}
      >
        {/* ── Injury / doubtful banner — only shown when NOT live (squad is frozen during live GW) */}
        {gwIntel && (gwIntel as any).injury_alerts && (gwIntel as any).injury_alerts.length > 0
          && !(gwState?.state === "deadline_passed" && !gwState?.finished) && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            style={{
              padding: "10px 14px",
              marginBottom: 12,
              background: "rgba(239,68,68,0.07)",
              border: "1px solid rgba(239,68,68,0.25)",
              borderRadius: 10,
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
            }}
          >
            <span style={{ fontSize: 14, flexShrink: 0, marginTop: 1 }}>⚠️</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 700, color: "rgba(239,68,68,0.9)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>
                Squad alert
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {(gwIntel as any).injury_alerts.map((a: any) => (
                  <span key={a.player_id} style={{
                    fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-1)",
                    background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
                    borderRadius: 6, padding: "2px 8px",
                  }}>
                    {a.web_name}
                    {a.status === "d" && " · doubtful"}
                    {a.status === "i" && " · injured"}
                    {a.status === "s" && " · suspended"}
                    {a.chance_of_playing != null && a.chance_of_playing < 75 && ` · ${a.chance_of_playing}%`}
                    {a.news ? ` — ${a.news}` : ""}
                  </span>
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {/* ── Settling: GW ended, within 12h recommendation sync window ── */}
        {gwState?.state === "settling" ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            style={{
              padding: "28px 24px", borderRadius: 16, textAlign: "center",
              background: "var(--surface)", border: "1px solid var(--divider)",
              maxWidth: 520, margin: "0 auto",
            }}
          >
            <div style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "var(--amber)", boxShadow: "0 0 10px var(--amber)",
              margin: "0 auto 16px", animation: "captain-pulse 2s ease-in-out infinite",
            }} />
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 700, color: "var(--text-1)", marginBottom: 8 }}>
              GW{gwState.current_gw} complete
            </div>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--text-3)", lineHeight: 1.6 }}>
              GW{gwState.next_gw ?? (gwState.current_gw! + 1)} recommendations sync in{" "}
              {gwState.settling_until
                ? (() => {
                    const diff = (new Date(gwState.settling_until).getTime() - Date.now()) / 60000;
                    const h = Math.floor(diff / 60);
                    const m = Math.round(diff % 60);
                    return h > 0 ? `~${h}h ${m}m` : `~${m}m`;
                  })()
                : "~12h"}
              {" "}— data settling overnight.
            </div>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginTop: 12, opacity: 0.6 }}>
              Check the Status page for exact timing.
            </div>
          </motion.div>
        ) : gwState?.state === "deadline_passed" ? (
          <>
            {/* Thin status bar */}
            <motion.div
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "8px 14px", marginBottom: 14,
                background: "var(--surface)", border: "1px solid var(--divider)",
                borderRadius: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: gwState.finished ? "var(--green)" : "var(--amber)",
                  boxShadow: gwState.finished ? "0 0 8px var(--green)" : "0 0 8px var(--amber)",
                }} />
                <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", fontWeight: 500 }}>
                  {gwState.finished
                    ? `GW${gwState.current_gw} · Results in`
                    : `GW${gwState.current_gw} · Awaiting results`}
                </span>
              </div>
              {gwState.finished && (
                <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)" }}>
                  GW{gwState.next_gw ?? (gwState.current_gw! + 1)} next
                </span>
              )}
            </motion.div>

            {/* Post-deadline first-login notice — no priority actions means just joined */}
            {(!priorityActions || priorityActions.actions.length === 0) && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                style={{
                  padding: "10px 14px", marginBottom: 12,
                  background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.22)",
                  borderRadius: 10, maxWidth: 700, margin: "0 auto 12px",
                }}
              >
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "rgba(59,130,246,0.9)", fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 3 }}>
                  GW{gwState.current_gw} locked
                </div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.5 }}>
                  Deadline has passed — squad is locked for this gameweek. Recommendations and decision tracking begin from GW{gwState.next_gw ?? (gwState.current_gw! + 1)}.
                </div>
              </motion.div>
            )}

            {/* Pitch — squad is locked, centered + large markers */}
            <div style={{ maxWidth: 700, margin: "0 auto", width: "100%" }}>
              {squad
                ? <NapkinPitch picks={squad.squad} large isLiveGw={!gwState.finished} />
                : <EmptyPitch />}
            </div>
          </>
        ) : (
          <>
            {/* Desktop: 3-column */}
            <div
              className="hidden lg:grid"
              style={{ gridTemplateColumns: "280px 1fr 300px", gap: 18, alignItems: "start" }}
            >
              {/* Left — Priority Brief + Intel */}
              <div style={{ position: "sticky", top: 20 }}>
                {priorityActions && priorityActions.actions.length > 0 && (
                  <ActionBrief brief={priorityActions} teamId={teamId} />
                )}
                {gwIntel
                  ? <StatsPostIt intel={gwIntel} />
                  : !priorityActions && <EmptyGlass  />}
              </div>

              {/* Center — Pitch */}
              <div>
                {squad
                  ? <NapkinPitch picks={squad.squad} />
                  : <EmptyPitch />}
              </div>

              {/* Right — Transfers */}
              <div style={{ position: "sticky", top: 20 }}>
                <TransferScratchpad
                  suggestions={transferSuggestions}
                  freeTransfers={ftCount}
                  bankMillions={bankM}
                  optimalSquad={optimalSquad}
                  benchStrategies={benchStrategies}
                  rateLimited={transfersRateLimited}
                />
              </div>
            </div>

            {/* Mobile: stacked */}
            <div className="lg:hidden flex flex-col" style={{ gap: 14 }}>
              {squad ? <NapkinPitch picks={squad.squad} /> : <EmptyPitch />}
              {priorityActions && priorityActions.actions.length > 0 && (
                <ActionBrief brief={priorityActions} teamId={teamId} />
              )}
              {gwIntel
                ? <StatsPostIt intel={gwIntel} />
                : !priorityActions && <EmptyGlass  />}
              <TransferScratchpad
                suggestions={transferSuggestions}
                freeTransfers={ftCount}
                bankMillions={bankM}
                optimalSquad={optimalSquad}
                benchStrategies={benchStrategies}
              />
            </div>
          </>
        )}
      </main>

      <BottomDock />
    </div>
  );
}

function EmptyPitch() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="glass"
      style={{
        minHeight: 520,
        borderRadius: 16,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 14,
      }}
    >
      {/* Pulsing pitch outline skeleton */}
      <div style={{ position: "relative", width: 52, height: 52 }}>
        <motion.div
          animate={{ opacity: [0.3, 0.7, 0.3] }}
          transition={{ repeat: Infinity, duration: 1.8, ease: "easeInOut" }}
          style={{
            width: 52, height: 52, borderRadius: "50%",
            background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.22)",
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22,
          }}
        >
          ⚽
        </motion.div>
      </div>
      <div style={{ width: 120, height: 2, background: "rgba(255,255,255,0.07)", borderRadius: 2, overflow: "hidden" }}>
        <motion.div
          animate={{ x: ["-100%", "160%"] }}
          transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
          style={{ width: "60%", height: "100%", background: "rgba(34,197,94,0.4)", borderRadius: 2 }}
        />
      </div>
    </motion.div>
  );
}

function EmptyGlass() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="glass"
      style={{ borderRadius: 16, padding: "32px 20px", textAlign: "center" }}
    >
      <div style={{ width: 80, height: 2, background: "rgba(255,255,255,0.07)", borderRadius: 2, overflow: "hidden", margin: "0 auto" }}>
        <motion.div
          animate={{ x: ["-100%", "160%"] }}
          transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
          style={{ width: "60%", height: "100%", background: "rgba(255,255,255,0.15)", borderRadius: 2 }}
        />
      </div>
    </motion.div>
  );
}
