"use client";
/**
 * StoreHydrator — runs once on every page mount.
 * Reads fpl_team_id from localStorage and seeds the Zustand store so that
 * any page (review, strategy, etc.) works correctly even on direct navigation
 * or hard refresh, without needing to visit the pitch page first.
 */
import { useEffect } from "react";
import { useFPLStore } from "@/store/fpl.store";

export default function StoreHydrator() {
  const teamId = useFPLStore((s) => s.teamId);
  const anonymousSessionToken = useFPLStore((s) => s.anonymousSessionToken);
  const setTeamId = useFPLStore((s) => s.setTeamId);
  const setAnonymousSessionToken = useFPLStore((s) => s.setAnonymousSessionToken);
  const setOnboardingComplete = useFPLStore((s) => s.setOnboardingComplete);

  useEffect(() => {
    if (teamId != null || anonymousSessionToken) return; // already hydrated by this session
    const stored = localStorage.getItem("fpl_team_id");
    const sessionToken = localStorage.getItem("fpl_anonymous_session_token");
    if (stored) {
      setTeamId(Number(stored));
      setOnboardingComplete(true);
      return;
    }
    if (sessionToken) {
      setAnonymousSessionToken(sessionToken);
      setOnboardingComplete(true);
      return;
    }
    setOnboardingComplete(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
