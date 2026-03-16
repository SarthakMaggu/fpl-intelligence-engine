"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { TrendingUp, TrendingDown, Star, Zap, AlertCircle, RefreshCw } from "lucide-react";
import BottomDock from "@/components/BottomDock";
import { formatCost } from "@/lib/fdr";


const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MarketPlayer {
  id: number;
  web_name: string;
  element_type: number;
  team_short_name?: string | null;
  team_code?: number | null;
  now_cost: number;
  price_millions?: number | null;
  selected_by_percent: number;
  transfers_in_event: number;
  transfers_out_event: number;
  predicted_xpts_next?: number | null;
  form?: number | null;
  status: string;
  news?: string | null;
  has_double_gw?: boolean;
  has_blank_gw?: boolean;
}

interface MarketTrends {
  most_transferred_in: MarketPlayer[];
  most_transferred_out: MarketPlayer[];
  differentials: MarketPlayer[];
  must_haves: MarketPlayer[];
  price_risers: MarketPlayer[];
  price_fallers: MarketPlayer[];
  summary: {
    total_players_analyzed: number;
    differentials_count: number;
    must_haves_count: number;
    price_risers_count: number;
    price_fallers_count: number;
  };
}

const POS_LABEL: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
const POS_COLOR: Record<number, string> = {
  1: "var(--amber)",
  2: "var(--green)",
  3: "var(--text-2)",
  4: "var(--red)",
};

type Tab = "transfers_in" | "transfers_out" | "differentials" | "must_haves" | "price_risers" | "price_fallers";

const TABS: { key: Tab; label: string; Icon: React.ElementType; color: string }[] = [
  { key: "transfers_in",   label: "Hot",         Icon: TrendingUp,   color: "var(--green)" },
  { key: "transfers_out",  label: "Selling",      Icon: TrendingDown, color: "var(--red)"   },
  { key: "differentials",  label: "Differential", Icon: Star,         color: "var(--amber)" },
  { key: "must_haves",     label: "Template",     Icon: Zap,          color: "var(--blue)"  },
  { key: "price_risers",   label: "Risers",       Icon: TrendingUp,   color: "var(--green)" },
  { key: "price_fallers",  label: "Fallers",      Icon: TrendingDown, color: "var(--red)"   },
];

function PlayerCard({ p, rank, showTransfers, showXpts }: {
  p: MarketPlayer;
  rank: number;
  showTransfers?: "in" | "out";
  showXpts?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: rank * 0.04 }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 14px",
        borderRadius: 10,
        background: "var(--surface)",
        border: "1px solid var(--divider)",
        marginBottom: 6,
      }}
    >
      {/* Rank */}
      <span style={{
        fontFamily: "var(--font-data)",
        fontSize: 11,
        color: "var(--text-3)",
        width: 18,
        flexShrink: 0,
        textAlign: "right",
      }}>
        {rank + 1}
      </span>

      {/* Team badge */}
      {p.team_code ? (
        <img
          src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
          width={18} height={18}
          style={{ objectFit: "contain", flexShrink: 0 }}
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      ) : <div style={{ width: 18 }} />}

      {/* Name + pos */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontFamily: "var(--font-ui)",
          fontSize: 13,
          fontWeight: 600,
          color: p.status === "i" || p.status === "d" ? "var(--red)" : "var(--text-1)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {p.web_name}
          {p.has_double_gw && (
            <span style={{ marginLeft: 6, fontSize: 9, color: "var(--amber)", fontWeight: 700 }}>DGW</span>
          )}
          {p.has_blank_gw && (
            <span style={{ marginLeft: 6, fontSize: 9, color: "var(--text-3)" }}>blank</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 2 }}>
          <span style={{
            fontSize: 9,
            fontFamily: "var(--font-ui)",
            color: POS_COLOR[p.element_type],
            fontWeight: 600,
            letterSpacing: "0.06em",
          }}>
            {POS_LABEL[p.element_type]}
          </span>
          {p.team_short_name && (
            <span style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)" }}>
              {p.team_short_name}
            </span>
          )}
          <span style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-data)" }}>
            {formatCost(p.now_cost)}
          </span>
        </div>
      </div>

      {/* Right stats */}
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        {showTransfers && (
          <div style={{
            fontFamily: "var(--font-data)",
            fontSize: 13,
            fontWeight: 700,
            color: showTransfers === "in" ? "var(--green)" : "var(--red)",
          }}>
            {showTransfers === "in"
              ? `+${(p.transfers_in_event || 0).toLocaleString()}`
              : `-${(p.transfers_out_event || 0).toLocaleString()}`}
          </div>
        )}
        {showXpts && p.predicted_xpts_next != null && (
          <div style={{
            fontFamily: "var(--font-data)",
            fontSize: 13,
            fontWeight: 700,
            color: p.predicted_xpts_next >= 6 ? "var(--green)" : p.predicted_xpts_next >= 4 ? "var(--amber)" : "var(--text-2)",
          }}>
            {p.predicted_xpts_next.toFixed(1)}
          </div>
        )}
        <div style={{
          fontFamily: "var(--font-ui)",
          fontSize: 9,
          color: "var(--text-3)",
          marginTop: 2,
        }}>
          {p.selected_by_percent?.toFixed(1)}% own
        </div>
      </div>
    </motion.div>
  );
}

