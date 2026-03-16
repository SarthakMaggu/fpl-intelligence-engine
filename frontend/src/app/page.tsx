"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RefreshCw, LogOut } from "lucide-react";
import { useFPLStore } from "@/store/fpl.store";
import NapkinPitch from "@/components/napkin/NapkinPitch";
import TransferScratchpad from "@/components/cards/TransferScratchpad";
import StatsPostIt from "@/components/cards/StatsPostIt";
import ActionBrief from "@/components/cards/ActionBrief";
import BottomDock from "@/components/BottomDock";
import Onboarding from "@/components/Onboarding";
import DeadlineTimer from "@/components/DeadlineTimer";

interface GWState {
  state: "pre_deadline" | "deadline_passed" | "finished" | "unknown";
  current_gw: number | null;
  next_gw: number | null;
  finished: boolean;
}

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
    fetchSquad,
    fetchGwIntel,
    fetchPriorityActions,
    fetchTransfers,
    syncSquad,
    setTeamId,
    setOnboardingComplete,
    logout,
    deadline,
  } = useFPLStore();

  const [gwState, setGwState] = useState<GWState | null>(null);


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
    fetch(`${API}/api/gameweeks/current`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setGwState(d))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onboardingComplete, teamId, anonymousSessionToken]);

  if (!onboardingComplete || (!teamId && !anonymousSessionToken)) return <Onboarding />;

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

        <motion.button
          whileHover={{ translateY: -1 }}
          whileTap={{ scale: 0.97 }}
          onClick={syncSquad}
          disabled={isSyncing}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontFamily: "var(--font-ui)",
            fontSize: 11,
            fontWeight: 600,
            padding: "6px 14px",
            borderRadius: 8,
            border: isSyncing ? "1px solid var(--divider)" : "1px solid rgba(34,197,94,0.3)",
            background: isSyncing ? "rgba(255,255,255,0.02)" : "rgba(34,197,94,0.07)",
            color: isSyncing ? "var(--text-3)" : "var(--green)",
            cursor: isSyncing ? "not-allowed" : "pointer",
            transition: "all 180ms",
          }}
        >
          <motion.span
            animate={isSyncing ? { rotate: 360 } : { rotate: 0 }}
            transition={isSyncing ? { duration: 1, repeat: Infinity, ease: "linear" } : {}}
            style={{ display: "flex" }}
          >
            <RefreshCw size={11} />
          </motion.span>
          {isSyncing ? (syncPhase || "syncing…") : "sync"}
        </motion.button>

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
        {/* ── Deadline passed / live: show locked squad + status ──── */}
        {gwState?.state === "deadline_passed" ? (
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

            {/* Pitch — squad is locked, centered + large markers */}
            <div style={{ maxWidth: 700, margin: "0 auto", width: "100%" }}>
              {squad
                ? <NapkinPitch picks={squad.squad} large />
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
                  : !priorityActions && <EmptyGlass label="sync squad to load intel" />}
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
                : !priorityActions && <EmptyGlass label="sync squad to load intel" />}
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
        gap: 10,
      }}
    >
      <div
        style={{
          width: 52,
          height: 52,
          borderRadius: "50%",
          background: "rgba(34,197,94,0.06)",
          border: "1px solid rgba(34,197,94,0.18)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 22,
        }}
      >
        ⚽
      </div>
      <p style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-ui)" }}>
        sync squad to load pitch
      </p>
    </motion.div>
  );
}

function EmptyGlass({ label }: { label: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="glass"
      style={{ borderRadius: 16, padding: "32px 20px", textAlign: "center" }}
    >
      <p style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-ui)" }}>{label}</p>
    </motion.div>
  );
}
