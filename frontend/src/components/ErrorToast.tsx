"use client";
import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useFPLStore } from "@/store/fpl.store";

export default function ErrorToast() {
  const { syncError, clearSyncError } = useFPLStore();

  useEffect(() => {
    if (!syncError) return;
    const t = setTimeout(clearSyncError, 5000);
    return () => clearTimeout(t);
  }, [syncError, clearSyncError]);

  return (
    <AnimatePresence>
      {syncError && (
        <motion.div
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 80, opacity: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 28 }}
          onClick={clearSyncError}
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 1000,
            background: "rgba(10, 16, 24, 0.95)",
            border: "1px solid rgba(255, 107, 107, 0.5)",
            borderRadius: 12,
            padding: "11px 18px",
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--neg)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 10,
            maxWidth: "90vw",
            boxShadow: "0 4px 24px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,107,107,0.15)",
          }}
        >
          <svg width={14} height={14} viewBox="0 0 14 14" fill="none">
            <line x1="2" y1="2" x2="12" y2="12" stroke="var(--neg)" strokeWidth="2" strokeLinecap="round"/>
            <line x1="12" y1="2" x2="2" y2="12" stroke="var(--neg)" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          {syncError}
          <span style={{ fontSize: 10, color: "var(--dimmed)", marginLeft: 4, letterSpacing: "0.06em" }}>
            tap to dismiss
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
