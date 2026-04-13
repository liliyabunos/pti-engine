// ---------------------------------------------------------------------------
// Shared formatting layer — all display transformations live here.
// Never duplicate these across components.
// ---------------------------------------------------------------------------

/** Format composite_market_score to 1 decimal place. */
export function fmtScore(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(1);
}

/** Format growth_rate as a signed percentage. */
export function fmtGrowth(v: number | null | undefined): string {
  if (v == null) return "—";
  const pct = (v * 100).toFixed(1);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

/** Format momentum ratio to 2 decimal places. */
export function fmtMomentum(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2) + "×";
}

/** Format confidence as a percentage. */
export function fmtConfidence(v: number | null | undefined): string {
  if (v == null) return "—";
  return (v * 100).toFixed(0) + "%";
}

/** Format engagement or mention counts with K/M suffixes. */
export function fmtCount(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return (v / 1_000).toFixed(1) + "K";
  return v.toFixed(0);
}

/** Format acceleration to signed 2 decimal places. */
export function fmtAcceleration(v: number | null | undefined): string {
  if (v == null) return "—";
  return v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2);
}

/** Format volatility to 2 decimal places. */
export function fmtVolatility(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

/** Human-readable signal type label. */
export function fmtSignalType(type: string | null | undefined): string {
  if (!type) return "—";
  const map: Record<string, string> = {
    breakout: "Breakout",
    acceleration_spike: "Accel Spike",
    reversal: "Reversal",
    new_entry: "New Entry",
  };
  return map[type] ?? type;
}

/** Format ISO datetime string to short display format. */
export function fmtDatetime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** Format ISO date string to short date. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

/** CSS class for growth direction (positive/negative/neutral). */
export function growthColor(v: number | null | undefined): string {
  if (v == null) return "text-zinc-500";
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-zinc-400";
}

/** CSS class for acceleration direction. */
export function accelColor(v: number | null | undefined): string {
  if (v == null) return "text-zinc-500";
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-zinc-400";
}

/** Signal type → color class mapping. */
export function signalColor(type: string | null | undefined): string {
  if (!type) return "text-zinc-500";
  const map: Record<string, string> = {
    breakout: "text-amber-400",
    acceleration_spike: "text-sky-400",
    reversal: "text-rose-400",
    new_entry: "text-emerald-400",
  };
  return map[type] ?? "text-zinc-400";
}

/** Signal type → background color class for badges. */
export function signalBgColor(type: string | null | undefined): string {
  if (!type) return "bg-zinc-800 text-zinc-400";
  const map: Record<string, string> = {
    breakout: "bg-amber-900/40 text-amber-400 border-amber-800",
    acceleration_spike: "bg-sky-900/40 text-sky-400 border-sky-800",
    reversal: "bg-rose-900/40 text-rose-400 border-rose-800",
    new_entry: "bg-emerald-900/40 text-emerald-400 border-emerald-800",
  };
  return map[type] ?? "bg-zinc-800 text-zinc-400 border-zinc-700";
}

/** Platform display name. */
export function fmtPlatform(platform: string | null | undefined): string {
  if (!platform) return "—";
  const map: Record<string, string> = {
    youtube: "YouTube",
    tiktok: "TikTok",
    reddit: "Reddit",
    other: "Other",
  };
  return map[platform] ?? platform;
}