export default function MarketPage() {
  const [trends, setTrends] = useState<MarketTrends | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("transfers_in");
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      setRefreshing(true);
      const res = await fetch(`${API}/api/market/trends?top_n=15`);
      if (res.ok) setTrends(await res.json());
    } catch { /* silent */ }
    finally { setLoading(false); setRefreshing(false); }
  };

  useEffect(() => { load(); }, []);

  const getPlayers = (): MarketPlayer[] => {
    if (!trends) return [];
    switch (activeTab) {
      case "transfers_in":  return trends.most_transferred_in;
      case "transfers_out": return trends.most_transferred_out;
      case "differentials": return trends.differentials;
      case "must_haves":    return trends.must_haves;
      case "price_risers":  return trends.price_risers;
      case "price_fallers": return trends.price_fallers;
      default: return [];
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--bg)",
      paddingBottom: 80,
    }}>
      {/* Top bar */}
      <div style={{
        padding: "18px 20px 0",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div>
          <div style={{
            fontFamily: "var(--font-display)",
            fontSize: 22,
            fontWeight: 700,
            color: "var(--text-1)",
            letterSpacing: "-0.02em",
          }}>
            Market Intel
          </div>
          {trends?.summary && (
            <div style={{
              fontFamily: "var(--font-ui)",
              fontSize: 11,
              color: "var(--text-3)",
              marginTop: 2,
            }}>
              {trends.summary.total_players_analyzed} players · {trends.summary.differentials_count} differentials
            </div>
          )}
        </div>
        <button
          onClick={load}
          disabled={refreshing}
          style={{
            background: "var(--surface)",
            border: "1px solid var(--divider)",
            borderRadius: 8,
            padding: "6px 10px",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 5,
            color: "var(--text-2)",
          }}
        >
          <RefreshCw size={13} style={{ animation: refreshing ? "spin 1s linear infinite" : "none" }} />
        </button>
      </div>

      {/* Tab strip */}
      <div style={{
        display: "flex",
        gap: 6,
        padding: "14px 20px 0",
        overflowX: "auto",
        scrollbarWidth: "none",
      }}>
        {TABS.map(({ key, label, Icon, color }) => {
          const active = activeTab === key;
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 12px",
                borderRadius: 8,
                border: `1px solid ${active ? color : "var(--divider)"}`,
                background: active ? `${color}18` : "var(--surface)",
                color: active ? color : "var(--text-3)",
                fontFamily: "var(--font-ui)",
                fontSize: 11,
                fontWeight: active ? 600 : 400,
                cursor: "pointer",
                whiteSpace: "nowrap",
                flexShrink: 0,
                transition: "all 150ms",
              }}
            >
              <Icon size={11} />
              {label}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div style={{ padding: "14px 20px" }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
            Loading market data...
          </div>
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              {getPlayers().map((p, i) => (
                <PlayerCard
                  key={p.id}
                  p={p}
                  rank={i}
                  showTransfers={
                    activeTab === "transfers_in" ? "in" :
                    activeTab === "transfers_out" ? "out" : undefined
                  }
                  showXpts={activeTab !== "transfers_in" && activeTab !== "transfers_out"}
                />
              ))}
              {getPlayers().length === 0 && (
                <div style={{
                  textAlign: "center",
                  padding: 40,
                  color: "var(--text-3)",
                  fontFamily: "var(--font-ui)",
                  fontSize: 13,
                }}>
                  <AlertCircle size={24} style={{ marginBottom: 8, opacity: 0.4 }} />
                  <div>No data available. Sync your squad first.</div>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </div>

      <BottomDock />
    </div>
  );
}
