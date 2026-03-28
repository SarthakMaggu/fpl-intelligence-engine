"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

/* ── Custom minimal SVG icons — no generic Lucide ─────────────────────── */

function IconPitch({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* pitch rectangle */}
      <rect x="2" y="3.5" width="18" height="15" rx="1" stroke={s} strokeWidth={active ? 1.6 : 1.2} />
      {/* center line */}
      <line x1="11" y1="3.5" x2="11" y2="18.5" stroke={s} strokeWidth={active ? 1.6 : 1.2} />
      {/* center spot */}
      <circle cx="11" cy="11" r="1" fill={s} />
      {/* left penalty box */}
      <rect x="2" y="7.5" width="4" height="7" stroke={s} strokeWidth={active ? 1.2 : 0.9} />
      {/* right penalty box */}
      <rect x="16" y="7.5" width="4" height="7" stroke={s} strokeWidth={active ? 1.2 : 0.9} />
    </svg>
  );
}

function IconStrategy({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* formation dots — 1-4-3 layout suggesting tactics */}
      {/* GK */}
      <circle cx="11" cy="19" r="1.5" fill={s} />
      {/* DEF row */}
      <circle cx="4" cy="14.5" r="1.5" fill={s} />
      <circle cx="8.5" cy="14.5" r="1.5" fill={s} />
      <circle cx="13.5" cy="14.5" r="1.5" fill={s} />
      <circle cx="18" cy="14.5" r="1.5" fill={s} />
      {/* MID row */}
      <circle cx="6.5" cy="10" r="1.5" fill={s} />
      <circle cx="11" cy="10" r="1.5" fill={s} />
      <circle cx="15.5" cy="10" r="1.5" fill={s} />
      {/* FWD row */}
      <circle cx="7.5" cy="5.5" r="1.5" fill={s} />
      <circle cx="14.5" cy="5.5" r="1.5" fill={s} />
      {/* captain arrow */}
      <line x1="11" y1="8.5" x2="11" y2="4" stroke={s} strokeWidth="1.2" strokeLinecap="round" />
      <polyline points="9,5.5 11,3.5 13,5.5" stroke={s} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function IconMarket({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* price trend line — upward */}
      <polyline
        points="2,17 6,13 9,15 13,9 17,11 20,5"
        stroke={s}
        strokeWidth={active ? 1.8 : 1.3}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      {/* price tag */}
      <circle cx="20" cy="5" r="1.6" fill={s} />
      {/* baseline */}
      <line x1="2" y1="20" x2="20" y2="20" stroke={s} strokeWidth="1" strokeOpacity="0.4" />
    </svg>
  );
}

function IconReview({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* clipboard body */}
      <rect x="4" y="4" width="14" height="16" rx="1.5" stroke={s} strokeWidth={active ? 1.6 : 1.2} />
      {/* clip top */}
      <rect x="8" y="2.5" width="6" height="3" rx="0.8" stroke={s} strokeWidth="1" />
      {/* checkmark row */}
      <polyline points="7,10 9.2,12.5 13,8.5" stroke={s} strokeWidth={active ? 1.6 : 1.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* lines */}
      <line x1="7" y1="15" x2="15" y2="15" stroke={s} strokeWidth="1" strokeOpacity="0.5" />
      <line x1="7" y1="17.5" x2="12" y2="17.5" stroke={s} strokeWidth="1" strokeOpacity="0.5" />
    </svg>
  );
}

function IconLive({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* signal arcs — broadcast style */}
      <path d="M4.5 17.5 A9 9 0 0 1 4.5 4.5" stroke={s} strokeWidth={active ? 1.6 : 1.2} strokeLinecap="round" fill="none" />
      <path d="M17.5 4.5 A9 9 0 0 1 17.5 17.5" stroke={s} strokeWidth={active ? 1.6 : 1.2} strokeLinecap="round" fill="none" />
      <path d="M7 14.5 A5.5 5.5 0 0 1 7 7.5" stroke={s} strokeWidth={active ? 1.4 : 1} strokeLinecap="round" fill="none" />
      <path d="M15 7.5 A5.5 5.5 0 0 1 15 14.5" stroke={s} strokeWidth={active ? 1.4 : 1} strokeLinecap="round" fill="none" />
      {/* center dot */}
      <circle cx="11" cy="11" r={active ? 2 : 1.5} fill={s} />
    </svg>
  );
}

