"use client";
import { useEffect, useState } from "react";

interface Props {
  deadline: string; // ISO string
}

function getCountdown(deadline: string): string {
  const diff = new Date(deadline).getTime() - Date.now();
  if (diff <= 0) return "DEADLINE PASSED";

  const totalMinutes = Math.floor(diff / 60000);
  const days    = Math.floor(totalMinutes / 1440);
  const hours   = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0)  return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export default function DeadlineTimer({ deadline }: Props) {
  const [label, setLabel] = useState(() => getCountdown(deadline));

  useEffect(() => {
    setLabel(getCountdown(deadline));
    const id = setInterval(() => setLabel(getCountdown(deadline)), 60_000);
    return () => clearInterval(id);
  }, [deadline]);

  const diff = new Date(deadline).getTime() - Date.now();
  const urgent = diff > 0 && diff < 3 * 60 * 60 * 1000; // < 3h

  return (
    <span
      style={{
        fontFamily: "var(--font-data)",
        fontSize: 11,
        letterSpacing: "0.06em",
        color: urgent ? "var(--red)" : "var(--text-3)",
        background: urgent ? "rgba(239,68,68,0.08)" : "transparent",
        border: urgent ? "1px solid rgba(239,68,68,0.25)" : "1px solid var(--divider)",
        borderRadius: 6,
        padding: "2px 7px",
        whiteSpace: "nowrap",
      }}
    >
      ⏱ {label}
    </span>
  );
}
