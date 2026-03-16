// FDR color palette — marker-pen feel
export const FDR_COLORS: Record<number, { bg: string; text: string; marker: string }> = {
  1: { bg: "#16a34a", text: "#ffffff", marker: "#15803d" },
  2: { bg: "#65a30d", text: "#ffffff", marker: "#4d7c0f" },
  3: { bg: "#ca8a04", text: "#ffffff", marker: "#a16207" },
  4: { bg: "#ea580c", text: "#ffffff", marker: "#c2410c" },
  5: { bg: "#dc2626", text: "#ffffff", marker: "#b91c1c" },
};

export function getFdrColor(fdr: number | null | undefined) {
  return FDR_COLORS[fdr ?? 3] ?? FDR_COLORS[3];
}

// Position colors (marker-pen palette)
export const POSITION_COLORS: Record<number, { bg: string; border: string; label: string }> = {
  1: { bg: "#fbbf24", border: "#d97706", label: "GK" },  // amber
  2: { bg: "#38bdf8", border: "#0284c7", label: "DEF" }, // sky
  3: { bg: "#34d399", border: "#059669", label: "MID" }, // emerald
  4: { bg: "#f87171", border: "#dc2626", label: "FWD" }, // rose
};

export function getPositionColor(elementType: number) {
  return POSITION_COLORS[elementType] ?? POSITION_COLORS[3];
}

export function formatCost(pence: number) {
  return `£${(pence / 10).toFixed(1)}m`;
}

export function positionLabel(elementType: number) {
  return POSITION_COLORS[elementType]?.label ?? "?";
}