function IconScout({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* lens */}
      <circle cx="9.5" cy="9.5" r="6" stroke={s} strokeWidth={active ? 1.6 : 1.2} />
      {/* handle */}
      <line x1="14" y1="14" x2="19.5" y2="19.5" stroke={s} strokeWidth={active ? 2 : 1.5} strokeLinecap="round" />
      {/* cross-hair inside lens */}
      <line x1="9.5" y1="6.5" x2="9.5" y2="12.5" stroke={s} strokeWidth="0.8" strokeOpacity="0.6" />
      <line x1="6.5" y1="9.5" x2="12.5" y2="9.5" stroke={s} strokeWidth="0.8" strokeOpacity="0.6" />
    </svg>
  );
}

function IconSchedule({ active }: { active: boolean }) {
  const s = active ? "rgba(255,255,255,1)" : "rgba(255,255,255,0.35)";
  const sw = active ? 1.5 : 1.1;
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      {/* calendar body */}
      <rect x="2.5" y="5.5" width="17" height="14" rx="1.5" stroke={s} strokeWidth={sw} />
      {/* header bar */}
      <line x1="2.5" y1="9.5" x2="19.5" y2="9.5" stroke={s} strokeWidth={sw} />
      {/* pin left */}
      <line x1="7" y1="3.5" x2="7" y2="7.5" stroke={s} strokeWidth={active ? 1.6 : 1.3} strokeLinecap="round" />
      {/* pin right */}
      <line x1="15" y1="3.5" x2="15" y2="7.5" stroke={s} strokeWidth={active ? 1.6 : 1.3} strokeLinecap="round" />
      {/* grid of day dots — 3×2 */}
      <circle cx="6.5"  cy="13" r="1.1" fill={s} />
      <circle cx="11"   cy="13" r="1.1" fill={s} />
      <circle cx="15.5" cy="13" r="1.1" fill={s} />
      <circle cx="6.5"  cy="17" r="1.1" fill={s} />
      <circle cx="11"   cy="17" r="1.1" fill={s} />
      <circle cx="15.5" cy="17" r="1.1" fill={s} />
    </svg>
  );
}

const DOCK_ITEMS = [
  { href: "/",         label: "Pitch",    Icon: IconPitch    },
  { href: "/strategy", label: "Strategy", Icon: IconStrategy },
  { href: "/market",   label: "Market",   Icon: IconMarket   },
  { href: "/review",   label: "Review",   Icon: IconReview   },
  { href: "/live",     label: "Live",     Icon: IconLive     },
  { href: "/players",  label: "Scout",    Icon: IconScout    },
  { href: "/status",   label: "Status",   Icon: IconSchedule },
];

export default function BottomDock() {
  const pathname = usePathname();

  return (
    <nav className="bottom-dock">
      {DOCK_ITEMS.map(({ href, label, Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={`dock-item${active ? " active" : ""}`}
            style={{ textDecoration: "none" }}
          >
            <Icon active={active} />
            <span
              style={{
                fontFamily: "var(--font-ui)",
                fontSize: 10,
                fontWeight: active ? 600 : 400,
                color: active ? "var(--text-1)" : "var(--text-3)",
                letterSpacing: "0.04em",
                transition: "color 150ms",
              }}
            >
              {label}
            </span>
            {/* Active indicator dot */}
            {active && (
              <span
                style={{
                  position: "absolute",
                  bottom: -8,
                  left: "50%",
                  transform: "translateX(-50%)",
                  width: 4,
                  height: 4,
                  borderRadius: "50%",
                  background: "var(--text-1)",
                }}
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
