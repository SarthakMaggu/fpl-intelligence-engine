"use client";
import { motion, AnimatePresence } from "framer-motion";

interface InkLoaderProps {
  visible: boolean;
  label?: string;
}

export default function InkLoader({ visible, label = "Analyzing squad…" }: InkLoaderProps) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12,
            padding: "48px 0",
          }}
        >
          {/* Three sequential fill bars */}
          <div style={{ display: "flex", flexDirection: "column", gap: 5, width: 120 }}>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: "100%",
                  height: 2,
                  background: "var(--divider)",
                  borderRadius: 1,
                  overflow: "hidden",
                }}
              >
                <motion.div
                  animate={{ x: ["-100%", "0%", "100%"] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    ease: "easeInOut",
                    delay: i * 0.22,
                  }}
                  style={{
                    width: "60%",
                    height: "100%",
                    background: "var(--text-2)",
                    borderRadius: 1,
                  }}
                />
              </div>
            ))}
          </div>

          <span
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 11,
              color: "var(--text-3)",
              letterSpacing: "0.06em",
            }}
          >
            {label}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
